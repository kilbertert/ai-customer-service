"""M12 PR-1 — basic_chat 模板 (Start → LLM → End)。

最简的对话流程,作为其他模板的基础。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.dify_toolkit.builder import (
    EndNode,
    LLMNode,
    StartNode,
    Variable,
    Workflow,
)


class BasicChatParams(BaseModel):
    """LLM 填参 schema — 单 LLM 节点的 4 个核心字段。"""

    system_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="LLM system prompt, 例如: '你是一个电商客服, 回答用户退货问题'",
    )
    user_prompt_template: str = Field(
        default="{{#sys.query#}}",
        description="user message 模板, 默认透传 Start 输入",
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        description="模型名, 走 basjoo 已知 model 列表",
    )
    temperature: float = Field(
        default=0.7,
        ge=0.0,
        le=2.0,
        description="LLM 温度",
    )


def _build(params: BasicChatParams) -> Workflow:
    wf = Workflow(name="basic_chat", description="基础对话工作流")
    wf.add(StartNode(variables=[Variable(
        variable="sys.query",
        label="user_input",
        type="paragraph",
        max_length=10000,
        required=True,
    )]))
    wf.add(LLMNode(
        id="4080",
        title="Generate Response",
        system_prompt=params.system_prompt,
        user_prompt=params.user_prompt_template,
        model_name=params.model_name,
        temperature=params.temperature,
    ))
    wf.add(EndNode(outputs=[
        {"variable": "output", "value_selector": ["4080", "text"]},
    ]))
    wf.connect("4001", "4080")
    wf.connect("4080", "4099")
    return wf


BASIC_CHAT_TEMPLATE = {
    "id": "basic_chat",
    "name": "基础对话",
    "description": "单 LLM 节点的简单对话, 适合通用客服 / 问答 / 内容生成",
    "category": "chat",
    "min_dify_version": "1.14.0",
    "params_schema": BasicChatParams,
    "to_workflow": _build,
    "test_cases": [
        {"input": "你好", "expect_contains": "你好"},
    ],
    "yml_preview": "Start → LLM(system_prompt, user_prompt) → End",
}
