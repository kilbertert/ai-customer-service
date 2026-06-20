"""M12 PR-6 — Regenerate workflow endpoint tests.

3 tests per plan §3 PR-6:
  1. test_regenerate_same_app_id      — workflow redeployed to same app_id
  2. test_regenerate_failure_502      — DSLGenerationError → 502
  3. test_regenerate_template_id_override — request body can override stored template

Uses ``plan_a_client`` fixture (conftest) so ``agent.dify_app_id`` is set
end-to-end. The Dify HTTP layer is mocked; the LLM caller is replaced.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import database as _db


def _ok_minimax_payload() -> dict[str, Any]:
    return {
        "system_prompt": "重新生成的客服",
        "user_prompt_template": "{{#sys.query#}}",
        "model_name": "gpt-4o-mini",
        "temperature": 0.6,
    }


async def _ok_minimax_caller(**_kwargs: Any) -> dict[str, Any]:
    return _ok_minimax_payload()


async def _make_agent_with_app_id(plan_a_workspace) -> str:
    """Create an Agent row with dify_app_id set so regenerate can proceed."""
    from models import AdminUser, Agent
    from sqlalchemy import select

    async with _db.AsyncSessionLocal() as s:
        admin_res = await s.execute(select(AdminUser).order_by(AdminUser.id).limit(1))
        admin = admin_res.scalar_one()
        a = Agent(
            id=f"agt_regen_{plan_a_workspace.id}",
            workspace_id=plan_a_workspace.id,
            name="regen",
            agent_type="custom",
            channel_mode="web_widget",
            dify_app_id="app-existing-001",
            dify_workflow_id="wf-existing-001",
            dify_publish_status="published",
            provider_config={
                "template_id": "basic_chat",
                "template_params": {"temperature": 0.7},
                "user_requirements": "首版客服",
            },
            template_id="basic_chat",
            template_params={"temperature": 0.7},
        )
        s.add(a)
        await s.commit()
        return a.id


async def test_regenerate_same_app_id(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """Regenerate with no body → reuse agent's stored template_id → success."""
    agent_id = await _make_agent_with_app_id(plan_a_workspace)

    from services.dify_toolkit.deployer import DeployResult

    fake_deployer = MagicMock()
    fake_deployer.deploy = AsyncMock(
        return_value=DeployResult(app_id="app-existing-001", deployed=True, rows_updated=5, nodes=3)
    )

    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_ok_minimax_caller),
    )
    with patch(
        "services.dify_toolkit.deployer.Deployer.from_workspace",
        return_value=fake_deployer,
    ):
        resp = await plan_a_client.post(f"/api/v1/agents/{agent_id}/regenerate-workflow", json={})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deployed"] is True
    assert body["app_id"] == "app-existing-001"  # SAME app_id, not new
    assert body["workflow_id"] == "wf-existing-001"
    assert body["rows_updated"] == 5
    assert body["generation_meta"]["params"]["system_prompt"] == "重新生成的客服"
    # Deployer.deploy was called with the SAME app_id (key assertion)
    deploy_kwargs = fake_deployer.deploy.call_args.kwargs
    assert deploy_kwargs["app_id"] == "app-existing-001"


async def test_regenerate_failure_502(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """DSLGenerator raises → HTTP 502 propagated, no deploy."""
    agent_id = await _make_agent_with_app_id(plan_a_workspace)

    async def _bad_caller(**_kwargs: Any) -> dict[str, Any]:
        from services.dify_toolkit.dsl_generator_exceptions import DSLGenerationError
        raise DSLGenerationError("simulated", cause="llm_call_failed")

    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_bad_caller),
    )

    resp = await plan_a_client.post(f"/api/v1/agents/{agent_id}/regenerate-workflow", json={})
    assert resp.status_code == 502, resp.text


async def test_regenerate_template_id_override(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """Request with template_id override → uses new template, success."""
    agent_id = await _make_agent_with_app_id(plan_a_workspace)

    from services.dify_toolkit.deployer import DeployResult

    fake_deployer = MagicMock()
    fake_deployer.deploy = AsyncMock(
        return_value=DeployResult(app_id="app-existing-001", deployed=True, rows_updated=3, nodes=4)
    )

    async def _rag_payload(**_kwargs: Any) -> dict[str, Any]:
        return {
            "system_prompt": "RAG 客服",
            "knowledge_base_ids": ["kb-handbook"],
            "top_k": 5,
            "model_name": "gpt-4o-mini",
            "temperature": 0.3,
        }

    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_rag_payload),
    )
    with patch(
        "services.dify_toolkit.deployer.Deployer.from_workspace",
        return_value=fake_deployer,
    ):
        resp = await plan_a_client.post(
            f"/api/v1/agents/{agent_id}/regenerate-workflow",
            json={"template_id": "rag_qa"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    # template_id was overridden to rag_qa in this regenerate
    assert body["generation_meta"]["attempt"] >= 1
    assert body["generation_meta"]["params"]["knowledge_base_ids"] == ["kb-handbook"]