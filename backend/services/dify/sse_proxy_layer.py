"""M3 SseProxyLayer — Backend ↔ Dify 之间的 SSE 翻译层。

职责（M3 锁定契约）：
- 输入：`DifyClient.run_workflow_stream(inputs, end_user)` 产出的事件 dict 流
  （形如 `{"event": <type>, "data": <inner>}`）
- 输出：H5 widget 友好的 SSE 字节流（`event: <name>\ndata: <json>\n\n`）

事件映射（M3 契约，2026-06-13 确认）：

    workflow_started                     → session_started      {session_id, started_at}
    text_chunk                           → message_delta        {text}  (M2 已 strip thinking)
    workflow_finished (succeeded)        → message_complete     {text, total_tokens, elapsed_time}
    workflow_finished (failed/stopped/…) → (跳过，M2 会 raise DifyUpstreamError)
    node_started / node_finished / ping  → (跳过)

错误映射（PR8 §6.5）：

    DifyAuthError        → error {code: "DIFY_AUTH",        message}
    DifyBadRequestError  → error {code: "DIFY_BAD_REQUEST", message}
    DifyUpstreamError    → error {code: "DIFY_UPSTREAM",    message}
    其它 DifyError       → error {code: "DIFY_UNKNOWN",     message}

错误规则（验收门）：
- error 事件必须是流的最后一个业务事件
- error.message 必须截断到 ≤ 200 字符（H3 加强，M2 默认 500）
- error 事件后必须紧跟 event: end，让客户端能干净关连接
- 非 DifyError 异常不吞（让 caller 知道发生预期外错误）

不变式：
- 不修改 M2 `DifyClient`（PR8/9/10 已锁定契约）
- 不再 strip `<think>` 块（M2 已在 text_chunk 阶段完成 §6.10）
- 透传 `DifyClient.run_workflow_stream` 的 `inputs` / `end_user`

M8.5 — `_sse_event` / `_truncate_error_message` 私有 helpers 已提取到
`services.dify.sse_bytes` 公共模块（DRY 修复，与 `main.py` 共享）。
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from services.dify.dify_client import (
    DifyAuthError,
    DifyBadRequestError,
    DifyClient,
    DifyError,
    DifyUpstreamError,
    extract_output_text,
)
from services.dify.sse_bytes import sse_bytes, truncate_error
from services.dify.strip_think import create_think_stripper

logger = logging.getLogger(__name__)


# ============== Constants ==============

# M3 错误码（与 PR8 §6.5 错误码映射对齐）
_ERROR_CODE_AUTH = "DIFY_AUTH"
_ERROR_CODE_BAD_REQUEST = "DIFY_BAD_REQUEST"
_ERROR_CODE_UPSTREAM = "DIFY_UPSTREAM"
_ERROR_CODE_UNKNOWN = "DIFY_UNKNOWN"


# ============== Proxy ==============

class SseProxyLayer:
    """Backend ↔ Dify 之间的 SSE 翻译层。

    构造时注入一个 `DifyClient` 实例。`proxy()` 是 async generator，
    每次 yield 一个 SSE 事件字节块（bytes），兼容 FastAPI `StreamingResponse`。
    """

    def __init__(self, dify_client: DifyClient) -> None:
        self._client = dify_client

    async def proxy(
        self,
        *,
        inputs: dict[str, Any],
        end_user: str | None = None,
    ) -> AsyncIterator[bytes]:
        """主入口：消费 Dify 流，产出 H5 SSE 字节流。

        错误路径：
        - `DifyAuthError`        → error{DIFY_AUTH} + end
        - `DifyBadRequestError`  → error{DIFY_BAD_REQUEST} + end
        - `DifyUpstreamError`    → error{DIFY_UPSTREAM} + end
        - 其它 `DifyError`       → error{DIFY_UNKNOWN} + end
        - 非 `DifyError` 异常     → 直接 propagate（不吞）

        PR4b (G5 #7)：text_chunk 走 ``_StreamingThinkStripper``，跨 chunk 累积
        状态由 proxy 持有；流结束 (Dify 流走完 / 错误返回前) 必须 ``stripper.flush()``
        以处理 Dify 没发的尾段 (unclosed <think> 视为模型异常丢弃)。
        """
        consumed = 0
        stripper = create_think_stripper()
        try:
            async for event in self._client.run_workflow_stream(
                inputs=inputs, end_user=end_user
            ):
                consumed += 1
                mapped = self._map_event(event, stripper=stripper)
                if mapped is not None:
                    yield mapped
        except DifyAuthError as e:
            tail = stripper.flush()
            if tail:
                yield sse_bytes("message_delta", {"text": tail})
            yield self._error_bytes(_ERROR_CODE_AUTH, e)
            yield self._end_bytes()
            return
        except DifyBadRequestError as e:
            tail = stripper.flush()
            if tail:
                yield sse_bytes("message_delta", {"text": tail})
            yield self._error_bytes(_ERROR_CODE_BAD_REQUEST, e)
            yield self._end_bytes()
            return
        except DifyUpstreamError as e:
            tail = stripper.flush()
            if tail:
                yield sse_bytes("message_delta", {"text": tail})
            yield self._error_bytes(_ERROR_CODE_UPSTREAM, e)
            yield self._end_bytes()
            return
        except DifyError as e:
            tail = stripper.flush()
            if tail:
                yield sse_bytes("message_delta", {"text": tail})
            yield self._error_bytes(_ERROR_CODE_UNKNOWN, e)
            yield self._end_bytes()
            return

        # Stream 正常结束 (Dify 流已走完)。flush stripper 把 trailing `<` 兜底
        # 释放出, 防止 message_complete.text 出现 end-of-stream look-ahead 残留。
        tail = stripper.flush()
        if tail:
            yield sse_bytes("message_delta", {"text": tail})

        # Review #1 防御：Dify 200 OK 但 SSE 流 0 事件（连接立即关闭 / 空 body）
        # 若不 raise，H5 widget 永远收不到 session_started / error / end 任何事件
        # 会一直 hang 到自身超时。归一为 DIFY_UPSTREAM 让 caller 转 SSE error。
        if consumed == 0:
            raise DifyUpstreamError("Dify stream produced no events")

    # ------------------------------------------------------------------
    # 内部：事件 → SSE 字节
    # ------------------------------------------------------------------

    def _map_event(
        self,
        event: dict[str, Any],
        *,
        stripper: "_StreamingThinkStripper | None" = None,
    ) -> bytes | None:
        """将 Dify 事件映射为 SSE 字节。返回 None 表示该事件不外发。

        Dify 事件形态（来自 DifyClient.run_workflow_stream）：
            {"event": "workflow_started", "data": {…}}
            {"event": "text_chunk",       "data": {"text": "…"}}
            {"event": "workflow_finished", "data": {"status": "succeeded", "outputs": …}}
            …

        PR4b (G5 #7)：``text_chunk`` 跨 chunk strip —— ``_StreamingThinkStripper``
        在 proxy() 入口实例化, 本函数 ``feed()`` 累积的字符级 delta, 返回的
        安全前缀被 yield 为 ``message_delta`` 字节。workflow_finished 的
        ``outputs.output`` 仍走 ``extract_output_text`` 路径 (M2 PR9 已 strip
        final-state, defense-in-depth)。
        """
        event_type = event.get("event")
        data = event.get("data") or {}

        if event_type == "workflow_started":
            return sse_bytes("session_started", {
                # workflow_run_id 是 v2 唯一稳定标识（id 字段在 v1/v2 都有，
                # 但 workflow_run_id 更具语义）
                "session_id": (
                    data.get("workflow_run_id")
                    or data.get("id")
                    or ""
                ),
                # v2 workflow_started 不含 created_at（M2 也不补），保留 None 让 H5 客户端兜底
                "started_at": data.get("created_at"),
            })

        if event_type == "text_chunk":
            text = data.get("text")
            raw = text if isinstance(text, str) else ""
            # PR4b: 跨 chunk strip.  stream-level 累积消除 character-level
            # tokens (Dify v2 ~1-3 chars/chunk) 带来的 per-chunk regex no-op 问题
            # (见 real-dify-per-chunk-strip-noop memory)。
            if stripper is None:
                # 防御性：调用方忘了传 stripper 时降级到原始 per-chunk 透传
                return sse_bytes("message_delta", {"text": raw})
            safe_text = stripper.feed(raw)
            if not safe_text:
                # hold all: 不外发空 message_delta 事件
                return None
            return sse_bytes("message_delta", {"text": safe_text})

        if event_type == "workflow_finished":
            status = data.get("status")
            # 只 succeeded → message_complete；其它状态由 M2 raise DifyUpstreamError
            if status != "succeeded":
                return None
            # 走 PR9 U1-U10 extract_output_text（fallback 键 + think strip）。
            # M2 已在 text_chunk 阶段 strip think 块 (defense-in-depth):
            # - message_delta: 走 PR4b _StreamingThinkStripper (本层)
            # - message_complete: 走 M2 extract_output_text → _strip_thinking
            # 双重保险, 即便 stripper 被禁用 / 失败, final-state 仍干净
            text = extract_output_text(data, "output")
            return sse_bytes("message_complete", {
                "text": text,
                "total_tokens": data.get("total_tokens"),
                "elapsed_time": data.get("elapsed_time"),
            })

        # 其它事件（node_started / node_finished / ping / tts_message / 未知）→ 跳过
        return None

    def _error_bytes(self, code: str, error: DifyError) -> bytes:
        """生成 error 事件字节（H3 截断到 200 字符）。"""
        return sse_bytes("error", {
            "code": code,
            "message": truncate_error(str(error)),
        })

    @staticmethod
    def _end_bytes() -> bytes:
        """生成 end 事件字节（终止信号，紧跟 error 之后）。"""
        return sse_bytes("end", {})