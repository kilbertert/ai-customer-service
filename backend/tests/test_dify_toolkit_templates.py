"""M12 PR-1 — 4 个 MVP 模板的测试。

覆盖 plan §3 PR-1 验收门:
  - test_template_ids_unique
  - test_to_workflow_basic_chat
  - test_to_workflow_rag_qa
  - test_to_workflow_conditional_router
  - test_to_workflow_tool_calling
  - test_all_templates_validate_yaml
  - test_params_schema_dump_json
  - test_pydantic_validation (extra)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.dify_toolkit.templates import TEMPLATES, TEMPLATES_BY_ID
from services.dify_toolkit.templates.basic_chat import BasicChatParams
from services.dify_toolkit.templates.rag_qa import RagQaParams
from services.dify_toolkit.templates.conditional_router import ConditionalRouterParams
from services.dify_toolkit.templates.tool_calling import ToolCallingParams
from services.dify_toolkit.yml_validator import validate_yaml


# ── 模板注册表 ─────────────────────────────────────────────────────────────
class TestTemplateRegistry:
    def test_template_ids_unique(self):
        """TEMPLATES 列表内 4 个 id 唯一。"""
        ids = [t.id for t in TEMPLATES]
        assert len(ids) == 4
        assert len(set(ids)) == len(ids), f"Duplicate template ids: {ids}"

    def test_all_4_templates_have_required_fields(self):
        """每个 Template 必填字段齐全。"""
        for t in TEMPLATES:
            assert t.id
            assert t.name
            assert t.description
            assert t.category
            assert t.min_dify_version
            assert t.params_schema is not None
            assert callable(t.to_workflow)

    def test_templates_by_id_lookups(self):
        """TEMPLATES_BY_ID dict 可按 id 查 4 个模板。"""
        for tid in ("basic_chat", "rag_qa", "conditional_router", "tool_calling"):
            assert tid in TEMPLATES_BY_ID
            assert TEMPLATES_BY_ID[tid].id == tid


# ── to_workflow 函数 ──────────────────────────────────────────────────────
class TestToWorkflow:
    def test_basic_chat(self):
        params = BasicChatParams(
            system_prompt="你是一个客服",
            model_name="gpt-4o-mini",
            temperature=0.5,
        )
        wf = TEMPLATES_BY_ID["basic_chat"].to_workflow(params)
        nodes = wf.nodes()
        assert len(nodes) == 3  # start + llm + end
        types = [n.data_type for n in nodes]
        assert types == ["start", "llm", "end"]

    def test_rag_qa(self):
        params = RagQaParams(
            system_prompt="基于知识库回答",
            knowledge_base_ids=["kb-1", "kb-2"],
            top_k=5,
            model_name="gpt-4o-mini",
            temperature=0.3,
        )
        wf = TEMPLATES_BY_ID["rag_qa"].to_workflow(params)
        nodes = wf.nodes()
        assert len(nodes) == 4  # start + retrieval + llm + end
        types = [n.data_type for n in nodes]
        assert "knowledge-retrieval" in types
        assert "llm" in types

    def test_conditional_router(self):
        params = ConditionalRouterParams(
            condition_variable="sys.query",
            condition_operator="contains",
            condition_value="技术",
            true_prompt="你是技术客服",
            false_prompt="你是普通客服",
            model_name="gpt-4o-mini",
        )
        wf = TEMPLATES_BY_ID["conditional_router"].to_workflow(params)
        nodes = wf.nodes()
        # start + if-else + llm-a + llm-b + aggregator + end = 6
        assert len(nodes) == 6
        types = [n.data_type for n in nodes]
        assert "if-else" in types
        assert types.count("llm") == 2
        assert "variable-aggregator" in types

    def test_tool_calling(self):
        params = ToolCallingParams(
            system_prompt="你可以调用工具",
            tool_ids=["tool-weather-1", "tool-search-2"],
            model_name="gpt-4o-mini",
            temperature=0.3,
        )
        wf = TEMPLATES_BY_ID["tool_calling"].to_workflow(params)
        nodes = wf.nodes()
        assert len(nodes) == 3  # start + llm + end
        llm_node = next(n for n in nodes if n.data_type == "llm")
        llm_data = llm_node.to_data()
        assert "tools" in llm_data
        assert len(llm_data["tools"]) == 2
        assert llm_data["tools"][0]["provider_id"] == "tool-weather-1"


# ── 校验 ──────────────────────────────────────────────────────────────────
class TestValidation:
    def test_all_templates_validate_yaml(self):
        """4 个模板 to_yaml() 输出都过 validate_yaml。"""
        sample_params = [
            (TEMPLATES_BY_ID["basic_chat"], BasicChatParams(system_prompt="x")),
            (TEMPLATES_BY_ID["rag_qa"], RagQaParams(
                system_prompt="x", knowledge_base_ids=["kb-1"])),
            (TEMPLATES_BY_ID["conditional_router"], ConditionalRouterParams(
                condition_value="x", true_prompt="a", false_prompt="b")),
            (TEMPLATES_BY_ID["tool_calling"], ToolCallingParams(
                system_prompt="x", tool_ids=["t-1"])),
        ]
        for template, params in sample_params:
            wf = template.to_workflow(params)
            yml = wf.to_yaml()
            validated = validate_yaml(yml)  # 不抛即过
            assert "workflow" in validated
            assert "graph" in validated["workflow"]

    def test_params_schema_dump_json(self):
        """每个 params_schema 可 model_dump, 含字段定义。"""
        for t in TEMPLATES:
            dumped = t.params_schema.model_json_schema()
            assert "properties" in dumped
            assert len(dumped["properties"]) >= 1

    def test_pydantic_validation_rejects_empty_system_prompt(self):
        """system_prompt min_length=1 校验 — 空字符串必拒。"""
        with pytest.raises(ValidationError):
            BasicChatParams(system_prompt="")

    def test_rag_qa_requires_at_least_one_kb(self):
        """RAG 模板 knowledge_base_ids 必填,空列表必拒。"""
        with pytest.raises(ValidationError):
            RagQaParams(system_prompt="x", knowledge_base_ids=[])
