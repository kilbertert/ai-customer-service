"""M12 PR-4 — Backend integration tests for ``POST /agents`` with wizard payload.

Uses the ``plan_a_client`` fixture (defined in conftest.py) which flips the
test workspace into Plan-A mode so ``_provision_dify_app`` actually exercises
the DSLGenerator wiring path.

Dify HTTP calls are mocked at the ``DifyAdminClient.from_workspace`` boundary;
the LLM caller is replaced with a fake that returns a fixed payload.

Test matrix (plan §3 PR-4, 4 tests):
  1. test_create_with_template_basic_chat           — full happy path
  2. test_create_without_template_uses_pr0_fallback — no template_id → PR-0 minimal graph
  3. test_template_params_optional                 — partial params dict accepted
  4. test_dsl_generation_failure_502               — DSLGenerator raise → 502
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


def _fake_dify_admin_client() -> MagicMock:
    """Build a MagicMock that quacks like ``DifyAdminClient.from_workspace``."""
    client = MagicMock()
    client.create_app_and_workflow = AsyncMock(
        return_value={"app_id": "app-fake-001", "workflow_id": "wf-fake-001"}
    )
    client.enable_api_and_create_key = AsyncMock(return_value="app-api-key-fake-001")
    client.publish_workflow = AsyncMock(return_value=True)
    return client


def _ok_minimax_payload() -> dict[str, Any]:
    """A basic_chat schema-valid payload (matches PR-2 BasicChatParams)."""
    return {
        "system_prompt": "你是一个友好的客服助手。",
        "user_prompt_template": "{{#sys.query#}}",
        "model_name": "gpt-4o-mini",
        "temperature": 0.7,
    }


async def _ok_minimax_caller(**_kwargs: Any) -> dict[str, Any]:
    return _ok_minimax_payload()


async def test_create_with_template_basic_chat(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """Happy path: POST /agents with template_id=basic_chat → 201 + dify_generation_meta set."""
    fake_dify = _fake_dify_admin_client()
    monkeypatch.setattr(
        "services.dify.admin_client.DifyAdminClient.from_workspace",
        classmethod(lambda cls, ws: fake_dify),
    )
    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_ok_minimax_caller),
    )

    payload = {
        "name": "测试客服",
        "agent_type": "custom",
        "channel_mode": "web_widget",
        "template_id": "basic_chat",
        "template_params": {"temperature": 0.5},
        "user_requirements": "电商退货客服",
    }
    resp = await plan_a_client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["template_id"] == "basic_chat"
    assert body["template_params"] == {"temperature": 0.5}
    meta = body.get("dify_generation_meta")
    assert meta is not None, f"dify_generation_meta missing in: {body}"
    assert meta["attempt"] >= 1
    assert meta["params"]["system_prompt"].startswith("你是")
    # DSLGenerator was actually called — verify DifyAdminClient received a non-empty graph
    kwargs = fake_dify.create_app_and_workflow.call_args.kwargs
    graph = kwargs.get("graph")
    assert graph is not None
    assert len(graph.get("nodes", [])) >= 3


async def test_create_without_template_uses_pr0_fallback(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """No template_id → wizard not used → PR-0 minimal Start+End graph (graph=None)."""
    fake_dify = _fake_dify_admin_client()
    monkeypatch.setattr(
        "services.dify.admin_client.DifyAdminClient.from_workspace",
        classmethod(lambda cls, ws: fake_dify),
    )
    # LLM caller must NOT be called on this path — install a strict mock that fails if invoked
    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=AssertionError("LLM must not be called when template_id is absent")),
    )

    payload = {
        "name": "无模板",
        "agent_type": "custom",
        "channel_mode": "web_widget",
    }
    resp = await plan_a_client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["template_id"] is None
    assert body["template_params"] is None
    assert body["dify_generation_meta"] is None
    kwargs = fake_dify.create_app_and_workflow.call_args.kwargs
    # PR-0 minimal graph fallback: graph=None, DifyAdminClient builds Start+End internally
    assert kwargs.get("graph") is None


async def test_template_params_optional(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """`template_params` may be partial — Pydantic schema fills defaults."""
    fake_dify = _fake_dify_admin_client()
    monkeypatch.setattr(
        "services.dify.admin_client.DifyAdminClient.from_workspace",
        classmethod(lambda cls, ws: fake_dify),
    )

    async def _partial_caller(**_kwargs: Any) -> dict[str, Any]:
        # Return a payload that omits `temperature` — Pydantic schema fills default 0.7
        return {
            "system_prompt": "简化版客服",
            "user_prompt_template": "{{#sys.query#}}",
            "model_name": "gpt-4o-mini",
        }

    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_partial_caller),
    )

    payload = {
        "name": "part",
        "agent_type": "custom",
        "channel_mode": "web_widget",
        "template_id": "basic_chat",
        # NO template_params at all
    }
    resp = await plan_a_client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201, resp.text

    body = resp.json()
    assert body["template_id"] == "basic_chat"
    assert body["dify_generation_meta"]["params"]["temperature"] == 0.7


async def test_dsl_generation_failure_502(plan_a_client, plan_a_workspace, monkeypatch) -> None:
    """DSLGenerator raises → HTTP 502 propagated, NO successful agent creation."""
    fake_dify = _fake_dify_admin_client()
    monkeypatch.setattr(
        "services.dify.admin_client.DifyAdminClient.from_workspace",
        classmethod(lambda cls, ws: fake_dify),
    )

    async def _bad_caller(**_kwargs: Any) -> dict[str, Any]:
        from services.dify_toolkit.dsl_generator_exceptions import DSLGenerationError
        raise DSLGenerationError("simulated LLM total failure", cause="llm_call_failed")

    monkeypatch.setattr(
        "services.llm_integration.minimax_client.minimax_call",
        AsyncMock(side_effect=_bad_caller),
    )

    payload = {
        "name": "fail",
        "agent_type": "custom",
        "channel_mode": "web_widget",
        "template_id": "basic_chat",
        "user_requirements": "test",
    }
    resp = await plan_a_client.post("/api/v1/agents", json=payload)
    # DSLGenerationError → 502 in _provision_dify_app
    assert resp.status_code == 502, resp.text
    # DifyAdminClient.create_app_and_workflow must NOT be reached on failure
    fake_dify.create_app_and_workflow.assert_not_called()