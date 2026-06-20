"""M12 PR-8 — Rate limiter tests.

2 tests per plan §3 PR-8b:
  1. test_under_limit_allowed        — first 10 calls succeed
  2. test_eleventh_call_rejected_429  — 11th call returns HTTP 429

Strategy: hit the real rate-limit gate via POST /workflows/preview with a
template_id that triggers the fast ``params_overrides`` path (no LLM, no
Dify — just Pydantic validation). That way we can pump 11 requests cheaply.
"""

from __future__ import annotations

import pytest

from services.rate_limit import (
    RateLimiter,
    reset_all_limits,
)


@pytest.fixture(autouse=True)
def _clear_limits() -> None:
    """Reset rate-limit buckets before each test to avoid cross-test leakage."""
    reset_all_limits()


async def test_preview_eleventh_call_rejected_429(client) -> None:
    """11th POST /workflows/preview within 60s → 429 (workspace shared rate limit)."""
    payload = {
        "template_id": "basic_chat",
        "params_overrides": {
            "system_prompt": "rate-limit-test",
            "user_prompt_template": "{{#sys.query#}}",
            "model_name": "gpt-4o-mini",
            "temperature": 0.7,
        },
    }
    # First 10 should pass (200)
    for i in range(10):
        r = await client.post("/api/v1/workflows/preview", json=payload)
        assert r.status_code == 200, f"call {i+1} should pass, got {r.status_code}: {r.text}"
    # 11th must be rejected by the workspace-level rate limiter
    r11 = await client.post("/api/v1/workflows/preview", json=payload)
    assert r11.status_code == 429, f"11th call should be 429, got {r11.status_code}: {r11.text}"
    assert "rate limit" in r11.text.lower()


def test_rate_limiter_unit_allow_and_reject() -> None:
    """Direct unit test of the RateLimiter class — independent of FastAPI."""
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert limiter.allow(workspace_id=1, route="x") is True
    assert limiter.allow(workspace_id=1, route="x") is True
    assert limiter.allow(workspace_id=1, route="x") is True
    assert limiter.allow(workspace_id=1, route="x") is False  # 4th rejected
    # Different workspace is independent
    assert limiter.allow(workspace_id=2, route="x") is True
    # Different route is independent
    assert limiter.allow(workspace_id=1, route="y") is True