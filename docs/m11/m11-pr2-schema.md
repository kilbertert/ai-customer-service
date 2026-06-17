# M11 PR2 — basjoo 数据模型迁移(sqlite_migrations 模式)

> **依赖**:无(可与 PR1 并行起步)
> **工作量**:0.2 周 1 人(实际已被压缩;`models.py` 已由用户在分支上预施工)
> **下游**:PR3 / PR4 都依赖此 schema

> **基线版本**:basjoo `feat/m11-basjoo-schema` 分支(PR2 已在该分支提交 `models.py` 改动)

---

## 1. 范围

basjoo 侧 2 项 schema 变更:
1. `workspaces` 表加 6 列 + 2 索引 + 1 UNIQUE INDEX
2. 新增 `audit_logs` 表 + 2 索引

---

## 2. 重要:basjoo **不使用 Alembic**

PR2 初版 spec 假设"Alembic 已就位",经核实**错误**。basjoo 实际自研一套更轻量的 SQLite migration 体系:

| 维度 | PR2 初版 spec | 实际 |
|------|--------------|------|
| 迁移工具 | Alembic (`alembic upgrade head`) | **无 Alembic**,用 `Base.metadata.create_all()` + `sqlite_migrations.py` 幂等函数 |
| 新部署 | alembic 自动建表 | `database.py:init_db()` 调 `Base.metadata.create_all`(`database.py:131`) |
| 演进迁移 | `op.add_column` / `op.create_index` | `sqlite_migrations._migrate_xxx(cursor)` 函数,启动时 `run_sqlite_migrations()` 自动调 |
| 历史 one-shot | Alembic 自动 | `backend/migrations/m10_dify_fields.py` 等,纯 sqlite3 stdlib,**手动**跑或 prod 部署时用 |
| 唯一约束 | `op.create_unique_constraint` | `CREATE UNIQUE INDEX` |
| 数据库 | SQLite + Postgres 双跑 | **SQLite only**(`docker-compose.yml` 里 `db_postgres` profile 是 Dify 用的,basjoo 始终 SQLite) |

**所以本 PR 的真实工作 = 写 `sqlite_migrations.py` 的幂等函数 + 写 `backend/migrations/*.py` 的 one-shot 脚本**。`models.py` 已经预施工,只需验证 + 微调。

---

## 3. 改动清单

| # | 文件 | 行数 | 状态 | 内容 |
|---|------|------|------|------|
| 1 | `backend/models.py` | +56 | **已施工(待验证)** | Workspace 加 6 字段 + AuditLog 新类 |
| 2 | `backend/sqlite_migrations.py` | +60 | 待施工 | 新增 `_migrate_workspaces_dify_provisioning` + 注册 |
| 3 | `backend/migrations/m11_dify_provisioning.py` | +60 | 待施工 | 历史 one-shot |
| 4 | `backend/migrations/m11_dify_provisioning_down.py` | +50 | 待施工 | 回滚脚本 |
| 5 | `docs/operations.md` | +10 | 待施工 | bootstrap workspace 初始化 SOP |
| 6 | `backend/tests/m11/test_workspace_provisioning.py` | +150 | 待施工 | 单测 |

(总实际待施工 ~330 行,`models.py` 的 +56 已完成)

---

## 4. `models.py` 改动(已施工,需施工 agent 验证)

### 4.1 Workspace 6 字段

参考样板(已存在于分支,git diff 可见):

```python
# Workspace 类末尾追加
dify_tenant_id = Column(String(36), nullable=True)
dify_account_id = Column(String(36), nullable=True)
dify_provisioning_status = Column(
    String(20), nullable=False, default="pending", server_default="pending"
)
dify_provisioning_attempts = Column(
    Integer, nullable=False, default=0, server_default="0"
)
dify_provisioning_last_error = Column(Text, nullable=True)
signup_idempotency_key = Column(String(36), unique=True, nullable=True)
```

### 4.2 AuditLog 类

参考样板(已存在于分支末尾):

```python
class AuditLog(Base):
    """M11 PR2 — Dify provisioning 审计日志..."""
    __tablename__ = "audit_logs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(36), nullable=False)
    actor_user_id = Column(Integer, nullable=False)
    action = Column(String(64), nullable=False)
    dify_request_id = Column(String(36), nullable=True)
    correlation_id = Column(String(36), nullable=False)
    status = Column(String(20), nullable=False)  # 'success' / 'failed'
    error_detail = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_audit_logs_tenant_id_created_at", "tenant_id", "created_at"),
        Index("idx_audit_logs_correlation_id", "correlation_id"),
    )
```

