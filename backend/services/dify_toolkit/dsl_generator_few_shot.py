"""Few-shot examples fed to MiniMax so it learns the JSON shape each template
expects. These are *system-prompt-friendly* — each is a pair of (user, assistant)
messages, where the assistant message is a JSON object that matches the
template's `params_schema`.

We deliberately keep examples short and varied so MiniMax learns the shape
without overfitting to phrasing. Updating a template's `params_schema`? Update
its few-shot example here too.
"""

from __future__ import annotations

from typing import Any

BASIC_CHAT_FEW_SHOT: list[dict[str, str]] = [
    {
        "role": "user",
        "content": (
            "Build a basic chat agent for a small e-commerce store's customer "
            "service. The agent should answer return-policy questions in a "
            "friendly tone."
        ),
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "system_prompt": "你是电商客服, 负责回答用户关于退货政策的疑问。'
            '回答时保持友好、简洁, 不要编造政策。",\n'
            '  "user_prompt_template": "{{#sys.query#}}",\n'
            '  "model_name": "gpt-4o-mini",\n'
            '  "temperature": 0.7\n'
            "}"
        ),
    },
]

RAG_QA_FEW_SHOT: list[dict[str, str]] = [
    {
        "role": "user",
        "content": (
            "I need a knowledge-QA agent that answers employee questions about "
            "the company handbook. Use knowledge base id kb-handbook-2024. "
            "Top 5 retrieval. Conservative temperature."
        ),
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "system_prompt": "你是企业 HR 助手。请仅基于检索到的公司手册内容回答, '
            '如果检索不到就说不知道, 不要编造。",\n'
            '  "knowledge_base_ids": ["kb-handbook-2024"],\n'
            '  "top_k": 5,\n'
            '  "model_name": "gpt-4o-mini",\n'
            '  "temperature": 0.3\n'
            "}"
        ),
    },
]

CONDITIONAL_ROUTER_FEW_SHOT: list[dict[str, str]] = [
    {
        "role": "user",
        "content": (
            "Build a routing agent for a SaaS support bot. If the user asks about "
            "pricing, send them to the sales pitch LLM. Otherwise, send to the "
            "general support LLM. The price-trigger keyword is '价格'."
        ),
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "condition_variable": "sys.query",\n'
            '  "condition_operator": "contains",\n'
            '  "condition_value": "价格",\n'
            '  "true_prompt": "你是销售助手, 介绍产品的价格优势和性价比。",\n'
            '  "false_prompt": "你是技术支持助手, 回答用户的产品使用问题。",\n'
            '  "model_name": "gpt-4o-mini"\n'
            "}"
        ),
    },
]

TOOL_CALLING_FEW_SHOT: list[dict[str, str]] = [
    {
        "role": "user",
        "content": (
            "Build a weather assistant. It can call two tools: get_current_weather "
            "and get_forecast. Decide when to call each."
        ),
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "system_prompt": "你是天气助手。根据用户问题选择调用 '
            'get_current_weather (当前天气) 或 get_forecast (未来预报) 工具。",\n'
            '  "tool_ids": ["get_current_weather", "get_forecast"],\n'
            '  "model_name": "gpt-4o-mini",\n'
            '  "temperature": 0.3\n'
            "}"
        ),
    },
]


# Map keyed by template id — DSLGenerator looks these up by template.id.
FEW_SHOT_BY_TEMPLATE_ID: dict[str, list[dict[str, str]]] = {
    "basic_chat": BASIC_CHAT_FEW_SHOT,
    "rag_qa": RAG_QA_FEW_SHOT,
    "conditional_router": CONDITIONAL_ROUTER_FEW_SHOT,
    "tool_calling": TOOL_CALLING_FEW_SHOT,
}


def get_few_shot(template_id: str) -> list[dict[str, str]]:
    """Return the few-shot examples for `template_id`, or an empty list if unknown."""
    return FEW_SHOT_BY_TEMPLATE_ID.get(template_id, [])


__all__ = [
    "BASIC_CHAT_FEW_SHOT",
    "CONDITIONAL_ROUTER_FEW_SHOT",
    "FEW_SHOT_BY_TEMPLATE_ID",
    "RAG_QA_FEW_SHOT",
    "TOOL_CALLING_FEW_SHOT",
    "get_few_shot",
]