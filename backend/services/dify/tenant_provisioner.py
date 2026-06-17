"""M11 PR3 — basjoo → Dify tenant provisioning 调用 wrapper。

基于 PR1 的 ``DifyAdminClient`` 复用其登录态 + HTTP 客户端,
本模块负责 ``/console/api/admin/workspaces`` POST 调用 + 异常归一化。

设计原则:
    - 不持有状态, 每次 ``provision_tenant`` 走 PR1 缓存的 session
    - 异常分两类: ``DifyTenantConflictError`` (409, 通常是 email/名字冲突) +
      ``DifyTenantProvisionError`` (其他 4xx/5xx/网络错误)
    - 响应体字段透传, ``initial_password`` 来自 Dify 一次性生成的明文密码
      (basjoo DB 不持久化, 由 owner 首次登录后立即改密)
"""
import logging
from typing import Any, Dict

from services.dify.admin_client import DifyAdminClient

logger = logging.getLogger(__name__)


class DifyTenantProvisionError(Exception):
    """Dify tenant provisioning 失败基类。"""


class DifyTenantConflictError(DifyTenantProvisionError):
    """Dify 返回 409 — 通常 email/workspace_name 已存在。"""


class DifyTenantProvisioner:
    def __init__(self, client: DifyAdminClient | None = None) -> None:
        self.client = client or DifyAdminClient()

    async def provision_tenant(
        self,
        workspace_name: str,
        owner_email: str,
        owner_name: str,
        owner_password: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        client = await self.client._get_client()
        resp = await client.post(
            "/console/api/admin/workspaces",
            json={
                "workspace_name": workspace_name,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "owner_password": owner_password,
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-CSRF-Token": client.cookies.get("csrf_token", ""),
                "X-Basjoo-Correlation-Id": correlation_id,
            },
        )
        if resp.status_code == 409:
            raise DifyTenantConflictError(
                f"Dify returned conflict: {resp.text[:500]}"
            )
        if resp.status_code >= 400:
            raise DifyTenantProvisionError(
                f"Dify returned {resp.status_code}: {resp.text[:500]}"
            )
        data = resp.json()
        return {
            "workspace_id": data["workspace_id"],
            "owner_account_id": data["owner_account_id"],
            "initial_password": data["initial_password"],
            "dify_request_id": resp.headers.get("X-Request-Id"),
        }

    async def rollback_tenant(self, workspace_id: str) -> bool:
        """删除已 provision 到 Dify 的 workspace(用于注册阶段失败回滚)。

        返回 True 表示 Dify 接受了删除或根本不存在(False 让 caller 决定重试)。
        """
        try:
            client = await self.client._get_client()
            resp = await client.delete(
                f"/console/api/admin/workspaces/{workspace_id}",
                headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
            )
            return resp.status_code in (200, 204, 404)
        except Exception as e:
            logger.exception("Failed to rollback Dify tenant %s: %s", workspace_id, e)
            return False

    async def health_check(self) -> bool:
        try:
            client = await self.client._get_client()
            resp = await client.get("/console/api/admin/workspaces/health")
            return resp.status_code == 200
        except Exception:
            return False
