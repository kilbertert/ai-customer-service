"""Shared, idempotent SQLite startup migration module.

Called by both ``database.py:init_db()`` and ``docker-entrypoint.py:migrate_sqlite_schema()``
so that the same set of columns / indexes / backfills is applied regardless of
startup path and the two lists can never drift apart.

Uses only the standard library so it can be imported before SQLAlchemy models
are fully loaded.
"""

import os
import sqlite3

# ---- URL parsing ------------------------------------------------------------


def _sqlite_db_path(database_url: str) -> str | None:
    """Extract the filesystem path from a SQLite database URL."""
    raw = (database_url or "").strip()
    for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
        if raw.startswith(prefix):
            rest = raw[len(prefix) :]
            # Strip query strings like ?cache=shared
            path = rest.split("?", 1)[0]
            # Resolve relative paths against CWD
            if not path.startswith("/"):
                path = os.path.abspath(path)
            return path
    return None


# ---- schema migration -------------------------------------------------------


def _ensure_columns(
    cursor: sqlite3.Cursor,
    table: str,
    columns: list[tuple[str, str]],
) -> int:
    """Add any missing columns to *table* (idempotent).  Returns count of columns added."""
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    added = 0
    for col_name, col_type in columns:
        if col_name not in existing:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
            added += 1
    return added


_DEFAULT_SIMILARITY_THRESHOLD = 0.01


