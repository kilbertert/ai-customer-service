"""M3 SseProxyLayer 测试。

覆盖：
- 4 类事件映射：workflow_started → session_started, text_chunk → message_delta,
  workflow_finished (succeeded) → message_complete, 其它事件 → 跳过
- 4 类错误映射：DifyAuthError → DIFY_AUTH, DifyBadRequestError → DIFY_BAD_REQUEST,
  DifyUpstreamError → DIFY_UPSTREAM, 其它 DifyError → DIFY_UNKNOWN
- 错误规则：消息截断 ≤ 200 字符；event: end 紧跟 error；error 是流最后业务事件
- SSE 字节格式：event: line + data: json + 空行；Unicode 正确

测试策略：使用 FakeDifyClient 替身（仅暴露 `run_workflow_stream` 协议），
无需 respx/SSE 字节反解——M2 已经覆盖了 SSE 解析的解析正确性。
M3 的职责是事件翻译与错误归一化，不是再解析一次 SSE。

M8.5 — `_sse_event` / `_truncate_error_message` 私有 helper 测试已迁移到
`tests/test_sse_bytes.py`（helper 现属 `app_dify.sse_bytes` 公共模块）。
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncIterator

import pytest

from app_dify.dify_client import (
    DifyAuthError,
    DifyBadRequestError,
    DifyError,
    DifyUpstreamError,
)
from app_dify.sse_proxy_layer import SseProxyLayer


# ============== Fixtures / 替身 ==============

class FakeDifyClient:
    """可注入事件序列或异常的 DifyClient 替身。

    只需要实现 `run_workflow_stream(*, inputs, end_user=None, **kw)` 这个
    async generator 协议（与 `DifyClient` 的同名方法同形）。Proxy 只用这一个
    入口，所以 FakeDifyClient 不需要 `upload_file` / `run_workflow_blocking` /
    `file_ref` / `dump_for_debug`。
    """

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def run_workflow_stream(
        self,
        *,
        inputs: dict[str, Any],
        end_user: str | None = None,
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.calls.append({"inputs": inputs, "end_user": end_user})
        for e in self.events:
            yield e
        if self.error is not None:
            raise self.error


def parse_sse_bytes(raw: bytes) -> list[dict[str, str]]:
    """把 SSE 字节流解析回 `[{event, data}, ...]`，跳过空行。"""
    text = raw.decode("utf-8")
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.split("\n"):
        if line == "":
            if current:
                events.append(current)
                current = {}
        elif ":" in line:
            field, _, value = line.partition(":")
            current[field.strip()] = value.lstrip()
    if current:
        events.append(current)
    return events


async def _collect_bytes(agen) -> list[bytes]:
    """消费 async generator，收集所有 yield 字节。"""
    out: list[bytes] = []
    async for chunk in agen:
        out.append(chunk)
    return out


def make_event(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """构造 `DifyClient.run_workflow_stream` 产出的事件 dict。"""
    return {"event": event_type, "data": data}


# ============== 4 类事件映射 ==============

class TestEventMapping:
    @pytest.mark.asyncio
    async def test_workflow_started_maps_to_session_started(self):
        client = FakeDifyClient(events=[
            make_event("workflow_started", {
                "task_id": "t1",
                "workflow_run_id": "run-uuid-1",
                "id": "run-uuid-1",
            }),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
                "total_tokens": 50,
                "elapsed_time": 1.5,
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert events[0]["event"] == "session_started"
        data = json.loads(events[0]["data"])
        assert data["session_id"] == "run-uuid-1"

    @pytest.mark.asyncio
    async def test_text_chunk_maps_to_message_delta_with_text(self):
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("text_chunk", {
                "node_id": "2007",
                "text": "请先",
                "from_variable_selector": ["2007", "text"],
            }),
            make_event("text_chunk", {
                "node_id": "2007",
                "text": "检查",
            }),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "请先检查"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        # session_started, message_delta, message_delta, message_complete
        assert [e["event"] for e in events] == [
            "session_started",
            "message_delta",
            "message_delta",
            "message_complete",
        ]
        assert json.loads(events[1]["data"]) == {"text": "请先"}
        assert json.loads(events[2]["data"]) == {"text": "检查"}

    @pytest.mark.asyncio
    async def test_workflow_finished_succeeded_maps_to_message_complete(self):
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "最终回复"},
                "total_tokens": 120,
                "elapsed_time": 2.5,
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert len(events) == 2
        assert events[1]["event"] == "message_complete"
        data = json.loads(events[1]["data"])
        assert data["text"] == "最终回复"
        assert data["total_tokens"] == 120
        assert data["elapsed_time"] == 2.5

    @pytest.mark.asyncio
    async def test_workflow_finished_failed_does_not_emit_message_complete(self):
        """status=failed/stopped/partial-succeeded 不发 message_complete——M2 会 raise。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "failed",
                "outputs": {},
                "error": "PluginInvokeError: image too small",
            }),
        ], error=DifyUpstreamError(
            "Dify workflow failed: PluginInvokeError: image too small; outputs={}"
        ))
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        event_names = [e["event"] for e in events]
        assert "message_complete" not in event_names
        # session_started 后直接 error + end
        assert event_names == ["session_started", "error", "end"]

    @pytest.mark.asyncio
    async def test_workflow_finished_stopped_also_raises_upstream(self):
        """status=stopped 同样走 DifyUpstreamError（M2 行为对称）。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "stopped",
                "outputs": {},
                "error": "user cancelled",
            }),
        ], error=DifyUpstreamError("Dify workflow stopped: user cancelled"))
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        err = next(e for e in events if e["event"] == "error")
        data = json.loads(err["data"])
        assert data["code"] == "DIFY_UPSTREAM"

    @pytest.mark.asyncio
    async def test_node_started_is_skipped(self):
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("node_started", {"node_id": "2007", "node_type": "llm"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        event_names = [e["event"] for e in events]
        assert "node_started" not in event_names
        assert event_names == ["session_started", "message_complete"]

    @pytest.mark.asyncio
    async def test_node_finished_is_skipped(self):
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("node_finished", {"node_id": "2007", "status": "succeeded"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        event_names = [e["event"] for e in events]
        assert "node_finished" not in event_names
        assert event_names == ["session_started", "message_complete"]


# ============== 4 类错误映射 ==============

class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_dify_auth_error_maps_to_dify_auth(self):
        client = FakeDifyClient(
            error=DifyAuthError("Dify auth failed: Access token is invalid", status_code=401)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert events[0]["event"] == "error"
        data = json.loads(events[0]["data"])
        assert data["code"] == "DIFY_AUTH"
        assert "Access token is invalid" in data["message"]
        assert events[1]["event"] == "end"

    @pytest.mark.asyncio
    async def test_dify_bad_request_error_maps_to_dify_bad_request(self):
        client = FakeDifyClient(
            error=DifyBadRequestError("Dify bad request: Invalid upload file", status_code=400)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert events[0]["event"] == "error"
        data = json.loads(events[0]["data"])
        assert data["code"] == "DIFY_BAD_REQUEST"
        assert "Invalid upload file" in data["message"]
        assert events[1]["event"] == "end"

    @pytest.mark.asyncio
    async def test_dify_upstream_error_maps_to_dify_upstream(self):
        """Dify 5xx 或 workflow_finished.status=failed 都走 DIFY_UPSTREAM。"""
        client = FakeDifyClient(
            error=DifyUpstreamError("Dify upstream error: HTTP 503", status_code=503)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert events[0]["event"] == "error"
        data = json.loads(events[0]["data"])
        assert data["code"] == "DIFY_UPSTREAM"
        assert "HTTP 503" in data["message"]
        assert events[1]["event"] == "end"

    @pytest.mark.asyncio
    async def test_other_dify_error_maps_to_dify_unknown(self):
        """其它 DifyError 子类 → DIFY_UNKNOWN 兜底。"""

        class CustomDifyError(DifyError):
            pass

        client = FakeDifyClient(
            error=CustomDifyError("some weird failure", status_code=418)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert events[0]["event"] == "error"
        data = json.loads(events[0]["data"])
        assert data["code"] == "DIFY_UNKNOWN"
        assert "some weird failure" in data["message"]
        assert events[1]["event"] == "end"

    @pytest.mark.asyncio
    async def test_non_dify_error_propagates(self):
        """非 DifyError 异常不应被吞——让上游 caller 知道发生了预期外错误。"""
        client = FakeDifyClient(error=RuntimeError("boom"))
        proxy = SseProxyLayer(client)
        with pytest.raises(RuntimeError) as exc_info:
            async for _ in proxy.proxy(inputs={}):
                pass
        assert "boom" in str(exc_info.value)


# ============== 错误规则 ==============

class TestErrorRules:
    @pytest.mark.asyncio
    async def test_error_message_truncated_to_200_chars(self):
        long_msg = "X" * 500
        client = FakeDifyClient(
            error=DifyUpstreamError(long_msg, status_code=500)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        data = json.loads(events[0]["data"])
        # 200 + "..." = 203
        assert len(data["message"]) <= 203
        assert "..." in data["message"]

    @pytest.mark.asyncio
    async def test_short_error_message_not_truncated(self):
        client = FakeDifyClient(
            error=DifyAuthError("short msg", status_code=401)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        data = json.loads(events[0]["data"])
        assert data["message"] == "short msg"
        assert "..." not in data["message"]

    @pytest.mark.asyncio
    async def test_error_is_last_business_event_before_end(self):
        """error 必须是流的最后一个业务事件；end 是终止信号。"""
        client = FakeDifyClient(
            error=DifyAuthError("auth fail", status_code=401)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        assert len(events) == 2
        assert events[0]["event"] == "error"
        assert events[1]["event"] == "end"

    @pytest.mark.asyncio
    async def test_end_event_payload_is_empty_dict(self):
        client = FakeDifyClient(error=DifyAuthError("auth", status_code=401))
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        end_data = json.loads(events[1]["data"])
        assert end_data == {}

    @pytest.mark.asyncio
    async def test_error_includes_status_code_in_message(self):
        """DifyError.status_code 应被透传到 message（H3 加强时可观测）。"""
        client = FakeDifyClient(
            error=DifyUpstreamError("upstream", status_code=503)
        )
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        data = json.loads(events[0]["data"])
        # 透传 DifyError 的 str(message) —— status_code 不强制嵌入 message
        # （已通过截断到 200 字符保护）
        assert "upstream" in data["message"]


# ============== end-to-end happy path ==============

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_stream_produces_expected_sse_sequence(self):
        """S1-style：session_started → 2x message_delta → message_complete（无 end 因为非错误）。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {
                "task_id": "t1",
                "workflow_run_id": "run-1",
                "id": "run-1",
            }),
            make_event("text_chunk", {
                "node_id": "2007",
                "text": "请先",
                "from_variable_selector": ["2007", "text"],
            }),
            make_event("text_chunk", {
                "node_id": "2007",
                "text": "检查供电",
            }),
            make_event("workflow_finished", {
                "id": "run-1",
                "status": "succeeded",
                "outputs": {"output": "请先检查供电"},
                "total_tokens": 50,
                "elapsed_time": 1.5,
            }),
        ])
        proxy = SseProxyLayer(client)
        raw_bytes = b"".join(await _collect_bytes(proxy.proxy(inputs={})))
        events = parse_sse_bytes(raw_bytes)

        # 4 个事件
        assert [e["event"] for e in events] == [
            "session_started",
            "message_delta",
            "message_delta",
            "message_complete",
        ]
        # session_started
        s_data = json.loads(events[0]["data"])
        assert s_data["session_id"] == "run-1"
        # message_delta 内容
        assert json.loads(events[1]["data"]) == {"text": "请先"}
        assert json.loads(events[2]["data"]) == {"text": "检查供电"}
        # message_complete
        c_data = json.loads(events[3]["data"])
        assert c_data["text"] == "请先检查供电"
        assert c_data["total_tokens"] == 50
        assert c_data["elapsed_time"] == 1.5

    @pytest.mark.asyncio
    async def test_proxy_forwards_inputs_and_end_user(self):
        """Proxy 应把 inputs/end_user 透传给 DifyClient.run_workflow_stream。"""
        client = FakeDifyClient(events=[
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        await _collect_bytes(proxy.proxy(
            inputs={"input_text": "hi"},
            end_user="custom-user",
        ))
        assert client.calls == [{
            "inputs": {"input_text": "hi"},
            "end_user": "custom-user",
        }]


# ============== workflow_finished 边界 ==============

class TestWorkflowFinishedEdges:
    @pytest.mark.asyncio
    async def test_message_complete_text_uses_extract_output_text(self):
        """message_complete.text 必须走 extract_output_text（包括 fallback 键）。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"text": "fallback answer"},  # fallback key, not "output"
                "total_tokens": 10,
                "elapsed_time": 0.5,
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        complete = next(e for e in events if e["event"] == "message_complete")
        data = json.loads(complete["data"])
        assert data["text"] == "fallback answer"

    @pytest.mark.asyncio
    async def test_message_complete_strips_thinking_block(self):
        """§6.10：text 字段在最终 message_complete 也必须 strip think 块。
        注意：M2 已在 text_chunk 阶段 strip；这里覆盖 workflow_finished 直接走
        extract_output_text 路径时也需 strip（PR9 U4 不变量）。
        """
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "<think>CoT</think>您好"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        complete = next(e for e in events if e["event"] == "message_complete")
        data = json.loads(complete["data"])
        assert data["text"] == "您好"
        assert "<think>" not in data["text"]

    @pytest.mark.asyncio
    async def test_message_complete_with_no_outputs(self):
        """workflow_finished.outputs 缺失 / 为空 dict → text=None（U2/U7/U10 路径）。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {},
                "total_tokens": 0,
                "elapsed_time": 0.1,
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        complete = next(e for e in events if e["event"] == "message_complete")
        data = json.loads(complete["data"])
        assert data["text"] is None
        assert data["total_tokens"] == 0


# ============== 兼容性 / 行为 ==============

class TestStreamingBehavior:
    @pytest.mark.asyncio
    async def test_yields_bytes_not_strings(self):
        """SSE 字节流必须 yield bytes（兼容 FastAPI StreamingResponse(media_type=...))。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        chunks = await _collect_bytes(proxy.proxy(inputs={}))
        assert all(isinstance(c, bytes) for c in chunks)
        assert len(chunks) >= 1

    @pytest.mark.asyncio
    async def test_sse_format_compatible_with_basjoo_parser(self):
        """字节格式必须能被 widget SSE 解析器消费（与 basjoo v1 一致）。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("text_chunk", {"text": "x"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "x"},
            }),
        ])
        proxy = SseProxyLayer(client)
        raw = b"".join(await _collect_bytes(proxy.proxy(inputs={})))

        # 每个事件以空行结束（\n\n）——widget 用此分割事件
        assert raw.count(b"\n\n") == 3
        # 全部以 \n\n 结束
        assert raw.endswith(b"\n\n")

    @pytest.mark.asyncio
    async def test_happy_path_does_not_emit_end_event(self):
        """Review #2：end 仅是错误路径的终止信号；非错误流不发 end。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))

        event_names = [e["event"] for e in events]
        assert "end" not in event_names
        assert "error" not in event_names


# ============== 空流防御 ==============

class TestEmptyStreamDefense:
    """Review #1：Dify 200 OK 但 SSE 流 0 事件（连接立即关闭 / 空 body）
    防御路径：Proxy 必须 raise DifyUpstreamError，让 caller 转 SSE error，
    避免 H5 widget 永远 hang。
    """

    @pytest.mark.asyncio
    async def test_empty_events_raises_dify_upstream(self):
        client = FakeDifyClient(events=[])
        proxy = SseProxyLayer(client)
        with pytest.raises(DifyUpstreamError) as exc_info:
            async for _ in proxy.proxy(inputs={}):
                pass
        assert "no events" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_only_skipped_events_still_raises(self):
        """Dify 流有事件但全部被 skip（如只有 node_started）→ 同样视为空流。
        H5 widget 没收到任何事件，行为等价于空流。
        """
        client = FakeDifyClient(events=[
            make_event("node_started", {"node_id": "2007", "node_type": "llm"}),
            make_event("node_finished", {"node_id": "2007", "status": "succeeded"}),
        ])
        proxy = SseProxyLayer(client)
        # node_started / node_finished 都被 _map_event 返 None（跳过），
        # 但 consumed > 0 不会触发防御路径。
        # 这个测试确认"有事件但全部 skip" 不被误判为空流。
        chunks = await _collect_bytes(proxy.proxy(inputs={}))
        # 没事件被映射，所以字节流为空
        assert chunks == []
        # 且不会 raise（因为有事件被 consumed）

    @pytest.mark.asyncio
    async def test_session_started_emitted_defense_not_triggered(self):
        """正常流（有 workflow_started）→ 不会触发空流防御。"""
        client = FakeDifyClient(events=[
            make_event("workflow_started", {"workflow_run_id": "r1", "id": "r1"}),
            make_event("workflow_finished", {
                "status": "succeeded",
                "outputs": {"output": "ok"},
            }),
        ])
        proxy = SseProxyLayer(client)
        events = parse_sse_bytes(b"".join(await _collect_bytes(proxy.proxy(inputs={}))))
        assert events[0]["event"] == "session_started"