"""M11 PR3 — basjoo 租户注册链路单元测试。

覆盖范围 (docs/m11/m11-pr3-register-flow.md §4.1):
    1.  happy path  → 200 + access_token + provisioning_status=ready
    2.  Dify 失败    → 200 + provisioning_status=failed (workspace 已建)
    3.  email 重复   → 409
    4.  黑名单邮箱   → 400
    5.  密码过短     → 422
    6.  未勾选 terms → 400
    7.  retry 成功   → failed → ready
    8.  retry 3 次后 → failed_permanent
    9.  auto_retry cron 选 failed workspace
    10. audit_logs 在 success/failure 路径都有
    11. signup_idempotency_key 唯一
    12. 并发同 email → 1 success + 1 409
    13. 限速: IP 5/h + email 3/h

策略: ``DifyTenantProvisioner.provision_tenant`` 在测试里被 monkeypatch 掉,
避免真打 Dify。``rate_limit_by_ip_and_email`` 的内存限速共享 dict 在
conftest fixture 间会污染, 因此限速相关测试单独 patch ``_check_endpoint_rate_limit``。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models import AdminUser, AuditLog, Workspace
from services.dify.tenant_provisioner import (
    DifyTenantConflictError,
    DifyTenantProvisionError,
)


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_register_rate_limit_history():
    """避免 test_rate_limit_per_ip 把 5 个槽位占满后污染后续 test。"""
    from middleware.rate_limit import (
        _REGISTER_EMAIL_HISTORY, _REGISTER_IP_HISTORY,
    )
    _REGISTER_IP_HISTORY.clear()
    _REGISTER_EMAIL_HISTORY.clear()
    yield
    _REGISTER_IP_HISTORY.clear()
    _REGISTER_EMAIL_HISTORY.clear()


@pytest_asyncio.fixture
async def tenant_client(setup_test_db):
    """公开客户端 — 不带 token, 用于 /tenants/register 等。"""
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_provisioner_ok(monkeypatch):
    fake = MagicMock()
    fake.provision_tenant = AsyncMock(
        return_value={
            "workspace_id": "dify-ws-uuid-001",
            "owner_account_id": "dify-acct-uuid-001",
            "initial_password": "InitPass!2026",
            "dify_request_id": "dify-req-uuid-001",
        }
    )
    fake.health_check = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "services.tenant_service.DifyTenantProvisioner", lambda: fake
    )
    return fake


@pytest.fixture
def mock_provisioner_fail(monkeypatch):
    fake = MagicMock()
    fake.provision_tenant = AsyncMock(
        side_effect=DifyTenantProvisionError("Dify returned 500: oops")
    )
    fake.health_check = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "services.tenant_service.DifyTenantProvisioner", lambda: fake
    )
    return fake


def _register_payload(email: str = "alice@example.com", **overrides) -> Dict[str, Any]:
    base = {
        "workspace_name": "Acme Co",
        "name": "Alice",
        "email": email,
        "password": "StrongP@ss1",
        "terms_accepted": True,
    }
    base.update(overrides)
    return base


# ── 1. happy path ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_tenant_success(tenant_client, mock_provisioner_ok, setup_test_db):
    resp = await tenant_client.post(
        "/api/v1/tenants/register", json=_register_payload()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"], "缺少 access_token"
    assert body["workspace_id"] > 0
    assert body["dify_initial_password"] == "InitPass!2026"
    assert body["provisioning_status"] == "ready"
    assert body["correlation_id"]


# ── 2. Dify 失败 → 200 但 provisioning_status=failed ────────────────────


@pytest.mark.asyncio
async def test_register_tenant_dify_failure(
    tenant_client, mock_provisioner_fail, setup_test_db
):
    resp = await tenant_client.post(
        "/api/v1/tenants/register", json=_register_payload(email="bob@ex.com")
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provisioning_status"] == "failed"
    assert body["workspace_id"] > 0
    assert body["dify_initial_password"] == ""


# ── 3. email 重复 → 409 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_tenant_duplicate_email(
    tenant_client, mock_provisioner_ok, setup_test_db
):
    p = _register_payload(email="dup@ex.com")
    r1 = await tenant_client.post("/api/v1/tenants/register", json=p)
    assert r1.status_code == 200, r1.text
    r2 = await tenant_client.post("/api/v1/tenants/register", json=p)
    assert r2.status_code == 409, r2.text
    assert "already" in r2.json()["detail"].lower()


# ── 4. 黑名单邮箱 → 400 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_tenant_blacklisted_email(
    tenant_client, mock_provisioner_ok, setup_test_db
):
    resp = await tenant_client.post(
        "/api/v1/tenants/register",
        json=_register_payload(email="throwaway@mailinator.com"),
    )
    assert resp.status_code == 400
    assert "domain" in resp.json()["detail"].lower()


# ── 5. 密码过短 → 422 (pydantic validation) ───────────────────────────


@pytest.mark.asyncio
async def test_register_tenant_password_too_short(
    tenant_client, mock_provisioner_ok, setup_test_db
):
    resp = await tenant_client.post(
        "/api/v1/tenants/register",
        json=_register_payload(email="weak@ex.com", password="Aa1!"),
    )
    assert resp.status_code == 422


# ── 6. 未勾选 terms → 400 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_tenant_terms_not_accepted(
    tenant_client, mock_provisioner_ok, setup_test_db
):
    resp = await tenant_client.post(
        "/api/v1/tenants/register",
        json=_register_payload(email="noagree@ex.com", terms_accepted=False),
    )
    assert resp.status_code == 400
    assert "terms" in resp.json()["detail"].lower()


# ── 7. retry 成功: failed → ready ──────────────────────────────────────


@pytest.mark.asyncio
async def test_retry_provisioning_success(setup_test_db, mock_provisioner_ok):
    from database import AsyncSessionLocal
    from services.tenant_service import TenantService

    async with AsyncSessionLocal() as db:
        ws = Workspace(
            name="Manual WS",
            owner_email="manual@ex.com",
            dify_provisioning_status="failed",
            dify_provisioning_attempts=1,
            dify_provisioning_last_error="Dify 500",
        )
        db.add(ws)
        await db.commit()
        await db.refresh(ws)

        service = TenantService(db)
        result = await service.retry_provisioning(ws.id, "corr-retry-1")

    assert result["success"] is True
    assert result["provisioning_status"] == "ready"


# ── 8. retry 3 次后 → failed_permanent ─────────────────────────────────


@pytest.mark.asyncio
async def test_retry_provisioning_max_attempts(setup_test_db, mock_provisioner_fail):
    from database import AsyncSessionLocal
    from services.tenant_service import TenantService

    async with AsyncSessionLocal() as db:
        ws = Workspace(
            name="Doomed WS",
            owner_email="doomed@ex.com",
            dify_provisioning_status="failed",
            dify_provisioning_attempts=2,
            dify_provisioning_last_error="prev fail",
        )
        db.add(ws)
        await db.commit()
        await db.refresh(ws)
        ws_id = ws.id

        service = TenantService(db)
        result = await service.retry_provisioning(ws_id, "corr-retry-max")

    assert result["success"] is False
    assert "Dify returned 500" in result["error"]

    async with AsyncSessionLocal() as db:
        ws = await db.get(Workspace, ws_id)
        assert ws.dify_provisioning_status == "failed_permanent"
        assert ws.dify_provisioning_attempts == 3


# ── 9. auto_retry cron 选 failed workspace ─────────────────────────────


@pytest.mark.asyncio
async def test_auto_retry_cron_picks_failed_workspaces(
    setup_test_db, mock_provisioner_ok
):
    from database import AsyncSessionLocal
    from scheduler.tenant_provisioning_retry import retry_failed_provisioning

    async with AsyncSessionLocal() as db:
        ws_retry = Workspace(
            name="CronTarget",
            owner_email="cron@ex.com",
            dify_provisioning_status="failed",
            dify_provisioning_attempts=1,
        )
        ws_ready = Workspace(
            name="AlreadyReady",
            owner_email="ready@ex.com",
            dify_provisioning_status="ready",
            dify_provisioning_attempts=0,
        )
        ws_perm = Workspace(
            name="Permanent",
            owner_email="perm@ex.com",
            dify_provisioning_status="failed_permanent",
            dify_provisioning_attempts=5,
        )
        db.add_all([ws_retry, ws_ready, ws_perm])
        await db.commit()

    processed = await retry_failed_provisioning()
    assert processed >= 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Workspace).where(Workspace.name == "CronTarget")
        )
        cron_ws = result.scalar_one()
        assert cron_ws.dify_provisioning_status == "ready"


# ── 10. audit_logs: success + failure 路径都有 ────────────────────────


@pytest.mark.asyncio
async def test_audit_logs_written_on_success_and_failure(
    setup_test_db, monkeypatch
):
    """success + failure 两条路径都写 audit_log。

    注: 一次只 patch 一个 provisioner 避免 fixture 互相覆盖。
    """
    from database import AsyncSessionLocal
    from services.tenant_service import TenantService

    # 1) success path
    ok_mock = MagicMock()
    ok_mock.provision_tenant = AsyncMock(
        return_value={
            "workspace_id": "dify-ws-aud-1",
            "owner_account_id": "dify-acct-aud-1",
            "initial_password": "InitPass!1",
            "dify_request_id": "dify-req-aud-1",
        }
    )
    monkeypatch.setattr(
        "services.tenant_service.DifyTenantProvisioner", lambda: ok_mock
    )
    async with AsyncSessionLocal() as db:
        svc = TenantService(db)
        await svc.register_tenant(
            workspace_name="Aud1",
            owner_name="Owner1",
            owner_email="aud1@ex.com",
            owner_password="StrongP@ss1",
            signup_idempotency_key="idem-aud-1",
            correlation_id="corr-aud-1",
        )

    # 2) failure path — 切到 fail mock
    fail_mock = MagicMock()
    fail_mock.provision_tenant = AsyncMock(
        side_effect=DifyTenantProvisionError("Dify returned 500: oops")
    )
    monkeypatch.setattr(
        "services.tenant_service.DifyTenantProvisioner", lambda: fail_mock
    )
    async with AsyncSessionLocal() as db:
        svc = TenantService(db)
        await svc.register_tenant(
            workspace_name="Aud2",
            owner_name="Owner2",
            owner_email="aud2@ex.com",
            owner_password="StrongP@ss1",
            signup_idempotency_key="idem-aud-2",
            correlation_id="corr-aud-2",
        )

    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AuditLog).where(
                    AuditLog.correlation_id.in_(["corr-aud-1", "corr-aud-2"])
                )
            )
        ).scalars().all()
        actions = {(r.correlation_id, r.action, r.status) for r in rows}
        assert ("corr-aud-1", "tenant.create", "success") in actions
        assert ("corr-aud-1", "tenant.provision", "success") in actions
        assert ("corr-aud-2", "tenant.create", "success") in actions
        assert ("corr-aud-2", "tenant.provision", "failed") in actions


# ── 11. signup_idempotency_key 唯一 ───────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_key_uniqueness(setup_test_db, mock_provisioner_fail):
    from database import AsyncSessionLocal
    from services.tenant_service import TenantService

    fixed_key = "fixed-idem-key-uuid-001"

    async with AsyncSessionLocal() as db:
        svc = TenantService(db)
        await svc.register_tenant(
            workspace_name="Idem1",
            owner_name="O1",
            owner_email="idem1@ex.com",
            owner_password="StrongP@ss1",
            signup_idempotency_key=fixed_key,
            correlation_id="corr-idem-1",
        )

    with patch(
        "services.tenant_service.DifyTenantProvisioner",
        lambda: mock_provisioner_fail,
    ):
        async with AsyncSessionLocal() as db:
            svc = TenantService(db)
            with pytest.raises(Exception) as ei:
                await svc.register_tenant(
                    workspace_name="Idem2",
                    owner_name="O2",
                    owner_email="idem2@ex.com",
                    owner_password="StrongP@ss1",
                    signup_idempotency_key=fixed_key,
                    correlation_id="corr-idem-2",
                )
            err_name = type(ei.value).__name__
            assert (
                "UniqueViolation" in err_name
                or "IntegrityError" in err_name
                or "UNIQUE" in str(ei.value).upper()
            ), f"unexpected error type: {err_name}: {ei.value}"


# ── 12. 并发同 email → 1 success + 1 409 ──────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_same_email(tenant_client, mock_provisioner_ok, setup_test_db):
    p = _register_payload(email="race@ex.com")
    r1, r2 = await asyncio.gather(
        tenant_client.post("/api/v1/tenants/register", json=p),
        tenant_client.post("/api/v1/tenants/register", json=p),
        return_exceptions=False,
    )
    codes = sorted([r1.status_code, r2.status_code])
    assert 200 in codes
    assert codes.count(200) == 1, f"期望仅 1 个 200, got {codes}"


# ── 13. 限速: 6th IP request → 429 ────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_per_ip(tenant_client, setup_test_db):
    fake = MagicMock()
    fake.provision_tenant = AsyncMock(
        side_effect=DifyTenantProvisionError("blocked for test")
    )
    with patch("services.tenant_service.DifyTenantProvisioner", lambda: fake):
        from middleware.rate_limit import (
            _REGISTER_IP_HISTORY, _REGISTER_EMAIL_HISTORY,
        )
        _REGISTER_IP_HISTORY.clear()
        _REGISTER_EMAIL_HISTORY.clear()
        statuses: List[int] = []
        for i in range(6):
            r = await tenant_client.post(
                "/api/v1/tenants/register",
                json=_register_payload(email=f"rl{i}@ex.com"),
            )
            statuses.append(r.status_code)
    assert statuses[:5] == [200] * 5, statuses
    assert statuses[5] == 429, statuses


# ── 14. 限速: 同一 email 第 4 次 → 429 ────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_per_email(tenant_client, setup_test_db):
    """同 email 4 次: 限速会让第 4 次收到 429; 2-3 次会过限速但因 email 重复
    在 endpoint 内被 409 拦截(同 email dup check 是 endpoint 行为, 与限速正交)。
    """
    fake = MagicMock()
    fake.provision_tenant = AsyncMock(
        side_effect=DifyTenantProvisionError("blocked for test")
    )
    with patch("services.tenant_service.DifyTenantProvisioner", lambda: fake):
        from middleware.rate_limit import (
            _REGISTER_IP_HISTORY, _REGISTER_EMAIL_HISTORY,
        )
        _REGISTER_IP_HISTORY.clear()
        _REGISTER_EMAIL_HISTORY.clear()
        statuses: List[int] = []
        for i in range(4):
            r = await tenant_client.post(
                "/api/v1/tenants/register",
                json=_register_payload(email="samelimit@ex.com"),
            )
            statuses.append(r.status_code)
    # 1st: 通过 (200)  2-3: 限速放行但 endpoint 内 409  4th: 限速拦截 (429)
    assert statuses[0] == 200, statuses
    assert statuses[1] == 409, statuses
    assert statuses[2] == 409, statuses
    assert statuses[3] == 429, statuses
