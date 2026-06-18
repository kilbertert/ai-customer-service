"""Dify workflow 表 schema 探针常量 (D10 决策 — P0-C §3)。

钉死 Dify 端 ``workflows`` 表的列 + 类型,deploy 路径在写前 probe,不匹配 → 5xx
报错 (阻止升级 1.15+ 静默 break)。
"""

from __future__ import annotations

# Required columns on Dify's ``workflows`` table. Order matters for diff readability.
# Source: Dify 1.14.2 api/models/workflow.py + alembic migration 5.2.x.
# - id:         uuid PK
# - app_id:     uuid FK → apps.id (1 agent = 1 workflow)
# - version:    text (e.g. "draft" or "2024-05-22T...") — pinned as text so v1.15
#               flipping to UUID-text doesn't break (D10 决策)
# - graph:      jsonb (the DSL payload that ``UPDATE`` writes to)
# - updated_at: timestamp (Dify app reload watches this)
# - tenant_id:  text (Dify 1.x multi-tenant support; nullable for backward compat
#               with pre-1.10 single-tenant rows)
DIFY_WORKFLOWS_REQUIRED_COLUMNS: dict[str, str] = {
    "id": "uuid",
    "app_id": "uuid",
    "version": "text",
    "graph": "jsonb",
    "updated_at": "timestamp",
    "tenant_id": "text",
}


# Dify API base path constants — referenced by verifier + cli
DIFY_CHAT_MESSAGES_PATH: str = "/v1/chat-messages"
DIFY_WORKFLOWS_RUN_PATH: str = "/v1/workflows/run"


# Default LLM provider for built-in LLMNode examples.
DEFAULT_LLM_PROVIDER: str = "langgenius/doubao/doubao-seed-2-0-lite"
DEFAULT_LLM_NAME: str = "doubao-seed-2-0-lite"
