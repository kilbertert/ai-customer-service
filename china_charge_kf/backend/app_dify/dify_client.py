"""Dify HTTP 客户端 (M2 扩展)。

M2 新增：
- 错误子类 `DifyAuthError` / `DifyBadRequestError` / `DifyUpstreamError`
- `run_workflow_blocking(*, inputs, end_user=None)` — blocking 模式 (原 run_workflow 别名)
- `run_workflow_stream(*, inputs, end_user=None, response_mode="streaming")` — async generator
- `extract_output_text(data, output_key="output")` — PR9 U1-U10 单测契约

保留不动 (PR10 锁定)：
- `upload_file()` — 文件上传
- `file_ref()` — file-ref array 序列化 (Backend 现有序列化代码)
- `dump_for_debug()` — 调试辅助
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


# ============== Errors ==============

class DifyError(RuntimeError):
    """Dify API 错误基类。

    M2 扩展：携带 status_code 便于日志/告警。
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class DifyAuthError(DifyError):
    """HTTP 401/403 — API key 失效/错误。

    SseProxyLayer 映射 SSE error.code = DIFY_AUTH (PR8 §6.5.1)。
    """


class DifyBadRequestError(DifyError):
    """HTTP 400 — yml 契约不匹配 / 文件不存在。

    SseProxyLayer 映射 SSE error.code = DIFY_BAD_REQUEST (PR8 §6.5.1)。
    """


class DifyUpstreamError(DifyError):
    """HTTP 5xx 或 HTTP 200 + data.status=failed。

    SseProxyLayer 映射 SSE error.code = DIFY_UPSTREAM (PR8 §6.5.2)。
    """


# ============== Helpers ==============

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """剥离 <think>...</think> 块 (§6.10)。幂等。"""
    if not text:
        return ""
    return _THINK_BLOCK_RE.sub("", text).strip()


_FALLBACK_OUTPUT_KEYS = ("output", "answer", "result", "text", "message", "content")

# 错误消息最大长度（Dify 400 错误可能 echo 整个 input value，需要截断避免日志/告警爆掉）
_MAX_ERROR_TEXT = 500


def _safe_body_text(resp) -> str:
    """安全读取 HTTP 错误响应体，失败时返回占位文本。"""
    try:
        return resp.text
    except Exception as e:  # body read may fail on connection drop
        return f"(body read failed: {type(e).__name__})"


async def _safe_aread(resp) -> str:
    """异步安全读取 streaming 响应体（C2），失败时返回占位文本。"""
    try:
        body = await resp.aread()
        return body.decode("utf-8", errors="replace")
    except Exception as e:
        return f"(body read failed: {type(e).__name__})"


def extract_output_text(data: dict | None, output_key: str = "output") -> str | None:
    """PR9 — 从 workflow_finished.data 提取 LLM 文本 (U1-U10)。

    判定规则：
    1. outputs[output_key] 非空 → 返回 (strip thinking, U1/U4)
    2. outputs[output_key] 空但其它 fallback 键命中 → 返回 (U3)
    3. status=failed 且 outputs 空 → 从 data.error 提取 (U5)
    4. status=failed 但 outputs 非空 → outputs 优先 (U6)
    5. 空字符串/纯空白视为无输出 → 返回 None (U8/U9)
    6. outputs=None / 空 dict / 完全空 data → None (U2/U7/U10)
    """
    if not isinstance(data, dict):
        return None
    outputs = data.get("outputs")
    if not isinstance(outputs, dict):
        outputs = {}

    # 1) 主路径
    primary = outputs.get(output_key)
    if isinstance(primary, str) and primary.strip():
        return _strip_thinking(primary)

    # 2) Fallback 键
    for k in _FALLBACK_OUTPUT_KEYS:
        if k == output_key:
            continue
        v = outputs.get(k)
        if isinstance(v, str) and v.strip():
            return _strip_thinking(v)

    # 3) status=failed → 从 data.error 兜底
    if data.get("status") == "failed":
        err = data.get("error")
        if isinstance(err, str) and err.strip():
            return _strip_thinking(err)

    return None


