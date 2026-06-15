"""M10+1 — DifyAdminClient unit tests.

覆盖 kickoff §6.5 列出的 16 case (test 17 deferred to M10+2):

构造期 fail-fast (3):
    1-3. ``__post_init__`` 拒空 api_base / admin_email / admin_password
2-step create_app_and_workflow (3):
    4. happy path → ``{app_id, workflow_id}``
    5. step 1 失败 → ``DifyBadRequestError`` (无回滚, 因无 App 行)
    6. step 2 失败 → 回滚 step 1 (DELETE /apps/{id} called) + 再抛
enable_api_and_create_key (1):
    7. happy path → 返回 ``app-xxx`` token
Auth (2):
    8. login 401 → ``DifyAuthError``
    9. 请求 401 → evict cache + 重登 + 重放 1 次成功
from_workspace (2):
    10. ``dify_admin_password_ref`` 以 ``enc:`` 开头 → Fernet decrypt
    11. ``dify_admin_password_ref`` 非密文 → 当明文用
session cache TTL (1):
    12. ``cache_ttl=-1`` → 每次都重登
publish_workflow (4):
    13. 200 → True
    14. 400 → False (D9c 空 graph 校验失败)
    15. 422 → False (D9c 空 graph 校验失败)
    16. 500 → ``DifyUpstreamError``

Test 17 ``test_create_agent_publish_failed_status_persists`` — TODO M10+2:
    需要 ``create_agent`` endpoint 实际调 ``DifyAdminClient.publish_workflow``;
    M10+1 endpoint 还没改, M10+2 PR1 才接入。参见
    ``docs/handoffs/M10PLUS-agent-dify-integration.md`` §6.4.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx

from services.dify.admin_client import DifyAdminClient, _session_cache
from services.dify.exceptions import (
    DifyAuthError,
    DifyBadRequestError,
    DifyConfigError,
    DifyUpstreamError,
)


# ===== Fixtures & helpers =====


@pytest.fixture(autouse=True)
def _clear_session_cache():
    """隔离 module-level session cache (frozen dataclass 不能 hold mutable state)."""
    _session_cache.clear()
    yield
    _session_cache.clear()


def _admin_client_factory(**overrides: Any) -> DifyAdminClient:
    """构造测试用的 DifyAdminClient (避免与 conftest.client fixture 重名)."""
    kwargs: dict[str, Any] = dict(
        api_base="https://dify.test",
        admin_email="admin@dify.test",
        admin_password="secret-pw",
    )
    kwargs.update(overrides)
    return DifyAdminClient(**kwargs)


def _login_response() -> httpx.Response:
    """Dify login 200 + 3 cookies (access/refresh/csrf)。"""
    return httpx.Response(
        200,
        headers={
            "set-cookie": (
                "access_token=acc-x; Path=/; HttpOnly, "
                "refresh_token=ref-x; Path=/; HttpOnly, "
                "csrf_token=csrf-x; Path=/"
            ),
        },
    )


# ===== 1-3: __post_init__ fail-fast =====


class TestFailFast:
    """M10+1 hard gate: 空 api_base / email / password 必须 raise DifyConfigError."""

    def test_empty_api_base_raises_config_error(self):
        with pytest.raises(DifyConfigError, match="api_base"):
            DifyAdminClient(
                api_base="",
                admin_email="x@y.z",
                admin_password="p",
            )

    def test_empty_admin_email_raises_config_error(self):
        with pytest.raises(DifyConfigError, match="admin_email"):
            DifyAdminClient(
                api_base="https://x",
                admin_email="",
                admin_password="p",
            )

    def test_empty_admin_password_raises_config_error(self):
        with pytest.raises(DifyConfigError, match="admin_password"):
            DifyAdminClient(
                api_base="https://x",
                admin_email="x@y.z",
                admin_password="",
            )


# ===== 4-6: create_app_and_workflow =====


class TestCreateAppAndWorkflow:
    """D3 课程修正: 2-step (POST /apps → POST /apps/{id}/workflows/draft)."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_app_and_workflow_ids(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-uuid-1"})
            )
            router.post("/console/api/apps/app-uuid-1/workflows/draft").mock(
                return_value=httpx.Response(200, json={"id": "wf-uuid-1"})
            )
            client = _admin_client_factory()

            result = await client.create_app_and_workflow(name="测试客服 Agent")

        assert result == {"app_id": "app-uuid-1", "workflow_id": "wf-uuid-1"}

    @pytest.mark.asyncio
    async def test_create_app_400_raises_bad_request_no_rollback(self):
        """Step 1 失败 → 直接抛, 无 App 行可回滚."""
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            apps_route = router.post("/console/api/apps").mock(
                return_value=httpx.Response(400, text="name too long")
            )
            client = _admin_client_factory()

            with pytest.raises(DifyBadRequestError):
                await client.create_app_and_workflow(name="x")

        assert apps_route.call_count == 1

    @pytest.mark.asyncio
    async def test_step2_failure_rolls_back_step1(self):
        """Step 2 失败 → DELETE /apps/{id} 回滚 step 1, 再抛原异常.

        Note: ``create_app_and_workflow`` 把 ``status >= 400`` 一律包成
        ``DifyBadRequestError`` (line 320), 即使上游 5xx 也是 ``DifyBadRequestError``,
        由外层 ``except Exception`` 捕获并触发 DELETE 回滚。
        """
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-rollback"})
            )
            router.post(
                "/console/api/apps/app-rollback/workflows/draft"
            ).mock(return_value=httpx.Response(500, text="server crashed"))
            delete_route = router.delete(
                "/console/api/apps/app-rollback"
            ).mock(return_value=httpx.Response(204))

            client = _admin_client_factory()

            with pytest.raises(DifyBadRequestError):
                await client.create_app_and_workflow(name="x")

        # 原子性保证: DELETE 必须被调用过 (best-effort cleanup)
        assert delete_route.call_count == 1


