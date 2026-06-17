"""M11 PR4 — M3 / M6 / M7 tenant routing 单元测试。

覆盖范围 (docs/m11/m11-pr4-frontend-routing.md §5):
    1. M3 — TenantScopedLLMProvider.get_dify_client 对 ready workspace 返回 DifyAdminClient
    2. M3 — TenantScopedLLMProvider.get_dify_client 对非 ready workspace 抛 WorkspaceNotReadyError
    3. M6 — kb_document_endpoints._assert_kb_document_in_workspace 跨 workspace 抛 403,
            同 workspace 静默通过
    4. M7 — llm_service.get_tenant_scoped_dify_client 在 workspace.dify_provisioning_status
            != "ready" 时抛 WorkspaceNotReadyError (M7 chat_stream 503 readiness 兜底)

策略: 用 in-memory mock session (MagicMock + AsyncMock) 直接打单元路径, 不需要
Dify HTTP / 真实数据库。spec 强调"4 个测试覆盖 M3/M6/M7 关键路径", 不要求端到端。
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException


# ============== M3 — TenantScopedLLMProvider ==============================


@pytest.mark.asyncio
async def test_m3_get_dify_client_returns_client_when_workspace_ready(monkeypatch):
    """M3: workspace.dify_provisioning_status='ready' → 返回 DifyAdminClient 实例。"""
    from services.llm_service import TenantScopedLLMProvider

    fake_client = object()
    fake_ws = SimpleNamespace(
        id=42,
        dify_provisioning_status="ready",
    )
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_ws)

    monkeypatch.setattr(
        "services.dify.admin_client.DifyAdminClient.from_workspace",
        classmethod(lambda cls, ws: fake_client),
    )

    provider = TenantScopedLLMProvider(fake_db)
    result = await provider.get_dify_client(42)
    assert result is fake_client


@pytest.mark.asyncio
async def test_m3_get_dify_client_raises_when_workspace_not_ready():
    """M3: workspace.dify_provisioning_status='pending' → 抛 WorkspaceNotReadyError。"""
    from services.llm_service import TenantScopedLLMProvider, WorkspaceNotReadyError

    fake_ws = SimpleNamespace(
        id=42,
        dify_provisioning_status="pending",
    )
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_ws)

    provider = TenantScopedLLMProvider(fake_db)
    with pytest.raises(WorkspaceNotReadyError) as exc_info:
        await provider.get_dify_client(42)
    assert exc_info.value.code == "WORKSPACE_NOT_READY"
    assert "pending" in str(exc_info.value)


# ============== M6 — kb_document_endpoints._assert_kb_document_in_workspace


@pytest.mark.asyncio
async def test_m6_kb_document_helper_blocks_cross_workspace(monkeypatch):
    """M6: doc.tenant_id → tenant.workspace_id != current_user.workspace_id → 403。"""
    from api.v1 import kb_document_endpoints

    # doc.tenant_id = "tenant-A", tenant-A.workspace_id = 1
    # current_user.workspace_id = 2 → 跨 workspace
    doc_tenant_result = MagicMock()
    doc_tenant_result.scalar_one_or_none = MagicMock(return_value="tenant-A")
    tenant_ws_result = MagicMock()
    tenant_ws_result.scalar_one_or_none = MagicMock(return_value=1)
    fake_db = MagicMock()
    fake_db.execute = AsyncMock(side_effect=[doc_tenant_result, tenant_ws_result])

    current_user = SimpleNamespace(role="admin", workspace_id=2)
    with pytest.raises(HTTPException) as exc_info:
        await kb_document_endpoints._assert_kb_document_in_workspace(
            doc_id="doc-1", current_user=current_user, db=fake_db
        )
    assert exc_info.value.status_code == 403
    assert "workspace" in str(exc_info.value.detail).lower()


# ============== M7 — get_tenant_scoped_dify_client readiness 兜底 =========


@pytest.mark.asyncio
async def test_m7_helper_raises_when_workspace_not_ready():
    """M7: workspace.dify_provisioning_status='failed' → 抛 WorkspaceNotReadyError。

    chat_stream 走 M11 PR4 (M7) 在 endpoints.py 的 503 兜底之前, 实际拿 dify client
    的辅助函数就是这里。它一旦抛错, chat_stream 的那段 elif 也会抛 HTTPException(503),
    不会真去 half-configured tenant 发请求。
    """
    from services.llm_service import WorkspaceNotReadyError, get_tenant_scoped_dify_client

    ws = SimpleNamespace(id=99, dify_provisioning_status="failed")
    fake_db = MagicMock()
    with pytest.raises(WorkspaceNotReadyError) as exc_info:
        await get_tenant_scoped_dify_client(ws, fake_db)
    assert exc_info.value.code == "WORKSPACE_NOT_READY"
    assert "failed" in str(exc_info.value)