def _parse_sse_event(event: dict[str, str]) -> dict[str, Any] | None:
    """解析单个 SSE event 为标准 dict。

    返回 `{"event": <type>, "data": <inner>}` 形态；ping/空/解析失败 → None。

    Dify SSE 规范 (M0.5 §2.1.1 格式 B)：
        data: {"event":"text_chunk","data":{"text":"hi",...}}

    其中 outer `data:` JSON 永远含 `event` 和 `data` 两个 key，
    `data.data` 才是真正的 payload。本函数把外层 `data` 字段展平，
    让调用方用 `chunk["data"]["text"]` 而不是 `chunk["data"]["data"]["text"]`。

    M7.5 兼容：真实部署 (124.243.178.156:8501) 的 Dify v2 workflow 不在 SSE
    `event:` 字段上写类型, 只在 `data:` JSON 内嵌 `event` 键。若 SSE 字段为空,
    退而读取 payload.event, 否则 SseProxyLayer 会把所有非 ping 事件当作未知
    类型过滤掉, 前端收到 0 事件 (静默失败)。v1 路径不变。
    """
    event_type = (event.get("event") or "").strip()
    data_str = (event.get("data") or "").strip()
    if not data_str:
        return None
    try:
        payload = json.loads(data_str)
    except json.JSONDecodeError:
        logger.warning("SSE data parse failed: %s", data_str[:200])
        return None

    # M7.5: Dify v2 真实部署只把事件类型写在 data JSON 内, 兜底读取
    if not event_type and isinstance(payload, dict):
        inner_event = payload.get("event")
        if isinstance(inner_event, str) and inner_event.strip():
            event_type = inner_event.strip()

    # Skip ping (M0.5 §2.2.3 — 保活事件不外发)
    if event_type == "ping":
        return None

    # 展平外层 `data` 字段
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        inner = payload["data"]
    else:
        inner = payload

    # text_chunk: strip thinking (§6.10)
    if event_type == "text_chunk" and isinstance(inner, dict):
        text = inner.get("text")
        if isinstance(text, str):
            inner["text"] = _strip_thinking(text)

    return {"event": event_type, "data": inner}


# ============== Client ==============

@dataclass(frozen=True)
class DifyClient:
    api_base: str  # e.g. https://api.dify.ai/v1
    api_key: str   # app-xxx
    end_user: str  # Dify requires a user identifier on every call

    def _headers(self, *, content_type: Optional[str] = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if content_type:
            h["Content-Type"] = content_type
        return h

    # ------------------------------------------------------------------
    # 1. File upload
    # ------------------------------------------------------------------
    async def upload_file(
        self,
        *,
        filename: str,
        content: bytes,
        content_type: str | None,
    ) -> str:
        """Upload a file (image / audio / etc.) to Dify.

        Endpoint:  POST {api_base}/files/upload
        Form:      file (binary), user (string)
        Response:  201 { id, name, mime_type, ... }

        Returns the file's ``id`` (UUID) — used as ``upload_file_id`` later
        when referencing the file in a workflow ``inputs`` file array.
        """
        url = f"{self.api_base.rstrip('/')}/files/upload"
        files = {"file": (filename, content, content_type or "application/octet-stream")}
        data = {"user": self.end_user}

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(url, headers=self._headers(), files=files, data=data)

        if resp.status_code >= 400:
            raise DifyError(f"Dify upload failed: HTTP {resp.status_code} {resp.text}")

        body = resp.json()
        file_id = body.get("id")
        if not file_id:
            raise DifyError(f"Dify upload returned no id: {body}")
        return str(file_id)

    # ------------------------------------------------------------------
    # 2. Workflow execution — blocking (M2 canonical)
    # ------------------------------------------------------------------
    async def run_workflow_blocking(
        self,
        *,
        inputs: dict[str, Any],
        end_user: str | None = None,
    ) -> dict[str, Any]:
        """阻塞模式调用 Workflow app。

        Endpoint:  POST {api_base}/workflows/run
        Body:      { inputs, response_mode: "blocking", user }
        Response:  { task_id, workflow_run_id, data: { status, outputs, error, ... } }

        错误映射 (PR8 §6.5)：
        - 401 → DifyAuthError (DIFY_AUTH)
        - 400 → DifyBadRequestError (DIFY_BAD_REQUEST)
        - 5xx → DifyUpstreamError (DIFY_UPSTREAM)
        - 200 + data.status=failed/stopped/partial-succeeded → DifyUpstreamError

        重要：HTTP 200 但 data.status=failed 时也抛错，调用方**必须**
        走 try/except DifyUpstreamError 而不是直接用 body.outputs。
        """
        actual_end_user = end_user if end_user is not None else self.end_user
        url = f"{self.api_base.rstrip('/')}/workflows/run"
        payload = {
            "inputs": inputs,
            "response_mode": "blocking",
            "user": actual_end_user,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.post(
                url,
                headers=self._headers(content_type="application/json"),
                json=payload,
            )

        if resp.status_code == 401:
            raise DifyAuthError(
                f"Dify auth failed: {_safe_body_text(resp)[:_MAX_ERROR_TEXT]}",
                status_code=resp.status_code,
            )
        if resp.status_code == 400:
            raise DifyBadRequestError(
                f"Dify bad request: {_safe_body_text(resp)[:_MAX_ERROR_TEXT]}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 500:
            raise DifyUpstreamError(
                f"Dify upstream error: HTTP {resp.status_code} "
                f"{_safe_body_text(resp)[:_MAX_ERROR_TEXT]}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise DifyError(
                f"Dify HTTP error: {resp.status_code} "
                f"{_safe_body_text(resp)[:_MAX_ERROR_TEXT]}",
                status_code=resp.status_code,
            )

        body = resp.json()
        data = body.get("data") or {}
        status = data.get("status")
        if status in ("failed", "stopped", "partial-succeeded"):
            err = data.get("error") or "(no error detail)"
            raise DifyUpstreamError(
                f"Dify workflow {status}: {err}; outputs={data.get('outputs')}"
            )
        return body

    # ------------------------------------------------------------------
    # 3. Workflow execution — streaming (M2 新增)
    # ------------------------------------------------------------------
    async def run_workflow_stream(
        self,
        *,
        inputs: dict[str, Any],
        end_user: str | None = None,
        response_mode: str = "streaming",
    ) -> AsyncIterator[dict[str, Any]]:
        """流式调用 Workflow app。

        Endpoint:  POST {api_base}/workflows/run
        Body:      { inputs, response_mode: "streaming", user }
        Response:  text/event-stream (SSE)

        产出事件形如 `{"event": <str>, "data": <dict>}`：
        - workflow_started →  yield
        - node_started    →  yield
        - text_chunk      →  yield, data.text 已 strip thinking (§6.10)
        - node_finished   →  yield
        - workflow_finished → yield
        - ping            →  跳过 (M0.5 §2.2.3)

        终止行为：
        - workflow_finished.status=succeeded → 自然结束
        - workflow_finished.status=failed/stopped/partial-succeeded
          → 仍 yield workflow_finished 事件，**随后** raise DifyUpstreamError
          （调用方可以先消费前面的事件再接收错误）
        - HTTP 401 → 在首个 yield 之前 raise DifyAuthError
        - HTTP 400 → 在首个 yield 之前 raise DifyBadRequestError
        - HTTP 5xx → 在首个 yield 之前 raise DifyUpstreamError
        """
        actual_end_user = end_user if end_user is not None else self.end_user
        url = f"{self.api_base.rstrip('/')}/workflows/run"
        payload = {
            "inputs": inputs,
            "response_mode": response_mode,
            "user": actual_end_user,
        }

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            async with client.stream(
                "POST",
                url,
                headers=self._headers(content_type="application/json"),
                json=payload,
            ) as resp:
                if resp.status_code == 401:
                    body = await _safe_aread(resp)
                    raise DifyAuthError(
                        f"Dify auth failed: {body[:_MAX_ERROR_TEXT]}",
                        status_code=resp.status_code,
                    )
                if resp.status_code == 400:
                    body = await _safe_aread(resp)
                    raise DifyBadRequestError(
                        f"Dify bad request: {body[:_MAX_ERROR_TEXT]}",
                        status_code=resp.status_code,
                    )
                if resp.status_code >= 500:
                    body = await _safe_aread(resp)
                    raise DifyUpstreamError(
                        f"Dify upstream error: HTTP {resp.status_code} "
                        f"{body[:_MAX_ERROR_TEXT]}",
                        status_code=resp.status_code,
                    )
                if resp.status_code >= 400:
                    body = await _safe_aread(resp)
                    raise DifyError(
                        f"Dify HTTP error: {resp.status_code} "
                        f"{body[:_MAX_ERROR_TEXT]}",
                        status_code=resp.status_code,
                    )

                # 解析 SSE 流（mid-stream 网络错误归一化为 DifyUpstreamError — H1）
                try:
                    current: dict[str, str] = {}
                    last_event: dict[str, Any] | None = None
                    async for raw_line in resp.aiter_lines():
                        line = raw_line.rstrip("\n").rstrip("\r")
                        if not line:
                            if current:
                                parsed = _parse_sse_event(current)
                                current = {}
                                if parsed is None:
                                    continue
                                last_event = parsed
                                yield parsed
                            continue
                        if ":" in line:
                            field, _, value = line.partition(":")
                            current[field.strip()] = value.lstrip()
                    # 流结束后可能还有最后一个事件
                    if current:
                        parsed = _parse_sse_event(current)
                        if parsed is not None:
                            last_event = parsed
                            yield parsed
                except httpx.HTTPError as e:
                    raise DifyUpstreamError(
                        f"Dify stream interrupted: {type(e).__name__}: "
                        f"{str(e)[:_MAX_ERROR_TEXT]}",
                        status_code=getattr(resp, "status_code", None),
                    ) from e

                # 流结束：检查 workflow_finished 状态
                if last_event and last_event["event"] == "workflow_finished":
                    status = (last_event["data"] or {}).get("status")
                    if status in ("failed", "stopped", "partial-succeeded"):
                        err = (last_event["data"] or {}).get("error") or "(no error detail)"
                        raise DifyUpstreamError(
                            f"Dify workflow {status}: {err}; "
                            f"outputs={(last_event['data'] or {}).get('outputs')}"
                        )

    # ------------------------------------------------------------------
    # 4. (legacy) Workflow execution — backward compat alias
    # ------------------------------------------------------------------
    async def run_workflow(
        self,
        *,
        inputs: dict[str, Any],
        response_mode: str = "blocking",
    ) -> dict[str, Any]:
        """Backward-compat alias for `run_workflow_blocking`.

        保留以兼容 `app_dify/main.py` 已有调用。新代码应使用
        `run_workflow_blocking` 或 `run_workflow_stream`。
        """
        if response_mode != "blocking":
            raise DifyError(
                "run_workflow legacy alias only supports blocking mode; "
                "use run_workflow_stream for streaming"
            )
        return await self.run_workflow_blocking(inputs=inputs, end_user=None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def file_ref(upload_file_id: str, file_type: str) -> dict[str, Any]:
        """Build a Dify file-object suitable for a workflow file-array input.

        file_type: 'image' | 'audio' | 'document' | 'video'

        PR10 锁定：调用方必须把返回值包在 array 中：
            inputs[input_img_id] = [client.file_ref(file_id, "image")]
        """
        return {
            "type": file_type,
            "transfer_method": "local_file",
            "upload_file_id": upload_file_id,
        }

    def dump_for_debug(self, body: dict[str, Any]) -> str:
        try:
            return json.dumps(body, ensure_ascii=False, indent=2)[:2000]
        except Exception:
            return str(body)[:2000]