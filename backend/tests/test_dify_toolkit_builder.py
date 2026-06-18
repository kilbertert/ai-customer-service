"""M11+ P0-C PR 3 — basjoo-side Dify toolkit builder 单元测试。

从老 `tools/dify_workflow_toolkit/tests/test_builder.py` cp 过来,改 import 路径
(`dify_workflow_toolkit` → `services.dify_toolkit`)。No Dify / no SSH — 全部 in-process。

覆盖范围:
  - 6 种 Node 子类 to_data / to_dict 形状 (start / llm / code / if-else / knowledge-retrieval / end)
  - Workflow 校验: missing end / duplicate id / unknown edge target
  - YAML round-trip + JSON vs YAML 字符串差异

依赖: services.dify_toolkit.__init__ 必须导出 Workflow + 6 Node 类 + Variable + ValidationError。
"""

from __future__ import annotations

import pytest

from services.dify_toolkit import (  # noqa: E402
    CodeNode,
    EndNode,
    IfElseNode,
    KnowledgeRetrievalNode,
    LLMNode,
    StartNode,
    Variable,
    Workflow,
    ValidationError,
)


def test_start_node_round_trip():
    n = StartNode(
        variables=[Variable(variable="text", label="用户文本", type="paragraph", max_length=2000)],
    )
    d = n.to_dict()
    assert d["id"] == "4001"
    assert d["data"]["type"] == "start"
    assert d["data"]["variables"][0]["variable"] == "text"
    assert d["data"]["variables"][0]["max_length"] == 2000


def test_llm_node_json_mode():
    n = LLMNode(
        id="4080",
        title="classifier",
        system_prompt="be concise",
        user_prompt="{{#4001.text#}}",
        json_mode=True,
        vision=True,
    )
    data = n.to_data()
    assert data["model"]["provider"].startswith("langgenius")
    assert data["vision"]["enabled"] is True
    assert data["model"]["completion_params"]["response_format"] == {"type": "json_object"}
    assert any(m.get("role") == "system" for m in data["prompt_template"])


def test_code_node_has_python3_default():
    n = CodeNode(id="4002", title="x", code="def main(): return 1")
    d = n.to_data()
    assert d["code_language"] == "python3"
    assert d["code"] == "def main(): return 1"


def test_if_else_case_helper():
    c = IfElseNode.case(["4002", "scene"], "=", "report")
    assert c["logical_operator"] == "and"
    assert c["conditions"][0]["value"] == "report"


def test_knowledge_retrieval_node():
    n = KnowledgeRetrievalNode(
        id="4022",
        title="kg",
        dataset_ids=["ds-1", "ds-2"],
        query_variable_selector=["4001", "text"],
        top_k=5,
    )
    d = n.to_data()
    assert d["dataset_ids"] == ["ds-1", "ds-2"]
    assert d["multiple_retrieval_config"]["top_k"] == 5


def test_workflow_minimal_valid():
    wf = Workflow(name="test_app", description="t")
    wf.add(StartNode())
    wf.add(CodeNode(id="4002", title="x", code="def main(): return {}"))
    wf.add(EndNode())
    wf.connect("4001", "4002")
    wf.connect("4002", "4099")
    d = wf.to_dict()
    assert d["app"]["name"] == "test_app"
    assert len(d["workflow"]["graph"]["nodes"]) == 3
    assert len(d["workflow"]["graph"]["edges"]) == 2


def test_workflow_duplicate_node_id_raises():
    wf = Workflow(name="t")
    wf.add(StartNode(id="4001"))
    with pytest.raises(ValueError, match="Duplicate node id"):
        wf.add(CodeNode(id="4001", title="dup", code="x"))


def test_workflow_missing_end_raises():
    wf = Workflow(name="t")
    wf.add(StartNode())
    wf.add(CodeNode(id="4002", title="x", code="x"))
    wf.connect("4001", "4002")
    with pytest.raises(ValidationError, match="end node"):
        wf.validate()


def test_workflow_unknown_edge_target_raises():
    wf = Workflow(name="t")
    wf.add(StartNode())
    wf.add(EndNode())
    wf.connect("4001", "4002")
    with pytest.raises(ValidationError, match="unknown target"):
        wf.validate()


def test_yaml_round_trip():
    wf = Workflow(name="t", description="d")
    wf.add(StartNode(variables=[Variable("text", "Text", type="paragraph")]))
    wf.add(LLMNode(id="4080", title="c", system_prompt="be brief", json_mode=True))
    wf.add(CodeNode(id="4002", title="x", code="def main(llm_text=''): return {'scene':'symptom'}",
                    variables=[{"variable": "llm_text", "value_selector": ["4080", "text"]}]))
    wf.add(EndNode(outputs=[{"variable": "output", "value_selector": ["4002", "scene"]}]))
    wf.connect("4001", "4080")
    wf.connect("4080", "4002")
    wf.connect("4002", "4099")

    yml = wf.to_yaml()
    import yaml as _y
    parsed = _y.safe_load(yml)
    assert parsed["app"]["name"] == "t"
    assert len(parsed["workflow"]["graph"]["nodes"]) == 4
    llm_node = next(n for n in parsed["workflow"]["graph"]["nodes"] if n["id"] == "4080")
    assert llm_node["data"]["type"] == "llm"
    assert llm_node["data"]["model"]["completion_params"]["response_format"] == {"type": "json_object"}


def test_yaml_compact_vs_pretty():
    wf = Workflow(name="t")
    wf.add(StartNode())
    wf.add(CodeNode(id="4002", title="x", code="x"))
    wf.add(EndNode())
    wf.connect("4001", "4002")
    wf.connect("4002", "4099")

    pretty = wf.to_yaml()
    compact = wf.to_json()
    assert "app:" in pretty
    assert '"app"' in compact