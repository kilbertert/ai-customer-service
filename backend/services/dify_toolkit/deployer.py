"""Deploy a Dify workflow DSL to the workspace's Dify tenant (P0-C PR 2)。

C1 安全收敛 (D8): 删 SSH / docker exec / paramiko,改 basjoo-side 直连 PG + 调
``DifyAdminClient.publish_workflow``。所有路径写 ``AuditLog`` 留痕(workflow.deploy_*)。

C3 租户路由 (D9): ``Deployer.from_workspace(ws)`` 从 ``Workspace.dify_api_base`` /
``dify_admin_email`` / ``dify_admin_password_ref`` / ``dify_tenant_id`` 4 字段构造,
per-tenant 隔离(Plan A 共用单 Dify 实例时,DB UPDATE 加 tenant_id 过滤)。

C2 升级探针 (D10): 开头调 ``db.probe_workflows_schema()`` + ``db.check_required_columns()``,
缺列 / 类型错 raise ``DifySchemaError`` → 端点 502 + audit ``workflow.deploy_schema_mismatch``,
不静默 break(Dify 1.15+ 升级时 P0-B §6 跑回归)。

调用模式:
    deployer = Deployer.from_workspace(workspace)
    result = await deployer.deploy(
        yml=yml_text,
        app_id=agent.dify_app_id,
        actor_user_id=admin.id,
        correlation_id=str(uuid.uuid4()),
        db_session=async_session,
    )

异常:
    DifySchemaError: 缺列 / 类型错 → 端点 502
    DifyPublishError: DB 写失败 或 Dify publish 失败 → 端点 502
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from models import AuditLog, Workspace
from services.dify.admin_client import DifyAdminClient
from services.dify.exceptions import DifyUpstreamError

from . import db
from .constants import DIFY_WORKFLOWS_REQUIRED_COLUMNS
from .exceptions import DifyPublishError, DifySchemaError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeployResult:
    """deploy() 成功路径返回值。

    fields:
        app_id:        Dify app UUID
        deployed:      True (DB 写 + Dify publish 都 OK)
        rows_updated:  DB UPDATE 受影响行数 (1 = 命中 published row)
        nodes:         workflow graph 顶层节点数 (粗校验用)
    """

    app_id: str
    deployed: bool
    rows_updated: int
    nodes: int


class Deployer:
    """Per-workspace Dify workflow deployer.

    用法:
        deployer = Deployer.from_workspace(workspace)
        await deployer.deploy(yml, app_id, actor_user_id=..., correlation_id=...,
                              db_session=async_session, tenant_id_for_audit=...)

    设计:
      - DB 直连 (services.dify_toolkit.db) 是 graph 写入的唯一可靠路径 — Dify 1.14.2
        的 HTTP API 没有稳定的"写 workflow graph"端点(老 toolkit 也是走 DB 直写)。
      - ``DifyAdminClient.publish_workflow`` 触发 Dify 把当前 draft 标为 published,
        走 Dify auth + RBAC(比直写 DB 安全)。
      - publish 失败 5xx → raise DifyPublishError(DB 已写但 Dify 端未确认 publish,
        admin 在 Dify UI 重试 publish 或重新调本端点)。
      - publish 失败 400/422 → D9c 容错返 False,deployer 转 DifyPublishError
        (graph 语法错,应回滚 yml 重新校验)。
    """

    def __init__(
        self,
        *,
        dify_admin: DifyAdminClient,
        workspace_id: int,
        dify_tenant_id: str | None = None,
    ) -> None:
        self.dify_admin = dify_admin
        self.workspace_id = workspace_id
        self.dify_tenant_id = dify_tenant_id

    @classmethod
    def from_workspace(cls, workspace: Workspace) -> "Deployer":
        """D9 决策: 从 workspace 拿 4 字段构造, per-tenant 隔离。

        workspace.dify_enabled 必填 — caller (endpoint) 已 check 过, 这里不重复。
        """
        return cls(
            dify_admin=DifyAdminClient.from_workspace(workspace),
            workspace_id=workspace.id,
            dify_tenant_id=getattr(workspace, "dify_tenant_id", None),
        )

    # ── Public API ──────────────────────────────────────────────────────
    async def deploy(
        self,
        *,
        yml: str,
        app_id: str,
        actor_user_id: int,
        correlation_id: str,
        db_session: AsyncSession,
        tenant_id_for_audit: str,
    ) -> DeployResult:
        """部署 yml 到指定 app。

        Args:
            yml:                 Dify workflow YAML 文本(``Workflow.to_yaml()`` 输出)
            app_id:              Dify app UUID(从 ``Agent.dify_app_id`` 拿)
            actor_user_id:       操作用户 ID(``admins.id``, 用于 audit)
            correlation_id:      一次调用共享同一 ID,串多条 audit 行
            db_session:          SQLAlchemy async session(端点 ``Depends(get_db)``)
            tenant_id_for_audit: 写入 AuditLog.tenant_id 的值(用 Workspace.id 字符串化)

        Returns:
            DeployResult — 成功时

        Raises:
            DifySchemaError: 缺列 / 类型错
            DifyPublishError: 部署失败(任意阶段)
        """
        # 1. parse yml → graph dict
        try:
            graph_dict = yaml.safe_load(yml)
            if not isinstance(graph_dict, dict):
                raise yaml.YAMLError(
                    f"workflow yml must be a mapping, got {type(graph_dict).__name__}"
                )
            graph_json = json.dumps(graph_dict, ensure_ascii=False)
        except yaml.YAMLError as e:
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_yaml_parse_failed", "failed", f"yaml: {e}",
            )
            raise DifyPublishError(app_id, f"yaml parse failed: {e}") from e

        nodes = len(graph_dict.get("workflow", {}).get("graph", {}).get("nodes", []))

        # 2. probe schema (D10 决策) — 缺列即 5xx
        try:
            with db.get_conn() as conn:
                actual = db.probe_workflows_schema(conn)
                missing = db.check_required_columns(actual)
        except Exception as e:  # noqa: BLE001 — probe 阶段任何错都包成 schema err
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_probe_failed", "failed", f"probe: {e}",
            )
            raise DifySchemaError(
                missing=list(DIFY_WORKFLOWS_REQUIRED_COLUMNS.keys()),
                actual={},
            ) from e

        if missing:
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_schema_mismatch", "failed",
                f"missing={missing} actual={actual}",
            )
            raise DifySchemaError(missing=missing, actual=actual)

        # 3. DB write (the only reliable graph write path)
        try:
            with db.get_conn() as conn:
                rowcount = db.update_workflow_graph(
                    conn,
                    app_id=app_id,
                    graph=graph_json,
                    tenant_id=self.dify_tenant_id,
                )
        except Exception as e:  # noqa: BLE001
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_db_failed", "failed", f"db write: {e}",
            )
            raise DifyPublishError(app_id, f"DB write failed: {e}") from e

        if rowcount == 0:
            # app 不存在 / tenant_id 不匹配 / 没有 published row
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_db_zero_row", "failed",
                f"app_id={app_id} tenant_id={self.dify_tenant_id} "
                f"matched 0 published rows (app not found or tenant mismatch)",
            )
            raise DifyPublishError(
                app_id,
                "DB write matched 0 rows (app not found or tenant_id mismatch)",
            )

        # 4. trigger Dify publish (D9c — 容错 400/422)
        try:
            publish_ok = await self.dify_admin.publish_workflow(app_id)
        except DifyUpstreamError as e:
            # DB 已写但 Dify publish 5xx — admin 后续在 Dify UI 重 publish 即可
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_publish_5xx", "failed",
                f"db write OK but Dify publish 5xx: {e}",
            )
            raise DifyPublishError(
                app_id, f"DB write OK but Dify publish 5xx: {e}"
            ) from e
        except Exception as e:  # noqa: BLE001 — 不可预期
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_publish_unexpected", "failed",
                f"unexpected: {type(e).__name__}: {e}",
            )
            raise DifyPublishError(
                app_id, f"Dify publish unexpected: {e}"
            ) from e

        if not publish_ok:
            # D9c 400/422 — Dify 说 graph 校验失败(空 graph / 缺 Start 等)
            await self._audit(
                db_session, tenant_id_for_audit, actor_user_id, correlation_id,
                "workflow.deploy_publish_invalid", "failed",
                "Dify 400/422 (graph invalid - admin should fix yml)",
            )
            raise DifyPublishError(
                app_id, "Dify 400/422 — graph invalid (admin should fix yml)"
            )

        # 5. all good — audit success
        await self._audit(
            db_session, tenant_id_for_audit, actor_user_id, correlation_id,
            "workflow.deploy_success", "success",
            f"app_id={app_id} nodes={nodes} rows_updated={rowcount}",
        )
        return DeployResult(
            app_id=app_id,
            deployed=True,
            rows_updated=rowcount,
            nodes=nodes,
        )

    # ── Audit helpers ───────────────────────────────────────────────────
    async def _audit(
        self,
        db_session: AsyncSession,
        tenant_id: str,
        actor_user_id: int,
        correlation_id: str,
        action: str,
        status: str,
        error_detail: str | None,
    ) -> None:
        """写 AuditLog, swallow DB error (audit 不阻断 deploy 主路径)。

        ``dify_request_id`` 暂不写 — 没有 Dify API 调用跟 audit 直接配对。
        """
        try:
            entry = AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action=action,
                correlation_id=correlation_id,
                status=status,
                error_detail=error_detail[:1024] if error_detail else None,
            )
            db_session.add(entry)
            await db_session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "AuditLog write failed (action=%s status=%s): %s",
                action, status, exc,
            )
            try:
                await db_session.rollback()
            except Exception:  # noqa: BLE001
                pass