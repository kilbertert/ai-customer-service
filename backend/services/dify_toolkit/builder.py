"""Workflow DSL builder — high-level API for constructing Dify workflow yml.

Each Node subclass knows how to render itself as a Dify `graph.nodes[*]`
entry. The `Workflow` class wires them together, computes edges, and emits
the final yml text.

This module deliberately hides Dify's verbose JSON shape so callers can
write:

    wf.add(LLMNode(
        id="4080",
        title="classifier",
        model_provider="langgenius/doubao/doubao-seed-2-0-lite",
        model_name="doubao-seed-2-0-lite",
        system_prompt="...",
        user_prompt="{{#sys.query#}}",
        json_mode=True,
    ))

instead of hand-crafting ~150 lines of nested dicts.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import yaml


# ─────────────────────────────────────────────────────────────────────
# Edge
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Edge:
    """A directed edge between two nodes."""

    source: str
    target: str
    source_handle: str = "source"
    target_handle: str = "target"
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", f"edge-{self.source}-{self.target}-{uuid.uuid4().hex[:6]}")


# ─────────────────────────────────────────────────────────────────────
# Variable (Start / End / Code I/O)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Variable:
    """A workflow variable. Type is one of: text-input, paragraph, number,
    select, file, file-list, json-object, boolean, etc."""

    variable: str
    label: str
    type: str = "text-input"
    required: bool = True
    max_length: int | None = None
    options: list[str] = field(default_factory=list)
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "variable": self.variable,
            "label": self.label,
            "type": self.type,
            "required": self.required,
        }
        if self.max_length is not None:
            d["max_length"] = self.max_length
        if self.options:
            d["options"] = self.options
        if self.default is not None:
            d["default"] = self.default
        return d


# ─────────────────────────────────────────────────────────────────────
# Node base
# ─────────────────────────────────────────────────────────────────────

class Node:
    """Base class for all workflow nodes."""

    data_type: str = ""

    def __init__(
        self,
        id: str,
        title: str,
        *,
        desc: str = "",
    ) -> None:
        self.id = id
        self.title = title
        self.desc = desc
        self._position: tuple[float, float] = (0.0, 0.0)

    def set_position(self, x: float, y: float) -> None:
        self._position = (x, y)

    def to_data(self) -> dict[str, Any]:
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "data": {"type": self.data_type, "title": self.title, **self.to_data()},
            "position": {"x": self._position[0], "y": self._position[1]},
            "positionAbsolute": {"x": self._position[0], "y": self._position[1]},
            "width": 244,
            "height": 54,
            "zIndex": 0,
            "sourcePosition": "right",
            "targetPosition": "left",
            "selected": False,
            "draggable": True,
        }


# ─────────────────────────────────────────────────────────────────────
# Start
# ─────────────────────────────────────────────────────────────────────

class StartNode(Node):
    data_type = "start"

    def __init__(self, id: str = "4001", title: str = "开始", variables: list[Variable] | None = None) -> None:
        super().__init__(id, title)
        self.variables: list[Variable] = variables or []

    def to_data(self) -> dict[str, Any]:
        return {
            "variables": [v.to_dict() for v in self.variables],
        }


# ─────────────────────────────────────────────────────────────────────
# End
# ─────────────────────────────────────────────────────────────────────

class EndNode(Node):
    data_type = "end"

    def __init__(self, id: str = "4099", title: str = "结束", outputs: list[dict[str, Any]] | None = None) -> None:
        super().__init__(id, title)
        self.outputs: list[dict[str, Any]] = outputs or [
            {"variable": "output", "value_selector": []},
        ]

    def to_data(self) -> dict[str, Any]:
        return {
            "outputs": self.outputs,
        }


# ─────────────────────────────────────────────────────────────────────
# Code
# ─────────────────────────────────────────────────────────────────────

class CodeNode(Node):
    data_type = "code"

    def __init__(
        self,
        id: str,
        title: str,
        code: str,
        *,
        variables: list[dict[str, Any]] | None = None,
        outputs: dict[str, Any] | None = None,
        desc: str = "",
    ) -> None:
        super().__init__(id, title, desc=desc)
        self.code = code
        self.variables: list[dict[str, Any]] = variables or []
        self.outputs: dict[str, Any] = outputs or {
            "type": "object",
            "properties": [],
            "additionalProperties": True,
        }

    def to_data(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "code_language": "python3",
            "variables": self.variables,
            "outputs": self.outputs,
        }


# ─────────────────────────────────────────────────────────────────────
# LLM
# ─────────────────────────────────────────────────────────────────────

class LLMNode(Node):
    data_type = "llm"

    def __init__(
        self,
        id: str,
        title: str,
        *,
        system_prompt: str,
        user_prompt: str = "{{#sys.query#}}",
        model_provider: str = "langgenius/doubao/doubao-seed-2-0-lite",
        model_name: str = "doubao-seed-2-0-lite",
        mode: str = "chat",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        json_mode: bool = False,
        vision: bool = False,
        context_variable: str | None = None,
        desc: str = "",
    ) -> None:
        super().__init__(id, title, desc=desc)
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.model_provider = model_provider
        self.model_name = model_name
        self.mode = mode
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.json_mode = json_mode
        self.vision = vision
        self.context_variable = context_variable

    def to_data(self) -> dict[str, Any]:
        prompt_template = [
            {"role": "system", "text": self.system_prompt},
            {"role": "user", "text": self.user_prompt},
        ]
        completion_params: dict[str, Any] = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            completion_params["response_format"] = {"type": "json_object"}

        data: dict[str, Any] = {
            "model": {
                "provider": self.model_provider,
                "name": self.model_name,
                "mode": self.mode,
                "completion_params": completion_params,
            },
            "prompt_template": prompt_template,
            "context": {
                "enabled": self.context_variable is not None,
                "variable_selector": [self.context_variable] if self.context_variable else [],
            },
            "vision": {"enabled": self.vision},
        }
        return data


# ─────────────────────────────────────────────────────────────────────
# If-Else
# ─────────────────────────────────────────────────────────────────────

class IfElseNode(Node):
    data_type = "if-else"

    def __init__(
        self,
        id: str,
        title: str,
        *,
        cases: list[dict[str, Any]] | None = None,
        desc: str = "",
    ) -> None:
        super().__init__(id, title, desc=desc)
        self.cases: list[dict[str, Any]] = cases or []

    def to_data(self) -> dict[str, Any]:
        return {
            "cases": self.cases,
        }

    @staticmethod
    def case(
        variable_selector: list[str],
        operator: str,
        value: Any,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "case_id": case_id or uuid.uuid4().hex[:6],
            "logical_operator": "and",
            "conditions": [
                {
                    "id": uuid.uuid4().hex[:6],
                    "comparison_operator": operator,
                    "value": value,
                    "varType": "string",
                    "variable_selector": variable_selector,
                }
            ],
        }


# ─────────────────────────────────────────────────────────────────────
# Knowledge Retrieval
# ─────────────────────────────────────────────────────────────────────

class KnowledgeRetrievalNode(Node):
    data_type = "knowledge-retrieval"

    def __init__(
        self,
        id: str,
        title: str,
        *,
        dataset_ids: list[str],
        query_variable_selector: list[str],
        retrieval_mode: str = "multiple",
        top_k: int = 3,
        score_threshold: float = 0.5,
        desc: str = "",
    ) -> None:
        super().__init__(id, title, desc=desc)
        self.dataset_ids = dataset_ids
        self.query_variable_selector = query_variable_selector
        self.retrieval_mode = retrieval_mode
        self.top_k = top_k
        self.score_threshold = score_threshold

    def to_data(self) -> dict[str, Any]:
        return {
            "dataset_ids": self.dataset_ids,
            "retrieval_mode": self.retrieval_mode,
            "multiple_retrieval_config": {
                "top_k": self.top_k,
                "score_threshold": self.score_threshold,
                "reranking_enable": False,
            },
            "query_variable_selector": self.query_variable_selector,
            "query_attachment": {"enabled": False},
        }


# ─────────────────────────────────────────────────────────────────────
# Variable Aggregator
# ─────────────────────────────────────────────────────────────────────

class VariableAggregatorNode(Node):
    data_type = "variable-aggregator"

    def __init__(
        self,
        id: str,
        title: str,
        *,
        variables: list[list[str]] | None = None,
        output_type: str = "object",
        desc: str = "",
    ) -> None:
        super().__init__(id, title, desc=desc)
        self.variables = variables or []
        self.output_type = output_type

    def to_data(self) -> dict[str, Any]:
        return {
            "variables": self.variables,
            "output_type": self.output_type,
        }


# ─────────────────────────────────────────────────────────────────────
# Workflow
# ─────────────────────────────────────────────────────────────────────

class Workflow:
    """A complete Dify workflow definition."""

    def __init__(
        self,
        name: str,
        description: str = "",
        *,
        mode: str = "workflow",
        kind: str = "app",
        version: str = "0.1.0",
        features: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.mode = mode
        self.kind = kind
        self.version = version
        self.features: dict[str, Any] = features or self._default_features()
        self._nodes: list[Node] = []
        self._edges: list[Edge] = []
        self._next_pos: tuple[float, float] = (-180.0, 0.0)

    @staticmethod
    def _default_features() -> dict[str, Any]:
        return {
            "file_upload": {
                "allowed_file_extensions": ["JPG", "PNG", "JPEG", "WEBP", "PDF"],
                "allowed_file_types": ["image", "document"],
                "enabled": False,
                "fileUploadConfig": {
                    "audio_file_size_limit": 50,
                    "batch_count_limit": 5,
                    "file_size_limit": 50,
                    "image_file_size_limit": 50,
                    "video_file_size_limit": 50,
                    "workflow_file_upload_limit": 10,
                },
                "image": {"enabled": False, "number_limits": 3, "transfer_methods": ["remote_url", "local_file"]},
            },
            "handoff_to_human": {"enabled": False},
            "opening_statement": "",
            "retriever_resource": {"enabled": False},
            "sensitive_word_avoidance": {"enabled": False},
            "speech_to_text": {"enabled": False},
            "suggested_questions": [],
            "text_to_speech": {"enabled": False},
        }

    def add(self, node: Node) -> Node:
        if any(n.id == node.id for n in self._nodes):
            raise ValueError(f"Duplicate node id: {node.id}")
        x, y = self._next_pos
        node.set_position(x, y)
        self._next_pos = (x + 280.0, y)
        self._nodes.append(node)
        return node

    def get(self, node_id: str) -> Node:
        for n in self._nodes:
            if n.id == node_id:
                return n
        raise KeyError(f"Node not found: {node_id}")

    def nodes(self) -> list[Node]:
        return list(self._nodes)

    def connect(
        self,
        source: str,
        target: str,
        *,
        source_handle: str = "source",
        target_handle: str = "target",
    ) -> Edge:
        edge = Edge(source, target, source_handle, target_handle)
        self._edges.append(edge)
        return edge

    def edges(self) -> list[Edge]:
        return list(self._edges)

    def validate(self) -> None:
        from .yml_validator import validate_workflow
        validate_workflow(self)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "app": {
                "description": self.description,
                "icon": "🤖",
                "icon_background": "#FFEAD5",
                "mode": self.mode,
                "name": self.name,
            },
            "use_icon_as_answer_icon": False,
            "kind": self.kind,
            "version": self.version,
            "workflow": {
                "conversation_variables": [],
                "environment_variables": [],
                "features": self.features,
                "graph": {
                    "nodes": [n.to_dict() for n in self._nodes],
                    "edges": [
                        {
                            "id": e.id,
                            "source": e.source,
                            "target": e.target,
                            "sourceHandle": e.source_handle,
                            "targetHandle": e.target_handle,
                            "type": "custom",
                            "data": {
                                "isInIteration": False,
                                "sourceType": "downstream",
                                "targetType": "upstream",
                            },
                            "zIndex": 0,
                            "selected": False,
                        }
                        for e in self._edges
                    ],
                    "viewport": {"x": 0, "y": 0, "zoom": 1},
                },
            },
        }

    def to_yaml(self, *, sort_keys: bool = False) -> str:
        return yaml.safe_dump(
            self.to_dict(),
            allow_unicode=True,
            sort_keys=sort_keys,
            default_flow_style=False,
            width=1000,
        )

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
