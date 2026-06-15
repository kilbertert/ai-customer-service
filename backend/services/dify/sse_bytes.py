"""Public helpers shared between SseProxyLayer and FastAPI endpoints.

M8.5 — extracted from `_sse_event` / `_truncate_error_message` in
`sse_proxy_layer.py` and `_sse_bytes` / `_truncate_error` in `main.py` to
eliminate DRY violation.

契约 (M3 / M4 frozen):
- ensure_ascii=False 保留中文字符（H5 客户端按 UTF-8 解析）
- 末尾双重换行是 SSE 规范要求（事件分隔符）
- 错误消息最大长度 200（H3 strengthening,M2 默认 500 → M3 收紧）
"""
from __future__ import annotations

import json
from typing import Any

_MAX_ERROR_MESSAGE = 200


def sse_bytes(event_type: str, data: dict[str, Any] | str) -> bytes:
    """Format a single SSE message per W3C SSE spec.

    Output shape:
        event: <event_type>\\n
        data: <json>\\n
        \\n

    `data` may be a dict (JSON-serialized with ensure_ascii=False) or a raw
    string (passed through unchanged).
    """
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event_type}\ndata: {data}\n\n".encode("utf-8")


def truncate_error(msg: str, limit: int = _MAX_ERROR_MESSAGE) -> str:
    """Cap error text length to keep SSE payload bounded.

    - `len(msg) <= limit` → returned unchanged
    - `len(msg) == limit + 1` → truncated to `msg[:limit] + "..."` (total `limit + 3`)
    """
    if len(msg) <= limit:
        return msg
    return msg[:limit] + "..."