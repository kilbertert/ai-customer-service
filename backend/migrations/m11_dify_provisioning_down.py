"""M11 PR2 DOWN — 回滚 Workspace Dify provisioning 6 字段 + audit_logs 表。

WARNING: this is a destructive rollback. It drops:
    1. ``audit_logs`` 表和它的 2 个索引(顺序倒置)。
    2. ``workspaces`` 上的 3 个 index(2 普通 + 1 UNIQUE)。
    3. ``workspaces`` 表的 6 个 provisioning 列(SQLite < 3.35 不支持
       ALTER TABLE DROP COLUMN,容错为 print warning 跳过该列)。

Standard rollback path is to revert the entire code commit
(models.py / sqlite_migrations.py + this script)。本脚本仅作 last resort。

Before running this, ensure:
    - 没有代码依赖 ``Workspace.dify_provisioning_status`` /
      ``Workspace.signup_idempotency_key`` / ``AuditLog``(先 revert models.py)。
    - 数据库已备份(本脚本也会自动备份,但 down 路径备份前请再次确认)。

⚠️  **Data loss**: 所有 audit_logs 行 + 6 个 provisioning 列里写入的数据都会
被删。回滚后无法恢复(只能从 .before_m11_dify_provisioning_down 备份恢复)。
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
    print(f"  备份 → {backup}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        # 1. Drop audit_logs 索引(顺序倒置:先专用索引,后可能存在的 auto)
        cursor.execute("DROP INDEX IF EXISTS idx_audit_logs_correlation_id")
        cursor.execute("DROP INDEX IF EXISTS idx_audit_logs_tenant_id_created_at")

        # 2. Drop audit_logs 表
        cursor.execute("DROP TABLE IF EXISTS audit_logs")

        # 3. Drop UNIQUE INDEX on signup_idempotency_key
        cursor.execute("DROP INDEX IF EXISTS uq_workspaces_signup_idempotency_key")

        # 4. Drop 普通 workspaces 索引
        cursor.execute("DROP INDEX IF EXISTS idx_workspaces_dify_provisioning_status")
        cursor.execute("DROP INDEX IF EXISTS idx_workspaces_dify_tenant_id")

        # 5. Drop 6 列(SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN,< 3.35 容错)
        #    SQLAlchemy create_all 时还会建一个表级 UNIQUE 约束
        #    (UNIQUE (signup_idempotency_key)),用 PRAGMA index_list 查名字再 drop
        #    (本脚本不处理这条 SQLAlchemy 自动 UNIQUE 索引,因为它在 models.py
        #     的 unique=True 触发,down 路径期望先 revert models.py 再跑本脚本)
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
                # SQLite < 3.35 没 DROP COLUMN,或列已不存在
                print(f"⚠️ DROP COLUMN {col} 失败(SQLite < 3.35?): {e}")

        conn.commit()
        print("✅ M11 PR2 down 完成")
        print(
            "   提醒:若 models.py 还在引用这 6 列,记得先 revert models.py 再重启,"
            "否则 SQLAlchemy 建表时会报 OperationalError。"
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
    downgrade()
