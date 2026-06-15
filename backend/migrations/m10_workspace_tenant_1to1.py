"""M10 G2 migration — Tenant ↔ Workspace 1:1 constraint.

Historical record for the M10 milestone (2026-06-15).
See: china_charge_kf/M10-PROMPT.md §3 + docs/dify-integration-plan.md §4.

This is the one-shot standalone version. The actual idempotent logic that
runs on every startup lives in ``sqlite_migrations._migrate_workspace_tenant_1to1``
(``backend/sqlite_migrations.py``). Use this script only if you need to apply the
change to a production database outside the normal startup path.

Changes:
    1. ``tenants.workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE``
       (added nullable, then backfilled, then ``UNIQUE INDEX`` enforces 1:1)
    2. ``knowledge_bases.workspace_id INTEGER REFERENCES workspaces(id) ON DELETE CASCADE``
       (added nullable, then backfilled from tenant)

Bug fixes included:
    - Bug 1: ``backend/services/kb_service.py:387-394`` was creating 1 Tenant
      per Agent (slug ``agent-{agent_id[:8]}``). After this migration, the same
      Workspace can only have 1 Tenant; redundant Tenants get merged.
    - Bug 2: ``backend/api/endpoints/auth.py:require_tenant_access`` (line 186)
      accepted ``current_user`` but never used it → any admin could access any
      Tenant. Now enforced via workspace membership check.
    - Bug 3: ``Tenant.plan`` / ``billing_email`` preserved as no-op fields
      (M11+ billing placeholder). 0 ACTIVE references in production code;
      schema-only field declaration in ``models.py`` (M10-PROMPT.md §3.6).

Backfill algorithm (SQLite):
    1. Add nullable ``workspace_id`` to ``tenants`` and ``knowledge_bases``.
    2. For each Tenant with slug LIKE 'agent-%', resolve workspace_id via
       ``agents.id LIKE substr(tenants.slug, 7) || '%'``.
    3. Dedupe Tenants per workspace: keep oldest (``MIN(id)``), reassign
       KnowledgeBase.tenant_id, delete the rest.
    4. Orphan Tenants (no agent match) get assigned to the canonical workspace
       (``SELECT MIN(id) FROM workspaces``), same pattern as ``admin_users``.
    5. Backfill ``knowledge_bases.workspace_id`` from their tenant.
    6. Create ``UNIQUE INDEX ix_tenants_workspace_id`` (enforces 1:1 at DB level).
    7. Create ``ix_knowledge_bases_workspace_id``.

NOT NULL constraint: model-level only (SQLite ``ALTER COLUMN NOT NULL`` requires
table rebuild, which we deliberately skip to keep migrations cheap). New rows
must provide workspace_id at the application layer (ORM enforces it).
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

    print(f"开始 M10 G2 迁移: {db_path}")
    backup = db_path + ".before_m10_workspace_tenant_1to1"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        from sqlite_migrations import _migrate_workspace_tenant_1to1

        _migrate_workspace_tenant_1to1(cursor)
        conn.commit()
        print("✅ M10 G2 迁移完成")
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