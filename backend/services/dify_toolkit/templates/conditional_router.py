"""M12 PR-1 — conditional_router 模板。

Start → IF-ELSE → [True: LLM-A, False: LLM-B] → Variable Aggregator → End

条件路由: 根据用户 query 类型选择不同 LLM 节点处理。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.dify_toolkit.builder import (
    EndNode,
    IfElseNode,
    LLMNode,
    StartNode,
    Variable,
    VariableAggregatorNode,
    Workflow,
)


class ConditionalRouterParams(BaseModel):
    """条件路由模板的 6 个核心字段。"""

    condition_variable: str = Field(
        default="sys.query",
        description="条件判断的源变量",
    )
    condition_operator: str = Field(
        default="contains",
        description="比较操作符, 候选: contains / is / not contains / start with / empty 等",
    )
    condition_value: str = Field(
        ...,
        min_length=1,
        description="条件比较的目标值, 例如: '技术' / '价格' / '售后'",
    )
    true_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="条件为 true 时走的 LLM system prompt",
    )
    false_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="条件为 false 时走的 LLM system prompt",
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        description="两个 LLM 节点共享的模型名",
    )


def _build(params: ConditionalRouterParams) -> Workflow:
    wf = Workflow(name="conditional_router", description="条件路由工作流")
    wf.add(StartNode(variables=[Variable(
        variable="sys.query",
        label="user_input",
        type="paragraph",
        max_length=10000,
        required=True,
    )]))
    # IF-ELSE node id=4085
    wf.add(IfElseNode(
        id="4085",
        title="Route Query",
        cases=[IfElseNode.case(
            variable_selector=[params.condition_variable.split(".")[0], params.condition_variable.split(".")[-1]],
            operator=params.condition_operator,
            value=params.condition_value,
        )],
    ))
    # LLM-True (4080) + LLM-False (4081)
    wf.add(LLMNode(
        id="4080",
        title="LLM True Branch",
        system_prompt=params.true_prompt,
        user_prompt="{{#sys.query#}}",
        model_name=params.model_name,
        temperature=0.7,
    ))
    wf.add(LLMNode(
        id="4081",
        title="LLM False Branch",
        system_prompt=params.false_prompt,
        user_prompt="{{#sys.query#}}",
        model_name=params.model_name,
        temperature=0.7,
    ))
    # Variable Aggregator (4090) — 合并两个 LLM 的输出
    wf.add(VariableAggregatorNode(
        id="4090",
        title="Aggregate Branches",
        variables=[["4080", "text"], ["4081", "text"]],
        output_type="string",
    ))
    wf.add(EndNode(outputs=[
        {"variable": "output", "value_selector": ["4090", "output"]},
    ]))
    # Edges
    wf.connect("4001", "4085")  # Start → IF-ELSE
    wf.connect("4085", "4080", source_handle="true")   # IF-ELSE true → LLM-A
    wf.connect("4085", "4081", source_handle="false")  # IF-ELSE false → LLM-B
    wf.connect("4080", "4090")  # LLM-A → Aggregator
    wf.connect("4081", "4090")  # LLM-B → Aggregator
    wf.connect("4090", "4099")  # Aggregator → End
    return wf


CONDITIONAL_ROUTER_TEMPLATE = {
    "id": "conditional_router",
    "name": "条件路由",
    "description": "根据 query 内容走不同 LLM 节点处理, 适合分流场景(技术/价格/售后)",
    "category": "branching",
    "min_dify_version": "1.14.0",
    "params_schema": ConditionalRouterParams,
    "to_workflow": _build,
    "test_cases": [
        {"input": "技术问题: API 怎么调用?", "expect_contains": "API"},
    ],
    "yml_preview": "Start → IF-ELSE → [True: LLM-A / False: LLM-B] → Aggregator → End",
}
