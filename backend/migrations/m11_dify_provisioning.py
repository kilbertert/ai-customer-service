"""M11 PR2 migration — Workspace Dify provisioning 6 字段 + audit_logs 表。

Historical one-shot script. The idempotent logic that runs on every startup
lives in ``sqlite_migrations._migrate_workspaces_dify_provisioning`` and
``sqlite_migrations._create_audit_logs_table`` (``backend/sqlite_migrations.py``).
Use this script only if you need to apply the change to a production database
outside the normal startup path (e.g. emergency fix on a DB that wasn't
auto-migrated).

Changes:
    1. ``workspaces`` table — 6 new columns:
       - dify_tenant_id VARCHAR(36) (nullable, Dify tenant UUID)
       - dify_account_id VARCHAR(36) (nullable, Dify account UUID)
       - dify_provisioning_status VARCHAR(20) NOT NULL DEFAULT 'pending'
         (状态机:pending → provisioning → ready/failed)
       - dify_provisioning_attempts INTEGER NOT NULL DEFAULT 0
       - dify_provisioning_last_error TEXT (nullable)
       - signup_idempotency_key VARCHAR(36) UNIQUE (注册幂等键,DB 层唯一约束)
    2. New indexes on ``workspaces``:
       - idx_workspaces_dify_tenant_id
       - idx_workspaces_dify_provisioning_status
       - uq_workspaces_signup_idempotency_key (UNIQUE, partial: WHERE IS NOT NULL)
    3. New table ``audit_logs`` (9 columns + 2 indexes) — Dify 注册流程审计日志。
       字段:id / tenant_id / actor_user_id / action / dify_request_id /
       correlation_id / status / error_detail / created_at
       索引:idx_audit_logs_tenant_id_created_at / idx_audit_logs_correlation_id

Bootstrap workspace 手工初始化(部署后**必须**在迁移完成后跑一次,见
docs/operations.md §M11-INIT "M11 bootstrap workspace 初始化 SOP"):
    UPDATE workspaces
    SET dify_provisioning_status='ready',
        dify_provisioning_attempts=0
    WHERE dify_tenant_id IS NULL
      AND dify_provisioning_status='pending';
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
    print(f"  备份 → {backup}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        from sqlite_migrations import (
            _migrate_workspaces_dify_provisioning,
            _create_audit_logs_table,
        )
        # 1. workspaces 加 6 列 + 2 index + 1 UNIQUE index
        _migrate_workspaces_dify_provisioning(cursor)
        # 2. audit_logs 表 + 2 index
        _create_audit_logs_table(cursor)
        conn.commit()
        print("✅ M11 PR2 迁移完成")
        print(
            "   提醒:请确认执行 docs/operations.md §M11-INIT 里的 "
            "bootstrap workspace 初始化 SQL。"
        )
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
