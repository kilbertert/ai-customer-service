"""M10 PR4a — chat_stream Dify path 端到端集成测试。

覆盖范围 (M10 §7 PR4a 验收门):
1. ``agent.dify_workflow_id`` 非空 → chat_stream 走 DifyProvider 路径
2. Dify HTTP 请求体含 G1 双层 ``end_user`` 编码
3. SSE 响应是 SseProxyLayer 风格 (session_started / message_delta / message_complete)
4. ``agent.dify_workflow_id`` 为空 → chat_stream 保持 LLM 路径 (不调 Dify)

策略: ``respx`` mock Dify HTTP 层, ``public_client`` 触发端到端。
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app


# ============== Dify SSE 字节构造器 ==============


def _dify_sse_bytes(events: list[dict[str, Any]]) -> bytes:
    """SseProxyLayer 输入格式: Dify workflow 事件 SSE 字节流。"""
    out: list[str] = []
    for e in events:
        out.append(f"event: {e['event']}")
        out.append(f"data: {json.dumps(e['data'], ensure_ascii=False)}")
        out.append("")
        out.append("")
    return "\n".join(out).encode("utf-8")


def _parse_h5_sse(raw: bytes) -> list[tuple[str, dict[str, Any]]]:
    """解析 H5 风格 SSE 字节 → [(event_name, payload), ...]."""
    text = raw.decode("utf-8")
    events: list[tuple[str, dict[str, Any]]] = []
    for raw_event in text.split("\n\n"):
        if not raw_event.strip():
            continue
        event_name = None
        payload_lines: list[str] = []
        for line in raw_event.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                payload_lines.append(line.split(":", 1)[1].strip())
        if event_name:
            try:
                payload = json.loads("\n".join(payload_lines))
            except json.JSONDecodeError:
                payload = {}
            events.append((event_name, payload))
    return events


# ============== Dify-enabled Agent fixture ==============


@pytest_asyncio.fixture(loop_scope="function")
async def dify_enabled_agent(setup_test_db):
    """把默认 test agent 升级为 dify_workflow_id + workspace dify_api_* 全配齐。

    返回 (agent_id, dify_api_base)。
    """
    async with database.AsyncSessionLocal() as session:
        from core.encryption import encrypt_api_key
        from models import Agent, Workspace

        # 1. 给 workspace 设 dify_api_base / dify_api_key (Fernet 加密, 与生产同路径)
        ws_q = await session.execute(
            select(Workspace).order_by(Workspace.id).limit(1)
        )
        workspace = ws_q.scalar_one()
        workspace.dify_api_base = "https://dify.test/v1"
        workspace.dify_api_key = encrypt_api_key("app-test-dify-key")
        workspace.dify_workspace_id = "dify-ws-uuid-test"
        workspace.dify_enabled = True

        # 2. 给 agent 绑 dify_workflow_id
        agent_q = await session.execute(
            select(Agent).where(Agent.is_active == True).order_by(Agent.created_at).limit(1)
        )
        agent = agent_q.scalar_one()
        agent.dify_workflow_id = "wf-test-uuid"
        agent.dify_user_prefix = "agent-"
        agent.dify_end_user_strategy = "dual_layer"

        await session.commit()
        return agent.id, workspace.dify_api_base


@pytest_asyncio.fixture(loop_scope="function")
async def dify_disabled_agent(setup_test_db):
    """对照组: agent.dify_workflow_id 为空, chat_stream 走 LLM 路径 (不调 Dify)。"""
    async with database.AsyncSessionLocal() as session:
        from models import Agent

        agent_q = await session.execute(
            select(Agent).where(Agent.is_active == True).order_by(Agent.created_at).limit(1)
        )
        agent = agent_q.scalar_one()
        # 显式置空 (确保不是被之前 test 残留值)
        agent.dify_workflow_id = None
        await session.commit()
        return agent.id


# ============== 1. Dify 路径走通 (端到端) ==============


class TestChatStreamDifyPath:
    @pytest.mark.asyncio
    async def test_dify_routing_emits_h5_sse_events(
        self, dify_enabled_agent
    ):
        """agent.dify_workflow_id 非空 → chat_stream 走 Dify 路径, 产出 H5 SSE 序列。"""
        agent_id, _ = dify_enabled_agent

        dify_events = [
            {"event": "workflow_started", "data": {"workflow_run_id": "r1", "id": "r1"}},
            {
                "event": "text_chunk",
                "data": {"node_id": "2007", "text": "请先", "from_variable_selector": ["2007", "text"]},
            },
            {
                "event": "text_chunk",
                "data": {"node_id": "2007", "text": "检查供电", "from_variable_selector": ["2007", "text"]},
            },
            {
                "event": "workflow_finished",
                "data": {
                    "id": "r1",
                    "status": "succeeded",
                    "outputs": {"output": "请先检查供电"},
                    "total_tokens": 50,
                    "elapsed_time": 1.5,
                },
            },
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
            with respx.mock(base_url="https://dify.test") as router:
                route = router.post("/v1/workflows/run").mock(
                    return_value=httpx.Response(
                        200,
                        content=_dify_sse_bytes(dify_events),
                        headers={"content-type": "text/event-stream"},
                    )
                )
                async with ac.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    json={
                        "agent_id": agent_id,
                        "message": "充电桩不通电",
                        "visitor_id": "vis_visitor_001",
                    },
                ) as resp:
                    assert resp.status_code == 200
                    assert resp.headers["content-type"].startswith("text/event-stream")
                    chunks = b""
                    async for chunk in resp.aiter_bytes():
                        chunks += chunk

        # 1. Dify HTTP 被调用 1 次
        assert route.call_count == 1
        # 2. 解析 H5 SSE 序列
        events = _parse_h5_sse(chunks)
        names = [e[0] for e in events]
        # Dify 路径不暴露 sources / content / done (走 message_complete 透传)
        assert "session_started" in names
        assert "message_delta" in names
        assert "message_complete" in names
        # 3. session_started 携带 workflow_run_id
        session_started = next(p for n, p in events if n == "session_started")
        assert session_started["session_id"] == "r1"
        # 4. message_complete 携带最终回复 + tokens
        complete = next(p for n, p in events if n == "message_complete")
        assert complete["text"] == "请先检查供电"
        assert complete["total_tokens"] == 50
        assert complete["elapsed_time"] == 1.5

    @pytest.mark.asyncio
    async def test_dify_request_body_uses_g1_dual_layer_end_user(
        self, dify_enabled_agent
    ):
        """G1 硬门 1: Dify request body.user 必须是 ``agent-{aid}-v-{vid}-s-{sid}`` 格式。"""
        agent_id, _ = dify_enabled_agent

        dify_events = [
            {"event": "workflow_started", "data": {"workflow_run_id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "ok"}},
            },
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
            with respx.mock(base_url="https://dify.test") as router:
                route = router.post("/v1/workflows/run").mock(
                    return_value=httpx.Response(
                        200,
                        content=_dify_sse_bytes(dify_events),
                        headers={"content-type": "text/event-stream"},
                    )
                )
                async with ac.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    json={
                        "agent_id": agent_id,
                        "message": "hi",
                        "visitor_id": "vis_abc",
                        "session_id": "sess_xyz",
                    },
                ) as resp:
                    async for _ in resp.aiter_bytes():
                        pass

        # 校验 Dify request body.user 编码
        request = route.calls.last.request
        body = json.loads(request.content)
        assert body["user"] == f"agent-{agent_id}-v-vis_abc-s-sess_xyz"
        # inputs 也按 M2 契约透传
        assert body["inputs"]["input_text"] == "hi"
        assert body["response_mode"] == "streaming"

    @pytest.mark.asyncio
    async def test_dify_anon_fallback_when_visitor_id_omitted(
        self, dify_enabled_agent
    ):
        """G1 硬门 1 case 2: visitor_id 缺省 → end_user 含 'anon'。"""
        agent_id, _ = dify_enabled_agent

        dify_events = [
            {"event": "workflow_started", "data": {"workflow_run_id": "r1"}},
            {
                "event": "workflow_finished",
                "data": {"status": "succeeded", "outputs": {"output": "ok"}},
            },
        ]

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
            with respx.mock(base_url="https://dify.test") as router:
                route = router.post("/v1/workflows/run").mock(
                    return_value=httpx.Response(
                        200,
                        content=_dify_sse_bytes(dify_events),
                        headers={"content-type": "text/event-stream"},
                    )
                )
                async with ac.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    json={
                        "agent_id": agent_id,
                        "message": "hi",
                        # 故意不传 visitor_id
                        "session_id": "sess_xyz",
                    },
                ) as resp:
                    async for _ in resp.aiter_bytes():
                        pass

        body = json.loads(route.calls.last.request.content)
        assert "anon" in body["user"]
        assert body["user"] == f"agent-{agent_id}-v-anon-s-sess_xyz"

    @pytest.mark.asyncio
    async def test_dify_path_does_not_call_dify_when_workflow_id_empty(
        self, dify_disabled_agent
    ):
        """对照组: agent.dify_workflow_id=None → chat_stream 不调 Dify, 走 LLM 路径。"""
        agent_id = dify_disabled_agent

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
            # 不注册任何 Dify route;如果 chat_stream 错误地走了 Dify 路径, respx
            # 会因 "no mock matched" 抛异常, 测试失败
            with respx.mock(assert_all_called=False):
                async with ac.stream(
                    "POST",
                    "/api/v1/chat/stream",
                    json={"agent_id": agent_id, "message": "hi"},
                ) as resp:
                    assert resp.status_code == 200
                    # LLM 路径产 sources / content / done;不产 session_started / message_complete
                    chunks = b""
                    async for chunk in resp.aiter_bytes():
                        chunks += chunk

        events = _parse_h5_sse(chunks)
        names = [e[0] for e in events]
        # LLM 路径特征: 必有 sources/content/done, 不应有 Dify 路径专属事件
        assert "sources" in names
        assert "content" in names
        assert "done" in names
        assert "session_started" not in names
        assert "message_complete" not in names
