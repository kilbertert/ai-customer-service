"""M11+ P0-A — TenantService.register_tenant / retry_provisioning 持久化 4 字段测试。

P0-A (D5 决策) 在 tenant_service.register_tenant Stage 3 + retry_provisioning 成功路径
持久化以下 4 字段,使 workspace.dify_enabled=True 解锁 create_agent 端点的 Plan A 死代码:

    ws.dify_api_base         = settings.dify_api_base
    ws.dify_admin_email      = owner_email
    ws.dify_admin_password_ref = encrypt_api_key(dify_result["initial_password"])
    ws.dify_enabled          = True

4 个单测 (见 docs/m11plus/p0a-plan-a-cutover.md §4.4 测试矩阵):
    1. test_register_persists_dify_admin_creds          # happy path 4 字段全 set + Fernet 可解密
    2. test_register_dify_failure_does_not_persist_creds  # 失败 → 4 字段全 None (原子性)
    3. test_retry_provisioning_success_persists_creds  # retry 成功路径同样持久化
    4. test_register_already_set_does_not_overwrite     # 老 workspace dify_enabled=False → 不动
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import database
from core.encryption import decrypt_api_key
from models import Workspace
from services.tenant_service import TenantService


def _make_dify_result(workspace_id: str = "ws-uuid-1") -> dict:
    """mock DifyTenantProvisioner.provision_tenant 的返回值 (Stage 3 消费)。"""
    return {
        "workspace_id": workspace_id,
        "owner_account_id": "acct-uuid-1",
        "initial_password": "Dify!InitPass-2026",
        "dify_request_id": "req-uuid-1",
    }


@pytest.mark.asyncio
async def test_register_persists_dify_admin_creds(setup_test_db):
    """register_tenant Stage 3 成功路径必须落 4 字段,Fernet 可解密回原密码。"""
    from config import settings

    owner_email = f"p0a_test_{uuid.uuid4().hex[:8]}@example.com"
    owner_name = "P0A Test Owner"
    workspace_name = f"p0a-ws-{uuid.uuid4().hex[:8]}"
    signup_key = str(uuid.uuid4())
    correlation_id = "corr-p0a-1"

    dify_result = _make_dify_result()

    mock_provisioner = MagicMock()
    mock_provisioner.provision_tenant = AsyncMock(return_value=dify_result)

    async with database.AsyncSessionLocal() as session:
        service = TenantService(session)
        service.provisioner = mock_provisioner

        result = await service.register_tenant(
            workspace_name=workspace_name,
            owner_name=owner_name,
            owner_email=owner_email,
            owner_password="basjoo-owner-pw",
            signup_idempotency_key=signup_key,
            correlation_id=correlation_id,
        )

        assert result["provisioning_status"] == "ready"
        assert result["workspace_id"] is not None
        assert result["access_token"]

        ws = await session.get(Workspace, result["workspace_id"])
        assert ws is not None
        assert ws.dify_api_base == settings.dify_api_base, (
            f"dify_api_base 没持久化,got {ws.dify_api_base!r}"
        )
        assert ws.dify_admin_email == owner_email
        assert ws.dify_admin_password_ref is not None
        assert ws.dify_admin_password_ref.startswith("enc:")
        assert ws.dify_enabled is True, "dify_enabled 没 flip True → Plan A 仍是死代码"

        decrypted = decrypt_api_key(ws.dify_admin_password_ref)
        assert decrypted == dify_result["initial_password"], (
            f"Fernet 解密后不等: got {decrypted!r}, "
            f"expected {dify_result['initial_password']!r}"
        )

        assert ws.dify_tenant_id == dify_result["workspace_id"]
        assert ws.dify_account_id == dify_result["owner_account_id"]
        assert ws.dify_provisioning_status == "ready"
        assert ws.dify_provisioning_last_error is None


@pytest.mark.asyncio
async def test_register_dify_failure_does_not_persist_creds(setup_test_db):
    """Dify provision 失败 → 4 字段必须全 None (原子性: 失败不留半截凭据)。"""
    owner_email = f"p0a_fail_{uuid.uuid4().hex[:8]}@example.com"
    workspace_name = f"p0a-fail-ws-{uuid.uuid4().hex[:8]}"
    signup_key = str(uuid.uuid4())

    mock_provisioner = MagicMock()
    mock_provisioner.provision_tenant = AsyncMock(
        side_effect=RuntimeError("Dify 502 upstream")
    )

    async with database.AsyncSessionLocal() as session:
        service = TenantService(session)
        service.provisioner = mock_provisioner

        result = await service.register_tenant(
            workspace_name=workspace_name,
            owner_name="Fail Owner",
            owner_email=owner_email,
            owner_password="pw",
            signup_idempotency_key=signup_key,
            correlation_id="corr-fail-1",
        )

        assert result["provisioning_status"] == "failed"
        workspace_id = result["workspace_id"]

        ws = await session.get(Workspace, workspace_id)
        assert ws is not None
        assert ws.dify_api_base is None, "失败路径不能持久化 dify_api_base"
        assert ws.dify_admin_email is None, "失败路径不能持久化 dify_admin_email"
        assert ws.dify_admin_password_ref is None, "失败路径不能持久化 dify_admin_password_ref"
        assert ws.dify_enabled is False, "失败路径不能 flip dify_enabled=True"
        assert ws.dify_provisioning_status == "failed"
        assert ws.dify_provisioning_last_error is not None
        assert "Dify 502" in ws.dify_provisioning_last_error


@pytest.mark.asyncio
async def test_retry_provisioning_success_persists_creds(setup_test_db):
    """retry_provisioning 成功路径同样持久化 4 字段 (老 workspace 也能 flip Plan A)。"""
    from config import settings

    owner_email = f"p0a_retry_{uuid.uuid4().hex[:8]}@example.com"
    workspace_name = f"p0a-retry-ws-{uuid.uuid4().hex[:8]}"

    fail_provisioner = MagicMock()
    fail_provisioner.provision_tenant = AsyncMock(
        side_effect=RuntimeError("first attempt fail")
    )

    async with database.AsyncSessionLocal() as session:
        service = TenantService(session)
        service.provisioner = fail_provisioner

        result = await service.register_tenant(
            workspace_name=workspace_name,
            owner_name="Retry Owner",
            owner_email=owner_email,
            owner_password="pw",
            signup_idempotency_key=str(uuid.uuid4()),
            correlation_id="corr-retry-A",
        )
        workspace_id = result["workspace_id"]
        assert result["provisioning_status"] == "failed"

        ws = await session.get(Workspace, workspace_id)
        assert ws.dify_enabled is False
        assert ws.dify_admin_password_ref is None

    success_provisioner = MagicMock()
    success_provisioner.provision_tenant = AsyncMock(
        return_value=_make_dify_result(workspace_id="ws-retry-uuid")
    )

    async with database.AsyncSessionLocal() as session:
        service = TenantService(session)
        service.provisioner = success_provisioner

        retry_result = await service.retry_provisioning(
            workspace_id=workspace_id,
            correlation_id="corr-retry-B",
        )

        assert retry_result["success"] is True
        assert retry_result["provisioning_status"] == "ready"

        ws = await session.get(Workspace, workspace_id)
        assert ws.dify_api_base == settings.dify_api_base
        assert ws.dify_admin_email == owner_email
        assert ws.dify_admin_password_ref is not None
        assert ws.dify_admin_password_ref.startswith("enc:")
        assert ws.dify_enabled is True
        assert ws.dify_provisioning_attempts == 2


@pytest.mark.asyncio
async def test_register_already_set_does_not_overwrite(setup_test_db):
    """已 set dify_enabled=True 的老 workspace 不被新 register 覆盖。

    register_tenant 每次都创建新 Workspace 行,不会 UPDATE 已有 row。
    验证两个独立 register 各持自己的 4 字段。
    """
    owner_email_1 = f"p0a_idem1_{uuid.uuid4().hex[:8]}@example.com"
    owner_email_2 = f"p0a_idem2_{uuid.uuid4().hex[:8]}@example.com"

    mock_provisioner = MagicMock()
    mock_provisioner.provision_tenant = AsyncMock(
        side_effect=[
            _make_dify_result(workspace_id="ws-idem-1"),
            _make_dify_result(workspace_id="ws-idem-2"),
        ]
    )

    async with database.AsyncSessionLocal() as session:
        service = TenantService(session)
        service.provisioner = mock_provisioner

        result_1 = await service.register_tenant(
            workspace_name=f"ws-idem-1-{uuid.uuid4().hex[:8]}",
            owner_name="Idem 1",
            owner_email=owner_email_1,
            owner_password="pw",
            signup_idempotency_key=str(uuid.uuid4()),
            correlation_id="corr-idem-1",
        )
        ws_id_1 = result_1["workspace_id"]

        result_2 = await service.register_tenant(
            workspace_name=f"ws-idem-2-{uuid.uuid4().hex[:8]}",
            owner_name="Idem 2",
            owner_email=owner_email_2,
            owner_password="pw",
            signup_idempotency_key=str(uuid.uuid4()),
            correlation_id="corr-idem-2",
        )
        ws_id_2 = result_2["workspace_id"]

        ws_1 = await session.get(Workspace, ws_id_1)
        assert ws_1.dify_enabled is True
        assert ws_1.dify_admin_email == owner_email_1

        ws_2 = await session.get(Workspace, ws_id_2)
        assert ws_2.dify_enabled is True
        assert ws_2.dify_admin_email == owner_email_2
        assert ws_2.dify_admin_password_ref is not None
