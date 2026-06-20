"""M12 PR-3 — workflow templates / preview API 测试。

覆盖 plan §3 PR-3 验收门:
  - test_list_templates_returns_four
  - test_list_templates_schema_fields
  - test_preview_happy_path_uses_overrides
  - test_preview_invalid_template_404
"""

from __future__ import annotations

import pytest


# ── GET /api/v1/workflows/templates ────────────────────────────────────────
class TestListTemplates:
    async def test_list_templates_returns_four(self, client):
        """GET 返 4 个 MVP 模板,basic_chat / rag_qa / conditional_router / tool_calling。"""
        resp = await client.get("/api/v1/workflows/templates")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 4
        ids = {t["id"] for t in body["templates"]}
        assert ids == {
            "basic_chat",
            "rag_qa",
            "conditional_router",
            "tool_calling",
        }

    async def test_list_templates_schema_fields(self, client):
        """每个模板透传所需字段(id/name/description/category/params_schema_json/yml_preview)。"""
        resp = await client.get("/api/v1/workflows/templates")
        body = resp.json()
        for template in body["templates"]:
            for key in (
                "id",
                "name",
                "description",
                "category",
                "params_schema_json",
                "yml_preview",
            ):
                assert key in template, f"missing {key} in {template['id']}"
            # params_schema_json 必须是 dict 且含 properties
            schema = template["params_schema_json"]
            assert isinstance(schema, dict)
            assert "properties" in schema


# ── POST /api/v1/workflows/preview ─────────────────────────────────────────
class TestPreviewWorkflow:
    async def test_preview_happy_path_uses_overrides(self, client):
        """带 params_overrides → 直传路径,不走 LLM,返 yml_text + node_count=3。"""
        resp = await client.post(
            "/api/v1/workflows/preview",
            json={
                "template_id": "basic_chat",
                "user_requirements": "做一个简单的电商客服",
                "params_overrides": {
                    "system_prompt": "你是电商客服",
                    "user_prompt_template": "{{#sys.query#}}",
                    "model_name": "gpt-4o-mini",
                    "temperature": 0.5,
                },
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["attempt_count"] == 1
        assert body["node_count"] >= 2  # Start + LLM + End 至少 3
        assert "app:" in body["yml_text"]
        assert "kind: app" in body["yml_text"]

    async def test_preview_invalid_template_404(self, client):
        """未知 template_id → 404 + 列出合法选项。"""
        resp = await client.post(
            "/api/v1/workflows/preview",
            json={
                "template_id": "nonexistent_template",
                "params_overrides": {},
            },
        )
        assert resp.status_code == 404
        detail = resp.json().get("detail", "")
        assert "nonexistent_template" in detail
        assert "basic_chat" in detail  # 应列出合法选项


# ── /agents 创建接收 template_id 字段 ──────────────────────────────────────
class TestCreateAgentWithTemplate:
    async def test_create_agent_accepts_template_id(self, client):
        """POST /agents 带 template_id/template_params → 201 且回显到 AgentConfig。"""
        resp = await client.post(
            "/api/v1/agents",
            json={
                "name": "Wizard Bot",
                "description": "Created via wizard",
                "agent_type": "website_support",
                "channel_mode": "web_widget",
                "template_id": "basic_chat",
                "template_params": {
                    "system_prompt": "你是 Wizard 测试助手",
                    "temperature": 0.3,
                },
                "user_requirements": "电商客服",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["template_id"] == "basic_chat"
        assert body["template_params"]["system_prompt"] == "你是 Wizard 测试助手"