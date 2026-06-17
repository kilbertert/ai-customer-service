"""M10 PR4a — DifyProvider unit tests.

覆盖 G1 双层 ``end_user`` 编码 (M10 §2.2 锁定)
+ Phase 3 ``extract_message_complete_text`` 持久化辅助
+ 构造期 fail-fast 校验
+ 端到端 ``stream_chat`` 走 respx mock Dify HTTP 层

不覆盖:
- SseProxyLayer 事件映射逻辑 (M3 test_sse_proxy_layer.py 已锁)
- DifyClient.run_workflow_stream 解析 (M2 test_dify_client.py 已锁)
- 端到端 POST /api/v1/chat/stream full link → test_chat_stream_dify.py
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, AsyncIterator, Optional

import httpx
import pytest
import respx

from services.dify.provider import DifyProvider, extract_message_complete_text


# ============== Fake model objects (avoid SQLAlchemy mapper noise) ==============


@dataclass
class _FakeAgent:
    """最小化的 Agent 替身,只覆盖 DifyProvider 关注的字段。"""

    id: str = "agt_a1b2c3d4e5f6"
    dify_workflow_id: Optional[str] = "wf-uuid-1"
    dify_user_prefix: str = "agent-"
    dify_end_user_strategy: str = "dual_layer"
    dify_inputs_schema: Optional[str] = None


@dataclass
class _FakeWorkspace:
    """最小化的 Workspace 替身,只覆盖 DifyProvider 关注的字段。"""

    id: int = 1
    dify_api_base: Optional[str] = "https://dify.test/v1"
    dify_api_key: Optional[str] = None
    dify_workspace_id: Optional[str] = None
    dify_enabled: bool = True


def _fake_agent(**overrides: Any) -> _FakeAgent:
    return _FakeAgent(**overrides)


def _fake_workspace(**overrides: Any) -> _FakeWorkspace:
    return _FakeWorkspace(**overrides)


# ============== SSE 字节助手 (与 SseProxyLayer 产出一致) ==============


def _dify_sse_bytes(events: list[dict[str, Any]]) -> bytes:
    """把事件列表序列化为 SseProxyLayer 风格的 SSE 字节流。"""
    out: list[str] = []
    for e in events:
        out.append(f"event: {e['event']}")
        out.append(f"data: {json.dumps(e['data'], ensure_ascii=False)}")
        out.append("")
        out.append("")
    return "\n".join(out).encode("utf-8")


async def _collect_bytes(agen) -> list[bytes]:
    """消费 async generator, 收集所有 yield 字节。"""
    out: list[bytes] = []
    async for chunk in agen:
        out.append(chunk)
    return out


# ============== _build_end_user 单元测试 (G1 编码核心) ==============


class TestBuildEndUser:
    """G1 dual-layer end_user 编码 — 9 cases."""

    def test_dual_layer_normal(self):
        agent = _fake_agent(id="agt_a1b2c3d4e5f6")
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-vis_abc-s-sess_xyz"

    def test_dual_layer_visitor_none_falls_back_to_anon(self):
        """M10 PR4a 硬门 1 case 2: visitor_id=None → 'anon'."""
        agent = _fake_agent(id="agt_a1b2c3d4e5f6")
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id=None,
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-anon-s-sess_xyz"

    def test_dual_layer_visitor_empty_string_falls_back_to_anon(self):
        """空字符串 visitor_id 同样兜底为 'anon'."""
        agent = _fake_agent(id="agt_a1b2c3d4e5f6")
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-anon-s-sess_xyz"

    def test_dual_layer_truncates_visitor_and_session_when_too_long(self):
        """总长 > 100 字符时, visitor_id 和 session_public_id 各 cap 到 36 字符。"""
        agent = _fake_agent(id="agt_a1b2c3d4e5f6")
        long_vid = "v" * 50
        long_sid = "s" * 50
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id=long_vid,
            session_public_id=long_sid,
        )
        # 截断后 36+36 字符, 总长 = 16("agent-agt_a1b2c3d4e5f6") + 2("-v-") + 36 + 2("-s-") + 36 = 92
        assert len(result) <= 100
        assert "-v-" + ("v" * 36) in result
        assert "-s-" + ("s" * 36) in result

    def test_agent_strategy_only_emits_prefix_and_id(self):
        """M3 legacy 兼容: strategy='agent' → 仅 'agent-{aid}'."""
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_end_user_strategy="agent",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6"

    def test_visitor_strategy_drops_session(self):
        """strategy='visitor' → 'agent-{aid}-v-{vid}' (无 session 粒度)。"""
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_end_user_strategy="visitor",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-vis_abc"

    def test_visitor_strategy_with_none_visitor_falls_back_to_anon(self):
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_end_user_strategy="visitor",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id=None,
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-anon"

    def test_unknown_strategy_falls_back_to_dual_layer(self):
        """防御性: 未知 strategy 退化为 dual_layer."""
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_end_user_strategy="weird_mode",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6-v-vis_abc-s-sess_xyz"

    def test_custom_prefix_is_respected(self):
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_user_prefix="bot_",
            dify_end_user_strategy="agent",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "bot_agt_a1b2c3d4e5f6"

    def test_empty_prefix_falls_back_to_default(self):
        """空字符串 prefix 退化为 'agent-'."""
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_user_prefix="",
            dify_end_user_strategy="agent",
        )
        result = DifyProvider._build_end_user(
            agent=agent,
            visitor_id="vis_abc",
            session_public_id="sess_xyz",
        )
        assert result == "agent-agt_a1b2c3d4e5f6"


# ============== extract_message_complete_text 单元测试 ==============


class TestExtractMessageCompleteText:
    """Phase 3 持久化辅助 — 5 cases."""

    def test_extracts_text_from_message_complete_chunk(self):
        chunk = _dify_sse_bytes([
            {
                "event": "message_complete",
                "data": {"text": "请先检查供电", "total_tokens": 50, "elapsed_time": 1.5},
            },
        ])
        result = extract_message_complete_text(chunk)
        assert result == "请先检查供电"

    def test_returns_none_for_message_delta_chunk(self):
        """message_delta 不带 text 终结字段 → 应返 None."""
        chunk = _dify_sse_bytes([
            {"event": "message_delta", "data": {"text": "请先"}},
        ])
        assert extract_message_complete_text(chunk) is None

    def test_returns_none_for_session_started_chunk(self):
        """session_started 也不是 message_complete."""
        chunk = _dify_sse_bytes([
            {"event": "session_started", "data": {"session_id": "run-1"}},
        ])
        assert extract_message_complete_text(chunk) is None

    def test_returns_none_for_invalid_json_in_data(self):
        """非 JSON 格式的 data 字段 → 返 None (不抛异常)。"""
        bad_chunk = b"event: message_complete\ndata: not-json{\n\n"
        assert extract_message_complete_text(bad_chunk) is None

    def test_returns_none_when_text_field_missing(self):
        """message_complete 但 text 字段缺失 → 返 None."""
        chunk = _dify_sse_bytes([
            {"event": "message_complete", "data": {"total_tokens": 10}},
        ])
        assert extract_message_complete_text(chunk) is None


# ============== DifyProvider 构造期 fail-fast 校验 ==============


def _make_fake_settings(
    *, dify_api_base: str = "", dify_api_key: str = ""
) -> SimpleNamespace:
    """构造一个 simple, mutable settings 替身, 避免动 Pydantic v2 singleton。

    Pydantic v2 BaseModel 在 setattr 时行为依赖 ``validate_assignment`` 配置;
    直接对 singleton 调 ``monkeypatch.setattr(settings, ...)`` 在完整测试套件
    顺序下不可靠。改用 monkeypatch 替换 ``services.dify.provider.settings``
    模块级引用。
    """
    return SimpleNamespace(dify_api_base=dify_api_base, dify_api_key=dify_api_key)


class _FakeSettings(SimpleNamespace):
    pass


@pytest.fixture(autouse=True)
def _isolate_provider_settings(monkeypatch):
    """用 mutable SimpleNamespace 替换 services.diy.provider.settings,
    防止上游 test_rate_limit_middleware 等对 Pydantic singleton 的 mutation
    污染本套测试。autouse 对本文件内所有测试生效。"""
    from services.dify import provider

    fake = _make_fake_settings(dify_api_base="", dify_api_key="")
    monkeypatch.setattr(provider, "settings", fake)
    yield
    # monkeypatch 自动还原


class TestDifyProviderInit:
    """__post_init__ fail-fast 行为 — 3 cases."""

    def test_raises_when_no_api_base(self, monkeypatch):
        """workspace.dify_api_base=None 且 provider.settings.dify_api_base='' → ValueError."""
        from services.dify import provider

        monkeypatch.setattr(
            provider, "settings", _make_fake_settings(dify_api_base="", dify_api_key="")
        )
        workspace = _fake_workspace(dify_api_base=None)
        agent = _fake_agent()

        with pytest.raises(ValueError) as exc_info:
            DifyProvider(workspace=workspace, agent=agent, visitor_id="vis_abc")

        assert "dify_api_base" in str(exc_info.value).lower()
        assert "plan b" in str(exc_info.value).lower()

    def test_raises_when_no_api_key(self, monkeypatch):
        """workspace 缺 key + provider settings 缺 key → DifyConfigError (M10+2 D8 升级).

        M10+2 §7.C: 3 级 fallback 全空时, 用 ``DifyConfigError`` (在 ``services.dify.exceptions``
        声明) 而非 ``ValueError``, 让 caller 显式知道是"配置缺失"而非其他 ValueError.
        """
        from services.dify import provider
        from services.dify.exceptions import DifyConfigError

        monkeypatch.setattr(
            provider,
            "settings",
            _make_fake_settings(dify_api_base="https://dify.test/v1", dify_api_key=""),
        )
        workspace = _fake_workspace(dify_api_base=None, dify_api_key=None)
        agent = _fake_agent()

        with pytest.raises(DifyConfigError) as exc_info:
            DifyProvider(workspace=workspace, agent=agent, visitor_id="vis_abc")

        assert "api key" in str(exc_info.value).lower()

    def test_raises_when_workflow_id_empty(self, monkeypatch):
        """agent.dify_workflow_id='' → ValueError (DifyProvider 应当被调用)。"""
        from services.dify import provider

        monkeypatch.setattr(
            provider,
            "settings",
            _make_fake_settings(
                dify_api_base="https://dify.test/v1", dify_api_key="app-test-key"
            ),
        )
        workspace = _fake_workspace(
            dify_api_base="https://dify.test/v1",
            dify_api_key="app-plain-key",  # plaintext (非 enc: 前缀), 走直接返回路径
        )
        agent = _fake_agent(dify_workflow_id="")

        with pytest.raises(ValueError) as exc_info:
            DifyProvider(workspace=workspace, agent=agent, visitor_id="vis_abc")

        assert "dify_workflow_id" in str(exc_info.value).lower()


# ============== DifyProvider.stream_chat 端到端 (respx mock Dify HTTP) ==============


class TestDifyProviderStreamChat:
    """端到端 stream_chat — 3 cases 验证 G1 编码透传到 Dify POST body。"""

    @pytest.mark.asyncio
    async def test_g1_dual_layer_end_user_in_request_body(
        self, monkeypatch
    ):
        from services.dify import provider

        monkeypatch.setattr(
            provider,
            "settings",
            _make_fake_settings(dify_api_base="", dify_api_key="app-test-key"),
        )
        workspace = _fake_workspace(
            dify_api_base="https://dify.test/v1",
            dify_api_key="app-test-key",
        )
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_workflow_id="wf-uuid-1",
            dify_end_user_strategy="dual_layer",
        )

        events_payload = _dify_sse_bytes([
            {"event": "workflow_started", "data": {"workflow_run_id": "r1", "id": "r1"}},
            {
                "event": "text_chunk",
                "data": {"text": "请先", "from_variable_selector": ["2007", "text"]},
            },
            {
                "event": "workflow_finished",
                "data": {
                    "status": "succeeded",
                    "outputs": {"output": "请先检查供电"},
                    "total_tokens": 50,
                    "elapsed_time": 1.5,
                },
            },
        ])

        with respx.mock(base_url="https://dify.test") as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=events_payload,
                )
            )
            provider = DifyProvider(
                workspace=workspace,
                agent=agent,
                visitor_id="vis_abc",
            )
            chunks = await _collect_bytes(
                provider.stream_chat(
                    text="充电桩不通电",
                    language="zh-CN",
                    file_ids=None,
                    session_public_id="sess_xyz",
                )
            )

        # 至少产出 3 个 SSE 事件 (session_started + message_delta + message_complete)
        assert len(chunks) >= 3
        # 校验 G1 end_user 编码透传到 Dify request body
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body["user"] == "agent-agt_a1b2c3d4e5f6-v-vis_abc-s-sess_xyz"
        assert body["inputs"]["input_text"] == "充电桩不通电"
        assert body["inputs"]["language"] == "zh-CN"
        assert body["response_mode"] == "streaming"

    @pytest.mark.asyncio
    async def test_anon_fallback_when_visitor_id_none(self, monkeypatch):
        """visitor_id=None → end_user 含 'anon' 兜底段."""
        from services.dify import provider

        monkeypatch.setattr(
            provider,
            "settings",
            _make_fake_settings(dify_api_base="", dify_api_key="app-test-key"),
        )
        workspace = _fake_workspace(
            dify_api_base="https://dify.test/v1",
            dify_api_key="app-test-key",
        )
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_workflow_id="wf-uuid-1",
        )

        events_payload = _dify_sse_bytes([
            {"event": "workflow_started", "data": {"workflow_run_id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {
                    "status": "succeeded",
                    "outputs": {"output": "ok"},
                },
            },
        ])

        with respx.mock(base_url="https://dify.test") as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=events_payload,
                )
            )
            provider = DifyProvider(
                workspace=workspace,
                agent=agent,
                visitor_id=None,  # 关键: None 触发 anon 兜底
            )
            await _collect_bytes(
                provider.stream_chat(
                    text="hi",
                    language="en-US",
                    file_ids=None,
                    session_public_id="sess_xyz",
                )
            )

        body = json.loads(route.calls.last.request.content)
        assert "anon" in body["user"]
        assert body["user"] == "agent-agt_a1b2c3d4e5f6-v-anon-s-sess_xyz"

    @pytest.mark.asyncio
    async def test_settings_fallback_when_workspace_lacks_api_base(
        self, monkeypatch
    ):
        """workspace.dify_api_base=None + provider settings.dify_api_base 非空 → 走 settings."""
        from services.dify import provider

        monkeypatch.setattr(
            provider,
            "settings",
            _make_fake_settings(
                dify_api_base="https://settings-dify.test/v1",
                dify_api_key="app-settings-key",
            ),
        )
        workspace = _fake_workspace(
            dify_api_base=None,  # workspace 未设, 走 settings
            dify_api_key=None,
        )
        agent = _fake_agent(
            id="agt_a1b2c3d4e5f6",
            dify_workflow_id="wf-uuid-1",
        )

        events_payload = _dify_sse_bytes([
            {"event": "workflow_started", "data": {"workflow_run_id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {
                    "status": "succeeded",
                    "outputs": {"output": "ok"},
                },
            },
        ])

        with respx.mock(base_url="https://settings-dify.test") as router:
            route = router.post("/v1/workflows/run").mock(
                return_value=httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    content=events_payload,
                )
            )
            provider = DifyProvider(
                workspace=workspace,
                agent=agent,
                visitor_id="vis_abc",
            )
            await _collect_bytes(
                provider.stream_chat(
                    text="hi",
                    language="en-US",
                    file_ids=None,
                    session_public_id="sess_xyz",
                )
            )

        # 请求打到 settings 配置的 base_url
        assert route.call_count == 1
        body = json.loads(route.calls.last.request.content)
        assert body["user"] == "agent-agt_a1b2c3d4e5f6-v-vis_abc-s-sess_xyz"