def run_sqlite_migrations(database_url: str) -> None:
    """Apply all pending SQLite migrations idempotently.

    If the database file does not exist yet this is a no-op — the tables have
    not been created and ``Base.metadata.create_all`` will create the full
    schema later.
    """
    db_path = _sqlite_db_path(database_url)
    if not db_path:
        return  # not SQLite

    if not os.path.exists(db_path):
        return  # fresh deployment, schema will be created by create_all

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # ── agents ────────────────────────────────────────────────────────
        if _table_exists(cursor, "agents"):
            _migrate_agents(cursor)

            # Dedicated per-column backfills (after all columns definitely exist)
            _backfill_agents(cursor)

        # ── agent_members ─────────────────────────────────────────────────
        if _table_exists(cursor, "agents") and _table_exists(cursor, "admin_users"):
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_members (
                    id INTEGER PRIMARY KEY,
                    agent_id VARCHAR(50) NOT NULL,
                    admin_user_id INTEGER NOT NULL,
                    role VARCHAR(50) NOT NULL DEFAULT 'admin',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(agent_id) REFERENCES agents(id),
                    FOREIGN KEY(admin_user_id) REFERENCES admin_users(id),
                    UNIQUE(agent_id, admin_user_id)
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_agent_members_agent_id ON agent_members(agent_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_agent_members_admin_user_id ON agent_members(admin_user_id)"
            )
            # Note: we no longer auto-insert AgentMember for super_admins on all agents
            # Super admins now use workspace-based auth (agent.workspace_id == admin.workspace_id)
            # This avoids cross-workspace membership that would bypass workspace isolation

        # ── chat_sessions ──────────────────────────────────────────────────
        if _table_exists(cursor, "chat_sessions"):
            _ensure_columns(
                cursor,
                "chat_sessions",
                [
                    ("visitor_ip", "TEXT"),
                    ("visitor_user_agent", "TEXT"),
                    ("visitor_country", "TEXT"),
                    ("visitor_region", "TEXT"),
                    ("visitor_city", "TEXT"),
                ],
            )

        # ── chat_messages ──────────────────────────────────────────────────
        if _table_exists(cursor, "chat_messages"):
            _ensure_columns(
                cursor,
                "chat_messages",
                [
                    ("sender_type", "TEXT"),
                    ("sender_id", "TEXT"),
                ],
            )

        # ── url_sources ───────────────────────────────────────────────────
        if _table_exists(cursor, "url_sources"):
            _ensure_columns(
                cursor,
                "url_sources",
                [
                    ("r2r_document_id", "VARCHAR(100)"),
                ],
            )

        # ── uq_chat_sessions_active_session unique index ───────────────────
        if _table_exists(cursor, "chat_sessions"):
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='uq_chat_sessions_active_session'"
            )
            if not cursor.fetchone():
                cursor.execute(
                    """
                    DELETE FROM chat_sessions
                    WHERE status != 'closed'
                      AND id NOT IN (
                        SELECT id FROM (
                            SELECT MAX(id) AS id
                            FROM chat_sessions
                            WHERE status != 'closed'
                            GROUP BY agent_id, session_id
                        )
                    )
                    """
                )
                cursor.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_chat_sessions_active_session "
                    "ON chat_sessions (agent_id, session_id) "
                    "WHERE status != 'closed'"
                )

        # ── workspace_quotas backfill ──────────────────────────────────────
        if _table_exists(cursor, "workspace_quotas"):
            cursor.execute(
                "UPDATE workspace_quotas SET max_agents = 10 WHERE max_agents IS NULL OR max_agents < 10"
            )
            if cursor.rowcount > 0:
                print(
                    f"✓ Backfilled workspace_quotas.max_agents for "
                    f"{cursor.rowcount} row(s)"
                )
            cursor.execute(
                "UPDATE workspace_quotas SET max_urls = 500 WHERE max_urls = 50"
            )
            if cursor.rowcount > 0:
                print(
                    f"✓ Backfilled workspace_quotas.max_urls for "
                    f"{cursor.rowcount} row(s)"
                )
            # multimodal chat (PR13) — column reserved; daily MB cap NOT
            # enforced in PR13 (follow-up).
            _ensure_columns(
                cursor,
                "workspace_quotas",
                [
                    ("max_attachment_mb_per_day", "INTEGER DEFAULT 50"),
                    ("used_attachment_mb_today", "FLOAT DEFAULT 0.0"),
                ],
            )

        # ── message_attachments (PR13) ──────────────────────────────────────
        # NOTE: PR13 实际产线 schema 跟旧版 CREATE TABLE IF NOT EXISTS 不一致:
        # 新增 storage_backend / ocr_text / modality_meta 三列,删了 session_id。
        # 表已存在时 IF NOT EXISTS 不会重写,旧版的"session_id" 索引在缺列
        # 的表上会炸("no such column: session_id")。修法是先建表(不补列),
        # 索引逐个检查列存在再建,缺列就跳过。
        if _table_exists(cursor, "agents"):
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS message_attachments (
                    id VARCHAR(50) PRIMARY KEY,
                    message_id INTEGER,
                    agent_id VARCHAR(50) NOT NULL,
                    kind VARCHAR(5) NOT NULL,
                    mime_type VARCHAR(120) NOT NULL,
                    filename VARCHAR(500),
                    size_bytes INTEGER,
                    storage_backend VARCHAR(20) NOT NULL DEFAULT 'local',
                    storage_key VARCHAR(500) NOT NULL,
                    sha256 VARCHAR(64) NOT NULL,
                    transcript TEXT,
                    ocr_text TEXT,
                    modality_meta JSON,
                    status VARCHAR(10) NOT NULL DEFAULT 'pending',
                    error_message TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME
                )
                """
            )

        if _table_exists(cursor, "message_attachments"):
            for index_col, index_name in (
                ("message_id", "ix_message_attachments_message_id"),
                ("agent_id", "ix_message_attachments_agent_id"),
            ):
                cursor.execute(
                    f"SELECT 1 FROM pragma_table_info('message_attachments') "
                    f"WHERE name = ?",
                    (index_col,),
                )
                if cursor.fetchone():
                    cursor.execute(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON message_attachments({index_col})"
                    )
                # 列不存在(更老/更新的 schema)就跳过,等真用上再加
            # session_id 索引单独看 —— 旧 schema 有,新 PR13 schema 删了。
            cursor.execute(
                "SELECT 1 FROM pragma_table_info('message_attachments') "
                "WHERE name = 'session_id'"
            )
            if cursor.fetchone():
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS ix_message_attachments_session_id "
                    "ON message_attachments(session_id)"
                )
            else:
                # PR13 起 session_id 不再在 message_attachments 上,索引跳过。
                # 若 session_id 真要索引化(在 chat_sessions / chat_messages
                # 上),在对应的 PR migration 里再加。
                pass

            # 其它索引:逐列检查 —— 老 / 新 schema 列不一样,缺列就跳过
            # (CREATE INDEX 缺列会 "no such column",跟 PR13 一样的根因)。
            for index_name, index_cols in (
                ("ix_message_attachments_sha256", ("sha256",)),
                ("ix_message_attachments_status", ("status",)),
            ):
                if all(
                    cursor.execute(
                        "SELECT 1 FROM pragma_table_info('message_attachments') "
                        "WHERE name = ?",
                        (col,),
                    ).fetchone()
                    for col in index_cols
                ):
                    cols_csv = ", ".join(index_cols)
                    cursor.execute(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON message_attachments({cols_csv})"
                    )

            # session_id + kind 复合索引:需要 session_id 列;新 PR13 schema
            # 没这列就跳过。
            cursor.execute(
                "SELECT 1 FROM pragma_table_info('message_attachments') "
                "WHERE name IN ('session_id', 'kind')"
            )
            if {row[0] for row in cursor.fetchall()} == {"session_id", "kind"}:
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS ix_msg_attach_session_kind "
                    "ON message_attachments(session_id, kind)"
                )

        # ── admin_users role migration ─────────────────────────────────────
        if _table_exists(cursor, "admin_users"):
            _ensure_columns(
                cursor,
                "admin_users",
                [("role", "VARCHAR(50) NOT NULL DEFAULT 'admin'")],
            )
            cursor.execute(
                "UPDATE admin_users SET role = 'support' WHERE role = 'readonly'"
            )
            if cursor.rowcount > 0:
                print(
                    f"✓ Migrated {cursor.rowcount} admin_user(s) from readonly to support"
                )

        # ── admin_users workspace_id migration ──────────────────────────────
        if _table_exists(cursor, "admin_users") and _table_exists(cursor, "workspaces"):
            _ensure_columns(
                cursor,
                "admin_users",
                [("workspace_id", "INTEGER REFERENCES workspaces(id)")],
            )
            # Create index if not exists
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS ix_admin_users_workspace_id ON admin_users(workspace_id)"
            )

            # Ensure at least one workspace exists
            cursor.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1")
            row = cursor.fetchone()
            if row:
                canonical_workspace_id = row[0]
            else:
                # Create default workspace if none exists
                cursor.execute(
                    "INSERT INTO workspaces (name, owner_email, created_at) VALUES ('Default Workspace', 'admin@basjoo.local', CURRENT_TIMESTAMP)"
                )
                canonical_workspace_id = cursor.lastrowid
                print(f"✓ Created default workspace with id={canonical_workspace_id}")

                # Ensure quota for this workspace
                if _table_exists(cursor, "workspace_quotas"):
                    cursor.execute(
                        "INSERT OR IGNORE INTO workspace_quotas (workspace_id, max_agents, max_urls, max_qa_items, max_messages_per_day, max_total_text_mb) VALUES (?, 10, 500, 100, 1500, 20)",
                        (canonical_workspace_id,),
                    )
                    if cursor.rowcount > 0:
                        print(
                            f"✓ Created workspace_quotas for workspace {canonical_workspace_id}"
                        )

            # Backfill null workspace_id for ALL admin users (super_admin, admin, support)
            # Legacy installs had no workspace_id column; all users need to be assigned to canonical workspace
            cursor.execute(
                "UPDATE admin_users SET workspace_id = ? WHERE workspace_id IS NULL",
                (canonical_workspace_id,),
            )
            admin_backfill_count = cursor.rowcount
            if admin_backfill_count > 0:
                print(
                    f"✓ Backfilled workspace_id for {admin_backfill_count} admin user(s)"
                )

            # Clean up old cross-workspace AgentMember records BEFORE consolidating agents
            # (agents still have their original workspace assignments at this point)
            # Old code did CROSS JOIN for super_admin × all agents, which now violates workspace isolation
            # Only delete super_admin memberships - admin/support assignments should be preserved
            if _table_exists(cursor, "agent_members") and _table_exists(
                cursor, "agents"
            ):
                # Delete AgentMember rows for super_admin where workspace mismatch
                # These were created by legacy CROSS JOIN and would bypass workspace isolation after role downgrade
                cursor.execute(
                    """
                    DELETE FROM agent_members
                    WHERE id IN (
                        SELECT am.id
                        FROM agent_members am
                        JOIN admin_users au ON am.admin_user_id = au.id
                        JOIN agents a ON am.agent_id = a.id
                        WHERE au.role = 'super_admin'
                          AND au.workspace_id IS NOT NULL
                          AND a.workspace_id IS NOT NULL
                          AND au.workspace_id != a.workspace_id
                    )
                    """
                )
                cross_workspace_members_deleted = cursor.rowcount
                if cross_workspace_members_deleted > 0:
                    print(
                        f"✓ Cleaned up {cross_workspace_members_deleted} super_admin cross-workspace AgentMember record(s) from legacy install"
                    )

            # Agent workspace_id handling
            if _table_exists(cursor, "agents"):
                # Legacy installs (pre-workspace-scoped super_admin) had one workspace per agent.
                # If we just backfilled admin workspace_id, consolidate agents to canonical workspace.
                # Newer installs with existing workspace assignments are preserved.
                if admin_backfill_count > 0:
                    # This is likely a legacy install - consolidate all agents to canonical workspace
                    cursor.execute(
                        "UPDATE agents SET workspace_id = ?", (canonical_workspace_id,)
                    )
                    if cursor.rowcount > 0:
                        print(
                            f"✓ Consolidated {cursor.rowcount} agent(s) to workspace {canonical_workspace_id} (legacy install migration)"
                        )
                else:
                    # Newer install - only backfill NULL workspace_ids, preserve existing assignments
                    cursor.execute(
                        "UPDATE agents SET workspace_id = ? WHERE workspace_id IS NULL",
                        (canonical_workspace_id,),
                    )
                    if cursor.rowcount > 0:
                        print(
                            f"✓ Backfilled workspace_id for {cursor.rowcount} agent(s) with NULL workspace_id"
                        )

        # ── M10 G2: Tenant ↔ Workspace 1:1 ──────────────────────────────────
        if _table_exists(cursor, "tenants"):
            _migrate_workspace_tenant_1to1(cursor)

        # ── M10 G3: Dify 集成层 4+4 字段 ────────────────────────────────────
        if _table_exists(cursor, "workspaces"):
            _migrate_workspaces_dify_fields(cursor)
        # agents 4 字段:加在 _migrate_agents 列表尾部,见下方

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---- helpers ----------------------------------------------------------------


def _table_exists(cursor: sqlite3.Cursor, table: str) -> bool:
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


# ---- agents migration -------------------------------------------------------


def _migrate_agents(cursor: sqlite3.Cursor):
    """Add any missing columns to the ``agents`` table.

    The column list mirrors the current ``models.py:Agent`` definition and must
    be kept in sync when the model gains new fields.
    """
    columns: list[tuple[str, str]] = [
        # LLM / provider
        ("agent_type", "VARCHAR(50) DEFAULT 'website_support'"),
        ("channel_mode", "VARCHAR(50) DEFAULT 'web_widget'"),
        ("avatar", "VARCHAR(500)"),
        ("deleted_at", "DATETIME"),
        ("purge_after", "DATETIME"),
        ("provider_type", "VARCHAR(50)"),
        ("azure_endpoint", "VARCHAR(500)"),
        ("azure_deployment_name", "VARCHAR(100)"),
        ("azure_api_version", "VARCHAR(20)"),
        ("anthropic_version", "VARCHAR(20) DEFAULT '2023-06-01'"),
        ("google_project_id", "VARCHAR(100)"),
        ("google_region", "VARCHAR(50)"),
        ("provider_config", "TEXT"),
        # embedding
        ("siliconflow_api_key", "VARCHAR(500) DEFAULT ''"),
        # multimodal chat (PR13) — image captioning + voice transcription
        ("vision_api_key", "VARCHAR(500) DEFAULT ''"),
        ("vision_base_url", "VARCHAR(500) DEFAULT 'https://api.openai.com/v1'"),
        ("vision_provider_type", "VARCHAR(20) DEFAULT 'openai'"),
        ("vision_model", "VARCHAR(100) DEFAULT 'gpt-4o'"),
        ("whisper_api_key", "VARCHAR(500) DEFAULT ''"),
        ("whisper_base_url", "VARCHAR(500) DEFAULT 'https://api.openai.com/v1'"),
        ("whisper_model", "VARCHAR(100) DEFAULT 'whisper-1'"),
        ("embedding_provider", "VARCHAR(20)"),
        ("embedding_api_base", "VARCHAR(500)"),
        ("embedding_model", "VARCHAR(100) DEFAULT 'jina-embeddings-v3'"),
        ("embedding_batch_size", "INTEGER DEFAULT 4"),
        # kb setup state
        ("kb_setup_completed", "BOOLEAN DEFAULT 0"),
        ("kb_id", "VARCHAR(36)"),
        # crawl / retrieval
        ("crawl_max_depth", "INTEGER DEFAULT 2"),
        ("crawl_max_pages", "INTEGER DEFAULT 500"),
        ("url_fetch_interval_days", "INTEGER DEFAULT 7"),
        ("enable_auto_fetch", "BOOLEAN DEFAULT 0"),
        ("top_k", "INTEGER DEFAULT 5"),
        ("similarity_threshold", f"FLOAT DEFAULT {_DEFAULT_SIMILARITY_THRESHOLD}"),
        ("enable_context", "BOOLEAN DEFAULT 0"),
        # rate-limit / error / widget
        ("restricted_reply", "TEXT DEFAULT '抱歉，当前服务受限，请稍后再试。'"),
        ("last_error_code", "VARCHAR(50)"),
        ("last_error_message", "TEXT"),
        ("last_error_at", "DATETIME"),
        ("allowed_widget_origins", "TEXT"),
        ("persona_type", "VARCHAR(20) DEFAULT 'general'"),
        ("widget_title", "VARCHAR(100) DEFAULT 'AI 客服'"),
        ("widget_color", "VARCHAR(20) DEFAULT '#06B6D4'"),
        (
            "welcome_message",
            "TEXT DEFAULT '您好！我是Basjoo助手，有什么可以帮您的吗？'",
        ),
        ("history_days", "INTEGER DEFAULT 30"),
        # M10 G3: Dify 集成层 per-agent 字段
        ("dify_workflow_id", "VARCHAR(64)"),
        ("dify_user_prefix", "VARCHAR(20) DEFAULT 'agent-'"),
        ("dify_inputs_schema", "TEXT"),
        ("dify_end_user_strategy", "VARCHAR(20) DEFAULT 'dual_layer'"),
        # M10+1: Dify 集成层 4 新字段 (D7/D8/D9c)
        # D7 — workflow 是 App 下属资源, 多 1 个外键便于回查
        ("dify_app_id", "VARCHAR(64)"),
        # D8 — per-agent runtime API key, Fernet 加密存储 (解密切 core.encryption)
        ("dify_api_key", "TEXT"),
        # D9(c) — workflow publish 状态机, 默认 'draft' 覆盖既有行
        ("dify_publish_status", "VARCHAR(32) DEFAULT 'draft'"),
        ("dify_publish_error", "TEXT"),
    ]

    # Handle the old column-name migration before we report existing columns
    cursor.execute("PRAGMA table_info(agents)")
    existing = {row[1] for row in cursor.fetchall()}

    if "rate_limit_per_hour" in existing and "rate_limit_per_minute" not in existing:
        cursor.execute(
            "ALTER TABLE agents RENAME COLUMN rate_limit_per_hour TO rate_limit_per_minute"
        )
        print("✓ Renamed rate_limit_per_hour → rate_limit_per_minute")
        existing.discard("rate_limit_per_hour")
        existing.add("rate_limit_per_minute")

    # Also add rate_limit_per_minute if it's simply missing (not a rename scenario)
    if "rate_limit_per_minute" not in existing:
        columns.insert(0, ("rate_limit_per_minute", "INTEGER DEFAULT 20"))

    # Add any still-missing columns
    added = _ensure_columns(cursor, "agents", columns)
    if added:
        print(f"✓ Added {added} column(s) to agents")


def _backfill_agents(cursor: sqlite3.Cursor):
    """Backfill safe defaults for existing agent rows."""

    cursor.execute("PRAGMA table_info(agents)")
    col_names = {row[1] for row in cursor.fetchall()}

    # ── provider_type (must come first so embedding_provider can use it) ─────
    if "provider_type" in col_names:
        # First repair values that aren't in the current Literal set
        cursor.execute(
            "UPDATE agents SET provider_type = NULL "
            "WHERE provider_type IS NOT NULL "
            "AND provider_type NOT IN ('openai','openai_native','google','anthropic','xai','openrouter','zai','deepseek','volcengine','moonshot','aliyun_bailian','siliconflow')"
        )
        # Then infer from api_base/model for NULL/empty rows
        cursor.execute(
            "UPDATE agents SET provider_type = "
            "CASE "
            "  WHEN api_base LIKE '%deepseek%' OR model LIKE 'deepseek%' THEN 'deepseek'"
            "  WHEN api_base LIKE '%siliconflow%' THEN 'siliconflow'"
            "  WHEN api_base LIKE '%google%' OR api_base LIKE '%gemini%' THEN 'google'"
            "  WHEN api_base LIKE '%anthropic%' OR api_base LIKE '%claude%' THEN 'anthropic'"
            "  WHEN api_base LIKE '%x.ai%' OR api_base LIKE '%xai%' THEN 'xai'"
            "  WHEN api_base LIKE '%openai%' OR api_base LIKE '%azure%' THEN 'openai'"
            "  ELSE 'openai' END "
            "WHERE provider_type IS NULL OR provider_type = ''"
        )

    # ── embedding_provider (now provider_type is correct) ────────────────────
    if "embedding_provider" in col_names:
        # First repair non-standard values
        cursor.execute(
            "UPDATE agents SET embedding_provider = NULL "
            "WHERE embedding_provider NOT IN ('jina', 'siliconflow', 'custom')"
        )
        if "provider_type" in col_names:
            cursor.execute(
                "UPDATE agents SET embedding_provider = 'siliconflow' "
                "WHERE provider_type = 'siliconflow' "
                "AND (embedding_provider IS NULL OR embedding_provider = '')"
            )
        cursor.execute(
            "UPDATE agents SET embedding_provider = 'jina' "
            "WHERE embedding_provider IS NULL OR embedding_provider = ''"
        )

    # ── embedding_model ──────────────────────────────────────────────────────
    if "embedding_model" in col_names:
        cursor.execute(
            "UPDATE agents SET embedding_model = 'jina-embeddings-v3' "
            "WHERE embedding_model IS NULL OR embedding_model = ''"
        )

    # ── persona_type ─────────────────────────────────────────────────────────
    if "persona_type" in col_names:
        cursor.execute(
            "UPDATE agents SET persona_type = 'general' "
            "WHERE persona_type IS NULL OR persona_type = ''"
        )
    if "agent_type" in col_names:
        cursor.execute(
            "UPDATE agents SET agent_type = 'website_support' "
            "WHERE agent_type IS NULL OR agent_type = ''"
        )
    if "channel_mode" in col_names:
        cursor.execute(
            "UPDATE agents SET channel_mode = 'web_widget' "
            "WHERE channel_mode IS NULL OR channel_mode = ''"
        )

    # ── top_k ────────────────────────────────────────────────────────────────
    if "top_k" in col_names:
        cursor.execute("UPDATE agents SET top_k = 5 WHERE top_k IS NULL")

    # ── similarity_threshold ─────────────────────────────────────────────────
    if "similarity_threshold" in col_names:
        # R2R uses RRF scores (≈0.01–0.05); old default 0.3 filters everything
        cursor.execute(
            "UPDATE agents SET similarity_threshold = ? "
            "WHERE similarity_threshold IS NULL OR similarity_threshold = 0.3",
            (_DEFAULT_SIMILARITY_THRESHOLD,),
        )

    # ── rate_limit_per_minute ────────────────────────────────────────────────
    if "rate_limit_per_minute" in col_names:
        cursor.execute(
            "UPDATE agents SET rate_limit_per_minute = 20 "
            "WHERE rate_limit_per_minute IS NULL"
        )

    # ── history_days ─────────────────────────────────────────────────────────
    if "history_days" in col_names:
        cursor.execute("UPDATE agents SET history_days = 30 WHERE history_days IS NULL")

    # ── boolean flags that should default to false ───────────────────────────
    for flag_col in ("enable_auto_fetch", "enable_context"):
        if flag_col in col_names:
            cursor.execute(f"UPDATE agents SET {flag_col} = 0 WHERE {flag_col} IS NULL")

    # ── crawl defaults ───────────────────────────────────────────────────────
    if "crawl_max_depth" in col_names:
        cursor.execute(
            "UPDATE agents SET crawl_max_depth = 2 WHERE crawl_max_depth IS NULL"
        )
    if "crawl_max_pages" in col_names:
        cursor.execute(
            "UPDATE agents SET crawl_max_pages = 500 WHERE crawl_max_pages IS NULL"
        )
    if "url_fetch_interval_days" in col_names:
        cursor.execute(
            "UPDATE agents SET url_fetch_interval_days = 7 "
            "WHERE url_fetch_interval_days IS NULL"
        )

    # ── widget defaults ──────────────────────────────────────────────────────
    if "widget_title" in col_names:
        cursor.execute(
            "UPDATE agents SET widget_title = 'AI 客服' "
            "WHERE widget_title IS NULL OR widget_title = ''"
        )
    if "widget_color" in col_names:
        cursor.execute(
            "UPDATE agents SET widget_color = '#06B6D4' "
            "WHERE widget_color IS NULL OR widget_color = ''"
        )
    if "welcome_message" in col_names:
        cursor.execute(
            "UPDATE agents SET welcome_message = '您好！我是Basjoo助手，有什么可以帮您的吗？' "
            "WHERE welcome_message IS NULL OR welcome_message = ''"
        )

    restricted_reply_default = "抱歉，当前服务受限，请稍后再试。"
    if "restricted_reply" in col_names:
        cursor.execute(
            "UPDATE agents SET restricted_reply = ? "
            "WHERE restricted_reply IS NULL OR restricted_reply = ''",
            (restricted_reply_default,),
        )


# ---- M10 G2: Tenant ↔ Workspace 1:1 -----------------------------------------


def _migrate_workspace_tenant_1to1(cursor: sqlite3.Cursor) -> None:
    """M10 G2 — Tenant ↔ Workspace 1:1 constraint + KnowledgeBase.workspace_id.

    Idempotent. Safe to run multiple times. See:
      china_charge_kf/M10-PROMPT.md §3.3
      docs/dify-integration-plan.md §4 (M10 changelog)

    Steps:
      1. Add nullable workspace_id to tenants and knowledge_bases.
      2. Backfill tenants.workspace_id from slug (slug LIKE 'agent-%' → agent).
      3. Dedupe tenants per workspace (keep MIN(id), reassign KBs, delete rest).
      4. Resolve orphan tenants (workspace_id still NULL) → canonical workspace.
      5. Backfill knowledge_bases.workspace_id from their tenant.
      6. Create UNIQUE INDEX ix_tenants_workspace_id (1:1 enforcement at DB).
      7. Create INDEX ix_knowledge_bases_workspace_id.

    NOT NULL constraint is enforced at the model layer (SQLAlchemy
    ``nullable=False``); SQLite ``ALTER COLUMN NOT NULL`` would require a full
    table rebuild, which we skip to keep this migration cheap. New writes go
    through the ORM and are checked there.
    """
    if not (
        _table_exists(cursor, "tenants")
        and _table_exists(cursor, "workspaces")
    ):
        return

    # Step 1: add columns (idempotent via PRAGMA table_info check).
    _ensure_columns(
        cursor,
        "tenants",
        [("workspace_id", "INTEGER REFERENCES workspaces(id) ON DELETE CASCADE")],
    )
    _ensure_columns(
        cursor,
        "knowledge_bases",
        [("workspace_id", "INTEGER REFERENCES workspaces(id) ON DELETE CASCADE")],
    )

    # Step 2: backfill tenants.workspace_id from slug.
    # Slug pattern: f"agent-{agent_id[:8]}" where agent_id = "agt_<12 hex>".
    # substr(slug, 7) is the 8-char prefix of agent_id; LIKE-match agents.id.
    if _table_exists(cursor, "agents"):
        cursor.execute(
            """
            UPDATE tenants
            SET workspace_id = (
                SELECT workspace_id FROM agents
                WHERE agents.id LIKE substr(tenants.slug, 7) || '%'
                LIMIT 1
            )
            WHERE workspace_id IS NULL AND slug LIKE 'agent-%'
            """
        )

    # Step 3: dedupe tenants per workspace. Keep oldest (MIN(id)), reassign
    # KnowledgeBase.tenant_id to the kept tenant, delete the rest.
    cursor.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS _m10_kept_tenants AS
        SELECT workspace_id, MIN(id) AS kept_id, COUNT(*) AS dup_count
        FROM tenants
        WHERE workspace_id IS NOT NULL
        GROUP BY workspace_id
        HAVING COUNT(*) > 1
        """
    )
    cursor.execute(
        """
        UPDATE knowledge_bases
        SET tenant_id = (
            SELECT k.kept_id FROM _m10_kept_tenants k
            WHERE k.workspace_id = knowledge_bases.workspace_id
        )
        WHERE tenant_id IN (
            SELECT t.id FROM tenants t
            JOIN _m10_kept_tenants k ON t.workspace_id = k.workspace_id
            WHERE t.id != k.kept_id
        )
        """
    )
    cursor.execute(
        """
        DELETE FROM tenants
        WHERE id IN (
            SELECT t.id FROM tenants t
            JOIN _m10_kept_tenants k ON t.workspace_id = k.workspace_id
            WHERE t.id != k.kept_id
        )
        """
    )
    cursor.execute("DROP TABLE IF EXISTS _m10_kept_tenants")

    # Step 4: resolve orphan tenants (workspace_id still NULL).
    # Match the admin_users pattern: pick MIN(id) as canonical.
    cursor.execute("SELECT id FROM workspaces ORDER BY id LIMIT 1")
    canonical = cursor.fetchone()
    if canonical:
        canonical_ws_id = canonical[0]
        cursor.execute(
            "UPDATE tenants SET workspace_id = ? WHERE workspace_id IS NULL",
            (canonical_ws_id,),
        )

    # Step 5: backfill knowledge_bases.workspace_id from their (now-resolved)
    # tenant. Handle orphan KBs (tenant_id NULL or unresolved) afterwards.
    cursor.execute(
        """
        UPDATE knowledge_bases
        SET workspace_id = (
            SELECT workspace_id FROM tenants
            WHERE tenants.id = knowledge_bases.tenant_id
        )
        WHERE workspace_id IS NULL AND tenant_id IS NOT NULL
        """
    )
    if canonical:
        cursor.execute(
            "UPDATE knowledge_bases SET workspace_id = ? WHERE workspace_id IS NULL",
            (canonical_ws_id,),
        )

    # Step 6 + 7: create indexes (idempotent via IF NOT EXISTS).
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_tenants_workspace_id "
        "ON tenants(workspace_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS ix_knowledge_bases_workspace_id "
        "ON knowledge_bases(workspace_id)"
    )


