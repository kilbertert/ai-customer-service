"""M11+ P0-C PR 3 残余 — Deployer 单元测试 (D8/D9/D10 决策闭环)。

4 个单元测试覆盖 P0-C PR 2 spec §4.4 测试矩阵的前 4 行:
  - test_from_workspace:        4 字段全 set, 引用 DifyAdminClient
  - test_probe_schema_ok:       probe 返回 [] → 走 Plan A 主路径 (DB + publish)
  - test_probe_schema_missing:  probe 缺列 → raise DifySchemaError
  - test_db_fallback_on_5xx:    Dify publish 5xx → DifyPublishError
  - test_publish_api_success:   D9c 200 → 不走 fallback, 写 deploy_success audit

端点测试在 test_api_workflow_deploy.py (走 FastAPI TestClient)。

设计: 直接替换 deployer.dify_admin 为 MagicMock(避免 respx + login 链路),
只测 deployer 自身的 probe → DB write → publish → audit 编排逻辑。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.dify.exceptions import DifyUpstreamError
from services.dify_toolkit import (
    Deployer,
    DifyPublishError,
    DifySchemaError,
)


# ── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
def mock_workspace():
    """M11+ P0-A 落地形态: 4 字段齐 + dify_enabled=True."""
    return SimpleNamespace(
        id=42,
        dify_api_base="https://dify.test",
        dify_admin_email="admin@dify.test",
        dify_admin_password_ref="plain-secret-pw",
        dify_tenant_id="tenant-uuid-42",
        dify_enabled=True,
    )


@pytest.fixture
def mock_db_session():
    """SQLAlchemy AsyncSession mock — 只关心 commit/rollback/add, 不真 query."""
    session = MagicMock()

    async def _noop(*_args, **_kwargs):
        return None

    session.add = MagicMock()
    session.commit = MagicMock(side_effect=_noop)
    session.rollback = MagicMock(side_effect=_noop)
    session.refresh = MagicMock(side_effect=_noop)
    return session


def _ctx_mock(value):
    """构造一个 ``__enter__ / __exit__`` ctx manager 返回 ``value``."""
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=value)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


SCHEMA_OK = {
    "id": "uuid", "app_id": "uuid", "version": "text",
    "graph": "jsonb", "updated_at": "timestamp", "tenant_id": "text",
}


def _stub_publish(*, return_value=None, side_effect=None):
    """返回 AsyncMock 包装的 publish_workflow."""
    return AsyncMock(return_value=return_value, side_effect=side_effect)


# ── tests ──────────────────────────────────────────────────────────────────
class TestFromWorkspace:
    """D9 决策: 4 字段全 set."""

    def test_from_workspace_sets_all_4_fields(self, mock_workspace):
        deployer = Deployer.from_workspace(mock_workspace)
        assert deployer.workspace_id == 42
        assert deployer.dify_tenant_id == "tenant-uuid-42"
        # dify_admin 必须是 DifyAdminClient 实例, 凭据来自 workspace 4 字段
        assert hasattr(deployer.dify_admin, "api_base")
        assert deployer.dify_admin.api_base == "https://dify.test"
        assert deployer.dify_admin.admin_email == "admin@dify.test"
        assert deployer.dify_admin.admin_password == "plain-secret-pw"

    def test_from_workspace_without_tenant_id(self, mock_workspace):
        """Plan A 早期: workspace.dify_tenant_id 还没填 → dify_tenant_id=None."""
        mock_workspace.dify_tenant_id = None
        deployer = Deployer.from_workspace(mock_workspace)
        assert deployer.dify_tenant_id is None


class TestProbeSchema:
    """D10 决策: probe_workflows_schema() + check_required_columns() 守门。"""

    @pytest.mark.asyncio
    async def test_probe_schema_ok_runs_full_deploy(
        self, mock_workspace, mock_db_session
    ):
        """schema OK → DB write + Dify publish 都调, 返回 DeployResult。"""
        deployer = Deployer.from_workspace(mock_workspace)
        deployer.dify_admin = MagicMock()
        deployer.dify_admin.publish_workflow = _stub_publish(return_value=True)

        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=SCHEMA_OK), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph",
                   return_value=1):
            result = await deployer.deploy(
                yml="app:\n  name: t\nworkflow:\n  graph:\n    nodes: [a, b]\n",
                app_id="app-uuid",
                actor_user_id=1,
                correlation_id="corr-1",
                db_session=mock_db_session,
                tenant_id_for_audit="42",
            )

        assert result.deployed is True
        assert result.app_id == "app-uuid"
        assert result.rows_updated == 1
        assert result.nodes == 2
        deployer.dify_admin.publish_workflow.assert_awaited_once_with("app-uuid")

    @pytest.mark.asyncio
    async def test_probe_schema_missing_raises(
        self, mock_workspace, mock_db_session
    ):
        """缺列 → raise DifySchemaError, 不调 DB write / Dify publish。"""
        deployer = Deployer.from_workspace(mock_workspace)
        deployer.dify_admin = MagicMock()
        deployer.dify_admin.publish_workflow = _stub_publish(return_value=True)

        # 缺 "graph" 和 "updated_at" (D10 期望)
        schema_missing = {
            "id": "uuid", "app_id": "uuid",
            "version": "text", "tenant_id": "text",
        }
        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=schema_missing), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph") as mock_db_write:
            with pytest.raises(DifySchemaError) as exc_info:
                await deployer.deploy(
                    yml="app:\n  name: t\nworkflow:\n  graph:\n    nodes: []\n",
                    app_id="app-uuid",
                    actor_user_id=1,
                    correlation_id="corr-2",
                    db_session=mock_db_session,
                    tenant_id_for_audit="42",
                )

        assert "graph" in exc_info.value.missing
        assert "updated_at" in exc_info.value.missing
        # DB write 不应被调 (schema 不通过, 跳过)
        mock_db_write.assert_not_called()
        # publish 也不应被调
        deployer.dify_admin.publish_workflow.assert_not_called()


class TestPublishFailure:
    """D9c 容错: Dify publish 5xx → DifyPublishError (不静默死)。"""

    @pytest.mark.asyncio
    async def test_db_fallback_on_5xx_raises(
        self, mock_workspace, mock_db_session
    ):
        """DB write OK 但 Dify publish 5xx → raise DifyPublishError。

        DB 已写但 Dify 端未确认 publish, deployer 抛 DifyPublishError 让端点 502,
        admin 后续在 Dify UI 重 publish 或重新调本端点。
        """
        deployer = Deployer.from_workspace(mock_workspace)
        deployer.dify_admin = MagicMock()
        deployer.dify_admin.publish_workflow = _stub_publish(
            side_effect=DifyUpstreamError("publish 500", status_code=500),
        )

        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=SCHEMA_OK), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph",
                   return_value=1):
            with pytest.raises(DifyPublishError) as exc_info:
                await deployer.deploy(
                    yml="app:\n  name: t\nworkflow:\n  graph:\n    nodes: [a]\n",
                    app_id="app-uuid",
                    actor_user_id=1,
                    correlation_id="corr-3",
                    db_session=mock_db_session,
                    tenant_id_for_audit="42",
                )

        assert "5xx" in str(exc_info.value) or "publish" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_publish_api_success_no_db_fallback(
        self, mock_workspace, mock_db_session
    ):
        """D9c 200 → 不走 db_fallback audit, 写 deploy_success。"""
        deployer = Deployer.from_workspace(mock_workspace)
        deployer.dify_admin = MagicMock()
        deployer.dify_admin.publish_workflow = _stub_publish(return_value=True)

        with patch("services.dify_toolkit.deployer.db.get_conn",
                   return_value=_ctx_mock(MagicMock())), \
             patch("services.dify_toolkit.deployer.db.probe_workflows_schema",
                   return_value=SCHEMA_OK), \
             patch("services.dify_toolkit.deployer.db.update_workflow_graph",
                   return_value=1):
            await deployer.deploy(
                yml="app:\n  name: t\nworkflow:\n  graph:\n    nodes: [a, b]\n",
                app_id="app-uuid",
                actor_user_id=1,
                correlation_id="corr-4",
                db_session=mock_db_session,
                tenant_id_for_audit="42",
            )

        # 至少 commit 一次 (AuditLog success)
        assert mock_db_session.commit.call_count >= 1
        # add() 至少被调一次 (AuditLog success)
        added_actions = [
            call.args[0].action
            for call in mock_db_session.add.call_args_list
            if call.args and hasattr(call.args[0], "action")
        ]
        assert "workflow.deploy_success" in added_actions
        # 没有 deploy_publish_5xx
        assert "workflow.deploy_publish_5xx" not in added_actions