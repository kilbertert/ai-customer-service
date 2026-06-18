"""Structural validation for Dify workflow yml / dicts.

Two entry points:
    validate_yaml(yml_text: str) -> None   # parses + validates
    validate_workflow(wf: Workflow) -> None  # validates in-memory graph

Both raise `ValidationError` on the first problem found, with a message
that includes the offending node id (when known) so the caller can
locate the issue without a debugger.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from .builder import Workflow


class ValidationError(ValueError):
    """Raised when a workflow definition violates the Dify DSL contract."""


def _err(msg: str, *, node_id: str | None = None) -> None:
    if node_id:
        raise ValidationError(f"[node {node_id}] {msg}")
    raise ValidationError(msg)


def _validate_node(node: Any) -> None:
    node_id = node.id
    if not node.id:
        _err("node missing 'id'")
    if not node.title:
        _err(f"node {node_id} missing 'title'")
    if not node.data_type:
        _err(f"node {node_id} missing 'data.type'")

    if node.data_type == "start":
        if not isinstance(node.variables, list):
            _err(f"start node requires 'variables' list", node_id=node_id)
    elif node.data_type == "code":
        if not node.code:
            _err(f"code node {node_id} missing 'code' body", node_id=node_id)
    elif node.data_type == "llm":
        data = node.to_data()
        prompt = data.get("prompt_template", [])
        if not any(m.get("role") == "system" and m.get("text") for m in prompt):
            _err(f"llm node {node_id} missing non-empty system prompt", node_id=node_id)
        model = data.get("model", {})
        if not model.get("provider") or not model.get("name"):
            _err(f"llm node {node_id} missing model.provider / model.name", node_id=node_id)
    elif node.data_type == "if-else":
        if not node.cases:
            _err(f"if-else node {node_id} has no cases", node_id=node_id)
    elif node.data_type == "knowledge-retrieval":
        if not node.dataset_ids:
            _err(f"knowledge-retrieval node {node_id} has no dataset_ids", node_id=node_id)
    elif node.data_type == "end":
        if not node.outputs:
            _err(f"end node {node_id} has no outputs", node_id=node_id)


def validate_workflow(wf: "Workflow") -> None:
    if not wf.name:
        _err("workflow missing 'name'")

    if not wf._nodes:
        _err("workflow has no nodes")

    ids = [n.id for n in wf._nodes]
    if len(set(ids)) != len(ids):
        seen: set[str] = set()
        for n in wf._nodes:
            if n.id in seen:
                _err(f"duplicate node id: {n.id}", node_id=n.id)
            seen.add(n.id)

    types = [n.data_type for n in wf._nodes]
    if "start" not in types:
        _err("workflow missing a start node")
    if "end" not in types:
        _err("workflow missing an end node")

    for e in wf._edges:
        if e.source not in ids:
            _err(f"edge {e.id} references unknown source: {e.source}")
        if e.target not in ids:
            _err(f"edge {e.id} references unknown target: {e.target}")

    for n in wf._nodes:
        _validate_node(n)


def validate_yaml(yml_text: str) -> dict[str, Any]:
    """Parse + structurally validate a Dify workflow yml string.

    Returns the parsed dict on success. Raises ValidationError otherwise.
    """
    try:
        data = yaml.safe_load(yml_text)
    except yaml.YAMLError as e:
        raise ValidationError(f"invalid yml: {e}") from e

    if not isinstance(data, dict):
        raise ValidationError("yml must be a mapping at the top level")

    if "workflow" not in data:
        raise ValidationError("yml missing 'workflow' key")

    graph = data["workflow"].get("graph") or {}
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    if not nodes:
        raise ValidationError("yml has no nodes")

    for n in nodes:
        if "id" not in n:
            raise ValidationError("a node is missing 'id'")
        if "data" not in n or "type" not in n["data"]:
            raise ValidationError(f"node {n.get('id')} missing data.type")

    return data


def diff_dicts(a: dict[str, Any], b: dict[str, Any], *, path: str = "") -> list[str]:
    """Return a list of human-readable differences between two dicts.

    Used by the verifier to show callers what changed between the
    deployed graph and a freshly-built one.
    """
    diffs: list[str] = []
    keys = set(a) | set(b)
    for k in keys:
        sub = f"{path}.{k}" if path else k
        if k not in a:
            diffs.append(f"+ {sub} (added in B)")
        elif k not in b:
            diffs.append(f"- {sub} (removed in A)")
        elif isinstance(a[k], dict) and isinstance(b[k], dict):
            diffs.extend(diff_dicts(a[k], b[k], path=sub))
        elif a[k] != b[k]:
            diffs.append(f"~ {sub}: {a[k]!r} -> {b[k]!r}")
    return diffs