**施工 agent 验证项**:
- `git diff backend/models.py` 应只有 + 类末尾追加,无任何已有字段修改
- `grep -n "class Workspace\|class AuditLog" backend/models.py` 确认两个类存在
- 无需自己写,只需要 `git add backend/models.py` 然后 commit 即可(若尚未 commit)

---

## 5. `sqlite_migrations.py` 改动(待施工)

### 5.1 新增 `_migrate_workspaces_dify_provisioning` 函数

在文件末尾(L856 之后)新增,参考 `_migrate_workspaces_dify_fields`(L817-856)的样板:

```python
def _migrate_workspaces_dify_provisioning(cursor: sqlite3.Cursor) -> None:
    """M11 PR2 — Workspace 表加 Dify provisioning 字段 + audit_logs 表。

    Idempotent. Safe to run multiple times. See:
      docs/m11/m11-pr2-schema.md §5
      docs/handoffs/M10PLUS-agent-dify-integration.md §7 (handoff chain)

    字段语义:
    - dify_tenant_id: Dify tenant UUID (NULL = 还没签 / bootstrap workspace)
    - dify_account_id: Dify account UUID (NULL = 还没签)
    - dify_provisioning_status: 'pending' / 'provisioning' / 'ready' / 'failed'
    - dify_provisioning_attempts: 累计失败次数,达 3 次后转 failed_permanent
    - dify_provisioning_last_error: 最近一次失败原因(给 ops debug)
    - signup_idempotency_key: 注册时一次性幂等键,DB 层 UNIQUE 约束

    设计取舍:
    - dify_provisioning_status NOT NULL with server_default='pending':
      让老 workspace 在升级后立即落到 pending,bootstrap workspace 由 ops
      手工 SQL 标 ready(见 docs/operations.md §M11-INIT)。
    - signup_idempotency_key UNIQUE: 并发同 email 注册仅一个成功,其余 409。
    """
    # 1. 加 6 列(idempotent via _ensure_columns)
    _ensure_columns(
        cursor,
        "workspaces",
        [
            ("dify_tenant_id", "VARCHAR(36)"),
            ("dify_account_id", "VARCHAR(36)"),
            (
                "dify_provisioning_status",
                "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            ),
            (
                "dify_provisioning_attempts",
                "INTEGER NOT NULL DEFAULT 0",
            ),
            ("dify_provisioning_last_error", "TEXT"),
            ("signup_idempotency_key", "VARCHAR(36)"),
        ],
    )

    # 2. 索引(idempotent via IF NOT EXISTS)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspaces_dify_tenant_id "
        "ON workspaces (dify_tenant_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspaces_dify_provisioning_status "
        "ON workspaces (dify_provisioning_status)"
    )

    # 3. UNIQUE INDEX on signup_idempotency_key(idempotent via IF NOT EXISTS)
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_signup_idempotency_key "
        "ON workspaces (signup_idempotency_key)"
    )

    # 4. audit_logs 表(idempotent via IF NOT EXISTS)
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id VARCHAR(36) NOT NULL,
            actor_user_id INTEGER NOT NULL,
            action VARCHAR(64) NOT NULL,
            dify_request_id VARCHAR(36),
            correlation_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_detail TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # 5. audit_logs 索引(idempotent via IF NOT EXISTS)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id_created_at "
        "ON audit_logs (tenant_id, created_at)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_correlation_id "
        "ON audit_logs (correlation_id)"
    )
```

### 5.2 在 `run_sqlite_migrations` 注册

修改 `sqlite_migrations.py:run_sqlite_migrations()` 中 L416 附近(M10 G3 调用之后),插入:

```python
# ── M11 PR2: Dify provisioning 字段 + audit_logs ───────────────────
if _table_exists(cursor, "workspaces"):
    _migrate_workspaces_dify_provisioning(cursor)
```

完整块(L412-418 修改后):

```python
        # ── M10 G2: Tenant ↔ Workspace 1:1 ──────────────────────────────────
        if _table_exists(cursor, "tenants"):
            _migrate_workspace_tenant_1to1(cursor)

        # ── M10 G3: Dify 集成层 4+4 字段 ────────────────────────────────────
        if _table_exists(cursor, "workspaces"):
            _migrate_workspaces_dify_fields(cursor)
        # agents 4 字段:加在 _migrate_agents 列表尾部,见下方

        # ── M11 PR2: Dify provisioning 字段 + audit_logs ───────────────────
        if _table_exists(cursor, "workspaces"):
            _migrate_workspaces_dify_provisioning(cursor)

        conn.commit()
```

---

## 6. `backend/migrations/m11_dify_provisioning.py`(历史 one-shot)

