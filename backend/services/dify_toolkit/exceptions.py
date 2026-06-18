"""Dify toolkit 专用异常 (P0-C PR 2)。

``DifySchemaError``  — ``workflows`` 表缺列 (C2 探针失败) → 端点 502 + audit
``DifyPublishError`` — DB fallback 路径 publish 仍失败 (C1 兜底) → 端点 502
"""

from __future__ import annotations


class DifySchemaError(Exception):
    """``workflows`` 表 schema 探针失败 (D10 决策)。

    Deployer.deploy 开头调 ``probe_workflows_schema()``,missing columns 即抛。
    端点 catch → HTTPException(502) + AuditLog(action="workflow.deploy_schema_mismatch")。
    """

    def __init__(self, missing: list[str], actual: dict[str, str] | None = None) -> None:
        self.missing = missing
        self.actual = actual or {}
        super().__init__(
            f"Dify workflows table schema mismatch. "
            f"Missing or wrong-type columns: {missing}. "
            f"Actual: {actual}"
        )


class DifyPublishError(Exception):
    """Dify publish 完全失败 (DifyAdminClient.publish_workflow 已容错 400/422)。

    ``DifyAdminClient.publish_workflow`` 自身 5xx 抛 ``DifyUpstreamError``(已 catch);
    4xx 400/422 返 ``False``(D9c 容错);这个异常只在 DB fallback 路径仍失败时抛。
    """

    def __init__(self, app_id: str, original_error: str) -> None:
        self.app_id = app_id
        self.original_error = original_error
        super().__init__(
            f"Dify publish for app {app_id} failed on both API and DB fallback: "
            f"{original_error}"
        )
