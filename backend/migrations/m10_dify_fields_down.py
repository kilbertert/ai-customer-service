"""M10 G3 migration rollback — drop Dify 4+4 字段。

Drops the 4 workspaces + 4 agents columns added in m10_dify_fields.py.
SQLite < 3.35 does not support ``ALTER TABLE DROP COLUMN``; this script
uses the table-rebuild pattern when the column exists.

⚠️  **Data loss**: any Dify API keys / workspace IDs / workflow IDs / user
prefixes stored in these columns will be lost. Re-running m10_dify_fields.py
will re-create the columns but cannot recover the deleted values.

Use only for emergency rollback in dev/staging. Production rollback should
use ``create_all`` from a clean DB or skip this and apply m10_dify_fields.py
forward.
"""

import os
import shutil
import sqlite3


def migrate_down():
    possible_paths = [
        "/app/data/basjoo.db",
        "./test.db",
        "./data/basjoo.db",
        "../data/basjoo.db",
    ]
    db_path = next((p for p in possible_paths if os.path.exists(p)), None)
    if not db_path:
        print("数据库文件不存在，无需回滚")
        return True

    print(f"开始 M10 G3 回滚: {db_path}")
    backup = db_path + ".before_m10_dify_fields_down"
    shutil.copy2(db_path, backup)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("PRAGMA table_info(agents)")
        agent_cols = {row[1] for row in cursor.fetchall()}
        agent_dify_cols = [
            c for c in (
                "dify_workflow_id",
                "dify_user_prefix",
                "dify_inputs_schema",
                "dify_end_user_strategy",
            )
            if c in agent_cols
        ]
        if agent_dify_cols:
            keep_cols = [
                r[1] for r in cursor.execute("PRAGMA table_info(agents)")
                if r[1] not in agent_dify_cols
            ]
            keep_csv = ", ".join(keep_cols)
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("ALTER TABLE agents RENAME TO _agents_old_m10g3")
            cursor.execute(
                f"CREATE TABLE agents ({_agents_schema_for_rebuild()})"
            )
            cursor.execute(
                f"INSERT INTO agents ({keep_csv}) SELECT {keep_csv} "
                f"FROM _agents_old_m10g3"
            )
            cursor.execute("DROP TABLE _agents_old_m10g3")
            cursor.execute("PRAGMA foreign_keys=ON")
            print(f"✓ Dropped {len(agent_dify_cols)} dify cols from agents")

        cursor.execute("PRAGMA table_info(workspaces)")
        ws_cols = {row[1] for row in cursor.fetchall()}
        ws_dify_cols = [
            c for c in (
                "dify_api_base",
                "dify_api_key",
                "dify_workspace_id",
                "dify_enabled",
            )
            if c in ws_cols
        ]
        if ws_dify_cols:
            keep_cols = [
                r[1] for r in cursor.execute("PRAGMA table_info(workspaces)")
                if r[1] not in ws_dify_cols
            ]
            keep_csv = ", ".join(keep_cols)
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("ALTER TABLE workspaces RENAME TO _workspaces_old_m10g3")
            cursor.execute(
                f"CREATE TABLE workspaces ({_workspaces_schema_for_rebuild()})"
            )
            cursor.execute(
                f"INSERT INTO workspaces ({keep_csv}) SELECT {keep_csv} "
                f"FROM _workspaces_old_m10g3"
            )
            cursor.execute("DROP TABLE _workspaces_old_m10g3")
            cursor.execute("PRAGMA foreign_keys=ON")
            print(f"✓ Dropped {len(ws_dify_cols)} dify cols from workspaces")

        conn.commit()
        print("✅ M10 G3 回滚完成")
        return True
    except Exception as e:
        print(f"❌ 回滚失败: {e}")
        conn.rollback()
        shutil.copy2(backup, db_path)
        print("已从备份恢复数据库")
        return False
    finally:
        conn.close()


def _agents_schema_for_rebuild() -> str:
    """Original agents schema (pre-m10_g3) — used for table rebuild on rollback."""
    return """
        id VARCHAR(50) PRIMARY KEY,
        workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
        name VARCHAR(100) NOT NULL DEFAULT 'AI Agent',
        description TEXT,
        agent_type VARCHAR(50) NOT NULL DEFAULT 'website_support',
        channel_mode VARCHAR(50) NOT NULL DEFAULT 'web_widget',
        avatar VARCHAR(500),
        system_prompt TEXT NOT NULL DEFAULT 'You are a helpful customer service assistant.',
        model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o-mini',
        temperature FLOAT NOT NULL DEFAULT 0.7,
        max_tokens INTEGER NOT NULL DEFAULT 1000,
        api_key VARCHAR(500),
        api_base VARCHAR(500),
        jina_api_key VARCHAR(500),
        siliconflow_api_key VARCHAR(500),
        vision_api_key VARCHAR(500),
        vision_base_url VARCHAR(500),
        vision_provider_type VARCHAR(20),
        vision_model VARCHAR(100),
        whisper_api_key VARCHAR(500),
        whisper_base_url VARCHAR(500),
        whisper_model VARCHAR(100),
        provider_type VARCHAR(50),
        azure_endpoint VARCHAR(500),
        azure_deployment_name VARCHAR(100),
        azure_api_version VARCHAR(20),
        anthropic_version VARCHAR(20),
        google_project_id VARCHAR(100),
        google_region VARCHAR(50),
        provider_config TEXT,
        embedding_provider VARCHAR(20),
        embedding_api_base VARCHAR(500),
        embedding_model VARCHAR(100),
        embedding_batch_size INTEGER,
        kb_setup_completed BOOLEAN DEFAULT 0,
        crawl_max_depth INTEGER DEFAULT 2,
        crawl_max_pages INTEGER DEFAULT 500,
        url_fetch_interval_days INTEGER DEFAULT 7,
        enable_auto_fetch BOOLEAN DEFAULT 0,
        top_k INTEGER DEFAULT 5,
        similarity_threshold FLOAT DEFAULT 0.01,
        enable_context BOOLEAN DEFAULT 0,
        rate_limit_per_minute INTEGER DEFAULT 20,
        restricted_reply TEXT,
        last_error_code VARCHAR(50),
        last_error_message TEXT,
        last_error_at DATETIME,
        allowed_widget_origins TEXT,
        persona_type VARCHAR(20) DEFAULT 'general',
        widget_title VARCHAR(100),
        widget_color VARCHAR(20),
        welcome_message TEXT,
        history_days INTEGER DEFAULT 30,
        is_active BOOLEAN,
        deleted_at DATETIME,
        purge_after DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME,
        kb_id VARCHAR(36)
    """


def _workspaces_schema_for_rebuild() -> str:
    """Original workspaces schema (pre-m10_g3) — used for table rebuild on rollback."""
    return """
        id INTEGER PRIMARY KEY,
        name VARCHAR(100) NOT NULL DEFAULT 'Default Workspace',
        owner_email VARCHAR(255) UNIQUE NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    """


if __name__ == "__main__":
    migrate_down()