参考 `backend/migrations/m10_dify_fields.py` 的样板(顶层 `migrate()` 函数 + 自动备份 + 调 `sqlite_migrations._migrate_workspaces_dify_provisioning(cursor)`):

```python
"""M11 PR2 migration — Workspace Dify provisioning 字段 + audit_logs 表。

Historical record. The actual idempotent logic that runs on every startup lives
in ``sqlite_migrations._migrate_workspaces_dify_provisioning``
(``backend/sqlite_migrations.py``). Use this script only if you need to apply
the change to a production database outside the normal startup path.

Changes:
    1. ``workspaces`` table:
       - dify_tenant_id VARCHAR(36) (nullable)
       - dify_account_id VARCHAR(36) (nullable)
       - dify_provisioning_status VARCHAR(20) NOT NULL DEFAULT 'pending'
       - dify_provisioning_attempts INTEGER NOT NULL DEFAULT 0
       - dify_provisioning_last_error TEXT (nullable)
       - signup_idempotency_key VARCHAR(36) (nullable, UNIQUE INDEX)
    2. Indexes:
       - idx_workspaces_dify_tenant_id
       - idx_workspaces_dify_provisioning_status
       - uq_workspaces_signup_idempotency_key (UNIQUE)
    3. New table ``audit_logs`` (8 columns + 2 indexes)

Bootstrap workspace 手工初始化(部署后必须跑):
    UPDATE workspaces SET dify_provisioning_status='ready',
        dify_provisioning_attempts=0
    WHERE dify_tenant_id IS NULL AND dify_provisioning_status='pending';
"""

import os
import shutil
import sqlite3


def migrate():
    possible_paths = [
        "/app/data/basjoo.db",
        "./test.db",
        "./data/basjoo.db",
        "../data/basjoo.db",
    ]
    db_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not db_path:
        print("数据库文件不存在，跳过（新部署由 create_all 处理）")
        return True

    print(f"开始 M11 PR2 迁移: {db_path}")
    backup = db_path + ".before_m11_dify_provisioning"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        from sqlite_migrations import _migrate_workspaces_dify_provisioning
        _migrate_workspaces_dify_provisioning(cursor)
        conn.commit()
        print("✅ M11 PR2 迁移完成")
        return True
    except Exception as e:
        print(f"❌ 失败: {e}")
        conn.rollback()
        shutil.copy2(backup, db_path)
        print("已从备份恢复数据库")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
```

---

## 7. `backend/migrations/m11_dify_provisioning_down.py`(回滚脚本)

参考 `backend/migrations/m10_workspace_tenant_1to1_down.py`(WARNING 头 + `downgrade()` 函数 + 自动备份 + DROP 顺序倒置):

```python
"""M11 PR2 DOWN — 移除 Workspace Dify provisioning 字段 + audit_logs 表。

WARNING: this is a destructive rollback. It drops:
    1. The audit_logs table and its 2 indexes.
    2. The uq_workspaces_signup_idempotency_key UNIQUE INDEX.
    3. The idx_workspaces_dify_provisioning_status index.
    4. The idx_workspaces_dify_tenant_id index.
    5. SQLite DROP COLUMN requires 3.35+; if older, skip the DROP COLUMN
       and recreate the table manually.

Standard rollback path is to revert the entire code commit (models.py /
sqlite_migrations.py + this script). Use this script only as a last resort.

Before running this, ensure:
    - No code relies on Workspace.dify_provisioning_status /
      signup_idempotency_key (revert models.py first).
    - Database is backed up (this script does NOT auto-backup the down path).
"""

import os
import shutil
import sqlite3


def downgrade():
    possible_paths = [
        "/app/data/basjoo.db",
        "./test.db",
        "./data/basjoo.db",
        "../data/basjoo.db",
    ]
    db_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not db_path:
        print("数据库文件不存在，跳过")
        return True

    print(f"开始 M11 PR2 down 迁移: {db_path}")
    backup = db_path + ".before_m11_dify_provisioning_down"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 1. Drop audit_logs 索引 + 表(顺序倒置)
        cursor.execute("DROP INDEX IF EXISTS idx_audit_logs_correlation_id")
        cursor.execute("DROP INDEX IF EXISTS idx_audit_logs_tenant_id_created_at")
        cursor.execute("DROP TABLE IF EXISTS audit_logs")

        # 2. Drop UNIQUE INDEX
        cursor.execute("DROP INDEX IF EXISTS uq_workspaces_signup_idempotency_key")

        # 3. Drop 普通索引
        cursor.execute("DROP INDEX IF EXISTS idx_workspaces_dify_provisioning_status")
        cursor.execute("DROP INDEX IF EXISTS idx_workspaces_dify_tenant_id")

        # 4. Drop columns(SQLite 3.35+)
        for col in (
            "signup_idempotency_key",
            "dify_provisioning_last_error",
            "dify_provisioning_attempts",
            "dify_provisioning_status",
            "dify_account_id",
            "dify_tenant_id",
        ):
            try:
                cursor.execute(f"ALTER TABLE workspaces DROP COLUMN {col}")
            except Exception as e:
                print(f"⚠️ DROP COLUMN {col} 失败(SQLite < 3.35?): {e}")

        conn.commit()
        print("✅ M11 PR2 down 完成")
        return True
    except Exception as e:
        print(f"❌ 失败: {e}")
        conn.rollback()
        shutil.copy2(backup, db_path)
        print("已从备份恢复数据库")
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    downgrade()
```