# ===== 7: enable_api_and_create_key =====


class TestEnableApiAndCreateKey:
    """D8: enable API + 创建 per-app runtime API key."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_token(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post("/console/api/apps/app-x/api-enable").mock(
                return_value=httpx.Response(200, json={"enable_api": True})
            )
            router.post("/console/api/apps/app-x/api-keys").mock(
                return_value=httpx.Response(
                    200, json={"token": "app-secret-token-123"}
                )
            )
            client = _admin_client_factory()

            token = await client.enable_api_and_create_key("app-x")

        assert token == "app-secret-token-123"


# ===== 8-9: Auth =====


class TestAuth:
    """401 retry 边界: 第一次 401 重登 1 次, 第二次 401 抛."""

    @pytest.mark.asyncio
    async def test_login_401_raises_auth_error(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(
                return_value=httpx.Response(401, text="bad creds")
            )
            client = _admin_client_factory()

            with pytest.raises(DifyAuthError):
                await client._get_client()  # 触发 _login

    @pytest.mark.asyncio
    async def test_401_retry_succeeds_after_relogin(self):
        """第一次请求 401 → 清缓存 + 重登 + 重放 1 次 成功."""
        with respx.mock(base_url="https://dify.test") as router:
            login_route = router.post("/console/api/auth/login").mock(
                return_value=_login_response()
            )
            apps_route = router.post("/console/api/apps").mock(
                side_effect=[
                    httpx.Response(401, text="session expired"),
                    httpx.Response(200, json={"id": "app-after-retry"}),
                ]
            )
            router.post(
                "/console/api/apps/app-after-retry/workflows/draft"
            ).mock(return_value=httpx.Response(200, json={"id": "wf-after-retry"}))

            client = _admin_client_factory()
            result = await client.create_app_and_workflow(name="retry")

        assert result["app_id"] == "app-after-retry"
        assert result["workflow_id"] == "wf-after-retry"
        # login 调用 2 次: 初次 + 401 后重登
        assert login_route.call_count == 2
        # /apps 调用 2 次: 401 + 重放 200
        assert apps_route.call_count == 2


# ===== 10-11: from_workspace =====


class TestFromWorkspace:
    """Workspace 字段 (M10+2 范围) 的 forward-compat shim."""

    def test_fernet_encrypted_password_decrypted(self, monkeypatch):
        """``dify_admin_password_ref`` 以 ``enc:`` 开头 → ``decrypt_api_key``.

        Note: ``from_workspace`` 是 lazy import ``from core.encryption import
        decrypt_api_key``, 所以 patch ``core.encryption.decrypt_api_key`` 而非
        ``services.dify.admin_client.decrypt_api_key`` (后者不在 module 命名空间)。
        """
        from core import encryption as encryption_module

        captured: list[str] = []

        def fake_decrypt(ref: str) -> str:
            captured.append(ref)
            return "decrypted-plaintext-pw"

        monkeypatch.setattr(encryption_module, "decrypt_api_key", fake_decrypt)

        ws = SimpleNamespace(
            dify_api_base="https://ws.dify.test",
            dify_admin_email="ws@dify.test",
            dify_admin_password_ref="enc:fernet-cipher-blob",
        )
        client = DifyAdminClient.from_workspace(ws)

        assert client.api_base == "https://ws.dify.test"
        assert client.admin_email == "ws@dify.test"
        assert client.admin_password == "decrypted-plaintext-pw"
        assert captured == ["enc:fernet-cipher-blob"]

    def test_plaintext_password_used_as_is(self):
        """``dify_admin_password_ref`` 无 ``enc:`` 前缀 → 当明文用."""
        ws = SimpleNamespace(
            dify_api_base="https://ws.dify.test",
            dify_admin_email="ws@dify.test",
            dify_admin_password_ref="plain-text-password",
        )
        client = DifyAdminClient.from_workspace(ws)

        assert client.admin_password == "plain-text-password"


# ===== 12: Session cache TTL =====


class TestSessionCache:
    """``cache_ttl=-1`` 强制每次重登 (cache 立即过期)."""

    @pytest.mark.asyncio
    async def test_cache_ttl_minus_one_forces_relogin(self):
        client = _admin_client_factory(cache_ttl=-1)
        with respx.mock(base_url="https://dify.test") as router:
            login_route = router.post("/console/api/auth/login").mock(
                return_value=_login_response()
            )
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-ttl"})
            )
            router.post(
                "/console/api/apps/app-ttl/workflows/draft"
            ).mock(return_value=httpx.Response(200, json={"id": "wf-ttl"}))

            await client.create_app_and_workflow(name="ttl-test")

        # TTL=-1: 首次请求 login → 后续请求因 cache 立即过期, 每次 _request 都重登
        # create_app_and_workflow 调 2 次 _request (step1 + step2), 所以 login ≥ 2
        assert login_route.call_count >= 2


# ===== 13-16: publish_workflow =====


class TestPublishWorkflow:
    """D9c 容错: 400/422 不抛 (admin 后续在 UI 补 graph); 5xx 抛."""

    @pytest.mark.asyncio
    async def test_200_returns_true(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(200, json={}))

            client = _admin_client_factory()
            ok = await client.publish_workflow("app-x")

        assert ok is True

    @pytest.mark.asyncio
    async def test_400_returns_false_no_raise(self):
        """D9c: 空 graph 校验失败 → False, caller 标 publish_failed."""
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(400, text="empty graph"))

            client = _admin_client_factory()
            ok = await client.publish_workflow("app-x")

        assert ok is False

    @pytest.mark.asyncio
    async def test_422_returns_false_no_raise(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(422, text="missing Start node"))

            client = _admin_client_factory()
            ok = await client.publish_workflow("app-x")

        assert ok is False

    @pytest.mark.asyncio
    async def test_500_raises_upstream_error(self):
        """5xx 真错误 → 抛, caller 走 D2 回滚."""
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/auth/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(500, text="server error"))

            client = _admin_client_factory()

            with pytest.raises(DifyUpstreamError):
                await client.publish_workflow("app-x")


# ===== 17: deferred to M10+2 =====


# TODO(M10+2): test_create_agent_publish_failed_status_persists
# Need: create_agent endpoint 调用 DifyAdminClient.publish_workflow 后,
#       agent.dify_publish_status 应被持久化为 "publish_failed".
# Blocked by: M10+2 PR1 (create_agent endpoint Dify 集成层接入).
# Spec: docs/handoffs/M10PLUS-agent-dify-integration.md §6.4.
