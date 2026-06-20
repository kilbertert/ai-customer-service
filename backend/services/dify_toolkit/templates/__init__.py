"""M12 PR-1 — 4 个 MVP 工作流模板注册表。

TEMPLATES: 列表, 提供给 API/前端遍历
TEMPLATES_BY_ID: dict, 供 PR-2 DSLGenerator 按 id 查找
"""

from __future__ import annotations

from ._common import Template
from .basic_chat import BASIC_CHAT_TEMPLATE
from .conditional_router import CONDITIONAL_ROUTER_TEMPLATE
from .rag_qa import RAG_QA_TEMPLATE
from .tool_calling import TOOL_CALLING_TEMPLATE

__all__ = [
    "Template",
    "TEMPLATES",
    "TEMPLATES_BY_ID",
]


def _to_template(d: dict) -> Template:
    return Template(
        id=d["id"],
        name=d["name"],
        description=d["description"],
        category=d["category"],
        min_dify_version=d["min_dify_version"],
        params_schema=d["params_schema"],
        to_workflow=d["to_workflow"],
        test_cases=d.get("test_cases", []),
        yml_preview=d.get("yml_preview", ""),
    )


TEMPLATES: list[Template] = [
    _to_template(BASIC_CHAT_TEMPLATE),
    _to_template(RAG_QA_TEMPLATE),
    _to_template(CONDITIONAL_ROUTER_TEMPLATE),
    _to_template(TOOL_CALLING_TEMPLATE),
]

TEMPLATES_BY_ID: dict[str, Template] = {t.id: t for t in TEMPLATES}
