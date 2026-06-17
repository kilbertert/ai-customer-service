"""M4 FastAPI wiring 测试。

覆盖 (per M4 brief)：
- GET /health：200 + {"status": "ok"}
- POST /api/chat/stream：
  - happy path：respx mock Dify 完整 SSE 流 → 解析 session_started / message_delta / message_complete
  - 4 类错误路径：Dify 401/400/5xx → SSE event:error + event:end
  - 0-事件空流防御：respx 200 + 空 body → 端点必须 yield error{DIFY_UPSTREAM} + end
  - CORS preflight：OPTIONS → Access-Control-Allow-Origin
  - end_user 默认值来自 .env
  - language 透传
  - file_ids 路径：DifyClient.upload_file 不被调用（DifyClient.run_workflow_stream 被调用）
- POST /api/files/upload：multipart 上传 → respx mock /v1/files/upload → 返回 {"file_id": "..."}

测试策略：
- 使用 FastAPI TestClient (sync, supports streaming via response.iter_bytes)
- respx 在 network 层 mock Dify
- monkeypatch settings 让 DifyClient 指向测试 base URL
- 解析 SSE 字节流 (复用 M3 test_sse_proxy_layer.parse_sse_bytes 模式)
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from services.dify.config import settings
from services.dify.main import app


# ============== Constants ==============

TEST_API_BASE = "http://dify.test"
TEST_API_BASE_URL = f"{TEST_API_BASE}/v1"
TEST_V2_KEY = "app-test-v2-key"
TEST_V1_KEY = "app-test-v1-key"
TEST_DEFAULT_END_USER = "test-h5-user"


# ============== SSE helpers ==============

def sse_dify_bytes(events: list[dict[str, Any]]) -> bytes:
    """把 Dify 事件列表序列化为 Dify SSE 字节流（format B — outer data JSON）。

    M0.5 §2.1.1 format B：
        event: workflow_started
        data: {"event":"workflow_started","data":{...}}

    本测试只走 outer-`data` 含 `event`+`data` 的形态，与真实 Dify 输出一致。
    """
    out: list[str] = []
    for e in events:
        out.append(f"event: {e['event']}")
        out.append(
            "data: " + json.dumps(
                {"event": e["event"], "data": e["data"]},
                ensure_ascii=False,
            )
        )
        out.append("")
        out.append("")
    return "\n".join(out).encode("utf-8")


def parse_sse_bytes(raw: bytes) -> list[dict[str, str]]:
    """解析 SSE 字节流为 [{event, data}]，跳过空行。"""
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


def parse_event_data(event: dict[str, str]) -> dict[str, Any]:
    """把 SSE event 的 data 字段（JSON 字符串）反序列化为 dict。"""
    return json.loads(event["data"])


# ============== Fixtures ==============

@pytest.fixture
def patched_settings(monkeypatch):
    """Override settings to use test Dify base + keys. v1 != v2 以便测试 v2 key 走流。"""
    monkeypatch.setattr(settings, "dify_api_base", TEST_API_BASE_URL)
    monkeypatch.setattr(settings, "dify_v2_api_key", TEST_V2_KEY)
    monkeypatch.setattr(settings, "dify_api_key", TEST_V1_KEY)  # 故意设成不同值
    monkeypatch.setattr(settings, "dify_end_user", TEST_DEFAULT_END_USER)
    return settings


@pytest.fixture
def client(patched_settings):
    """FastAPI TestClient (sync, supports streaming responses)."""
    return TestClient(app)


# ============== GET /health ==============

class TestHealth:
    def test_health_returns_status_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_simple_no_dify_call(self, client):
        """/health 不应触发任何 Dify 调用 — 纯 liveness probe。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            # 如果有意外调用,respx 未注册的 route 会 raise
            resp = client.get("/health")
        assert resp.status_code == 200


# ============== POST /api/chat/stream — Happy path ==============

