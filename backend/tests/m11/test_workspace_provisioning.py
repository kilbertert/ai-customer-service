"""M11 PR2 — basjoo schema 迁移 + AuditLog 单元测试。

覆盖范围 (docs/m11/m11-pr2-schema.md §6):
    1. _migrate_workspaces_dify_provisioning 给 workspaces 加 6 列
    2. _create_audit_logs_table 建 audit_logs 表 + 2 索引
    3. signup_idempotency_key UNIQUE 约束生效(重复抛 IntegrityError)
    4. AuditLog 模型可写入并按 tenant_id + created_at 查询
    5. run_sqlite_migrations 整跑包含 M11 段无异常
    6. 多次跑 _migrate_workspaces_dify_provisioning 幂等

与 M10+5 兼容性:
    - Workspace 新字段都有 default,既有 INSERT 路径不受影响
    - AuditLog 是纯新增表
    - signup_idempotency_key nullable=True,旧行不冲突
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

import pytest
from sqlalchemy import select

from models import AuditLog, Workspace
from sqlite_migrations import (
    _create_audit_logs_table,
    _migrate_workspaces_dify_provisioning,
    run_sqlite_migrations,
)


# ─── 1. _migrate_workspaces_dify_provisioning 加 6 列 + 3 索引 ────────────


def test_migration_adds_6_workspace_columns():
    """M11 PR2:旧 workspaces (无 dify_provisioning_* 字段) 升级后 6 列齐备。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
    """)
    _migrate_workspaces_dify_provisioning(cur)
    conn.commit()

    cur.execute("PRAGMA table_info(workspaces)")
    cols = {row[1] for row in cur.fetchall()}

    expected_new = {
        "dify_tenant_id",
        "dify_account_id",
        "dify_provisioning_status",
        "dify_provisioning_attempts",
        "dify_provisioning_last_error",
        "signup_idempotency_key",
    }
    missing = expected_new - cols
    assert not missing, f"workspaces 缺 M11 PR2 字段 {missing},实际 {cols}"

    # 索引必须建出来
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='workspaces' AND name LIKE 'idx_workspaces_dify%'"
    )
    idx = {row[0] for row in cur.fetchall()}
    assert "idx_workspaces_dify_tenant_id" in idx
    assert "idx_workspaces_dify_provisioning_status" in idx

    # UNIQUE 约束也必须建出来
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='workspaces' AND name='uq_workspaces_signup_idempotency_key'"
    )
    assert cur.fetchone() is not None, "uq_workspaces_signup_idempotency_key 索引未建"

    conn.close()


def test_migration_workspace_provisioning_is_idempotent():
    """多次跑 _migrate_workspaces_dify_provisioning 无 ALTER 错误。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript("CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name TEXT);")

    for _ in range(3):
        _migrate_workspaces_dify_provisioning(cur)
    conn.commit()

    cur.execute("PRAGMA table_info(workspaces)")
    cols = [row[1] for row in cur.fetchall()]
    assert "dify_provisioning_status" in cols
    conn.close()


# ─── 2. _create_audit_logs_table ────────────────────────────────────────────


def test_audit_logs_table_creation():
    """M11 PR2:audit_logs 表 + 9 列 + 2 索引齐全。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    _create_audit_logs_table(cur)
    conn.commit()

    cur.execute("PRAGMA table_info(audit_logs)")
    cols = {row[1] for row in cur.fetchall()}
    expected = {
        "id",
        "tenant_id",
        "actor_user_id",
        "action",
        "dify_request_id",
        "correlation_id",
        "status",
        "error_detail",
        "created_at",
    }
    assert cols == expected, f"audit_logs 列不符,got {cols}"

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit_logs'"
    )
    idx = {row[0] for row in cur.fetchall()}
    assert "idx_audit_logs_tenant_id_created_at" in idx
    assert "idx_audit_logs_correlation_id" in idx

    conn.close()


def test_audit_logs_table_creation_is_idempotent():
    """多次跑 _create_audit_logs_table 不报错。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()

    _create_audit_logs_table(cur)
    _create_audit_logs_table(cur)
    _create_audit_logs_table(cur)
    conn.commit()

    cur.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='audit_logs'")
    assert cur.fetchone()[0] == 1
    conn.close()