---

## 8. SQLite 兼容性(SQLite only)

basjoo 实际 DB 层只用 SQLite(`docker-compose.yml` 里 `db_postgres` 是 Dify 容器),不需要考虑 Postgres 分支索引 / `postgresql_where` 等。**PR2 初版 spec 里的 SQLite/Postgres 双兼容章节作废**。

---

## 9. bootstrap workspace 手工初始化

无历史数据迁移。bootstrap workspace 的 `dify_provisioning_status` 默认 `pending`,**必须**手工初始化为 `ready`(因为它没有对应 Dify tenant):

```sql
-- 手工 SQL,只跑一次(在迁移完成后):
UPDATE workspaces
SET dify_provisioning_status = 'ready',
    dify_provisioning_attempts = 0
WHERE dify_tenant_id IS NULL
  AND dify_provisioning_status = 'pending';
```

此 SQL 不进 migration 脚本(依赖具体部署环境),**必须写进 `docs/operations.md` 的"M11 bootstrap workspace 初始化 SOP"章节**。

---

## 10. 测试(全部 SQLite + 在 conftest 现有框架下)

新增 `backend/tests/m11/test_workspace_provisioning.py`(目录不存在则创建):

| 测试 | 期望 |
|------|------|
| `test_run_sqlite_migrations_idempotent` | 同一 DB 跑 2 次 `_migrate_workspaces_dify_provisioning` 无报错 |
| `test_workspace_columns_added` | `PRAGMA table_info(workspaces)` 含 6 个新列 |
| `test_workspace_indexes_created` | `sqlite_master` 含 3 个 index |
| `test_signup_idempotency_key_unique_constraint` | 重复 key 抛 IntegrityError |
| `test_audit_logs_table_created` | `PRAGMA table_info(audit_logs)` 含 9 列 |
| `test_audit_logs_indexes_created` | `sqlite_master` 含 2 个 audit_logs 索引 |
| `test_models_workspace_provisioning_fields_exist` | `Workspace.dify_provisioning_status` 等 6 字段在 ORM 中 |
| `test_models_auditlog_class_exists` | `AuditLog` 类 + 9 列 + 2 索引可在 ORM 中查 |
| `test_audit_log_basic_insert_and_query` | 写一行 + 按 tenant_id + created_at 查询 |
| `test_init_db_creates_audit_logs_via_create_all` | `database.init_db()` 后 audit_logs 表存在 |

**测试技巧**:
- 用 `conftest.py` 的 `BASJOO_TEST_MODE=1` + 临时 SQLite(`backend/.pytest_dbs/test.db`)
- `init_db()` 自动调 `run_sqlite_migrations()` + `Base.metadata.create_all()`
- PRAGMA 查询走 `sqlite3` 直连,不走 SQLAlchemy

---

## 11. PR2 评审 checklist

提交 PR 前自检:
- [ ] `backend/models.py` 已 git add(若是预施工分支未提交)
- [ ] `backend/sqlite_migrations.py` 新增 `_migrate_workspaces_dify_provisioning` + 在 `run_sqlite_migrations` 注册
- [ ] `backend/migrations/m11_dify_provisioning.py` 历史 one-shot 已写
- [ ] `backend/migrations/m11_dify_provisioning_down.py` 回滚脚本已写
- [ ] `docs/operations.md` 含 "M11 bootstrap workspace 初始化 SOP" 章节
- [ ] `backend/tests/m11/test_workspace_provisioning.py` 单测 ≥ 80% 覆盖率
- [ ] M10+5 已有测试无回归(跑 `pytest tests/ --ignore=tests/integration/`)
- [ ] 单测 + 手工运行 `python backend/migrations/m11_dify_provisioning.py` 在 fresh DB 干净
- [ ] 单测 + 手工运行 `python backend/migrations/m11_dify_provisioning_down.py` 干净
- [ ] git commit:`feat(backend): PR2 dify provisioning schema (m11, sqlite_migrations)`