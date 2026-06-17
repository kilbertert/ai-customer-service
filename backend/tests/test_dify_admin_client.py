"""M10+1 + M10+2 — DifyAdminClient / create_agent endpoint / DifyProvider tests.

M10+1 覆盖 (16 cases, 见 kickoff §6.5):
    构造期 fail-fast (3) / create_app_and_workflow (3) / enable_api (1) /
    auth (2) / from_workspace (2) / session cache (1) / publish_workflow (4).

M10+2 覆盖 (4 cases, 见 kickoff §7.D):
    - test_create_agent_publish_failed_status_persists: D9(c) → dify_publish_status='publish_failed'
    - test_create_agent_dify_disabled_fallback: Plan B 兼容 (M10 既有路径)
    - test_create_agent_publish_5xx_triggers_rollback: D2 → 整笔事务回滚
    - test_dify_provider_api_key_resolution_priority: D8 3 级 fallback (4 优先级场景)
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Optional

import httpx
import pytest
import respx
from sqlalchemy import select

import database
from core.encryption import encrypt_api_key
from models import Agent, Workspace
from services.dify.admin_client import DifyAdminClient, _session_cache
from services.dify.exceptions import (
    DifyAuthError,
    DifyBadRequestError,
    DifyConfigError,
    DifyUpstreamError,
)
from services.dify.provider import DifyProvider


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
            router.post("/console/api/login").mock(return_value=_login_response())
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
            router.post("/console/api/login").mock(return_value=_login_response())
            apps_route = router.post("/console/api/apps").mock(
                return_value=httpx.Response(400, text="name too long")
            )
            client = _admin_client_factory()

            with pytest.raises(DifyBadRequestError):
                await client.create_app_and_workflow(name="x")

        assert apps_route.call_count == 1

    @pytest.mark.asyncio
    async def test_d9d_regression_returns_dict_not_none(self):
        """D9d regression guard (M10+4 → M10+5 fix):
        ``create_app_and_workflow`` happy path **必须**返 ``dict``,不能隐式 None
        (fall-through bug 修法是在 ``except`` 后显式 ``return {"app_id", "workflow_id"}``)。

        M10+4 commit ``8dc84e9`` 引入 D9d fallback 时漏写成功路径 ``return``,
        导致函数 fall-through 到 None。 本测试在 happy path 上**额外**断言
        ``isinstance(result, dict)`` + ``"app_id" in result`` + ``result is not None``,
        锁住回归。
        """
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/login").mock(return_value=_login_response())
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-uuid-1"})
            )
            router.post("/console/api/apps/app-uuid-1/workflows/draft").mock(
                return_value=httpx.Response(200, json={"id": "wf-uuid-1"})
            )
            client = _admin_client_factory()

            result = await client.create_app_and_workflow(name="回归测试 Agent")

        # 显式 return-type assertions (M10+5 §10.5 #3)
        assert result is not None, "create_app_and_workflow returned None (D9d fall-through bug)"
        assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
        assert "app_id" in result, "result missing 'app_id' key"
        assert "workflow_id" in result, "result missing 'workflow_id' key"
        assert result["app_id"] == "app-uuid-1"
        assert result["workflow_id"] == "wf-uuid-1"

    @pytest.mark.asyncio
    async def test_step2_failure_rolls_back_step1(self):
        """Step 2 失败 → DELETE /apps/{id} 回滚 step 1, 再抛原异常.

        Note: ``create_app_and_workflow`` 把 ``status >= 400`` 一律包成
        ``DifyBadRequestError`` (line 320), 即使上游 5xx 也是 ``DifyBadRequestError``,
        由外层 ``except Exception`` 捕获并触发 DELETE 回滚。
        """
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/login").mock(return_value=_login_response())
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
            router.post("/console/api/login").mock(return_value=_login_response())
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
            router.post("/console/api/login").mock(
                return_value=httpx.Response(401, text="bad creds")
            )
            client = _admin_client_factory()

            with pytest.raises(DifyAuthError):
                await client._get_client()  # 触发 _login

    @pytest.mark.asyncio
    async def test_401_retry_succeeds_after_relogin(self):
        """第一次请求 401 → 清缓存 + 重登 + 重放 1 次 成功."""
        with respx.mock(base_url="https://dify.test") as router:
            login_route = router.post("/console/api/login").mock(
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
            login_route = router.post("/console/api/login").mock(
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
            router.post("/console/api/login").mock(return_value=_login_response())
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
            router.post("/console/api/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(400, text="empty graph"))

            client = _admin_client_factory()
            ok = await client.publish_workflow("app-x")

        assert ok is False

    @pytest.mark.asyncio
    async def test_422_returns_false_no_raise(self):
        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/login").mock(return_value=_login_response())
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
            router.post("/console/api/login").mock(return_value=_login_response())
            router.post(
                "/console/api/apps/app-x/workflows/publish"
            ).mock(return_value=httpx.Response(500, text="server error"))

            client = _admin_client_factory()

            with pytest.raises(DifyUpstreamError):
                await client.publish_workflow("app-x")


# ===== M10+2 §7.B: create_agent endpoint Dify 集成 (3 cases) =====


async def _enable_workspace_dify(*, set_admin_creds: bool = True) -> None:
    """Test helper: 开启 workspace.dify_enabled 并 (可选) 设置 admin 凭据."""
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(
            select(Workspace).order_by(Workspace.id).limit(1)
        )
        workspace = result.scalar_one()
        workspace.dify_api_base = "https://dify.test"
        workspace.dify_enabled = True
        if set_admin_creds:
            workspace.dify_admin_email = "admin@dify.test"
            workspace.dify_admin_password_ref = encrypt_api_key("secret-pw")
        await session.commit()


async def _disable_workspace_dify() -> None:
    """Test helper: 关闭 workspace.dify_enabled (Plan B fallback 测试用)."""
    async with database.AsyncSessionLocal() as session:
        result = await session.execute(
            select(Workspace).order_by(Workspace.id).limit(1)
        )
        workspace = result.scalar_one()
        workspace.dify_enabled = False
        await session.commit()


class TestCreateAgentDifyIntegration:
    """M10+2 §7.B + §7.D: 3 个 endpoint 集成测试覆盖 D9(c)/D2/Plan B 边界."""

    @pytest.mark.asyncio
    async def test_create_agent_publish_failed_status_persists(
        self, client, setup_test_db
    ):
        """D9(c): publish 422 → agent.dify_publish_status='publish_failed', 不回滚.

        Mock 序列: login 200 → create_app 200 → sync_workflow 200 → enable_api 200
        → api-keys 200 → publish_workflow 422 → 期望 agent 行写入 + status='publish_failed'.
        """
        await _enable_workspace_dify()

        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/login").mock(return_value=_login_response())
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-fail"})
            )
            router.post("/console/api/apps/app-fail/workflows/draft").mock(
                return_value=httpx.Response(200, json={"id": "wf-fail"})
            )
            router.post("/console/api/apps/app-fail/api-enable").mock(
                return_value=httpx.Response(200, json={"enable_api": True})
            )
            router.post("/console/api/apps/app-fail/api-keys").mock(
                return_value=httpx.Response(
                    200, json={"token": "app-test-key-xyz"}
                )
            )
            router.post(
                "/console/api/apps/app-fail/workflows/publish"
            ).mock(return_value=httpx.Response(422, text="empty graph"))

            response = await client.post(
                "/api/v1/agents",
                json={
                    "name": "testfail",
                    "description": "publish 422 容错测试",
                    "agent_type": "ai_clone",
                },
            )

        assert response.status_code == 201
        created = response.json()
        agent_id = created["id"]

        # 验证 DB 状态: agent 行存在 (没回滚) + status='publish_failed' + error 非空
        async with database.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one()

            assert agent.dify_app_id == "app-fail"
            assert agent.dify_workflow_id == "wf-fail"
            assert agent.dify_api_key is not None
            assert agent.dify_api_key.startswith("enc:")  # Fernet 加密
            assert agent.dify_publish_status == "publish_failed"
            assert agent.dify_publish_error  # 非空
            assert "publish" in agent.dify_publish_error.lower()  # 含诊断信息

    @pytest.mark.asyncio
    async def test_create_agent_dify_disabled_fallback(
        self, client, setup_test_db
    ):
        """Plan B 兼容: dify_enabled=False → 跟 M10 既有路径 byte-for-byte 一致.

        不调 Dify, 不需要 respx mock. 验证 4 个 dify_* 字段保持默认 (None / 'draft').
        """
        await _disable_workspace_dify()

        response = await client.post(
            "/api/v1/agents",
            json={
                "name": "Plan B",
                "description": "M10 既有路径兼容",
                "agent_type": "ai_clone",
            },
        )

        assert response.status_code == 201
        created = response.json()
        agent_id = created["id"]

        async with database.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )
            agent = result.scalar_one()

            assert agent.dify_app_id is None
            assert agent.dify_workflow_id is None  # M10 legacy, 保持 None
            assert agent.dify_api_key is None
            assert agent.dify_publish_status == "draft"  # 默认
            assert agent.dify_publish_error is None

    @pytest.mark.asyncio
    async def test_create_agent_publish_5xx_triggers_rollback(
        self, client, setup_test_db
    ):
        """D2: publish 5xx → 整笔事务回滚, DB 无 agent 行.

        Mock 序列前 4 步成功 (login + create_app + sync + enable_api + api-keys),
        第 5 步 publish_workflow 500 → DifyUpstreamError → endpoint 502 + rollback.
        """
        await _enable_workspace_dify()

        with respx.mock(base_url="https://dify.test") as router:
            router.post("/console/api/login").mock(return_value=_login_response())
            router.post("/console/api/apps").mock(
                return_value=httpx.Response(200, json={"id": "app-rollback"})
            )
            router.post(
                "/console/api/apps/app-rollback/workflows/draft"
            ).mock(return_value=httpx.Response(200, json={"id": "wf-rollback"}))
            router.post(
                "/console/api/apps/app-rollback/api-enable"
            ).mock(return_value=httpx.Response(200, json={"enable_api": True}))
            router.post(
                "/console/api/apps/app-rollback/api-keys"
            ).mock(return_value=httpx.Response(200, json={"token": "app-rb-key"}))
            router.post(
                "/console/api/apps/app-rollback/workflows/publish"
            ).mock(return_value=httpx.Response(500, text="server error"))

            response = await client.post(
                "/api/v1/agents",
                json={
                    "name": "Rollback",
                    "description": "publish 5xx 应回滚",
                    "agent_type": "ai_clone",
                },
            )

        # 端点应返回 502 (D2 兜底), 不创建 agent 行
        assert response.status_code == 502
        assert "Dify" in response.json()["detail"]

        # 验证 DB 无 agent 行 (rollback 生效)
        async with database.AsyncSessionLocal() as session:
            result = await session.execute(
                select(Agent).where(Agent.name == "Rollback")
            )
            agent = result.scalar_one_or_none()
            assert agent is None, "Agent 行应被 rollback 删除"


# ===== M10+2 §7.C: DifyProvider._resolve_api_key 3 级 fallback (1 parametrized) =====


@dataclass
class _ProviderFakeAgent:
    """最小 Agent 替身 (覆盖 _resolve_api_key 关注的字段)."""

    id: str = "agt_a1b2c3d4e5f6"
    dify_workflow_id: Optional[str] = "wf-uuid-1"
    dify_api_key: Optional[str] = None
    dify_user_prefix: str = "agent-"
    dify_end_user_strategy: str = "dual_layer"
    dify_inputs_schema: Optional[str] = None


@dataclass
class _ProviderFakeWorkspace:
    """最小 Workspace 替身 (覆盖 _resolve_api_key 关注的字段)."""

    id: int = 1
    dify_api_base: str = "https://dify.test/v1"
    dify_api_key: Optional[str] = None
    dify_workspace_id: Optional[str] = None
    dify_enabled: bool = True


class TestDifyProviderApiKeyResolution:
    """M10+2 §7.C: DifyProvider._resolve_api_key 3 级 fallback (D8 priority).

    优先级: agent.dify_api_key > workspace.dify_api_key > settings.dify_api_key.
    """

    def _build_provider(
        self,
        agent_key: Optional[str],
        workspace_key: Optional[str],
        settings_key: Optional[str],
        monkeypatch,
    ) -> DifyProvider:
        """构造 DifyProvider, 三层 key 可独立控制."""
        from services.dify import provider as provider_module

        class _FakeSettings:
            dify_api_base = "https://dify.test/v1"
            dify_api_key = settings_key or ""

        monkeypatch.setattr(provider_module, "settings", _FakeSettings())

        agent = _ProviderFakeAgent(dify_api_key=agent_key)
        workspace = _ProviderFakeWorkspace(dify_api_key=workspace_key)
        return DifyProvider(workspace=workspace, agent=agent, visitor_id="v")

    @pytest.mark.parametrize(
        "agent_key_plain,workspace_key_plain,settings_key_plain,expected",
        [
            # 1) agent 优先: 即使 workspace/settings 都有, agent 赢
            ("agent-key", "workspace-key", "settings-key", "agent-key"),
            # 2) agent 空, workspace 次之
            (None, "workspace-key", "settings-key", "workspace-key"),
            # 3) agent + workspace 都空, settings 兜底
            (None, None, "settings-key", "settings-key"),
            # 4) 三层都空 → __init__ 已先 raise DifyConfigError, 见独立测试
        ],
    )
    def test_priority_resolution(
        self,
        agent_key_plain,
        workspace_key_plain,
        settings_key_plain,
        expected,
        monkeypatch,
    ):
        agent_key = encrypt_api_key(agent_key_plain) if agent_key_plain else None
        workspace_key = (
            encrypt_api_key(workspace_key_plain) if workspace_key_plain else None
        )
        provider = self._build_provider(
            agent_key=agent_key,
            workspace_key=workspace_key,
            settings_key=settings_key_plain,
            monkeypatch=monkeypatch,
        )
        assert provider._resolve_api_key() == expected

    def test_no_key_anywhere_raises_dify_config_error(self, monkeypatch):
        """M10+1 新增异常: 三层都拿不到 → DifyConfigError 而非 ValueError.

        Note: 此断言发生在 ``DifyProvider.__init__`` 内部 (_resolve_api_key 被
        __post_init__ 调用), 不需要直接调 _resolve_api_key.
        """
        from services.dify import provider as provider_module

        class _FakeSettings:
            dify_api_base = "https://dify.test/v1"
            dify_api_key = ""

        monkeypatch.setattr(provider_module, "settings", _FakeSettings())

        agent = _ProviderFakeAgent()
        workspace = _ProviderFakeWorkspace()
        with pytest.raises(DifyConfigError, match="No Dify API key resolved"):
            DifyProvider(workspace=workspace, agent=agent, visitor_id="v")