# ─── 3. signup_idempotency_key UNIQUE 约束生效 ────────────────────────────


def test_signup_idempotency_key_unique_enforced():
    """同一 signup_idempotency_key 重复插入必须抛 IntegrityError。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(
        "CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name TEXT);"
    )
    _migrate_workspaces_dify_provisioning(cur)
    conn.commit()

    cur.execute(
        "INSERT INTO workspaces (id, name, signup_idempotency_key) "
        "VALUES (1, 'ws1', 'idem-key-uuid-aaa')"
    )
    conn.commit()

    # SQLite 在 UNIQUE INDEX 违反时会在 INSERT 阶段就抛 IntegrityError
    # (不等到 commit),所以这里用 cur.execute() 直接断言
    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO workspaces (id, name, signup_idempotency_key) "
            "VALUES (2, 'ws2', 'idem-key-uuid-aaa')"
        )

    conn.close()


def test_signup_idempotency_key_nullable_allows_many_nulls():
    """SQLite UNIQUE INDEX 上 WHERE ... IS NOT NULL:多行 signup_idempotency_key=NULL
    应当都允许(SQL 标准允许多个 NULL 不违反 UNIQUE)。
    """
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript("CREATE TABLE workspaces (id INTEGER PRIMARY KEY, name TEXT);")
    _migrate_workspaces_dify_provisioning(cur)
    conn.commit()

    for i in range(3):
        cur.execute(
            "INSERT INTO workspaces (id, name, signup_idempotency_key) "
            f"VALUES ({i}, 'ws{i}', NULL)"
        )
    conn.commit()
    cur.execute("SELECT count(*) FROM workspaces")
    assert cur.fetchone()[0] == 3
    conn.close()


# ─── 4. AuditLog 模型 ORM 写入 + 查询 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_log_basic_insert_and_query(setup_test_db):
    """ORM 写入 audit_logs 行 + 按 tenant_id + created_at DESC 查回。"""
    from database import AsyncSessionLocal

    tenant = "tenant-uuid-test-001"
    correlation = "corr-uuid-test-001"

    async with AsyncSessionLocal() as session:
        # 写 3 条 audit 行
        rows = [
            AuditLog(
                tenant_id=tenant,
                actor_user_id=1,
                action="dify.tenant.create",
                dify_request_id=None,
                correlation_id=correlation,
                status="success",
                error_detail=None,
            ),
            AuditLog(
                tenant_id=tenant,
                actor_user_id=1,
                action="dify.account.create",
                dify_request_id="dify-req-001",
                correlation_id=correlation,
                status="success",
                error_detail=None,
            ),
            AuditLog(
                tenant_id=tenant,
                actor_user_id=1,
                action="dify.tenant.create",
                dify_request_id="dify-req-002",
                correlation_id=correlation,
                status="failed",
                error_detail="Dify 5xx timeout",
            ),
        ]
        for r in rows:
            session.add(r)
        await session.commit()
        for r in rows:
            await session.refresh(r)

    async with AsyncSessionLocal() as session:
        # 按 tenant_id 过滤
        result = await session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant)
        )
        fetched = result.scalars().all()
        assert len(fetched) == 3

        # 按 status 过滤
        result = await session.execute(
            select(AuditLog).where(
                AuditLog.tenant_id == tenant, AuditLog.status == "failed"
            )
        )
        failed = result.scalars().all()
        assert len(failed) == 1
        assert failed[0].error_detail == "Dify 5xx timeout"

        # 按 correlation_id 串联
        result = await session.execute(
            select(AuditLog).where(AuditLog.correlation_id == correlation)
        )
        timeline = result.scalars().all()
        assert len(timeline) == 3


@pytest.mark.asyncio
async def test_workspace_provisioning_status_default(setup_test_db):
    """新 Workspace 默认 dify_provisioning_status='pending'。"""
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ws = Workspace(
            name="M11 PR2 Test WS",
            owner_email=f"m11-test-{uuid4().hex[:8]}@example.com",
        )
        session.add(ws)
        await session.commit()
        await session.refresh(ws)

        assert ws.dify_provisioning_status == "pending"
        assert ws.dify_provisioning_attempts == 0
        assert ws.dify_tenant_id is None
        assert ws.dify_account_id is None
        assert ws.dify_provisioning_last_error is None
        assert ws.signup_idempotency_key is None


@pytest.mark.asyncio
async def test_workspace_signup_idempotency_key_unique_via_orm(setup_test_db):
    """DB 层 UNIQUE 约束:ORM 重复 signup_idempotency_key 抛 IntegrityError。"""
    from database import AsyncSessionLocal
    from sqlalchemy.exc import IntegrityError

    key = f"idem-{uuid4().hex}"

    async with AsyncSessionLocal() as session:
        ws1 = Workspace(
            name="WS-1",
            owner_email=f"ws1-{uuid4().hex[:8]}@example.com",
            signup_idempotency_key=key,
        )
        session.add(ws1)
        await session.commit()

    async with AsyncSessionLocal() as session:
        ws2 = Workspace(
            name="WS-2",
            owner_email=f"ws2-{uuid4().hex[:8]}@example.com",
            signup_idempotency_key=key,
        )
        session.add(ws2)
        with pytest.raises(IntegrityError):
            await session.commit()


# ─── 5. run_sqlite_migrations 端到端 (sqlite 路径) ───────────────────────


def test_run_sqlite_migrations_includes_m11_segment(tmp_db):
    """整跑 run_sqlite_migrations 包含 M11 PR2 段(6 workspaces 列 + audit_logs)。"""
    db_url = f"sqlite:///{tmp_db}"
    run_sqlite_migrations(db_url)

    conn = sqlite3.connect(tmp_db)
    cur = conn.cursor()

    # workspaces 必须有 6 新字段
    cur.execute("PRAGMA table_info(workspaces)")
    ws_cols = {row[1] for row in cur.fetchall()}
    expected_new = {
        "dify_tenant_id",
        "dify_account_id",
        "dify_provisioning_status",
        "dify_provisioning_attempts",
        "dify_provisioning_last_error",
        "signup_idempotency_key",
    }
    assert expected_new.issubset(ws_cols), (
        f"run_sqlite_migrations 没把 M11 列加齐,缺 {expected_new - ws_cols}"
    )

    # audit_logs 表必须建出来
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_logs'"
    )
    assert cur.fetchone() is not None, "audit_logs 表未建"

    # audit_logs 索引必须建出来
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='audit_logs'"
    )
    au_idx = {row[0] for row in cur.fetchall()}
    assert "idx_audit_logs_tenant_id_created_at" in au_idx
    assert "idx_audit_logs_correlation_id" in au_idx

    conn.close()


def test_run_sqlite_migrations_is_idempotent_with_m11(tmp_db):
    """整跑 run_sqlite_migrations 两次,第二次应当 no-op 不报错。"""
    db_url = f"sqlite:///{tmp_db}"
    run_sqlite_migrations(db_url)
    run_sqlite_migrations(db_url)

    # workspaces 仍然只有 6 个新字段(没有重复添加导致出现 N 倍列)
    conn = sqlite3.connect(tmp_db)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(workspaces)")
    cols = [row[1] for row in cur.fetchall()]
    for f in (
        "dify_tenant_id",
        "dify_account_id",
        "dify_provisioning_status",
        "dify_provisioning_attempts",
        "dify_provisioning_last_error",
        "signup_idempotency_key",
    ):
        assert cols.count(f) == 1, f"{f} 出现 {cols.count(f)} 次,幂等失败"

    cur.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='audit_logs'"
    )
    assert cur.fetchone()[0] == 1

    conn.close()


# ─── 6. 默认值兜底(workspaces 表新行 dify_provisioning_status='pending') ──


# ─── 7. Workspace ORM 模型字段存在性 (spec §10 #7) ──────────────────────────


def test_models_workspace_provisioning_fields_exist():
    """ORM Workspace 类声明 6 个 M11 PR2 字段且属性正确。"""
    expected_attrs = {
        "dify_tenant_id": (str, type(None)),  # nullable
        "dify_account_id": (str, type(None)),
        "dify_provisioning_status": str,  # NOT NULL
        "dify_provisioning_attempts": int,  # NOT NULL
        "dify_provisioning_last_error": (str, type(None)),
        "signup_idempotency_key": (str, type(None)),
    }
    for attr in expected_attrs:
        assert hasattr(Workspace, attr), f"Workspace 缺字段 {attr}"

    # 默认值
    assert Workspace.dify_provisioning_status.default.arg == "pending"
    assert Workspace.dify_provisioning_status.server_default.arg == "pending"
    assert Workspace.dify_provisioning_attempts.default.arg == 0
    assert Workspace.dify_provisioning_attempts.server_default.arg == "0"
    # UNIQUE 约束
    assert Workspace.signup_idempotency_key.unique is True
    # nullable
    assert Workspace.dify_tenant_id.nullable is True
    assert Workspace.dify_provisioning_status.nullable is False


# ─── 8. AuditLog ORM 模型存在性 (spec §10 #8) ──────────────────────────────


def test_models_auditlog_class_exists():
    """ORM AuditLog 类声明 9 个字段 + 2 个 Index。"""
    assert hasattr(AuditLog, "id")
    assert hasattr(AuditLog, "tenant_id")
    assert hasattr(AuditLog, "actor_user_id")
    assert hasattr(AuditLog, "action")
    assert hasattr(AuditLog, "dify_request_id")
    assert hasattr(AuditLog, "correlation_id")
    assert hasattr(AuditLog, "status")
    assert hasattr(AuditLog, "error_detail")
    assert hasattr(AuditLog, "created_at")

    # 表名
    assert AuditLog.__tablename__ == "audit_logs"

    # 9 个 column
    column_names = {c.name for c in AuditLog.__table__.columns}
    expected = {
        "id",
        "tenant_id",
        "actor_user_id",
        "action",
        "dify_request_id",
        "correlation_id",
        "status",
        "error_detail",
        "created_at",
    }
    assert column_names == expected, f"AuditLog 列不符,got {column_names}"

    # 2 个 index
    index_names = {idx.name for idx in AuditLog.__table__.indexes}
    assert "idx_audit_logs_tenant_id_created_at" in index_names
    assert "idx_audit_logs_correlation_id" in index_names

    # 关键 nullable
    assert AuditLog.tenant_id.nullable is False
    assert AuditLog.dify_request_id.nullable is True
    assert AuditLog.created_at.nullable is False


# ─── 9. 默认值兜底(workspaces 表新行 dify_provisioning_status='pending') ──


def test_default_value_for_existing_workspace_after_migration():
    """迁移把现有 workspaces 行的 dify_provisioning_status 设为 'pending'(DEFAULT)。"""
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
        INSERT INTO workspaces (id, name, owner_email) VALUES
            (1, 'pre-m11-ws', 'pre-m11@example.com');
        """
    )
    _migrate_workspaces_dify_provisioning(cur)
    conn.commit()

    cur.execute(
        "SELECT dify_provisioning_status, dify_provisioning_attempts "
        "FROM workspaces WHERE id=1"
    )
    row = cur.fetchone()
    assert row[0] == "pending"
    assert row[1] == 0
    conn.close()


# ─── fixtures ---------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    """给端到端测试一个临时 DB 文件路径(已有空 workspaces 表)。"""
    db_path = tmp_path / f"m11_pr2_{uuid4().hex}.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
        """
    )
    conn.commit()
    conn.close()
    return str(db_path)