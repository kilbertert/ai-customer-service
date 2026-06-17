"""M10+1 — DifyAdminClient (生产侧 Dify 管理 API 客户端)。

vs ``DifyClient`` (M10, 消费侧):
    - DifyClient: 调 ``/v1/workflows/run`` (runtime API key, Bearer ``app-xxx``)
    - DifyAdminClient: 调 ``/console/api/*`` (admin session cookie, email/password),
      用于: 创建 App、创建 Workflow、启用 API、创建 per-app API key、publish workflow

生产侧 5 步工作流 (D3 课程修正 + D8 + D9c 决策):
    Step 1: ``POST /console/api/apps`` (body ``mode="workflow"``)
    Step 2: ``POST /console/api/apps/{app_id}/workflows/draft`` (空 graph 懒创建)
    Step 3: ``POST /console/api/apps/{app_id}/api-enable`` (``{"enable_api": true}``)
    Step 4: ``POST /console/api/apps/{app_id}/api-keys`` → 返回 ``app-xxx`` token
    Step 5: ``POST /console/api/apps/{app_id}/workflows/publish`` (D9c 容错)

Auth 模型 (G3 部分闭环):
    - Dify admin 用 Flask session cookie (3 cookie: access/refresh/csrf)
    - POST 必带 ``X-CSRF-Token`` header
    - LRU cache: ``key=(api_base, admin_email)`` → ``(httpx.AsyncClient, expiry_ts)``
    - TTL: 1 小时 (可构造覆盖), 401 retry 最多 1 次 (避免死循环)
    - session cookie redact: 日志不外泄 ``Set-Cookie`` 内容

失败回滚策略 (D2 + D9c 边界):
    - D3 step 1 失败 → 直接抛, 无回滚 (无 App 行)
    - D3 step 2 失败 → 调 ``DELETE /apps/{id}`` 回滚 step 1, 再抛
    - D9c step 5 失败 (400/422) → 返回 ``False``, 不抛 502, 主流程继续
    - 5xx / 网络错 → 抛 ``DifyUpstreamError``, 走 D2 失败回滚
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from config import settings
from services.dify.exceptions import (
    DifyAuthError,
    DifyBadRequestError,
    DifyConfigError,
    DifyError,
    DifyUpstreamError,
)

logger = logging.getLogger(__name__)


# 4 步生产侧标准超时: 30s (Dify app creation 同步, 用户在 form 提交按钮看到 loading)
DEFAULT_TIMEOUT = 30.0

# LRU session cache 配置 (G3 PARTIALLY RESOLVED)
_SESSION_CACHE_MAX = 512
_SESSION_TTL_SECONDS = 3600  # 1 hour

# Module-level LRU cache. frozen dataclass 不能改 self, 用 module-level dict
# 隔离测试用同一 DifyAdminClient 实例不会污染其他测试 (key 包含 admin_email)
_session_cache: dict[tuple[str, str], tuple[httpx.AsyncClient, float]] = {}


def _safe_log_email(email: str) -> str:
    """日志脱敏: 仅保留 @ 前的 2 字符 + *** + @domain."""
    if "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


@dataclass(frozen=True)
class DifyAdminClient:
    """M10+1: Production-side Dify 管理 API 客户端。

    Auth: Dify admin Flask session cookie (NOT Bearer)。调 ``/console/api/*`` 用于
    创建 App、Workflow、API key、publish workflow。

    设计原则:
        - frozen dataclass: 不可变实例 (api_base/email/password 是构造参数)
        - ``__post_init__`` fail-fast: 空 api_base/email/password → ``DifyConfigError``
        - LRU session cache: 避免每个请求都 login, 1h TTL + 401 retry 1 次
        - 2-step 原子 ``create_app_and_workflow``: step 2 失败回滚 step 1
        - ``publish_workflow`` 容错: 400/422 返回 ``False``, 不抛
        - httpx timeout=30s: 兜底, 超时走 D2 回滚
        - cookie redact: 日志不外泄 session 内容
    """

    api_base: str
    admin_email: str
    admin_password: str
    timeout: float = DEFAULT_TIMEOUT
    cache_ttl: int = _SESSION_TTL_SECONDS

    def __post_init__(self) -> None:
        if not self.api_base or not self.api_base.strip():
            raise DifyConfigError("DifyAdminClient: api_base is empty")
        if not self.admin_email or not self.admin_email.strip():
            raise DifyConfigError("DifyAdminClient: admin_email is empty")
        if not self.admin_password:
            raise DifyConfigError("DifyAdminClient: admin_password is empty")

    @classmethod
    def from_workspace(cls, workspace: Any) -> "DifyAdminClient":
        """从 workspace-like 对象构造 DifyAdminClient。

        Args:
            workspace: 任何有 ``dify_api_base`` / ``dify_admin_email`` /
                       ``dify_admin_password_ref`` 属性的对象。Workspace 字段
                       (D4.1) 是 M10+2 范围, 本类用 ``getattr(..., default)``
                       兜底, 允许 M10+1 测试用 mock / SimpleNamespace 传入。

        Password 处理:
            - 若 ``dify_admin_password_ref`` 以 ``enc:`` 开头 → Fernet 解密
            - 否则按明文直接用 (允许测试或 M10+1 临时态跳过 Fernet)
        """
        api_base = (
            getattr(workspace, "dify_api_base", None)
            or getattr(settings, "dify_api_base", None)
            or ""
        )
        admin_email = getattr(workspace, "dify_admin_email", None) or ""
        admin_password_ref = getattr(workspace, "dify_admin_password_ref", None)

        if admin_password_ref and admin_password_ref.startswith("enc:"):
            from core.encryption import decrypt_api_key

            admin_password = decrypt_api_key(admin_password_ref) or ""
        else:
            admin_password = admin_password_ref or ""

        return cls(
            api_base=api_base,
            admin_email=admin_email,
            admin_password=admin_password,
        )

    # ------------------------------------------------------------------
    # Session management (login + LRU cache)
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """LRU cached session client. 命中且未过期 → 复用, 否则重新 login."""
        key = (self.api_base.rstrip("/"), self.admin_email)
        now = time.monotonic()
        cached = _session_cache.get(key)
        if cached and cached[1] > now:
            return cached[0]
        # 过期或未命中 → login
        client = await self._login()
        if len(_session_cache) >= _SESSION_CACHE_MAX:
            # 简单 FIFO eviction: 超过 512 entries 直接清空 (实际 prod 不会到这规模)
            _session_cache.clear()
        _session_cache[key] = (client, now + self.cache_ttl)
        return client

    async def _login(self) -> httpx.AsyncClient:
        """登录 Dify 拿 session cookie (3 cookie: access/refresh/csrf)。"""
        client = httpx.AsyncClient(
            base_url=self.api_base.rstrip("/"),
            timeout=self.timeout,
        )
        try:
            resp = await client.post(
                "/console/api/login",
                json={
                    "email": self.admin_email,
                    "password": __import__("base64").b64encode(self.admin_password.encode()).decode(),
                    "remember_me": True,
                },
            )
        except httpx.HTTPError as e:
            await client.aclose()
            raise DifyUpstreamError(
                f"Dify login HTTP error: {type(e).__name__}: {e}"
            ) from e

        if resp.status_code in (401, 403):
            await client.aclose()
            raise DifyAuthError(
                f"Dify login failed: {resp.status_code}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            await client.aclose()
            raise DifyBadRequestError(
                f"Dify login unexpected {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
            )

        logger.info(
            "DifyAdminClient login success email=%s status=%d",
            _safe_log_email(self.admin_email),
            resp.status_code,
        )
        return client

    def _evict_cache(self) -> None:
        """清掉本 client key 的 session cache (401 重登前调用)。"""
        key = (self.api_base.rstrip("/"), self.admin_email)
        _session_cache.pop(key, None)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        retry_on_401: bool = True,
    ) -> httpx.Response:
        """通用请求: 自动加 ``X-CSRF-Token``, 401 重登 1 次, 错误路径 raise。

        401 retry 边界:
            - 第一次 401 → 清缓存 + 重登 + 重放 1 次 (用新 client 直调, 不递归)
            - 第二次 401 → 抛 ``DifyAuthError`` (无死循环)
            - 5xx / 网络错 → 不重试, 抛 ``DifyUpstreamError``
            - 4xx 其他 → 不重试, 由调用方按状态码分支
        """
        client = await self._get_client()
        csrf = client.cookies.get("csrf_token", "")
        headers: dict[str, str] = {}
        if method != "GET" and csrf:
            headers["X-CSRF-Token"] = csrf

        try:
            resp = await client.request(method, path, json=json_body, headers=headers)
        except httpx.HTTPError as e:
            raise DifyUpstreamError(
                f"Dify {method} {path} HTTP error: {type(e).__name__}: {e}"
            ) from e

        if resp.status_code == 401 and retry_on_401:
            # 清缓存 + 重登 + 重放 1 次 (直接用新 client 调, 不递归 _request)
            self._evict_cache()
            new_client = await self._get_client()
            new_csrf = new_client.cookies.get("csrf_token", "")
            new_headers: dict[str, str] = {}
            if method != "GET" and new_csrf:
                new_headers["X-CSRF-Token"] = new_csrf
            try:
                resp = await new_client.request(
                    method, path, json=json_body, headers=new_headers
                )
            except httpx.HTTPError as e:
                raise DifyUpstreamError(
                    f"Dify {method} {path} (retry) HTTP error: {e}"
                ) from e
            if resp.status_code == 401:
                raise DifyAuthError(
                    f"Dify {method} {path} 401 even after relogin",
                    status_code=401,
                )
            return resp

        if resp.status_code == 401:
            raise DifyAuthError(
                f"Dify {method} {path} 401 (retry disabled)",
                status_code=401,
            )

        return resp

    # ------------------------------------------------------------------
    # Step 1+2: 2-step create_app_and_workflow (D3 课程修正)
    # ------------------------------------------------------------------

    async def create_app_and_workflow(
        self,
        name: str,
        description: str = "",
        mode: str = "workflow",
        icon_type: str = "emoji",
        icon: str = "🤖",
        icon_background: str = "#FFEAD5",
    ) -> dict:
        """2-step 创建 App + 懒创建 Workflow 行 (D3 课程修正)。

        Step 1: ``POST /console/api/apps`` (body ``mode=workflow``)
        Step 2: ``POST /console/api/apps/{app_id}/workflows/draft`` (空 graph 合法)

        原子性: step 2 失败 → 调 ``DELETE /apps/{app_id}`` 回滚 step 1, 再抛。

        Returns:
            ``{"app_id": str, "workflow_id": str}`` 两个 Dify UUID
        """
        # Step 1: create app
        app_resp = await self._request(
            "POST",
            "/console/api/apps",
            json_body={
                "name": name,
                "description": description,
                "mode": mode,
                "icon_type": icon_type,
                "icon": icon,
                "icon_background": icon_background,
            },
        )
        if app_resp.status_code >= 400:
            raise DifyBadRequestError(
                f"create_app failed: {app_resp.status_code} {app_resp.text[:200]}",
                status_code=app_resp.status_code,
            )
        app_id = app_resp.json().get("id")
        if not app_id:
            raise DifyUpstreamError(
                f"create_app returned no id: {app_resp.text[:200]}"
            )

        # Step 2: lazy create workflow 行 (空 graph)
        try:
            wf_resp = await self._request(
                "POST",
                f"/console/api/apps/{app_id}/workflows/draft",
                json_body={
                    "graph": {"nodes": [], "edges": []},
                    "features": {},
                    "environment_variables": [],
                    "conversation_variables": [],
                },
            )
            if wf_resp.status_code >= 400:
                raise DifyBadRequestError(
                    f"sync_draft_workflow failed: {wf_resp.status_code} "
                    f"{wf_resp.text[:200]}",
                    status_code=wf_resp.status_code,
                )
            workflow_id = wf_resp.json().get("id")
            if not workflow_id:
                # Dify 1.14.2 returns {result:success, hash, updated_at} without id
                # Fetch via GET /console/api/apps/{app_id}/workflows
                try:
                    list_resp = await self._request(
                        "GET",
                        f"/console/api/apps/{app_id}/workflows",
                    )
                    if list_resp.status_code < 400:
                        items = list_resp.json() or []
                        if items:
                            workflow_id = items[0].get("id")
                except Exception as fetch_err:
                    logger.warning("fetch workflows list failed: %s", fetch_err)
            if not workflow_id:
                logger.info(
                    "create_app_and_workflow: Dify 1.14.2 sync_draft returned no id; "
                    "workflow will be linked after Dify Studio config. app_id=%s",
                    app_id,
                )
                return {"app_id": app_id, "workflow_id": ""}
        except Exception as step2_err:
            # 原子性: step 2 失败, 回滚 step 1 (best-effort, 不二次抛)
            logger.warning(
                "create_app_and_workflow step 2 failed (%s), rolling back app %s",
                type(step2_err).__name__,
                app_id,
            )
            await self._delete_app(app_id)
            raise

        return {"app_id": app_id, "workflow_id": workflow_id}

    async def _delete_app(self, app_id: str) -> None:
        """``DELETE /apps/{id}`` — ``create_app_and_workflow`` 失败时回滚用。

        best-effort: 任何异常都 swallow (避免在 except 块里二次抛)。仅记录 warning。
        """
        try:
            resp = await self._request("DELETE", f"/console/api/apps/{app_id}")
            if resp.status_code >= 400:
                logger.warning(
                    "DELETE /apps/%s returned %s: %s",
                    app_id,
                    resp.status_code,
                    resp.text[:200],
                )
        except DifyError as e:
            logger.warning("DELETE /apps/%s raised %s", app_id, e)
        except Exception as e:  # noqa: BLE001 — best-effort cleanup
            logger.warning(
                "DELETE /apps/%s unexpected error: %s", app_id, type(e).__name__
            )

    # ------------------------------------------------------------------
    # Step 3+4: enable API + create per-app API key (D8)
    # ------------------------------------------------------------------

    async def enable_api_and_create_key(self, app_id: str) -> str:
        """2-step 启用 API 并创建 per-app runtime API key (D8)。

        Step 3: ``POST /console/api/apps/{app_id}/api-enable`` (``{"enable_api": true}``)
        Step 4: ``POST /console/api/apps/{app_id}/api-keys`` → 返回 ``app-xxx`` token

        Returns:
            ``app-xxx...`` 格式的 plain token。caller 负责 Fernet 加密存 DB。
        """
        # Step 3
        enable_resp = await self._request(
            "POST",
            f"/console/api/apps/{app_id}/api-enable",
            json_body={"enable_api": True},
        )
        if enable_resp.status_code >= 400:
            raise DifyBadRequestError(
                f"enable_api failed: {enable_resp.status_code} "
                f"{enable_resp.text[:200]}",
                status_code=enable_resp.status_code,
            )

        # Step 4
        key_resp = await self._request(
            "POST",
            f"/console/api/apps/{app_id}/api-keys",
        )
        if key_resp.status_code >= 400:
            raise DifyBadRequestError(
                f"create_api_key failed: {key_resp.status_code} "
                f"{key_resp.text[:200]}",
                status_code=key_resp.status_code,
            )
        token = key_resp.json().get("token")
        if not token:
            raise DifyUpstreamError(
                f"create_api_key returned no token: {key_resp.text[:200]}"
            )
        return token

    # ------------------------------------------------------------------
    # Step 5: publish_workflow (D9c — 容错 400/422)
    # ------------------------------------------------------------------

    async def publish_workflow(self, app_id: str) -> bool:
        """D9c: 自动 publish, 容错 400/422 (空 graph 校验失败等)。

        Returns:
            True: 200/201 publish 成功
            False: 400/422 Dify 校验失败 (空 graph 无 Start 节点等), 不抛
            raise ``DifyUpstreamError``: 5xx 等真错误

        D9c 与 D2 边界 (kickoff §5.3):
            - publish 400/422 = 业务可恢复 (admin 在 Dify UI 补 graph), 不回滚
            - step 1-4 失败 = 系统故障, 回滚
        """
        try:
            # Dify 1.14.2 publish endpoint requires explicit Content-Type: application/json
            # with valid PublishWorkflowPayload body; empty body → 415
            resp = await self._request(
                "POST",
                f"/console/api/apps/{app_id}/workflows/publish",
                json_body={"marked_name": "", "marked_comment": ""},
            )
        except DifyError:
            raise  # 5xx 已 raise, 不要 swallow

        if resp.status_code in (200, 201):
            return True
        if resp.status_code in (400, 422):
            # Dify 校验失败 (空 graph 等), 不抛, 让 caller 标记 publish_failed
            return False
        # 4xx 其他 (404/403/...): 当 upstream 错误抛, caller 回滚
        raise DifyUpstreamError(
            f"publish_workflow unexpected {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )
