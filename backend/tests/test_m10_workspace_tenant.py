"""M10 G2 tests — Tenant ↔ Workspace 1:1 invariant.

覆盖范围 (M10-PROMPT.md §3):
    1. UNIQUE INDEX 强制 1:1 (数据库层)
    2. kb_service: 同 workspace 2 个 agent → 1 个 Tenant
    3. auth: 跨 workspace 访问被 403
    4. auth: super_admin 跨 workspace 放行
    5. migration: 旧数据回填 + dedupe
    6. migration: 新部署幂等 noop
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

import database
from models import (
    AdminUser,
    Agent,
    KnowledgeBase,
    Tenant,
    Workspace,
    WorkspaceQuota,
)
from services.kb_service import KbService


# ─── 1. UNIQUE 约束测试 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenants_workspace_id_unique_constraint(setup_test_db):
    """Tenant.workspace_id 唯一: 同 workspace 创建第 2 个 Tenant 应失败。

    验证数据库层 (UNIQUE INDEX ix_tenants_workspace_id) 真正生效。
    """
    async with database.AsyncSessionLocal() as session:
        ws_result = await session.execute(
            select(Workspace).order_by(Workspace.id).limit(1)
        )
        workspace = ws_result.scalar_one()

        # 第一个 Tenant 成功
        tenant1 = Tenant(
            name="First",
            slug="ws-1-first",
            workspace_id=workspace.id,
        )
        session.add(tenant1)
        await session.commit()

        # 第二个 Tenant 同样的 workspace_id → 必须在 flush 时失败
        tenant2 = Tenant(
            name="Second",
            slug="ws-1-second",
            workspace_id=workspace.id,
        )
        session.add(tenant2)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()


# ─── 2. kb_service per-workspace find-or-create ──────────────────────────


@pytest.mark.asyncio
async def test_get_or_create_agent_kb_shares_tenant_within_workspace(
    setup_test_db, default_agent_id
):
    """同 workspace 创建第 2 个 agent, kb_service 应复用同一个 Tenant。

    Bug 1 回归测试: 旧逻辑按 agent_id 切片做 slug,导致多 Tenant;
    M10 G2 修复后应 per-workspace 共享。
    """
    async with database.AsyncSessionLocal() as session:
        # 拿到当前 default agent 的 workspace
        agent_result = await session.execute(
            select(Agent).where(Agent.id == default_agent_id)
        )
        first_agent = agent_result.scalar_one()
        workspace_id = first_agent.workspace_id

        # 创建第 2 个 agent(同 workspace)
        second_agent = Agent(
            workspace_id=workspace_id,
            name="Second Agent",
            description="M10 G2 test second agent",
        )
        session.add(second_agent)
        await session.commit()
        second_agent_id = second_agent.id

    # 调 kb_service 两次,返回的 Tenant 应是同一个
    # (使用显式 session 绕开 kb_service.py 的 import-time AsyncSessionLocal
    # 捕获,这是 basjoo 既有 test 模式)
    # Mock Qdrant 调用(测试环境无 Qdrant server)
    with patch("services.kb_service.QdrantKbService.ensure_collection", new=AsyncMock()):
        async with database.AsyncSessionLocal() as session:
            kb_svc = KbService(session=session)
            tenant_a, _kb_a = await kb_svc.get_or_create_agent_kb(default_agent_id)
        async with database.AsyncSessionLocal() as session:
            kb_svc = KbService(session=session)
            tenant_b, _kb_b = await kb_svc.get_or_create_agent_kb(second_agent_id)

    assert tenant_a.id == tenant_b.id, (
        f"同 workspace 两个 agent 必须共享 Tenant, "
        f"got {tenant_a.id} vs {tenant_b.id}"
    )
    assert tenant_a.workspace_id == workspace_id


@pytest.mark.asyncio
async def test_get_or_create_agent_kb_slug_format(setup_test_db, default_agent_id):
    """Tenant.slug 是 ws-<workspace_id> 格式 (per M10-PROMPT.md §3.5)。"""
    async with database.AsyncSessionLocal() as session:
        agent_result = await session.execute(
            select(Agent).where(Agent.id == default_agent_id)
        )
        first_agent = agent_result.scalar_one()
        workspace_id = first_agent.workspace_id

    with patch("services.kb_service.QdrantKbService.ensure_collection", new=AsyncMock()):
        async with database.AsyncSessionLocal() as session:
            kb_svc = KbService(session=session)
            tenant, _kb = await kb_svc.get_or_create_agent_kb(default_agent_id)

    assert tenant.slug == f"ws-{workspace_id}"
    assert tenant.workspace_id == workspace_id


# ─── 3 & 4. auth 权限测试 ────────────────────────────────────────────────


@pytest_asyncio.fixture(loop_scope="function")
async def two_workspaces_with_admins(setup_test_db):
    """建 2 个 workspace + 各一个普通 admin,返回 token dict。"""
    from services.auth_service import AuthService

    async with database.AsyncSessionLocal() as session:
        # 第一个 workspace 用 conftest.py 已建的
        ws1 = (
            await session.execute(select(Workspace).order_by(Workspace.id).limit(1))
        ).scalar_one()

        # 第二个 workspace
        ws2 = Workspace(
            name="WS2", owner_email="ws2@example.com"
        )
        session.add(ws2)
        await session.flush()
        session.add(WorkspaceQuota(workspace_id=ws2.id))

        auth = AuthService(session)

        # ws1 admin (non-super)
        admin1 = await auth.create_admin(
            email="ws1_admin@example.com",
            password="testpass123",
            name="WS1 Admin",
            role="admin",
            workspace_id=ws1.id,
        )
        token1 = auth.create_access_token({"sub": str(admin1.id)})

        # ws2 admin
        admin2 = await auth.create_admin(
            email="ws2_admin@example.com",
            password="testpass123",
            name="WS2 Admin",
            role="admin",
            workspace_id=ws2.id,
        )
        token2 = auth.create_access_token({"sub": str(admin2.id)})

        # super admin
        super_admin = await auth.create_admin(
            email="super_admin_m10@example.com",
            password="testpass123",
            name="Super Admin M10",
            role="super_admin",
            workspace_id=None,  # super admin 无 workspace 限制
        )
        super_token = auth.create_access_token({"sub": str(super_admin.id)})

        await session.commit()

        # 在 ws1 建一个 Tenant (供 admin2 试图越权访问)
        tenant_ws1 = Tenant(
            name="WS1 Tenant",
            slug="ws1-only",
            workspace_id=ws1.id,
        )
        session.add(tenant_ws1)
        await session.commit()
        tenant_ws1_id = str(tenant_ws1.id)

    return {
        "ws1_id": ws1.id,
        "ws2_id": ws2.id,
        "tenant_ws1_id": tenant_ws1_id,
        "token_ws1_admin": token1,
        "token_ws2_admin": token2,
        "token_super_admin": super_token,
    }


@pytest.mark.asyncio
async def test_require_tenant_access_blocks_cross_workspace(two_workspaces_with_admins):
    """普通 admin 跨 workspace 访问 Tenant → 403 (Bug 2 修复)。"""
    from fastapi import HTTPException

    from api.endpoints.auth import require_tenant_access

    fixture = two_workspaces_with_admins
    # ws2 admin 试图访问 ws1 的 Tenant
    admin2_user = MagicMock(spec=AdminUser)
    admin2_user.role = "admin"
    admin2_user.workspace_id = fixture["ws2_id"]

    # Mock db session
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.workspace_id = fixture["ws1_id"]
    mock_result.scalar_one_or_none.return_value = mock_tenant
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await require_tenant_access(
            tenant_id=fixture["tenant_ws1_id"],
            current_user=admin2_user,
            db=mock_db,
        )
    assert exc_info.value.status_code == 403
    assert "workspace" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_require_tenant_access_allows_same_workspace(two_workspaces_with_admins):
    """同 workspace admin 访问本 workspace Tenant → 200。"""
    from api.endpoints.auth import require_tenant_access

    fixture = two_workspaces_with_admins
    admin1_user = MagicMock(spec=AdminUser)
    admin1_user.role = "admin"
    admin1_user.workspace_id = fixture["ws1_id"]

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.workspace_id = fixture["ws1_id"]
    mock_result.scalar_one_or_none.return_value = mock_tenant
    mock_db.execute.return_value = mock_result

    result = await require_tenant_access(
        tenant_id=fixture["tenant_ws1_id"],
        current_user=admin1_user,
        db=mock_db,
    )
    assert result == fixture["tenant_ws1_id"]


@pytest.mark.asyncio
async def test_require_tenant_access_super_admin_bypass(two_workspaces_with_admins):
    """super_admin 跨 workspace 访问 → 放行。"""
    from api.endpoints.auth import require_tenant_access

    fixture = two_workspaces_with_admins
    super_user = MagicMock(spec=AdminUser)
    super_user.role = "super_admin"
    super_user.workspace_id = None  # super admin 无 workspace

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_tenant = MagicMock()
    mock_tenant.workspace_id = fixture["ws1_id"]  # 跨到 ws1
    mock_result.scalar_one_or_none.return_value = mock_tenant
    mock_db.execute.return_value = mock_result

    # 必须不抛 403
    result = await require_tenant_access(
        tenant_id=fixture["tenant_ws1_id"],
        current_user=super_user,
        db=mock_db,
    )
    assert result == fixture["tenant_ws1_id"]


# ─── 5 & 6. 迁移测试 ─────────────────────────────────────────────────────


@pytest.fixture
def legacy_tenant_db(tmp_path):
    """构造一个 legacy schema 的 SQLite DB,模拟 M10 之前的数据状态。

    含:
        - 1 个 workspace
        - 2 个 agent (同 workspace)
        - 2 个 Tenant (slug='agent-<agent_id>')  — 旧 bug
        - 1 个 KB
    迁移后应合并为 1 个 Tenant。
    """
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id)
        );
        CREATE TABLE tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL
        );
        CREATE TABLE knowledge_bases (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(id)
        );
    """)
    cur.execute("INSERT INTO workspaces VALUES (1, 'Legacy WS', 'legacy@example.com')")
    cur.execute("INSERT INTO agents VALUES ('agt_aaaabbbb', 1)")
    cur.execute("INSERT INTO agents VALUES ('agt_ccccdddd', 1)")
    # 旧 bug: 每个 agent 一个 Tenant,slug=f"agent-<agent_id>[:8]"
    cur.execute("INSERT INTO tenants VALUES ('t1', 'Agent Tenant 1', 'agent-agt_aaaa')")
    cur.execute("INSERT INTO tenants VALUES ('t2', 'Agent Tenant 2', 'agent-agt_cccc')")
    cur.execute("INSERT INTO knowledge_bases VALUES ('kb1', 't1')")
    conn.commit()
    conn.close()
    return db_path


def test_migration_backfill_and_dedupe(legacy_tenant_db):
    """迁移: 旧数据回填 + dedupe Tenant + 加 UNIQUE INDEX。"""
    from sqlite_migrations import _migrate_workspace_tenant_1to1

    conn = sqlite3.connect(str(legacy_tenant_db))
    cur = conn.cursor()
    _migrate_workspace_tenant_1to1(cur)
    conn.commit()

    # 1. 验证 workspace_id 被回填
    cur.execute("SELECT workspace_id FROM tenants ORDER BY id")
    ws_ids = [r[0] for r in cur.fetchall()]
    assert all(w == 1 for w in ws_ids), (
        f"所有 Tenant 应被回填到 workspace 1, got {ws_ids}"
    )

    # 2. 验证 dedupe: 2 个 Tenant 应合并为 1 个
    cur.execute("SELECT COUNT(*) FROM tenants")
    tenant_count = cur.fetchone()[0]
    assert tenant_count == 1, f"应只剩 1 个 Tenant, got {tenant_count}"

    # 3. 验证 KB 仍能访问(被 reassign 到合并后的 Tenant)
    cur.execute("SELECT tenant_id FROM knowledge_bases WHERE id='kb1'")
    kb_tenant_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM tenants")
    kept_tenant_id = cur.fetchone()[0]
    assert kb_tenant_id == kept_tenant_id, "KB 应被 reassign 到保留的 Tenant"

    # 4. 验证 UNIQUE INDEX 已创建
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND name='ix_tenants_workspace_id'"
    )
    assert cur.fetchone() is not None, "UNIQUE INDEX ix_tenants_workspace_id 应被创建"

    # 5. 验证插入第 2 个 Tenant 同 workspace → 被 UNIQUE 拒绝
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO tenants (id, name, slug, workspace_id) "
            "VALUES ('t_dup', 'Dup', 'dup-slug', 1)"
        )
        conn.commit()
    conn.close()


def test_migration_idempotent_on_fresh_db():
    """迁移: 新部署(空库)应幂等 noop。"""
    from sqlite_migrations import _migrate_workspace_tenant_1to1

    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    # 空库: tenants 表都不存在,函数应 noop
    _migrate_workspace_tenant_1to1(cur)
    conn.commit()
    # 没有表创建,也无错误
    assert True


# ─── 注: Tenant.plan / billing_email 是 M11+ billing 占位字段, schema 保留
# 但本 M10 不消费, 也不写测试 (M10-PROMPT.md §3.6: 0 active references).
