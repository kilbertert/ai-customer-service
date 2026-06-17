"""M11 PR3 — B 端租户注册业务核心。

2 阶段事务:
    阶段 1: basjoo DB 原子写 (workspace + quota + admin_user + audit)
    阶段 2: 调 Dify tenant provisioner(失败 → 标记 failed, 写 audit)
    阶段 3: 把 Dify 写回结果落到 basjoo DB (dify_tenant_id/dify_account_id/ready)

失败重试: ``retry_provisioning`` 由 cron 调用, 3 次后转 failed_permanent。
"""
import logging
import uuid
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from models import AdminUser, AuditLog, Workspace, WorkspaceQuota
from services.auth_service import AuthService
from services.dify.tenant_provisioner import DifyTenantProvisioner

logger = logging.getLogger(__name__)

# 给 retry 调用占位: Dify 那边 owner_password 是一次性的, 重新 provision 时
# basjoo 不会把明文密码再发给 Dify;实际重试只重试"已生成的 Dify 账号是否能
# 关联上 basjoo workspace", 此处为幂等回放占位字符串。
_RETRY_PASSWORD_PLACEHOLDER = "<retry-no-op>"


class TenantService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.provisioner = DifyTenantProvisioner()
        self.auth_service = AuthService(db)

    async def register_tenant(
        self,
        workspace_name: str,
        owner_name: str,
        owner_email: str,
        owner_password: str,
        signup_idempotency_key: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        # ── 阶段 1: basjoo DB 原子写 ──────────────────────────────────────
        # 注: 端点层 ``db.execute(select AdminUser)`` 已开启隐式事务,
        # 因此这里改用显式 commit 而不是 ``async with self.db.begin():``
        # (后者会与隐式事务冲突报 "A transaction is already begun")。
        workspace = Workspace(
            name=workspace_name,
            owner_email=owner_email,
            dify_provisioning_status="provisioning",
            dify_provisioning_attempts=1,
            signup_idempotency_key=signup_idempotency_key,
        )
        self.db.add(workspace)
        await self.db.flush()

        quota = WorkspaceQuota(workspace_id=workspace.id)
        self.db.add(quota)

        admin = await self.auth_service.create_admin(
            email=owner_email,
            password=owner_password,
            name=owner_name,
            role="tenant_owner",
            workspace_id=workspace.id,
        )

        self.db.add(AuditLog(
            tenant_id=str(workspace.id),
            actor_user_id=admin.id,
            action="tenant.create",
            correlation_id=correlation_id,
            status="success",
        ))
        await self.db.commit()
        workspace_id = workspace.id
        admin_id = admin.id

        # ── 阶段 2: 调 Dify(事务外) ──────────────────────────────────────
        try:
            dify_result = await self.provisioner.provision_tenant(
                workspace_name=workspace_name,
                owner_email=owner_email,
                owner_name=owner_name,
                owner_password=owner_password,
                idempotency_key=signup_idempotency_key,
                correlation_id=correlation_id,
            )
        except Exception as e:
            logger.exception(
                "Dify provision failed workspace_id=%s: %s", workspace_id, e
            )
            ws = await self.db.get(Workspace, workspace_id)
            ws.dify_provisioning_status = "failed"
            ws.dify_provisioning_last_error = str(e)[:1000]
            self.db.add(AuditLog(
                tenant_id=str(workspace_id),
                actor_user_id=admin_id,
                action="tenant.provision",
                correlation_id=correlation_id,
                status="failed",
                error_detail=str(e)[:2000],
            ))
            await self.db.commit()
            access_token = self.auth_service.create_access_token(
                data={"sub": str(admin_id)}
            )
            return {
                "access_token": access_token,
                "workspace_id": workspace_id,
                "dify_initial_password": "",
                "provisioning_status": "failed",
                "correlation_id": correlation_id,
            }

        # ── 阶段 3: 写 Dify 成功结果回 basjoo DB ──────────────────────────
        ws = await self.db.get(Workspace, workspace_id)
        ws.dify_tenant_id = dify_result["workspace_id"]
        ws.dify_account_id = dify_result["owner_account_id"]
        ws.dify_provisioning_status = "ready"
        ws.dify_provisioning_last_error = None
        self.db.add(AuditLog(
            tenant_id=str(workspace_id),
            actor_user_id=admin_id,
            action="tenant.provision",
            correlation_id=correlation_id,
            dify_request_id=dify_result.get("dify_request_id"),
            status="success",
        ))
        await self.db.commit()

        access_token = self.auth_service.create_access_token(
            data={"sub": str(admin_id)}
        )
        return {
            "access_token": access_token,
            "workspace_id": workspace_id,
            "dify_initial_password": dify_result["initial_password"],
            "provisioning_status": "ready",
            "correlation_id": correlation_id,
        }

    async def retry_provisioning(
        self, workspace_id: int, correlation_id: str
    ) -> Dict[str, Any]:
        ws = await self.db.get(Workspace, workspace_id)
        if not ws:
            return {"success": False, "error": "Workspace not found"}

        ws.dify_provisioning_status = "provisioning"
        ws.dify_provisioning_attempts += 1
        await self.db.commit()

        try:
            dify_result = await self.provisioner.provision_tenant(
                workspace_name=ws.name,
                owner_email=ws.owner_email,
                owner_name=ws.name,
                owner_password=_RETRY_PASSWORD_PLACEHOLDER,
                idempotency_key=ws.signup_idempotency_key or str(uuid.uuid4()),
                correlation_id=correlation_id,
            )
        except Exception as e:
            max_attempts = 3
            ws.dify_provisioning_status = (
                "failed_permanent"
                if ws.dify_provisioning_attempts >= max_attempts
                else "failed"
            )
            ws.dify_provisioning_last_error = str(e)[:1000]
            await self.db.commit()
            return {"success": False, "error": str(e)}

        ws.dify_tenant_id = dify_result["workspace_id"]
        ws.dify_account_id = dify_result["owner_account_id"]
        ws.dify_provisioning_status = "ready"
        ws.dify_provisioning_last_error = None
        await self.db.commit()
        return {"success": True, "provisioning_status": "ready"}
