"""M11 PR3 — basjoo → Dify tenant provisioning 调用 wrapper。

基于 PR1 的 ``DifyAdminClient`` 复用其登录态 + HTTP 客户端,
本模块负责 ``/console/api/admin/workspaces`` POST 调用 + 异常归一化。

设计原则:
    - 不持有状态, 每次 ``provision_tenant`` 走 PR1 缓存的 session
    - 异常分两类: ``DifyTenantConflictError`` (409, 通常是 email/名字冲突) +
      ``DifyTenantProvisionError`` (其他 4xx/5xx/网络错误)
    - 响应体字段透传, ``initial_password`` 来自 Dify 一次性生成的明文密码
      (basjoo DB 不持久化, 由 owner 首次登录后立即改密)

认证 (M11 PR3 修复 — chicken-and-egg 解决):
    - Provisioning 阶段 workspace 还没有自己的 Dify 凭据, 必须用系统级
      super-admin (``settings.dify_admin_email`` / ``settings.dify_admin_password``)
    - 之前 ``DifyAdminClient()`` 空构造是 contract bug — frozen dataclass
      必填 3 字段, 抛 ``TypeError`` 一直兜底成 500
    - 现在: 配置缺失 → 立刻抛 ``DifyConfigError`` 让端点层转 503 (degraded),
      而不是 500 (broken)
"""
import logging
from typing import Any, Dict, Optional

from config import settings
from services.dify.admin_client import DifyAdminClient
from services.dify.exceptions import DifyConfigError

logger = logging.getLogger(__name__)


class DifyTenantProvisionError(Exception):
    """Dify tenant provisioning 失败基类。"""


class DifyTenantConflictError(DifyTenantProvisionError):
    """Dify 返回 409 — 通常 email/workspace_name 已存在。"""


class DifyTenantProvisioner:
    def __init__(self, client: Optional[DifyAdminClient] = None) -> None:
        if client is not None:
            self.client = client
            self._bearer_key = ""
            return

        api_base = (settings.dify_api_base or "").strip()
        admin_api_key = (settings.dify_admin_api_key or "").strip()
        admin_email = (settings.dify_admin_email or "").strip()
        admin_password = settings.dify_admin_password or ""

        if not api_base:
            raise DifyConfigError(
                "DifyTenantProvisioner: DIFY_API_BASE not set. "
                "Required for /api/v1/tenants/register to reach Dify admin endpoints."
            )

        # M11 PR1 fork: 优先 Bearer ADMIN_API_KEY, fallback email/password
        if admin_api_key:
            self._bearer_key = admin_api_key
            self.client = None
            return

        if not admin_email or not admin_password:
            missing = []
            if not admin_email:
                missing.append("DIFY_ADMIN_EMAIL")
            if not admin_password:
                missing.append("DIFY_ADMIN_PASSWORD")
            raise DifyConfigError(
                "DifyTenantProvisioner: system Dify admin not configured. "
                + "Missing env vars: " + ", ".join(missing)
                + " (or set DIFY_ADMIN_API_KEY for Bearer auth). "
                + "Required for /api/v1/tenants/register to create new Dify "
                + "workspaces (workspace-level Dify creds do not exist yet at provision time)."
            )

        self._bearer_key = ""
        self.client = DifyAdminClient(
            api_base=api_base,
            admin_email=admin_email,
            admin_password=admin_password,
        )

    def _bearer_base_url(self) -> str:
        return (settings.dify_admin_api_base or settings.dify_api_base or "").rstrip("/").rstrip("/v1")

    def _bearer_headers(self, correlation_id: str = "") -> dict:
        h = {"Authorization": "Bearer " + self._bearer_key}
        if correlation_id:
            h["X-Basjoo-Correlation-Id"] = correlation_id
        return h

    async def _bearer_post(self, path, body, correlation_id: str = ""):
        import httpx
        async with httpx.AsyncClient(
            base_url=self._bearer_base_url(),
            timeout=30.0,
        ) as client:
            return await client.post(path, json=body, headers=self._bearer_headers(correlation_id))

    async def _bearer_delete(self, path):
        import httpx
        async with httpx.AsyncClient(
            base_url=self._bearer_base_url(),
            timeout=30.0,
        ) as client:
            return await client.delete(path, headers=self._bearer_headers())

    async def _bearer_get(self, path):
        import httpx
        async with httpx.AsyncClient(
            base_url=self._bearer_base_url(),
            timeout=30.0,
        ) as client:
            return await client.get(path, headers=self._bearer_headers())

    async def provision_tenant(
        self,
        workspace_name: str,
        owner_email: str,
        owner_name: str,
        owner_password: str,
        idempotency_key: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        if self._bearer_key:
            resp = await self._bearer_post(
                "/console/api/admin/workspaces",
                {
                    "workspace_name": workspace_name,
                    "owner_email": owner_email,
                    "owner_name": owner_name,
                    "owner_password": owner_password,
                    "idempotency_key": idempotency_key,
                },
                correlation_id=correlation_id,
            )
        else:
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
        """删除已 provision 到 Dify 的 workspace(用于注册阶段失败回滚)。"""
        try:
            if self._bearer_key:
                resp = await self._bearer_delete(
                    "/console/api/admin/workspaces/" + workspace_id
                )
            else:
                client = await self.client._get_client()
                resp = await client.delete(
                    "/console/api/admin/workspaces/" + workspace_id,
                    headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
                )
            return resp.status_code in (200, 204, 404)
        except Exception as e:
            logger.exception("Failed to rollback Dify tenant %s: %s", workspace_id, e)
            return False

    async def health_check(self) -> bool:
        try:
            if self._bearer_key:
                resp = await self._bearer_get(
                    "/console/api/admin/workspaces/health"
                )
            else:
                client = await self.client._get_client()
                resp = await client.get("/console/api/admin/workspaces/health")
            return resp.status_code == 200
        except Exception:
            return False
