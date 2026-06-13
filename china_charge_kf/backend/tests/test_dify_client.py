"""M2 DifyClient 测试。

覆盖来源：
- M1.5 v5 findings (§1.2 / §1.3 / §2.2) — 真实 SSE 事件形态 + 错误响应
- PR8 — `sse-event-mapping.md §6.5` 错误码映射（DIFY_AUTH / DIFY_BAD_REQUEST / DIFY_UPSTREAM）
- PR9 — `api-contract-dify.md §4.2.1` extract_output_text 单测（U1-U10）
- PR10 — `api-contract-dify.md §4.2` 输入契约 file-list（不动现有序列化代码）

RED 阶段：本文件先写完，pytest 应全部失败（方法/类尚未实现）。
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from app_dify.dify_client import (
    DifyAuthError,
    DifyBadRequestError,
    DifyClient,
    DifyError,
    DifyUpstreamError,
    extract_output_text,
)


# ============== Fixtures ==============

@pytest.fixture
def client() -> DifyClient:
    return DifyClient(
        api_base="https://dify.test/v1",
        api_key="app-test-key",
        end_user="test-user",
    )


@pytest.fixture
def api_base() -> str:
    return "https://dify.test"


def sse_bytes(events: list[dict[str, Any]]) -> bytes:
    """把事件列表序列化为 SSE 字节流。

    每个 event dict 必须含 'event'（事件名）和 'data'（payload dict）。
    """
    out: list[str] = []
    for e in events:
        out.append(f"event: {e['event']}")
        out.append(f"data: {json.dumps(e['data'], ensure_ascii=False)}")
        out.append("")
        out.append("")
    return "\n".join(out).encode("utf-8")


async def _collect(agen):
    """消费 async generator，收集所有 yield。"""
    out = []
    async for item in agen:
        out.append(item)
    return out


# ============== Error 子类存在性 ==============

class TestErrorSubclasses:
    def test_subclasses_inherit_from_dify_error(self):
        for cls in (DifyAuthError, DifyBadRequestError, DifyUpstreamError):
            assert issubclass(cls, DifyError)

    def test_subclasses_inherit_from_runtime_error(self):
        """保证现有 except DifyError / except RuntimeError 捕获路径不变。"""
        for cls in (DifyAuthError, DifyBadRequestError, DifyUpstreamError):
            assert issubclass(cls, RuntimeError)

    def test_subclasses_carry_distinct_messages(self):
        e_auth = DifyAuthError("auth fail")
        e_bad = DifyBadRequestError("bad request")
        e_up = DifyUpstreamError("upstream fail")
        assert "auth fail" in str(e_auth)
        assert "bad request" in str(e_bad)
        assert "upstream fail" in str(e_up)

    def test_subclasses_carry_status_code(self):
        """错误实例应记录 HTTP 状态码便于日志/告警（PR8 错误码映射来源）。"""
        e_auth = DifyAuthError("msg", status_code=401)
        e_bad = DifyBadRequestError("msg", status_code=400)
        e_up = DifyUpstreamError("msg", status_code=200)
        assert e_auth.status_code == 401
        assert e_bad.status_code == 400
        assert e_up.status_code == 200


# ============== run_workflow_blocking ==============

class TestRunWorkflowBlocking:
    @pytest.mark.asyncio
    async def test_succeeded_returns_full_body(self, client, api_base):
        body = {
            "workflow_run_id": "r1",
            "task_id": "t1",
            "data": {
                "id": "r1",
                "status": "succeeded",
                "outputs": {"output": "请先检查供电"},
                "error": None,
                "total_tokens": 100,
                "elapsed_time": 2.5,
            },
        }
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            result = await client.run_workflow_blocking(inputs={"input_text": "hello"})

        assert result == body
        assert result["data"]["outputs"]["output"] == "请先检查供电"
        request = route.calls.last.request
        payload = json.loads(request.content)
        assert payload["response_mode"] == "blocking"
        assert payload["inputs"] == {"input_text": "hello"}
        assert payload["user"] == "test-user"

    @pytest.mark.asyncio
    async def test_401_raises_dify_auth_error(self, client, api_base):
        err_body = {
            "code": "unauthorized",
            "message": "Access token is invalid",
            "status": 401,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(401, json=err_body)
            )
            with pytest.raises(DifyAuthError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

        assert exc_info.value.status_code == 401
        assert "Access token is invalid" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_400_must_be_string_raises_bad_request(self, client, api_base):
        err_body = {
            "code": "invalid_param",
            "message": "input_img_id in input form must be a string",
            "status": 400,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(400, json=err_body)
            )
            with pytest.raises(DifyBadRequestError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

        assert exc_info.value.status_code == 400
        assert "must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_400_must_be_file_raises_bad_request(self, client, api_base):
        err_body = {
            "code": "invalid_param",
            "message": "input_img_id in input form must be a file",
            "status": 400,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(400, json=err_body)
            )
            with pytest.raises(DifyBadRequestError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

        assert "must be a file" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_400_invalid_upload_file_raises_bad_request(self, client, api_base):
        """S6 实测：假 upload_file_id 直接被 Dify 平台层 400 拦截。"""
        err_body = {
            "code": "invalid_param",
            "message": "Invalid upload file",
            "status": 400,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(400, json=err_body)
            )
            with pytest.raises(DifyBadRequestError):
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

    @pytest.mark.asyncio
    async def test_200_status_failed_plugin_error_raises_upstream(self, client, api_base):
        """S6b 实测：v2 workflow 内部 LLM 插件失败。"""
        body = {
            "workflow_run_id": "r1",
            "task_id": "t1",
            "data": {
                "status": "failed",
                "outputs": {},
                "error": (
                    "req_id: e1e91af65d PluginInvokeError: "
                    "ArkBadRequestError: image too small"
                ),
            },
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            with pytest.raises(DifyUpstreamError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

        assert "PluginInvokeError" in str(exc_info.value)
        assert "ArkBadRequestError" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_200_status_failed_non_plugin_raises_upstream(self, client, api_base):
        """非 PluginInvokeError 但 status=failed 也应抛 DifyUpstreamError（兜底）。"""
        body = {"data": {"status": "failed", "error": "some other error", "outputs": {}}}
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            with pytest.raises(DifyUpstreamError):
                await client.run_workflow_blocking(inputs={"input_text": "hi"})

    @pytest.mark.asyncio
    async def test_end_user_override(self, client, api_base):
        """run_workflow_blocking 接受 end_user 覆盖 self.end_user。"""
        body = {"data": {"status": "succeeded", "outputs": {"output": "ok"}}}
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            await client.run_workflow_blocking(
                inputs={"input_text": "hi"},
                end_user="override-user",
            )
        payload = json.loads(route.calls.last.request.content)
        assert payload["user"] == "override-user"


# ============== run_workflow_stream ==============

class TestRunWorkflowStream:
    @pytest.mark.asyncio
    async def test_yields_events_in_order(self, client, api_base):
        """S1 实测：workflow_started → text_chunk*N → workflow_finished。"""
        events = [
            {
                "event": "workflow_started",
                "data": {"task_id": "t1", "workflow_run_id": "r1", "data": {"id": "r1"}},
            },
            {
                "event": "text_chunk",
                "data": {
                    "node_id": "2007",
                    "text": "你好",
                    "from_variable_selector": ["2007", "text"],
                },
            },
            {
                "event": "text_chunk",
                "data": {
                    "node_id": "2007",
                    "text": "世界",
                    "from_variable_selector": ["2007", "text"],
                },
            },
            {
                "event": "workflow_finished",
                "data": {
                    "id": "r1",
                    "status": "succeeded",
                    "outputs": {"output": "你好世界"},
                    "total_tokens": 50,
                    "elapsed_time": 1.5,
                },
            },
        ]
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            collected = await _collect(
                client.run_workflow_stream(inputs={"input_text": "hi"})
            )

        assert [e["event"] for e in collected] == [
            "workflow_started",
            "text_chunk",
            "text_chunk",
            "workflow_finished",
        ]
        assert collected[1]["data"]["text"] == "你好"
        assert collected[3]["data"]["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_text_chunk_thinking_block_stripped(self, client, api_base):
        """§6.10：text_chunk 阶段必须 strip <think>...</think> 块。"""
        events = [
            {
                "event": "text_chunk",
                "data": {
                    "node_id": "2007",
                    "text": "<think>\n让我想想</think>您好",
                    "from_variable_selector": ["2007", "text"],
                },
            },
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "您好"}},
            },
        ]
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            collected = await _collect(
                client.run_workflow_stream(inputs={"input_text": "hi"})
            )

        chunk = collected[0]
        assert chunk["event"] == "text_chunk"
        assert "<think>" not in chunk["data"]["text"]
        assert "您好" in chunk["data"]["text"]

    @pytest.mark.asyncio
    async def test_text_chunk_only_thinking_yields_empty(self, client, api_base):
        """§6.10：整段是 think 块时 strip 后为空。"""
        events = [
            {
                "event": "text_chunk",
                "data": {
                    "node_id": "2007",
                    "text": "<think>\nCoT</think>",
                    "from_variable_selector": ["2007", "text"],
                },
            },
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "后续回复"}},
            },
        ]
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            collected = await _collect(
                client.run_workflow_stream(inputs={"input_text": "hi"})
            )

        chunk = next(e for e in collected if e["event"] == "text_chunk")
        assert chunk["data"]["text"] == ""

    @pytest.mark.asyncio
    async def test_ping_events_are_skipped(self, client, api_base):
        """ping 事件（保活）不应 yield 给调用方（M0.5 §2.2.3）。"""
        events = [
            {"event": "workflow_started", "data": {"id": "r1"}},
            {"event": "ping", "data": {}},
            {
                "event": "text_chunk",
                "data": {"text": "ok", "from_variable_selector": ["2007", "text"]},
            },
            {"event": "ping", "data": {}},
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "ok"}},
            },
        ]
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            collected = await _collect(
                client.run_workflow_stream(inputs={"input_text": "hi"})
            )

        assert all(e["event"] != "ping" for e in collected)
        assert len(collected) == 3

    @pytest.mark.asyncio
    async def test_workflow_finished_failed_raises_upstream(self, client, api_base):
        """流式路径 status=failed → DifyUpstreamError（允许调用方先消费前面的事件再 raise）。"""
        events = [
            {"event": "workflow_started", "data": {"id": "r1"}},
            {
                "event": "text_chunk",
                "data": {"text": "部分输出", "from_variable_selector": ["2007", "text"]},
            },
            {
                "event": "workflow_finished",
                "data": {
                    "status": "failed",
                    "outputs": {},
                    "error": "PluginInvokeError: rate_limit exceeded",
                },
            },
        ]
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                    pass
        assert "PluginInvokeError" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_401_during_streaming_raises_auth_error(self, client, api_base):
        err_body = {
            "code": "unauthorized",
            "message": "Access token is invalid",
            "status": 401,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(401, json=err_body)
            )
            with pytest.raises(DifyAuthError) as exc_info:
                async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                    pass
        assert "Access token is invalid" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_400_during_streaming_raises_bad_request(self, client, api_base):
        err_body = {
            "code": "invalid_param",
            "message": "Invalid upload file",
            "status": 400,
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(400, json=err_body)
            )
            with pytest.raises(DifyBadRequestError):
                async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                    pass

    @pytest.mark.asyncio
    async def test_request_uses_streaming_response_mode(self, client, api_base):
        """流式端点必须在请求体声明 response_mode=streaming。"""
        events = [
            {"event": "workflow_started", "data": {"id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "ok"}},
            },
        ]
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            await _collect(client.run_workflow_stream(inputs={"input_text": "hi"}))
        payload = json.loads(route.calls.last.request.content)
        assert payload["response_mode"] == "streaming"
        assert payload["user"] == "test-user"

    @pytest.mark.asyncio
    async def test_end_user_override(self, client, api_base):
        """run_workflow_stream 接受 end_user 覆盖 self.end_user。"""
        events = [
            {"event": "workflow_started", "data": {"id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "ok"}},
            },
        ]
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=sse_bytes(events),
                )
            )
            await _collect(
                client.run_workflow_stream(
                    inputs={"input_text": "hi"},
                    end_user="custom-user",
                )
            )
        payload = json.loads(route.calls.last.request.content)
        assert payload["user"] == "custom-user"


# ============== extract_output_text (PR9 U1-U10) ==============

class TestExtractOutputText:
    """PR9 单测 — 来自 `docs/api-contract-dify.md §4.2.1` 表 U1-U10。

    关键不变量：
    - status=failed 时**不**返回 None（U5：error 兜底；U6：outputs 优先）
    - _strip_thinking 必须在所有返回路径上调用（U4 幂等）
    - 空字符串/纯空白视为无输出，返回 None（U8/U9）
    - 缺失字段、null 字段、空 data 都不抛异常（U2/U7/U10）
    """

    def test_u1_normal_succeeded(self):
        data = {"status": "succeeded", "outputs": {"output": "请先检查供电..."}}
        assert extract_output_text(data, "output") == "请先检查供电..."

    def test_u2_empty_outputs_dict(self):
        data = {"status": "succeeded", "outputs": {}}
        assert extract_output_text(data, "output") is None

    def test_u3_fallback_key_hit(self):
        """V10b：yml 输出变量名漂移到 'text' 时 fallback 命中。"""
        data = {"status": "succeeded", "outputs": {"text": "fallback answer..."}}
        assert extract_output_text(data, "output") == "fallback answer..."

    def test_u4_strip_think_block(self):
        data = {"status": "succeeded", "outputs": {"output": "<think>CoT</think>您好"}}
        assert extract_output_text(data, "output") == "您好"

    def test_u5_status_failed_extract_error(self):
        """v2 S6b 新增：status=failed 时从 data.error 提取（**不**返回 None）。"""
        data = {
            "status": "failed",
            "error": "PluginInvokeError: ArkBadRequestError: image too small",
            "outputs": {},
        }
        result = extract_output_text(data, "output")
        assert result is not None
        assert "PluginInvokeError" in result
        assert "ArkBadRequestError" in result

    def test_u6_status_failed_outputs_priority(self):
        """status=failed 但 outputs 非空 → outputs 优先（M0.5 D6）。"""
        data = {
            "status": "failed",
            "error": "PluginInvokeError: some error",
            "outputs": {"output": "partial answer"},
        }
        assert extract_output_text(data, "output") == "partial answer"

    def test_u7_outputs_is_null(self):
        """outputs=null 时不应抛 AttributeError，返 None。"""
        data = {"status": "stopped", "outputs": None}
        assert extract_output_text(data, "output") is None

    def test_u8_empty_string_output(self):
        data = {"status": "succeeded", "outputs": {"output": ""}}
        assert extract_output_text(data, "output") is None

    def test_u9_whitespace_only_output(self):
        data = {"status": "succeeded", "outputs": {"output": "   "}}
        assert extract_output_text(data, "output") is None

    def test_u10_completely_empty_data(self):
        assert extract_output_text({}, "output") is None

    def test_strip_thinking_idempotent(self):
        """_strip_thinking 幂等：多次调用结果一致。"""
        raw = "<think>step1</think>中间<think>step2</think>结尾"
        once = extract_output_text(
            {"status": "succeeded", "outputs": {"output": raw}}, "output"
        )
        twice = extract_output_text(
            {"status": "succeeded", "outputs": {"output": once}}, "output"
        )
        assert once == twice == "中间结尾"

    def test_non_dict_data_returns_none(self):
        """data 是非 dict（list/str/None）时不抛异常，返 None。"""
        assert extract_output_text(None, "output") is None  # type: ignore[arg-type]
        assert extract_output_text([], "output") is None  # type: ignore[arg-type]
        assert extract_output_text("just a string", "output") is None  # type: ignore[arg-type]

    def test_outputs_is_non_dict_returns_none(self):
        """outputs 是非 dict（list/str）时 fallback dict 后再判定为空。"""
        assert extract_output_text({"outputs": "weird"}, "output") is None
        assert extract_output_text({"outputs": [1, 2]}, "output") is None

    def test_status_failed_with_no_error_returns_none(self):
        """status=failed 但 error 字段也缺失/非字符串 → 返 None（U5 兜底无内容时）。"""
        data = {"status": "failed", "outputs": {}}
        assert extract_output_text(data, "output") is None
        data2 = {"status": "failed", "outputs": {}, "error": None}
        assert extract_output_text(data2, "output") is None

    def test_status_failed_with_non_string_error_returns_none(self):
        """status=failed 但 error 是 dict/list 时不抛异常。"""
        data = {"status": "failed", "outputs": {}, "error": {"code": "x"}}
        assert extract_output_text(data, "output") is None

    def test_whitespace_output_via_fallback_key(self):
        """fallback 键命中空白字符串也应视为无输出。"""
        data = {"status": "succeeded", "outputs": {"text": "   "}}
        assert extract_output_text(data, "output") is None

    def test_non_string_output_value_ignored(self):
        """outputs[output_key] 是 dict/list/None 时视为无主输出，回退 fallback。"""
        data = {
            "status": "succeeded",
            "outputs": {"output": {"nested": "x"}, "text": "real answer"},
        }
        assert extract_output_text(data, "output") == "real answer"


# ============== _strip_thinking 直接单测 ==============

class TestStripThinking:
    """直接覆盖 `_strip_thinking` 边界（line 69 空文本早返回）。"""

    def test_empty_string(self):
        from app_dify.dify_client import _strip_thinking
        assert _strip_thinking("") == ""

    def test_none_safe(self):
        """空串/纯空白都被视为无内容。"""
        from app_dify.dify_client import _strip_thinking
        assert _strip_thinking("   \n\t  ") == ""

    def test_no_think_block_unchanged(self):
        from app_dify.dify_client import _strip_thinking
        assert _strip_thinking("普通文本") == "普通文本"

    def test_multiple_think_blocks(self):
        from app_dify.dify_client import _strip_thinking
        raw = "<think>a</think>A<think>b</think>B"
        assert _strip_thinking(raw) == "AB"


# ============== _parse_sse_event 直接单测 ==============

class TestParseSseEvent:
    """直接覆盖 `_parse_sse_event` 边界（line 130 空 data / lines 133-135 JSON 错误）。"""

    def test_empty_data_returns_none(self):
        from app_dify.dify_client import _parse_sse_event
        assert _parse_sse_event({"event": "text_chunk", "data": ""}) is None
        assert _parse_sse_event({"event": "text_chunk", "data": "   "}) is None

    def test_invalid_json_returns_none(self):
        from app_dify.dify_client import _parse_sse_event
        result = _parse_sse_event({"event": "text_chunk", "data": "not-json{"})
        assert result is None

    def test_ping_returns_none(self):
        from app_dify.dify_client import _parse_sse_event
        result = _parse_sse_event({"event": "ping", "data": "{}"})
        assert result is None

    def test_payload_with_inner_data_flattens(self):
        from app_dify.dify_client import _parse_sse_event
        result = _parse_sse_event({
            "event": "text_chunk",
            "data": json.dumps({
                "event": "text_chunk",
                "data": {"text": "hi", "from_variable_selector": ["x"]},
            }),
        })
        assert result == {
            "event": "text_chunk",
            "data": {"text": "hi", "from_variable_selector": ["x"]},
        }

    def test_payload_without_inner_data_passthrough(self):
        from app_dify.dify_client import _parse_sse_event
        result = _parse_sse_event({
            "event": "workflow_finished",
            "data": json.dumps({"status": "succeeded"}),
        })
        assert result == {"event": "workflow_finished", "data": {"status": "succeeded"}}

    def test_text_chunk_strips_thinking_in_helper(self):
        """text_chunk 的 strip 是在 _parse_sse_event 内部做的，单独验证。"""
        from app_dify.dify_client import _parse_sse_event
        result = _parse_sse_event({
            "event": "text_chunk",
            "data": json.dumps({
                "event": "text_chunk",
                "data": {"text": "<think>CoT</think>答案", "node_id": "2007"},
            }),
        })
        assert result["data"]["text"] == "答案"


# ============== upload_file ==============

class TestUploadFile:
    """PR10 锁定：upload_file 签名不可变；本套测试覆盖成功 + 失败路径。"""

    @pytest.mark.asyncio
    async def test_upload_file_success_returns_id(self, client, api_base):
        body = {"id": "file-uuid-abc", "name": "voice.wav", "mime_type": "audio/wav"}
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json=body)
            )
            file_id = await client.upload_file(
                filename="voice.wav",
                content=b"RIFF....",
                content_type="audio/wav",
            )
        assert file_id == "file-uuid-abc"
        request = route.calls.last.request
        # multipart: filename + content-type + user field 都应在请求体内
        body_text = request.content.decode("latin-1")
        assert "voice.wav" in body_text
        assert "audio/wav" in body_text
        assert "test-user" in body_text

    @pytest.mark.asyncio
    async def test_upload_file_4xx_raises_dify_error(self, client, api_base):
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/files/upload").mock(
                return_value=httpx.Response(400, text="bad file")
            )
            with pytest.raises(DifyError) as exc_info:
                await client.upload_file(
                    filename="x.bin", content=b"x", content_type=None
                )
        # PR10 锁定的 upload_file 不传 status_code，但 4xx 文本应透传
        assert "bad file" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_upload_file_no_id_raises_dify_error(self, client, api_base):
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json={"name": "x"})
            )
            with pytest.raises(DifyError) as exc_info:
                await client.upload_file(
                    filename="x.bin", content=b"x", content_type="application/octet-stream"
                )
        assert "no id" in str(exc_info.value)


# ============== run_workflow_blocking 错误码覆盖 ==============

class TestRunWorkflowBlockingErrors:
    """补 5xx / 其他 4xx 路径（line 253, 258）。"""

    @pytest.mark.asyncio
    async def test_500_raises_upstream_error(self, client, api_base):
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(500, text="internal")
            )
            with pytest.raises(DifyUpstreamError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})
        assert exc_info.value.status_code == 500
        assert "internal" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_403_raises_generic_dify_error(self, client, api_base):
        """403 不是 401/400/5xx → 走通用 DifyError（兜底）。"""
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(403, text="forbidden")
            )
            with pytest.raises(DifyError) as exc_info:
                await client.run_workflow_blocking(inputs={"input_text": "hi"})
        # 403 不是 DIFY_AUTH（401）或 DIFY_BAD_REQUEST（400），应是裸 DifyError
        assert not isinstance(exc_info.value, DifyAuthError)
        assert not isinstance(exc_info.value, DifyBadRequestError)
        assert not isinstance(exc_info.value, DifyUpstreamError)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_status_stopped_raises_upstream(self, client, api_base):
        """status=stopped 同样视为上游失败（与 failed 对称）。"""
        body = {
            "data": {
                "status": "stopped",
                "outputs": {},
                "error": "user cancelled",
            }
        }
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            with pytest.raises(DifyUpstreamError):
                await client.run_workflow_blocking(inputs={"input_text": "hi"})


# ============== run_workflow_stream 错误码覆盖 ==============

class TestRunWorkflowStreamErrors:
    """补 5xx / 其他 4xx / 末尾事件 路径（line 334-335, 341-342, 367-370）。"""

    @pytest.mark.asyncio
    async def test_500_raises_upstream_error(self, client, api_base):
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(500, text="upstream down")
            )
            with pytest.raises(DifyUpstreamError) as exc_info:
                async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                    pass
        assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_403_raises_generic_dify_error(self, client, api_base):
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(403, text="forbidden")
            )
            with pytest.raises(DifyError) as exc_info:
                async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                    pass
        assert exc_info.value.status_code == 403
        assert not isinstance(exc_info.value, DifyAuthError)

    @pytest.mark.asyncio
    async def test_final_event_without_trailing_blank_line(self, client, api_base):
        """流以非空行结尾（缺尾随空行）时也应被解析。"""
        # 直接构造一个无尾随换行的 SSE 流
        raw = (
            "event: workflow_started\n"
            "data: {\"id\":\"r1\"}\n"
            "\n"
            "event: workflow_finished\n"
            "data: {\"status\":\"succeeded\",\"outputs\":{\"output\":\"ok\"}}"
        ).encode("utf-8")
        with respx.mock(base_url=api_base) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=raw,
                )
            )
            collected = await _collect(
                client.run_workflow_stream(inputs={"input_text": "hi"})
            )
        # 末尾无空行也必须解析到 workflow_finished
        assert any(e["event"] == "workflow_finished" for e in collected)


# ============== run_workflow (legacy alias) ==============

class TestRunWorkflowLegacyAlias:
    """PR10 兼容：run_workflow 保留作为 run_workflow_blocking 别名。"""

    @pytest.mark.asyncio
    async def test_blocking_mode_delegates(self, client, api_base):
        body = {"data": {"status": "succeeded", "outputs": {"output": "ok"}}}
        with respx.mock(base_url=api_base) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json=body)
            )
            result = await client.run_workflow(
                inputs={"input_text": "hi"},
                response_mode="blocking",
            )
        assert result == body
        payload = json.loads(route.calls.last.request.content)
        assert payload["response_mode"] == "blocking"

    @pytest.mark.asyncio
    async def test_streaming_mode_rejected(self, client):
        """非 blocking 模式 → DifyError（流式必须用 run_workflow_stream）。"""
        with pytest.raises(DifyError) as exc_info:
            await client.run_workflow(
                inputs={"input_text": "hi"},
                response_mode="streaming",
            )
        assert "run_workflow_stream" in str(exc_info.value)


# ============== H1/C2 防御性路径 ==============

class TestDefensiveErrorPaths:
    """Code review H1+C2：流式 mid-stream 错误 + body read 失败都应归一化为 Dify 错误类。"""

    @pytest.mark.asyncio
    async def test_stream_midstream_network_error_raises_upstream(self, client, api_base, monkeypatch):
        """H1：aiter_lines 中途 httpx 错误 → DifyUpstreamError（不泄漏 httpx.HTTPError）。"""
        from httpx import AsyncClient
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _stream_with_boom(*_args, **_kwargs):
            class _Resp:
                status_code = 200
                async def aiter_lines(self):
                    raise httpx.RemoteProtocolError("server closed connection")
                    yield ""  # noqa: unreachable — make this a generator
            yield _Resp()

        monkeypatch.setattr(AsyncClient, "stream", _stream_with_boom)

        with pytest.raises(DifyUpstreamError) as exc_info:
            async for _ in client.run_workflow_stream(inputs={"input_text": "hi"}):
                pass
        assert "stream interrupted" in str(exc_info.value).lower()
        assert "RemoteProtocolError" in str(exc_info.value)

    def test_safe_body_text_handles_unreadable_body(self):
        from app_dify.dify_client import _safe_body_text
        class _BadResp:
            @property
            def text(self):
                raise RuntimeError("body unavailable")
        result = _safe_body_text(_BadResp())
        assert "body read failed" in result
        assert "RuntimeError" in result

    @pytest.mark.asyncio
    async def test_safe_aread_handles_unreadable_body(self):
        from app_dify.dify_client import _safe_aread
        class _BadResp:
            async def aread(self):
                raise RuntimeError("aread boom")
        result = await _safe_aread(_BadResp())
        assert "body read failed" in result
        assert "RuntimeError" in result