class TestChatStreamHappyPath:
    def test_full_dify_stream_maps_to_h5_events(self, client):
        """S1 纯文本：session_started → 2x message_delta → message_complete。"""
        dify_events = [
            {"event": "workflow_started", "data": {"workflow_run_id": "r1", "id": "r1"}},
            {"event": "text_chunk", "data": {"node_id": "2007", "text": "请先"}},
            {"event": "text_chunk", "data": {"node_id": "2007", "text": "检查"}},
            {"event": "workflow_finished", "data": {
                "status": "succeeded",
                "outputs": {"output": "请先检查"},
                "total_tokens": 50,
                "elapsed_time": 1.5,
            }},
        ]

        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes(dify_events),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                assert resp.status_code == 200
                assert resp.headers["content-type"].startswith("text/event-stream")
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        names = [e["event"] for e in parsed]
        assert names == [
            "session_started",
            "message_delta",
            "message_delta",
            "message_complete",
        ]
        assert parse_event_data(parsed[0])["session_id"] == "r1"
        assert parse_event_data(parsed[1]) == {"text": "请先"}
        assert parse_event_data(parsed[2]) == {"text": "检查"}
        complete = parse_event_data(parsed[3])
        assert complete["text"] == "请先检查"
        assert complete["total_tokens"] == 50
        assert complete["elapsed_time"] == 1.5

        # 验证 Dify 真的被调了 1 次
        assert route.call_count == 1

    def test_endpoint_uses_v2_key_not_v1(self, client):
        """v1 key 与 v2 key 不同时,流端点必须用 v2 key (Bearer header)。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                list(resp.iter_bytes())  # 消费完

        # 抓取实际请求的 Authorization
        request = route.calls[0].request
        auth = request.headers.get("authorization", "")
        assert auth == f"Bearer {TEST_V2_KEY}", f"expected v2 key, got {auth!r}"

    def test_end_user_defaults_to_settings_when_omitted(self, client):
        """请求体不传 end_user → 端点用 settings.dify_end_user。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert body["user"] == TEST_DEFAULT_END_USER

    def test_end_user_override_from_request(self, client):
        """请求体传 end_user → 端点透传,不用 settings.dify_end_user。"""
        custom_user = "custom-test-user"
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream",
                              json={"text": "hi", "end_user": custom_user}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert body["user"] == custom_user

    def test_language_passthrough_to_dify_inputs(self, client):
        """language 字段应透传到 Dify inputs[dify_input_language]。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream",
                              json={"text": "hi", "language": "vi"}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert body["inputs"]["language"] == "vi"
        assert body["inputs"]["input_text"] == "hi"

    def test_text_in_dify_inputs(self, client):
        """text 字段必须作为 Dify inputs[input_text]。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream",
                              json={"text": "用户问题ABC"}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert body["inputs"]["input_text"] == "用户问题ABC"

    def test_response_mode_is_streaming(self, client):
        """DifyClient 必须以 streaming 模式调用 (response_mode=streaming)。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert body["response_mode"] == "streaming"


# ============== POST /api/chat/stream — file_ids 路径 ==============

class TestChatStreamFileIds:
    def test_file_ids_does_not_call_upload_file(self, client):
        """file_ids 是已上传的 ID 列表 — 端点**不应**调 DifyClient.upload_file。

        验证策略：只 mock /v1/workflows/run, 让 respx 对未 mock 的 /v1/files/upload
        路由 fail（如被意外调用）。assert_all_called=False 是因为 respx 默认
        检查所有 mock 路由都被调用过 — 而本测试只注册了 workflows/run。
        """
        with respx.mock(base_url=TEST_API_BASE, assert_all_called=False) as router:
            run_route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            # /v1/files/upload 未注册 — 如果端点意外调它,respx 会因
            # assert_all_mocked=True 默认 fail。或者 httpx 抛 ConnectError。

            with client.stream("POST", "/api/chat/stream",
                              json={"text": "hi", "file_ids": ["file-uuid-1"]}) as resp:
                list(resp.iter_bytes())

        assert run_route.call_count == 1

    def test_file_ids_passed_in_dify_inputs(self, client):
        """file_ids 应被附加到 Dify inputs[input_img_id]（v2 workflow 的 file-list 槽）。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream",
                              json={"text": "hi", "file_ids": ["file-uuid-A", "file-uuid-B"]}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        img_ids = body["inputs"]["input_img_id"]
        assert isinstance(img_ids, list)
        assert len(img_ids) == 2
        for entry in img_ids:
            assert entry["upload_file_id"] in ("file-uuid-A", "file-uuid-B")
            assert entry["transfer_method"] == "local_file"

    def test_no_file_ids_omits_input_img_id(self, client):
        """file_ids 缺省时,Dify inputs 不应含 input_img_id 键。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=sse_dify_bytes([
                        {"event": "workflow_finished", "data": {
                            "status": "succeeded", "outputs": {"output": "ok"},
                        }},
                    ]),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                list(resp.iter_bytes())

        body = json.loads(route.calls[0].request.content)
        assert "input_img_id" not in body["inputs"]


# ============== POST /api/chat/stream — 错误路径 ==============

class TestChatStreamErrors:
    def test_dify_401_yields_dify_auth_error(self, client):
        """Dify 返 401 → SSE event:error{code:DIFY_AUTH} + event:end。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(401, text="Access token is invalid")
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                assert resp.status_code == 200  # SSE 响应本身 200,错误在 body 里
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        names = [e["event"] for e in parsed]
        assert names == ["error", "end"]
        err = parse_event_data(parsed[0])
        assert err["code"] == "DIFY_AUTH"
        assert "Access token is invalid" in err["message"]

    def test_dify_400_yields_dify_bad_request_error(self, client):
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(400, text="Invalid upload file")
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        assert parse_event_data(parsed[0])["code"] == "DIFY_BAD_REQUEST"
        assert "Invalid upload file" in parse_event_data(parsed[0])["message"]
        assert parsed[1]["event"] == "end"

    def test_dify_500_yields_dify_upstream_error(self, client):
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(503, text="Service Unavailable")
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        assert parse_event_data(parsed[0])["code"] == "DIFY_UPSTREAM"
        assert parsed[1]["event"] == "end"

    def test_dify_200_empty_body_yields_dify_upstream(self, client):
        """Review #1 端点层验证：Dify 200 + 空 body → 端点必须 yield error{DIFY_UPSTREAM} + end。

        SseProxyLayer.proxy() 会在 0 事件时 raise DifyUpstreamError，**端点**必须
        catch 这个 raise 并把错误翻译成 SSE bytes。
        """
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    content=b"",  # 空 body → 0 事件
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                assert resp.status_code == 200
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        names = [e["event"] for e in parsed]
        # 关键：必须有 error + end,且 error code 是 DIFY_UPSTREAM
        assert "error" in names
        assert "end" in names
        err_evt = next(e for e in parsed if e["event"] == "error")
        err = parse_event_data(err_evt)
        assert err["code"] == "DIFY_UPSTREAM"
        assert "no events" in err["message"].lower()

    def test_dify_workflow_finished_failed_yields_dify_upstream(self, client):
        """Dify 200 + workflow_finished.status=failed → DIFY_UPSTREAM (经 SseProxyLayer)。"""
        events = [
            {"event": "workflow_started", "data": {"workflow_run_id": "r1", "id": "r1"}},
            {"event": "workflow_finished", "data": {
                "status": "failed",
                "outputs": {},
                "error": "PluginInvokeError: image too small",
            }},
        ]
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200, content=sse_dify_bytes(events),
                    headers={"content-type": "text/event-stream"},
                )
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        # session_started 应被 yield（来自 Dify 第一个事件），然后 error + end
        names = [e["event"] for e in parsed]
        assert "session_started" in names
        assert "error" in names
        assert names[-1] == "end"
        err = parse_event_data(next(e for e in parsed if e["event"] == "error"))
        assert err["code"] == "DIFY_UPSTREAM"
        assert "image too small" in err["message"]

    def test_dify_404_yields_dify_unknown(self, client):
        """其它 HTTP 错误（404）→ DIFY_UNKNOWN (经 SseProxyLayer 兜底分支)。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            with client.stream("POST", "/api/chat/stream", json={"text": "hi"}) as resp:
                chunks = b"".join(resp.iter_bytes())

        parsed = parse_sse_bytes(chunks)
        assert parse_event_data(parsed[0])["code"] == "DIFY_UNKNOWN"


# ============== POST /api/chat/stream — CORS ==============

class TestCors:
    def test_preflight_returns_allow_origin(self, client):
        """OPTIONS preflight 必须带 Access-Control-Allow-Origin。"""
        resp = client.options(
            "/api/chat/stream",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        # CORS middleware 通常返 200
        assert resp.status_code in (200, 204)
        assert "access-control-allow-origin" in {k.lower() for k in resp.headers.keys()}

    def test_health_responds_to_options(self, client):
        """/health (无路由的简单 GET) — 端点本身应可被 OPTIONS 探活。"""
        resp = client.options("/health", headers={"Origin": "http://localhost:5173"})
        # CORSMiddleware 对未注册 method 的 OPTIONS 返 405,但带 CORS 头
        # 只要 access-control-allow-origin 存在即通过
        acao = resp.headers.get("access-control-allow-origin")
        assert acao is not None


# ============== POST /api/chat/stream — 入参校验 ==============

class TestChatStreamValidation:
    def test_missing_text_returns_422(self, client):
        resp = client.post("/api/chat/stream", json={})
        assert resp.status_code == 422

    def test_empty_text_returns_422(self, client):
        """text 是必填且 min_length>=1,空字符串应被拒。"""
        resp = client.post("/api/chat/stream", json={"text": ""})
        assert resp.status_code == 422

    def test_oversized_text_returns_422(self, client):
        """text 最大 2000 字符（v2 workflow input_text.max_length）。"""
        resp = client.post("/api/chat/stream", json={"text": "x" * 2001})
        assert resp.status_code == 422


# ============== POST /api/files/upload ==============

class TestFileUpload:
    def test_upload_returns_file_id(self, client):
        """multipart 上传文件 → 调 Dify /v1/files/upload → 返 {"file_id": "<uuid>"}。"""
        fake_file_id = "uploaded-uuid-abc"
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json={
                    "id": fake_file_id,
                    "name": "test.jpg",
                    "mime_type": "image/jpeg",
                })
            )
            resp = client.post(
                "/api/files/upload",
                files={"file": ("test.jpg", b"fake-jpeg-bytes", "image/jpeg")},
            )

        assert resp.status_code == 200
        assert resp.json() == {"file_id": fake_file_id}
        assert route.call_count == 1

    def test_upload_uses_v2_key(self, client):
        """upload 端点必须用 v2 key (与 streaming 端点一致)。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json={"id": "x"})
            )
            client.post(
                "/api/files/upload",
                files={"file": ("a.txt", b"hello", "text/plain")},
            )

        auth = route.calls[0].request.headers.get("authorization", "")
        assert auth == f"Bearer {TEST_V2_KEY}"

    def test_upload_sends_user_field(self, client):
        """Dify /v1/files/upload 必带 user 字段 (Dify 强制)。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json={"id": "x"})
            )
            client.post(
                "/api/files/upload",
                files={"file": ("a.txt", b"hello", "text/plain")},
            )

        # multipart body — DifyClient.upload_file 用 httpx files= + data= 发,user 在 form field
        request_body = route.calls[0].request.content
        # body 是 multipart 编码,直接搜 "name=\"user\"" 字段
        assert b'name="user"' in request_body
        assert TEST_DEFAULT_END_USER.encode() in request_body

    def test_upload_passes_filename_and_content_type(self, client):
        """文件名 + MIME 应被透传到 Dify upload_file()。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/files/upload").mock(
                return_value=httpx.Response(201, json={"id": "x"})
            )
            client.post(
                "/api/files/upload",
                files={"file": ("my-photo.jpg", b"\xff\xd8\xff\xe0", "image/jpeg")},
            )

        request_body = route.calls[0].request.content
        # multipart 编码检查 filename + Content-Type
        assert b"my-photo.jpg" in request_body
        assert b"image/jpeg" in request_body

    def test_upload_empty_file_returns_400(self, client):
        """空文件应返 400 而非 500（Dify upload 会 fail, 端点应提前拦截）。"""
        resp = client.post(
            "/api/files/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()


# ============== Legacy Coze-era 端点 (kept for backward compat with App.tsx:399) ==============
# 前端 src/App.tsx:399 仍 fetch /api/chat;M4 不删这些端点,加测试保证不退化。

class TestLegacyEndpoints:
    def test_api_health_returns_full_info(self, client):
        """legacy /api/health 返 ok=True + backend 标识 + api_base / end_user。"""
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["backend"] == "dify"
        assert body["api_base"] == TEST_API_BASE_URL
        assert body["end_user"] == TEST_DEFAULT_END_USER

    def test_favicon_returns_204(self, client):
        """/favicon.ico 返 204 (no content)。"""
        resp = client.get("/favicon.ico")
        assert resp.status_code == 204

    def test_legacy_chat_no_file_path(self, client):
        """legacy /api/chat (multipart blocking) — 仅 text 无 image/audio。

        走 v1 API key (settings.dify_api_key)。respx mock 返 succeeded。
        """
        with respx.mock(base_url=TEST_API_BASE) as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(200, json={
                    "task_id": "t1",
                    "workflow_run_id": "r1",
                    "data": {
                        "id": "r1",
                        "status": "succeeded",
                        "outputs": {"output": "legacy reply"},
                        "error": None,
                        "total_tokens": 10,
                        "elapsed_time": 1.0,
                    },
                })
            )
            resp = client.post(
                "/api/chat",
                data={"text": "hi", "language": "中文"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["assistant_text"] == "legacy reply"
        assert body["image_id"] is None
        assert body["audio_id"] is None
        # 验证走的是 v1 key 不是 v2 key
        auth = route.calls[0].request.headers.get("authorization", "")
        assert auth == f"Bearer {TEST_V1_KEY}"

    def test_legacy_chat_dify_error_returns_graceful(self, client):
        """Dify 出错时,legacy /api/chat 不抛 500,而是返 assistant_text 包含错误信息。"""
        with respx.mock(base_url=TEST_API_BASE) as router:
            router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(401, text="invalid key")
            )
            resp = client.post(
                "/api/chat",
                data={"text": "hi", "language": "中文"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "DifyError" in body["assistant_text"]


# ============== 集成测试（默认 skip） ==============

@pytest.mark.integration
class TestIntegrationRealDify:
    """跑真实 Dify v2 workflow。

    默认 skip。要跑：
        pytest tests/test_main.py -m integration -v
    或手动设置环境变量后跑。
    """

    def test_s1_text_chat_against_real_dify(self):
        """S1 纯文本：session_started + 至少 1 个 message_delta + message_complete。"""
        pytest.skip("integration test — run manually with real Dify credentials")
