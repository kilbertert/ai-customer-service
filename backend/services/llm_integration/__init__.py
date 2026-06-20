"""LLM integration clients used by basjoo tools that need an LLM outside per-agent configs.

The chat-completion provider abstraction in `services/llm_service.py` is keyed on
basjoo Agents — it answers "which model should this tenant's agent use". The
clients here are used by tools that must run before any Agent exists, e.g. the
DSL generator that synthesises a workflow from a user's free-text description.

Today: MiniMax (the MiniMax M-series, MiniMax-Text-01).
Tomorrow: drop in additional providers without touching the call sites.
"""

from __future__ import annotations

from .minimax_client import (
    MiniMaxAPIError,
    MiniMaxClient,
    MiniMaxResponse,
    minimax_call,
)

__all__ = [
    "MiniMaxAPIError",
    "MiniMaxClient",
    "MiniMaxResponse",
    "minimax_call",
]