# ---- M10 G3: Dify 集成层 4+4 字段 ------------------------------------------


def _migrate_workspaces_dify_fields(cursor: sqlite3.Cursor) -> None:
    """M10 G3 — Workspace 表加 4 个 Dify 集成字段。

    Idempotent. Safe to run multiple times. See:
      china_charge_kf/M10-PROMPT.md §4
      docs/dify-integration-plan.md §4 (M10 changelog)

    字段语义:
    - dify_api_base: Dify API endpoint (NULL = 走系统默认;非空 = 本 workspace 覆盖)
    - dify_api_key: Fernet 加密存储(M10 §4.3 锁)
      - 加密入口:core.encryption.encrypt_api_key()
      - 解密入口:core.encryption.decrypt_api_key()
      - 解密失败兜底:返回 None(操作员需检查 ENCRYPTION_KEY 轮转)
    - dify_workspace_id: Dify 端 workspace UUID
    - dify_enabled: 总开关(False = 走 OpenAI 直连,True = 走 Dify Workflow)

    Plan A / Plan B 自动判定(runtime):
    - dify_api_key IS NULL → Plan B (共享 Dify workspace + 全局 API key)
    - dify_api_key IS NOT NULL → Plan A (本 workspace 独占 Dify workspace)
    """
    _ensure_columns(
        cursor,
        "workspaces",
        [
            ("dify_api_base", "VARCHAR(255)"),
            ("dify_api_key", "TEXT"),
            ("dify_workspace_id", "VARCHAR(64)"),
            ("dify_enabled", "BOOLEAN DEFAULT 0"),
        ],
    )
