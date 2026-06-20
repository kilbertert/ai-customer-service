"""M12 PR-1 — 4 个 MVP 工作流模板的共享基础。

每个模板是 Template dataclass 实例,包含:
  - id: 唯一标识符 (供 API 路由 + 前端 wizard 用)
  - name: 中文显示名
  - description: 1-2 句场景说明
  - category: 分类 (chat / rag / branching / tool)
  - min_dify_version: 最低 Dify 版本
  - params_schema: Pydantic v2 BaseModel (LLM 填参 + 前端表单渲染依据)
  - to_workflow(params) -> Workflow: 接受校验过的 params, 返 builder Workflow
  - test_cases: 简单 smoke test 输入(供 PR-2 LLM 生成后人工 sanity)
  - yml_preview: 参数占位符示例 (供前端 step 4 预览展示)

调用方:
  - PR-1 API: GET /api/v1/workflows/templates → 返 [TemplateMetaResponse, ...]
  - PR-2 DSLGenerator: TEMPLATES_BY_ID[template_id].to_workflow(params)
  - PR-3 前端: listTemplates() → 渲染 step 2 卡片 + step 3 动态表单
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Type

from pydantic import BaseModel

from services.dify_toolkit.builder import Workflow


@dataclass(frozen=True)
class Template:
    """一个工作流模板的元数据 + 构造器。"""

    id: str
    name: str
    description: str
    category: str
    min_dify_version: str
    params_schema: Type[BaseModel]
    to_workflow: Callable[[BaseModel], Workflow]
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    yml_preview: str = ""

    def to_metadata(self) -> dict[str, Any]:
        """返前端用的元数据(不含 to_workflow Callable)。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "min_dify_version": self.min_dify_version,
            "params_schema_json": self.params_schema.model_json_schema(),
            "yml_preview": self.yml_preview,
        }
