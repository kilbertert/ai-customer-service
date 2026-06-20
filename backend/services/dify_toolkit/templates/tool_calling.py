"""M12 PR-1 — tool_calling 模板 (Start → LLM(tools=[...]) → End)。

LLM 节点带工具调用能力, 由 LLM 决定何时调哪个工具。
注: Dify 1.14.2 的 LLM 节点用 `tools` 数组声明可用工具(每项含 provider_id/tool_name/tool_parameters)。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from services.dify_toolkit.builder import (
    EndNode,
    LLMNode,
    StartNode,
    Variable,
    Workflow,
)


class ToolCallingParams(BaseModel):
    """工具调用模板的 4 个核心字段。"""

    system_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="LLM system prompt, 应告知模型可用工具 + 何时调用",
    )
    tool_ids: list[str] = Field(
        ...,
        min_length=1,
        description="可用工具 ID 列表(必填, LLM 不得编造)",
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        description="LLM 模型名",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="LLM 温度, 工具调用推荐 0.3 (低温度更稳)",
    )


def _build(params: ToolCallingParams) -> Workflow:
    wf = Workflow(name="tool_calling", description="工具调用工作流")
    wf.add(StartNode(variables=[Variable(
        variable="sys.query",
        label="user_input",
        type="paragraph",
        max_length=10000,
        required=True,
    )]))
    # LLM 节点的 tools 数组: 每项 {provider_id, tool_name, enabled=true, params={}}
    tools_config: list[dict[str, Any]] = [
        {
            "provider_id": tool_id,
            "tool_name": tool_id,
            "enabled": True,
            "params": {},
        }
        for tool_id in params.tool_ids
    ]
    wf.add(LLMNode(
        id="4080",
        title="Tool-Calling LLM",
        system_prompt=params.system_prompt,
        user_prompt="{{#sys.query#}}",
        model_name=params.model_name,
        temperature=params.temperature,
    ))
    # 把 tools 数组注入 LLMNode 的 to_data 输出
    # 已知 builder.LLMNode.to_data() 不含 tools 字段, 需要后处理
    wf.get("4080").to_data = lambda: {  # type: ignore[method-assign]
        "model": {
            "provider": "langgenius/openai/openai",
            "name": params.model_name,
            "mode": "chat",
            "completion_params": {"temperature": params.temperature, "max_tokens": 2048},
        },
        "prompt_template": [
            {"role": "system", "text": params.system_prompt},
            {"role": "user", "text": "{{#sys.query#}}"},
        ],
        "context": {"enabled": False, "variable_selector": []},
        "vision": {"enabled": False},
        "tools": tools_config,
    }
    wf.add(EndNode(outputs=[
        {"variable": "output", "value_selector": ["4080", "text"]},
    ]))
    wf.connect("4001", "4080")
    wf.connect("4080", "4099")
    return wf


TOOL_CALLING_TEMPLATE = {
    "id": "tool_calling",
    "name": "工具调用",
    "description": "LLM 带工具调用能力, 由模型决定何时调哪个外部工具",
    "category": "tool",
    "min_dify_version": "1.14.0",
    "params_schema": ToolCallingParams,
    "to_workflow": _build,
    "test_cases": [
        {"input": "查询上海天气", "expect_contains": "天气"},
    ],
    "yml_preview": "Start → LLM(tools=[...]) → End",
}
