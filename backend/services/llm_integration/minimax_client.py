"""MiniMax Chat Completions v2 client.

Used by the DSL generator (M12 PR-2) to turn a user's free-text request into a
JSON payload that fills a workflow template's `params_schema`.

Design notes (verified by probe `tools/minimax_probe.py`, 2026-06-19):
- Default model is `MiniMax-Text-01`.
- `response_format={"type": "json_object"}` BREAKS the API (the server returns
  no `choices` field and we get a `None` content). Do not use it.
- `reply_constraints.grep_constraint` is accepted by the API but the server
  still returns content wrapped in ```json fences; treat it as a hint, not
  enforcement. We strip the fences in `_extract_json`.
- The reliable path is: strong system prompt + post-processing JSON strip +
  Pydantic validation in the caller. This client just delivers the raw content
  plus a normalised usage dict; the caller decides what counts as success.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from config import get_settings

logger = logging.getLogger(__name__)


class MiniMaxAPIError(RuntimeError):
    """Raised when the MiniMax API returns an error or an unparseable body."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MiniMaxResponse:
    """Normalised result of a MiniMax chat completion call."""

    content: str               # Raw assistant message (may still contain ```json fences)
    parsed: dict[str, Any]     # JSON body parsed (or empty dict on parse failure)
    model: str                 # Echoed back by the API
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_json_fences(text: str) -> str:
    """Strip ```json ... ``` fences MiniMax wraps around JSON output."""
    return _FENCE_RE.sub("", text).strip()


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object found in `text`.

    Strategy:
      1. Try direct `json.loads` after stripping fences.
      2. If that fails, find the first balanced `{ ... }` substring and parse it.
      3. If both fail, raise `MiniMaxAPIError` — the caller (DSLGenerator) will
         retry or surface a schema-fail error to the user.
    """
    candidate = _strip_json_fences(text)
    try:
        result = json.loads(candidate)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Locate first balanced {...} substring. MiniMax sometimes adds prose before/after.
    start = candidate.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(candidate)):
            ch = candidate[end]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    snippet = candidate[start : end + 1]
                    try:
                        parsed = json.loads(snippet)
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break
                    break
        start = candidate.find("{", start + 1)

    raise MiniMaxAPIError(f"could not locate a JSON object in MiniMax response: {text[:200]!r}")


class MiniMaxClient:
    """Thin async wrapper around the MiniMax Chat Completions v2 endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.minimax_api_key
        self.api_base = (api_base or settings.minimax_api_base).rstrip("/")
        self.model = model or settings.minimax_model
        self.timeout_seconds = timeout_seconds

    def _endpoint(self) -> str:
        return f"{self.api_base}/v1/text/chatcompletion_v2"

    async def chat(
        self,
        *,
        system: str,
        user: str,
        few_shot: list[dict[str, str]] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> MiniMaxResponse:
        """Send a single-turn chat completion and return the parsed response.

        `few_shot` is a list of `{"role": ..., "content": ...}` dicts that will
        be inserted between the system message and the user message. This lets
        the DSLGenerator teach MiniMax the expected output shape per template.
        """
        if not self.api_key:
            raise MiniMaxAPIError("MINIMAX_API_KEY is not configured (set it in backend/.env)")

        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if few_shot:
            messages.extend(few_shot)
        messages.append({"role": "user", "content": user})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as http:
            try:
                resp = await http.post(self._endpoint(), json=payload, headers=headers)
            except httpx.HTTPError as e:
                raise MiniMaxAPIError(f"network error talking to MiniMax: {e}") from e

        if resp.status_code >= 400:
            # Surface the body's `base_resp.status_msg` when present — that is
            # what MiniMax uses for human-readable error info.
            try:
                err_body = resp.json()
                msg = err_body.get("base_resp", {}).get("status_msg") or err_body.get("message") or resp.text
            except Exception:
                msg = resp.text
            raise MiniMaxAPIError(f"MiniMax API error: {msg}", status_code=resp.status_code)

        data = resp.json()
        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code", 0) != 0:
            raise MiniMaxAPIError(
                f"MiniMax base_resp error: {base_resp.get('status_msg') or 'unknown'}",
                status_code=resp.status_code,
            )

        choices = data.get("choices") or []
        if not choices:
            raise MiniMaxAPIError(f"MiniMax returned no choices: {data}")

        content = choices[0].get("message", {}).get("content") or ""
        usage = data.get("usage") or {}
        parsed = _extract_json(content)

        return MiniMaxResponse(
            content=content,
            parsed=parsed,
            model=data.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------

_default_client: MiniMaxClient | None = None


def _get_default_client() -> MiniMaxClient:
    global _default_client
    if _default_client is None:
        _default_client = MiniMaxClient()
    return _default_client


async def minimax_call(
    *,
    system: str,
    user: str,
    few_shot: list[dict[str, str]] | None = None,
    json_mode: bool = True,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    """Functional helper that mirrors the `llm_caller` signature expected by
    `services/dify_toolkit/dsl_generator.py`.

    Returns the parsed JSON dict PLUS a hidden ``__usage__`` key containing the
    MiniMax token-usage dict (prompt/completion/total). DSLGenerator reads
    this key for cost tracking (PR-8). `json_mode` is a no-op kept for caller
    readability — see module docstring for rationale.
    """
    del json_mode  # see module docstring
    resp = await _get_default_client().chat(
        system=system,
        user=user,
        few_shot=few_shot,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    out = dict(resp.parsed)
    # Inject usage metadata so DSLGenerator can record it for cost tracking.
    # `__usage__` is consumed by DSLGenerator._call_llm_and_validate_schema
    # and stripped before saving to dify_generation_meta.
    out["__usage__"] = {
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "total_tokens": resp.total_tokens,
        "model": resp.model,
    }
    return out