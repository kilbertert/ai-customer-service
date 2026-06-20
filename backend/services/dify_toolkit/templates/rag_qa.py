"""M12 PR-1 — rag_qa 模板 (Start → Knowledge Retrieval → LLM → End)。

RAG 知识问答,先检索知识库再交给 LLM 回答。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from services.dify_toolkit.builder import (
    EndNode,
    KnowledgeRetrievalNode,
    LLMNode,
    StartNode,
    Variable,
    Workflow,
)


class RagQaParams(BaseModel):
    """RAG 模板的 5 个核心字段。"""

    system_prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="LLM system prompt, 应指引模型基于检索结果回答",
    )
    knowledge_base_ids: list[str] = Field(
        ...,
        min_length=1,
        description="知识库 dataset_id 列表(必填, LLM 不得编造)",
    )
    top_k: int = Field(
        default=3,
        ge=1,
        le=10,
        description="检索 top_k",
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        description="LLM 模型名",
    )
    temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=2.0,
        description="LLM 温度, 知识问答推荐 0.3-0.5",
    )


def _build(params: RagQaParams) -> Workflow:
    wf = Workflow(name="rag_qa", description="RAG 知识问答工作流")
    wf.add(StartNode(variables=[Variable(
        variable="sys.query",
        label="user_input",
        type="paragraph",
        max_length=10000,
        required=True,
    )]))
    # Node id 4080 (LLM) + 4081 (Knowledge Retrieval) — Dify 4xxx 编号空间
    wf.add(KnowledgeRetrievalNode(
        id="4081",
        title="Search Knowledge",
        dataset_ids=params.knowledge_base_ids,
        query_variable_selector=["sys", "query"],
        top_k=params.top_k,
    ))
    wf.add(LLMNode(
        id="4080",
        title="Generate Response",
        system_prompt=params.system_prompt,
        user_prompt="{{#sys.query#}}",
        model_name=params.model_name,
        temperature=params.temperature,
        context_variable="4081",  # 用 retrieval 结果作为 context
    ))
    wf.add(EndNode(outputs=[
        {"variable": "output", "value_selector": ["4080", "text"]},
    ]))
    wf.connect("4001", "4081")  # Start → Knowledge Retrieval
    wf.connect("4081", "4080")  # Knowledge Retrieval → LLM
    wf.connect("4080", "4099")  # LLM → End
    return wf


RAG_QA_TEMPLATE = {
    "id": "rag_qa",
    "name": "知识问答",
    "description": "RAG 检索增强问答, 先查知识库再交给 LLM 综合回答",
    "category": "rag",
    "min_dify_version": "1.14.0",
    "params_schema": RagQaParams,
    "to_workflow": _build,
    "test_cases": [
        {"input": "什么是 basjoo?", "expect_contains": "客服"},
    ],
    "yml_preview": "Start → Knowledge Retrieval → LLM(context) → End",
}
