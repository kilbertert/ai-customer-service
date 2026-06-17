"""M10 G3 migration — Workspace/Agent Dify 集成层 4+4 字段。

Historical record for the M10 milestone (2026-06-15).
See: china_charge_kf/M10-PROMPT.md §4 + docs/dify-integration-plan.md §4.

This is the one-shot standalone version. The actual idempotent logic that
runs on every startup lives in ``sqlite_migrations._migrate_workspaces_dify_fields``
(``backend/sqlite_migrations.py``) and the 4-agent-fields append in
``_migrate_agents``. Use this script only if you need to apply the change to
a production database outside the normal startup path.

Changes:
    1. ``workspaces`` table:
       - ``dify_api_base VARCHAR(255)`` (nullable)
       - ``dify_api_key TEXT`` (nullable, Fernet-encrypted at write time)
       - ``dify_workspace_id VARCHAR(64)`` (nullable, Dify 端 workspace UUID)
       - ``dify_enabled BOOLEAN NOT NULL DEFAULT 0`` (总开关)
    2. ``agents`` table:
       - ``dify_workflow_id VARCHAR(64)`` (nullable, 1 agent = 1 workflow)
       - ``dify_user_prefix VARCHAR(20) NOT NULL DEFAULT 'agent-'`` (G1)
       - ``dify_inputs_schema TEXT`` (nullable, JSON-encoded G1 schema)
       - ``dify_end_user_strategy VARCHAR(20) NOT NULL DEFAULT 'dual_layer'`` (G1)

Plan A / Plan B 拓扑自动判定(runtime):
    - ``dify_api_key IS NULL`` → Plan B (共享 Dify workspace + 全局 API key)
    - ``dify_api_key IS NOT NULL`` → Plan A (本 workspace 独占 Dify workspace)

设计原则:
    - 加密/解密均在应用层 (Pydantic setter + core.encryption) 完成
    - DB 层只存密文,不带任何 "enc:" 标记外的语义
    - NOT NULL 约束仅加在布尔 / 字符串 default 上(便于查询)
    - nullable 字段的 NOT NULL 收紧留给应用层 (避免 SQLite table rebuild)
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

    print(f"开始 M10 G3 迁移: {db_path}")
    backup = db_path + ".before_m10_dify_fields"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        from sqlite_migrations import _migrate_workspaces_dify_fields

        _migrate_workspaces_dify_fields(cursor)
        conn.commit()
        print("✅ M10 G3 迁移完成")
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
