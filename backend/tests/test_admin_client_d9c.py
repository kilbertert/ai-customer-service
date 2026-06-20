"""M12 PR-0 — D9c 最小图回退 4 个测试。

覆盖 plan §3 PR-0 验收门的 4 个 case:
  - test_graph_none_uses_minimal:         无 graph 参数 → Start+End 模板
  - test_graph_explicit_uses_passed:      传 graph → 透传
  - test_minimal_validates_with_yml_validator: 走 validate_yaml 校验
  - test_publish_succeeds_with_minimal:   end-to-end publish 200 路径

设计: 直接 mock DifyAdminClient._request 为 AsyncMock 返回成功响应,只测
create_app_and_workflow 自身的 graph 选择逻辑,无 DB / 无 FastAPI 依赖。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.dify.admin_client import DifyAdminClient
from services.dify_toolkit.builder import EndNode, StartNode, Variable, Workflow
from services.dify_toolkit.yml_validator import validate_yaml


# ── fixtures ───────────────────────────────────────────────────────────────
@pytest.fixture
def admin_client() -> DifyAdminClient:
    """构造 DifyAdminClient 实例, _request 留给各测试 mock。"""
    return DifyAdminClient(
        api_base="https://dify.test",
        admin_email="admin@dify.test",
        admin_password="secret",
    )


@pytest.fixture
def mock_request_factory():
    """返回一个 factory, 调用者按顺序返回各 _request 调用的响应。

    DifyAdminClient.create_app_and_workflow 内部按以下顺序调 _request:
      1. POST /console/api/apps  (create app)
      2. POST /console/api/apps/{app_id}/workflows/draft  (sync draft)
      [可选 3. GET /console/api/apps/{app_id}/workflows  (fetch workflow_id)]
    """
    def _factory(responses: list[MagicMock]):
        call_iter = iter(responses)

        async def _mock_request(method, path, **kwargs):
            return next(call_iter)

        return AsyncMock(side_effect=_mock_request)
    return _factory


def _ok_json_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = str(payload)[:200]
    return resp


# ── tests ──────────────────────────────────────────────────────────────────
class TestD9cMinimalGraph:
    """M12 PR-0 D9c-2: create_app_and_workflow graph 参数。"""

    @pytest.mark.asyncio
    async def test_graph_none_uses_minimal(
        self, admin_client, mock_request_factory
    ):
        """不传 graph → Step 2 body 含 Start+End 节点, 不再是空 nodes:[]."""
        app_resp = _ok_json_response({"id": "app-uuid-123"}, status=201)
        draft_resp = _ok_json_response({
            "id": "wf-uuid-456", "hash": "abc", "updated_at": "2026-06-19T00:00:00Z"
        })
        mock_req = mock_request_factory([app_resp, draft_resp])
        # DifyAdminClient 是 @dataclass(frozen=True) — 需用 object.__setattr__ 绕过
        object.__setattr__(admin_client, "_request", mock_req)

        result = await admin_client.create_app_and_workflow(name="test-agent")

        assert result["app_id"] == "app-uuid-123"
        assert result["workflow_id"] == "wf-uuid-456"

        # 检查 Step 2 调用时传入的 graph 包含 Start+End
        step2_call = mock_req.call_args_list[1]
        sent_graph = step2_call.kwargs["json_body"]["graph"]
        nodes = sent_graph["nodes"]
        node_types = [n["data"]["type"] for n in nodes]
        assert "start" in node_types, f"Expected start node, got {node_types}"
        assert "end" in node_types, f"Expected end node, got {node_types}"
        assert len(nodes) == 2, f"Expected exactly 2 nodes (start+end), got {len(nodes)}"
        # 边: start → end
        edges = sent_graph["edges"]
        assert len(edges) == 1
        start_node = next(n for n in nodes if n["data"]["type"] == "start")
        end_node = next(n for n in nodes if n["data"]["type"] == "end")
        assert edges[0]["source"] == start_node["id"]
        assert edges[0]["target"] == end_node["id"]

    @pytest.mark.asyncio
    async def test_graph_explicit_uses_passed(
        self, admin_client, mock_request_factory
    ):
        """显式传 graph → 透传, 不构造 fallback."""
        custom_graph = {
            "nodes": [
                {"id": "4001", "data": {"type": "start", "title": "S"}, "position": {"x": 0, "y": 0}},
                {"id": "4080", "data": {"type": "llm", "title": "L"}, "position": {"x": 200, "y": 0}},
                {"id": "4099", "data": {"type": "end", "title": "E"}, "position": {"x": 400, "y": 0}},
            ],
            "edges": [
                {"id": "e1", "source": "4001", "target": "4080", "sourceHandle": "source", "targetHandle": "target"},
                {"id": "e2", "source": "4080", "target": "4099", "sourceHandle": "source", "targetHandle": "target"},
            ],
        }

        app_resp = _ok_json_response({"id": "app-uuid-123"}, status=201)
        draft_resp = _ok_json_response({"id": "wf-uuid-456"})
        mock_req = mock_request_factory([app_resp, draft_resp])
        object.__setattr__(admin_client, "_request", mock_req)

        result = await admin_client.create_app_and_workflow(
            name="test-agent", graph=custom_graph
        )

        assert result["app_id"] == "app-uuid-123"

        # Step 2 收到的 graph 必须是原传入的 custom_graph(identity)
        step2_call = mock_req.call_args_list[1]
        sent_graph = step2_call.kwargs["json_body"]["graph"]
        assert sent_graph is custom_graph or sent_graph == custom_graph
        # 节点数 3 (start + llm + end), 不是 fallback 的 2
        assert len(sent_graph["nodes"]) == 3

    def test_minimal_validates_with_yml_validator(self):
        """PR-0 构造的最小图走 YmlValidator 应通过。"""
        # 模拟 create_app_and_workflow graph=None 路径的内部构造逻辑
        wf = Workflow(name="minimal_test")
        wf.add(StartNode(variables=[Variable(
            variable="sys.query",
            label="user_input",
            type="paragraph",
            max_length=10000,
            required=True,
        )]))
        wf.add(EndNode(outputs=[{"variable": "output", "value_selector": []}]))
        wf.connect("4001", "4099")

        # 关键断言: 走 validate_yaml 不抛 ValidationError, 返 parsed dict
        yml = wf.to_yaml()
        validated = validate_yaml(yml)
        # validate_yaml 返 dict 包含 workflow.graph
        assert "workflow" in validated
        assert "graph" in validated["workflow"]
        nodes = validated["workflow"]["graph"]["nodes"]
        assert len(nodes) == 2
        # Start node 必须有 user_input 变量
        start_node = next(n for n in nodes if n["data"]["type"] == "start")
        variables = start_node["data"].get("variables", [])
        assert any(v["variable"] == "sys.query" for v in variables)

    @pytest.mark.asyncio
    async def test_publish_succeeds_with_minimal(
        self, admin_client, mock_request_factory
    ):
        """端到端: graph=None → create → draft → Dify 接受(2xx), 返 app_id/workflow_id."""
        app_resp = _ok_json_response({"id": "app-uuid-fallback"}, status=201)
        draft_resp = _ok_json_response({
            "id": "wf-uuid-fallback",
            "hash": "x",
            "updated_at": "2026-06-19T00:00:00Z",
        })
        mock_req = mock_request_factory([app_resp, draft_resp])
        object.__setattr__(admin_client, "_request", mock_req)

        result = await admin_client.create_app_and_workflow(name="fallback-test")

        # 必须成功拿到两个 id(无 ValidationError / DifyBadRequestError)
        assert result["app_id"] == "app-uuid-fallback"
        assert result["workflow_id"] == "wf-uuid-fallback"
        # _request 被调 2 次 (create + draft), 无 rollback DELETE
        assert mock_req.call_count == 2
        delete_calls = [
            c for c in mock_req.call_args_list
            if c.args[0] == "DELETE"
        ]
        assert len(delete_calls) == 0
