"""M8.5 — Unit tests for `app_dify.sse_bytes` public helpers.

Coverage targets:
- `sse_bytes(event_type, data)` — dict / str payloads, UTF-8 safe (中文 / emoji).
- `truncate_error(msg, limit)` — short / exact / over limit, ellipsis suffix.
- `_MAX_ERROR_MESSAGE` constant default (200, H3 strengthening).

Tests previously colocated in test_sse_proxy_layer.py (TestSseEventHelper /
TestTruncateErrorMessage) moved here to target the correct module after DRY
extraction (M8.5).
"""
from __future__ import annotations

import json

from app_dify.sse_bytes import _MAX_ERROR_MESSAGE, sse_bytes, truncate_error


# ============== sse_bytes — dict payload ==============


class TestSseBytesDictPayload:
    """W3C SSE wire format with dict payload (JSON-serialized)."""

    def test_format_event_line(self) -> None:
        out = sse_bytes("message_delta", {"text": "hi"}).decode("utf-8")
        assert out.startswith("event: message_delta\n")

    def test_format_data_line_is_json(self) -> None:
        out = sse_bytes("message_delta", {"text": "hi"}).decode("utf-8")
        # Extract `data: ...` payload and verify JSON round-trip
        data_line = [ln for ln in out.split("\n") if ln.startswith("data: ")][0]
        payload = data_line[len("data: ") :]
        assert json.loads(payload) == {"text": "hi"}

    def test_format_ends_with_blank_line(self) -> None:
        # SSE spec: event-data block must be terminated by an empty line
        out = sse_bytes("end", {}).decode("utf-8")
        assert out.endswith("\n\n")

    def test_returns_bytes_not_str(self) -> None:
        out = sse_bytes("end", {})
        assert isinstance(out, bytes)


# ============== sse_bytes — string payload ==============


class TestSseBytesStringPayload:
    """Pre-serialized string payload is passed through unchanged (no JSON re-encode)."""

    def test_string_payload_passthrough(self) -> None:
        out = sse_bytes("custom", "raw text payload").decode("utf-8")
        assert "data: raw text payload\n" in out

    def test_string_payload_not_json_encoded(self) -> None:
        # If caller passes a string, we must NOT wrap it in quotes
        out = sse_bytes("custom", "already json").decode("utf-8")
        assert 'data: "already json"' not in out
        assert "data: already json\n" in out


# ============== sse_bytes — UTF-8 safety (ensure_ascii=False) ==============


class TestSseBytesUtf8Safe:
    """H5 client parses payload as UTF-8 — Chinese / emoji must not be \\uXXXX escaped."""

    def test_chinese_not_escaped(self) -> None:
        out = sse_bytes("message_delta", {"text": "你好世界"}).decode("utf-8")
        assert "你好世界" in out
        # ensure_ascii=False guarantee: no \uXXXX in payload
        assert "\\u" not in out

    def test_emoji_not_escaped(self) -> None:
        out = sse_bytes("message_delta", {"text": "🎉🚀"}).decode("utf-8")
        assert "🎉🚀" in out
        assert "\\ud83c" not in out.lower()

    def test_mixed_scripts_preserved(self) -> None:
        out = sse_bytes("message_delta", {"text": "ABC 中文 🌟 العربية"}).decode("utf-8")
        assert "中文" in out
        assert "🌟" in out
        assert "العربية" in out


# ============== truncate_error — boundary & ellipsis behavior ==============


class TestTruncateError:
    """H3 strengthening: error.message length capped at 200 (M2 default 500 → M3 收紧)."""

    def test_short_message_unchanged(self) -> None:
        assert truncate_error("short") == "short"

    def test_short_message_chinese_unchanged(self) -> None:
        assert truncate_error("简短错误") == "简短错误"

    def test_exact_limit_boundary(self) -> None:
        # Exactly at limit — must NOT be truncated
        msg = "x" * _MAX_ERROR_MESSAGE
        assert truncate_error(msg) == msg
        assert len(truncate_error(msg)) == _MAX_ERROR_MESSAGE

    def test_long_capped_with_ellipsis(self) -> None:
        # 500 chars → truncated to limit + "..."  (M3 frozen contract)
        msg = "x" * 500
        out = truncate_error(msg)
        assert out.endswith("...")
        assert len(out) == _MAX_ERROR_MESSAGE + 3  # 203

    def test_just_over_limit_truncated(self) -> None:
        # limit+1 char → truncated to msg[:limit] + "..."  (total = limit + 3)
        msg = "x" * (_MAX_ERROR_MESSAGE + 1)
        out = truncate_error(msg)
        assert out.endswith("...")
        assert len(out) == _MAX_ERROR_MESSAGE + 3
        assert out[:_MAX_ERROR_MESSAGE] == "x" * _MAX_ERROR_MESSAGE

    def test_custom_limit_respected(self) -> None:
        out = truncate_error("0123456789", limit=5)
        assert out == "01234..."
        assert len(out) == 5 + 3

    def test_empty_message_unchanged(self) -> None:
        assert truncate_error("") == ""


# ============== _MAX_ERROR_MESSAGE constant ==============


class TestMaxErrorMessageConstant:
    """The default cap is 200 (H3 strengthening — keep this regression-locked)."""

    def test_default_constant_is_200(self) -> None:
        assert _MAX_ERROR_MESSAGE == 200

    def test_truncate_error_default_uses_constant(self) -> None:
        # Calling without `limit` must use _MAX_ERROR_MESSAGE
        msg = "y" * (_MAX_ERROR_MESSAGE + 50)
        out = truncate_error(msg)
        assert len(out) == _MAX_ERROR_MESSAGE + 3
