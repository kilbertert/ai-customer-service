"""M10 G2 migration DOWN — remove Tenant.workspace_id / KnowledgeBase.workspace_id.

WARNING: this is a destructive rollback. It removes the 1:1 enforcement and the
backfilled workspace_id values. After running this, the legacy per-agent Tenant
behavior (bug 1 from M10-PROMPT.md §3.1) is restored.

Use only as a last-resort rollback. The standard downgrade path is to revert
the entire code commit (models.py / sqlite_migrations.py / kb_service.py /
auth.py).

Steps:
    1. Drop UNIQUE INDEX ix_tenants_workspace_id.
    2. Drop INDEX ix_knowledge_bases_workspace_id.
    3. SQLite does not support DROP COLUMN safely on all versions; we attempt
       the standard ALTER TABLE DROP COLUMN, which works on SQLite 3.35+.
       If your SQLite is older, this script will skip the DROP COLUMN and you
       must recreate the table manually.

Before running this, ensure:
    - No code is currently relying on Tenant.workspace_id or
      KnowledgeBase.workspace_id (i.e., revert kb_service.py + auth.py first).
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

    print(f"开始 M10 G2 down 迁移: {db_path}")
    backup = db_path + ".before_m10_workspace_tenant_1to1_down"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 1. Drop the unique index (loses 1:1 enforcement)
        cursor.execute("DROP INDEX IF EXISTS ix_tenants_workspace_id")
        # 2. Drop the workspace_id index on knowledge_bases
        cursor.execute("DROP INDEX IF EXISTS ix_knowledge_bases_workspace_id")
        # 3. Try to drop the workspace_id columns (SQLite 3.35+).
        # Older SQLite versions will fail; we don't try to recreate the table
        # here because that's destructive on data.
        sqlite_version = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
        if sqlite_version >= (3, 35, 0):
            try:
                cursor.execute("ALTER TABLE tenants DROP COLUMN workspace_id")
                print("✓ Dropped tenants.workspace_id")
            except Exception as e:
                print(f"⚠️ DROP COLUMN tenants.workspace_id failed: {e}")
            try:
                cursor.execute(
                    "ALTER TABLE knowledge_bases DROP COLUMN workspace_id"
                )
                print("✓ Dropped knowledge_bases.workspace_id")
            except Exception as e:
                print(f"⚠️ DROP COLUMN knowledge_bases.workspace_id failed: {e}")
        else:
            print(
                f"⚠️ SQLite {sqlite3.sqlite_version} < 3.35, "
                "DROP COLUMN not attempted. Manual cleanup required."
            )

        conn.commit()
        print("✅ M10 G2 down 迁移完成")
        return True
    except Exception as e:
        print(f"❌ 失败: {e}")
        conn.rollback()
        shutil.copy2(backup, db_path)
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    downgrade()