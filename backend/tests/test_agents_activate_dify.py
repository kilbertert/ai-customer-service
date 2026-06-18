"""M11+ P0-A — activate_dify_for_agent 端点测试 (3 cases per docs/m11plus/p0a-plan-a-cutover.md §4.4).

POST /api/v1/agents/{agent_id}/activate-dify
  - 200: Plan B agent (dify_app_id=NULL) → 走 _provision_dify_app helper → 写 4 字段
  - 400: workspace 缺 Dify admin 凭据 (dify_enabled=True 但 dify_admin_* 空)
  - 502: Dify 5xx / network → rollback, agent 字段不变

权限: super_admin ∪ tenant_owner (D3 决策 + M11 PR4 fix)。
"""
from __future__ import annotations

import uuid

import httpx
import pytest
import respx
from sqlalchemy import select

import database
from models import Agent, Workspace
from services.dify.admin_client import _session_cache
from tests.test_dify_admin_client import (
    _enable_workspace_dify,
    _login_response,
)


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """DifyAdminClient session cache 是 module-level LRU,测试间必须清空
    否则上一 test 的 session 复用 → 本 test 的 /login mock 不被调用 → respx 报
    'some routes were not called'。"""
    _session_cache.clear()
    yield
    _session_cache.clear()


async def _create_plan_b_agent(workspace_id: int) -> str:
    """在 DB 直接造一个 Plan B agent (dify_app_id=NULL),返回 agent_id 字符串。"""
    async with database.AsyncSessionLocal() as session:
        agent = Agent(
            id=f"agt_{uuid.uuid4().hex[:12]}",
            name=f"planB-{uuid.uuid4().hex[:6]}",
            workspace_id=workspace_id,
            agent_type="ai_clone",
            is_active=True,
            dify_app_id=None,
        )
        session.add(agent)
        await session.commit()
        return agent.id


@pytest.mark.asyncio
async def test_activate_dify_200(setup_test_db, client):
    """Plan B agent → activate-dify 200 → agent.dify_app_id 写入 UUID + dify_publish_status='published'。

    Mock 序列: login 200 → create_app 200 → draft 200 → api-enable 200 →
    api-keys 200 → publish_workflow 200 → 期望 dify_app_id='app-p0a-1' + 4 字段全 set。
    """
    await _enable_workspace_dify()

    async with database.AsyncSessionLocal() as session:
        workspace = (
            await session.execute(select(Workspace).order_by(Workspace.id).limit(1))
        ).scalar_one()
        agent_id = await _create_plan_b_agent(workspace.id)

    with respx.mock(base_url="https://dify.test") as router:
        router.post("/console/api/login").mock(return_value=_login_response())
        router.post("/console/api/apps").mock(
            return_value=httpx.Response(200, json={"id": "app-p0a-1"})
        )
        router.post(
            "/console/api/apps/app-p0a-1/workflows/draft"
        ).mock(return_value=httpx.Response(200, json={"id": "wf-p0a-1"}))
        router.post("/console/api/apps/app-p0a-1/api-enable").mock(
            return_value=httpx.Response(200, json={"enable_api": True})
        )
        router.post("/console/api/apps/app-p0a-1/api-keys").mock(
            return_value=httpx.Response(200, json={"token": "app-p0a-runtime-key"})
        )
        router.post(
            "/console/api/apps/app-p0a-1/workflows/publish"
        ).mock(return_value=httpx.Response(200, json={"result": "success"}))

        response = await client.post(f"/api/v1/agents/{agent_id}/activate-dify")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == agent_id

    async with database.AsyncSessionLocal() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one()
        assert agent.dify_app_id == "app-p0a-1", "Plan A app_id 没写入"
        assert agent.dify_workflow_id == "wf-p0a-1"
        assert agent.dify_api_key is not None
        assert agent.dify_api_key.startswith("enc:")
        assert agent.dify_publish_status == "published"


@pytest.mark.asyncio
async def test_activate_dify_400_no_creds(setup_test_db, client):
    """workspace 缺 Dify admin 凭据 → 400, agent 字段不变。

    场景: dify_enabled=True 但 dify_admin_email / dify_admin_password_ref 是 None。
    """
    # 启用 Plan A 但不设 admin 凭据 (set_admin_creds=False)
    await _enable_workspace_dify(set_admin_creds=False)

    async with database.AsyncSessionLocal() as session:
        workspace = (
            await session.execute(select(Workspace).order_by(Workspace.id).limit(1))
        ).scalar_one()
        agent_id = await _create_plan_b_agent(workspace.id)

        agent = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one()
        assert agent.dify_app_id is None
        original_dify_publish_status = agent.dify_publish_status

    # 不需要 respx mock: 应该 400 在调 Dify 之前就 fail-fast
    response = await client.post(f"/api/v1/agents/{agent_id}/activate-dify")

    assert response.status_code == 400, response.text
    body = response.json()
    detail_lower = body["detail"].lower()
    assert "credential" in detail_lower or "凭据" in body["detail"]

    async with database.AsyncSessionLocal() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one()
        assert agent.dify_app_id is None, "400 路径不能让 dify_app_id 写半截"
        assert agent.dify_workflow_id is None
        assert agent.dify_api_key is None
        assert agent.dify_publish_status == original_dify_publish_status


@pytest.mark.asyncio
async def test_activate_dify_502_dify_upstream(setup_test_db, client):
    """Dify upstream 错误 → 502, agent 字段不变 (rollback)。

    场景: Dify /console/api/apps 返回 200 但 body 没 id → DifyAdminClient 抛 DifyUpstreamError
    (admin_client.py:303),_provision_dify_app 转 HTTPException(502),端点 rollback → agent 不变。
    """
    await _enable_workspace_dify()

    async with database.AsyncSessionLocal() as session:
        workspace = (
            await session.execute(select(Workspace).order_by(Workspace.id).limit(1))
        ).scalar_one()
        agent_id = await _create_plan_b_agent(workspace.id)

    with respx.mock(base_url="https://dify.test") as router:
        router.post("/console/api/login").mock(return_value=_login_response())
        # 200 但无 id 字段 → DifyUpstreamError (admin_client.py:303)
        router.post("/console/api/apps").mock(
            return_value=httpx.Response(200, json={})
        )

        response = await client.post(f"/api/v1/agents/{agent_id}/activate-dify")

    assert response.status_code == 502, response.text
    body = response.json()
    assert "dify" in body["detail"].lower() or "502" in body["detail"].lower()

    async with database.AsyncSessionLocal() as session:
        agent = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one()
        assert agent.dify_app_id is None, "502 路径必须 rollback, 不能留半截 dify_app_id"
        assert agent.dify_workflow_id is None
        assert agent.dify_api_key is None
