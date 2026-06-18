"""M11+ P0-C PR 3 残余 — POST /workflows/{agent_id}/deploy 端点集成测试。

覆盖 spec §4.4 测试矩阵的 3 个端点 case:
  - test_200_deploy:         Plan A 完整路径 → 200, audit 写 deploy_success
  - test_502_schema_mismatch: probe 缺列 → 502, 错误信息含 missing
  - test_403_not_owner:      非 workspace_owner → 403

依赖: ``client`` fixture (authed super_admin) + ``support_client`` (普通 user role)
+ respx mock Dify publish API + patch services.dify_toolkit.deployer.db.*
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from sqlalchemy import select

import database
from models import Agent, AuditLog, Workspace


def _session():
    """Re-read ``database.AsyncSessionLocal`` per call (configured per-test in conftest)."""
    return database.AsyncSessionLocal()


def _stub_dify_admin(*, publish_ok: bool = True, publish_side_effect: Exception | None = None):
    """Return a MagicMock ``dify_admin`` with ``publish_workflow`` as AsyncMock.

    端点测试 helper: 直接替换 ``DifyAdminClient.from_workspace()`` 的返回值,
    跳过 respx + Dify login 链 (login POST /console/api/login 不需要 mock)。
    """
    mock = MagicMock()
    mock.publish_workflow = AsyncMock(
        return_value=publish_ok if publish_side_effect is None else None,
        side_effect=publish_side_effect,
    )
    return mock


# ── helpers ────────────────────────────────────────────────────────────────
async def _enable_workspace_with_agent(*, agent_dify_app_id: str = "app-test-uuid"):
    """打开 workspace.dify_enabled, 给默认 agent 设 dify_app_id。"""
    async with _session() as session:
        ws = (await session.execute(
            select(Workspace).order_by(Workspace.id).limit(1)
        )).scalar_one()
        ws.dify_api_base = "https://dify.test"
        ws.dify_enabled = True
        ws.dify_admin_email = "admin@dify.test"
        ws.dify_admin_password_ref = "plain-secret-pw"
        ws.dify_tenant_id = "tenant-uuid"
        await session.commit()

        agent = (await session.execute(
            select(Agent).order_by(Agent.id).limit(1)
        )).scalar_one()
        agent.dify_app_id = agent_dify_app_id
        await session.commit()
        return agent.id


def _ctx_mock(value):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=value)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


SAMPLE_YML = """\
app:
  name: deploy_test
workflow:
  graph:
    nodes:
      - id: "4001"
        data:
          type: start
      - id: "4099"
        data:
          type: end
"""


# ── tests ──────────────────────────────────────────────────────────────────
class TestDeployEndpoint:
    """M11+ P0-C PR 2 — ``POST /api/v1/workflows/{agent_id}/deploy``."""

    @pytest.mark.asyncio
    async def test_200_deploy(
        self, client, setup_test_db
    ):
        """Plan A 完整路径: schema OK + Dify publish 200 → 200 + DeployResult."""
        agent_id = await _enable_workspace_with_agent()

        schema_ok = {
            "id": "uuid", "app_id": "uuid", "version": "text",
            "graph": "jsonb", "updated_at": "timestamp", "tenant_id": "text",
        }
        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=schema_ok), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph",
                   return_value=1), \
             patch("services.dify_toolkit.deployer.DifyAdminClient.from_workspace",
                   return_value=_stub_dify_admin(publish_ok=True)):
            response = await client.post(
                f"/api/v1/workflows/{agent_id}/deploy",
                json={"yml": SAMPLE_YML},
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["deployed"] is True
        assert body["app_id"] == "app-test-uuid"
        assert body["rows_updated"] == 1
        assert body["nodes"] == 2  # start + end
        assert body["correlation_id"]  # UUID 字符串

        # 审计: workflow.deploy_success 必须写到 AuditLog
        async with _session() as session:
            result = await session.execute(
                select(AuditLog).where(
                    AuditLog.action == "workflow.deploy_success",
                    AuditLog.correlation_id == body["correlation_id"],
                )
            )
            audit = result.scalar_one_or_none()
            assert audit is not None
            assert audit.status == "success"

    @pytest.mark.asyncio
    async def test_502_schema_mismatch(
        self, client, setup_test_db
    ):
        """probe 缺列 → 502, 错误信息含 missing columns + audit schema_mismatch。"""
        agent_id = await _enable_workspace_with_agent()

        # 缺 "graph" 和 "updated_at"
        schema_missing = {
            "id": "uuid", "app_id": "uuid",
            "version": "text", "tenant_id": "text",
        }
        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=schema_missing), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph") as mock_db_write, \
             patch("services.dify_toolkit.deployer.DifyAdminClient.from_workspace",
                   return_value=_stub_dify_admin(publish_ok=True)):
            response = await client.post(
                f"/api/v1/workflows/{agent_id}/deploy",
                json={"yml": SAMPLE_YML},
            )

        assert response.status_code == 502, response.text
        detail = response.json()["detail"]
        assert "schema" in detail.lower() or "missing" in detail.lower()
        # 错误信息列出 missing 列名 (D10: 帮助 admin 排错)
        assert "graph" in detail or "updated_at" in detail
        # DB write 不应被调 (schema probe 失败, 跳过)
        mock_db_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_403_not_owner(self, support_client, setup_test_db):
        """非 workspace_owner (support role) → 403, 不调 deploy。"""
        agent_id = await _enable_workspace_with_agent()

        response = await support_client.post(
            f"/api/v1/workflows/{agent_id}/deploy",
            json={"yml": SAMPLE_YML},
        )

        assert response.status_code == 403
        # 没有 audit (权限被拒在 endpoint 入口, deployer 没机会写 audit)
        async with _session() as session:
            result = await session.execute(
                select(AuditLog).where(
                    AuditLog.action.like("workflow.deploy_%")
                )
            )
            deploy_audits = result.scalars().all()
            # _enable_workspace_with_agent 不会写 audit, 所以应该是空
            assert len(deploy_audits) == 0