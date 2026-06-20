"""M12 PR-2 — DSL generator.

Converts a user's free-text request into a validated Dify workflow YAML by:
  1. Asking MiniMax (or any injected `llm_caller`) for a JSON object matching
     the chosen template's `params_schema`.
  2. Validating the JSON against the Pydantic schema.
  3. Running `template.to_workflow(params)` to build a `Workflow`.
  4. Validating the resulting yml against `YmlValidator` (including the
     `forbid_patterns` env-var-injection check).
  5. Retrying up to `max_attempts` times on any failure.

The LLM **never sees yml**. It only fills template parameters; Python turns
those parameters into yml via the existing builder. This is the 60% → 95%
success-rate lever called out in plan §3 PR-2.

Usage:
    gen = DSLGenerator(llm_caller=minimax_call)
    yml, meta = await gen.generate(
        template_id="basic_chat",
        user_input={
            "user_requirements": "我需要一个电商退货客服",
            "params_overrides": {"temperature": 0.5},
        },
    )

`meta` is a dict containing `attempt`, `params`, and (when produced by the
real MiniMax client) `usage` for cost tracking.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from services.dify_toolkit.dsl_generator_exceptions import DSLGenerationError
from services.dify_toolkit.dsl_generator_few_shot import get_few_shot
from services.dify_toolkit.templates import TEMPLATES_BY_ID
from services.dify_toolkit.yml_validator import (
    ValidationError as YmlValidationError,
    validate_yaml,
)

logger = logging.getLogger(__name__)


# A typed alias for the LLM caller signature. The actual implementation is
# `services.llm_integration.minimax_call`. We accept any callable so the
# generator stays trivially mockable in tests.
LLMCaller = Callable[..., Awaitable[dict[str, Any]]]


# Patterns that MUST NOT appear in the generated yml. Used by YmlValidator via
# `forbid_patterns` to block attempts at template-time injection of env vars or
# sys secrets (plan §7 G3).
DEFAULT_FORBID_PATTERNS: list[str] = [
    "{{#env.",
    "{{#sys.env.",
    "{{#plugin.env.",
    "${ENV.",
    "process.env",
]


@dataclass(frozen=True)
class GenerationResult:
    """The output of a successful `DSLGenerator.generate` call."""

    yml_text: str
    params: dict[str, Any]
    attempt: int
    usage: dict[str, int] = field(default_factory=dict)


class DSLGenerator:
    """Async service that turns free-text user requests into Dify workflow yml."""

    def __init__(
        self,
        *,
        llm_caller: LLMCaller,
        max_attempts: int = 3,
        forbid_patterns: list[str] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.llm_caller = llm_caller
        self.max_attempts = max_attempts
        self.forbid_patterns = (
            list(forbid_patterns) if forbid_patterns is not None else list(DEFAULT_FORBID_PATTERNS)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        template_id: str,
        user_input: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        """Generate a yml string + metadata for `template_id`.

        Returns `(yml_text, metadata)` where `metadata` contains the final
        `attempt` count, the validated params dict, and any `usage` stats
        returned by the LLM caller. Raises `DSLGenerationError` on failure.
        """
        template = TEMPLATES_BY_ID.get(template_id)
        if template is None:
            raise DSLGenerationError(
                f"unknown template_id: {template_id!r}; "
                f"valid options: {sorted(TEMPLATES_BY_ID.keys())}",
                cause="unknown_template",
            )

        params_schema: type[BaseModel] = template.params_schema
        system_prompt = self._build_system_prompt(template, params_schema)
        few_shot = get_few_shot(template_id)
        user_prompt = self._build_user_prompt(user_input)

        last_error: DSLGenerationError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                typed, usage = await self._call_llm_and_validate_schema(
                    system=system_prompt,
                    user=user_prompt,
                    few_shot=few_shot,
                    params_schema=params_schema,
                )
            except DSLGenerationError as e:
                last_error = e
                logger.warning(
                    "DSLGenerator attempt %d/%d failed: %s (cause=%s)",
                    attempt, self.max_attempts, e, e.cause,
                )
                continue

            try:
                wf = template.to_workflow(typed)
            except Exception as e:
                # Builder bug — not the LLM's fault, but still no yml to return.
                raise DSLGenerationError(
                    f"template.to_workflow raised for {template_id}: {e}",
                    attempt=attempt,
                    cause="builder_error",
                ) from e

            yml_text = wf.to_yaml()

            try:
                validate_yaml(yml_text, forbid_patterns=self.forbid_patterns)
            except YmlValidationError as e:
                last_error = DSLGenerationError(
                    f"generated yml failed YmlValidator: {e}",
                    attempt=attempt,
                    cause="yml_invalid",
                )
                logger.warning(
                    "DSLGenerator attempt %d/%d yml invalid: %s",
                    attempt, self.max_attempts, e,
                )
                continue

            metadata: dict[str, Any] = {
                "attempt": attempt,
                "params": typed.model_dump(),
                "usage": usage,
            }
            return yml_text, metadata

        # All attempts exhausted.
        raise DSLGenerationError(
            f"DSL generation failed after {self.max_attempts} attempts: {last_error}",
            attempt=self.max_attempts,
            cause=last_error.cause if last_error else "unknown",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _call_llm_and_validate_schema(
        self,
        *,
        system: str,
        user: str,
        few_shot: list[dict[str, str]],
        params_schema: type[BaseModel],
    ) -> tuple[BaseModel, dict[str, int]]:
        """Single LLM round-trip: call → parse → pydantic-validate."""
        try:
            raw = await self.llm_caller(
                system=system,
                user=user,
                few_shot=few_shot,
                json_mode=True,
            )
        except Exception as e:
            raise DSLGenerationError(
                f"LLM call failed: {e}",
                cause="llm_call_failed",
            ) from e

        if not isinstance(raw, dict):
            raise DSLGenerationError(
                f"LLM returned non-dict payload: {type(raw).__name__}",
                cause="llm_bad_payload",
            )

        try:
            typed = params_schema.model_validate(raw)
        except ValidationError as e:
            raise DSLGenerationError(
                f"params_schema validation failed: {e}",
                cause="schema_invalid",
            ) from e

        # If the caller attached usage metadata (real MiniMax does, mocks may
        # not), capture it; otherwise empty dict.
        usage: dict[str, int] = {}
        meta = raw.get("__usage__")
        if isinstance(meta, dict):
            usage = {k: int(v) for k, v in meta.items() if isinstance(v, (int, float))}

        return typed, usage

    def _build_system_prompt(
        self,
        template: Any,
        params_schema: type[BaseModel],
    ) -> str:
        schema_json = json.dumps(params_schema.model_json_schema(), indent=2)
        return (
            "You are a workflow-parameter generator for the basjoo platform.\n"
            "You fill parameters for a Dify workflow template; Python code turns "
            "those parameters into the final workflow yml.\n"
            "\n"
            "Output STRICT JSON that matches the SCHEMA below. No prose, no "
            "markdown, no commentary. Do not output yaml, do not output fields "
            "that are not in SCHEMA.\n"
            "\n"
            f"TEMPLATE: {template.name} — {template.description}\n"
            "\n"
            "CONSTRAINTS:\n"
            "- variable references MUST use Dify `{{#node.field#}}` syntax when "
            "needed; the schema's `description` fields explain which values go where.\n"
            "- Do NOT include API keys, env vars, secrets, or PII.\n"
            "- For `knowledge_base_ids` and `tool_ids`, only use values the user "
            "explicitly listed — never invent new IDs.\n"
            "- For `model_name`, default to a sensible value (e.g. "
            "`gpt-4o-mini`) unless the user specifies another.\n"
            "- For numeric ranges (e.g. temperature 0.0–2.0), stay inside them.\n"
            "- Keep `system_prompt` under 2000 characters.\n"
            "\n"
            f"SCHEMA:\n{schema_json}\n"
        )

    def _build_user_prompt(self, user_input: dict[str, Any]) -> str:
        requirements = user_input.get("user_requirements") or ""
        overrides = user_input.get("params_overrides") or {}
        kb_ids = user_input.get("knowledge_base_ids") or []
        tool_ids = user_input.get("tool_ids") or []

        parts: list[str] = []
        if requirements.strip():
            parts.append(f"USER REQUEST:\n{requirements.strip()}\n")
        if kb_ids:
            parts.append(
                "USER-PROVIDED KNOWLEDGE BASE IDS (you MUST pick from this list, "
                f"do not invent new ones):\n{json.dumps(kb_ids, ensure_ascii=False)}\n"
            )
        if tool_ids:
            parts.append(
                "USER-PROVIDED TOOL IDS (you MUST pick from this list, "
                f"do not invent new ones):\n{json.dumps(tool_ids, ensure_ascii=False)}\n"
            )
        if overrides:
            parts.append(
                "USER-PROVIDED PARAM OVERRIDES (apply these verbatim, do not change):\n"
                f"{json.dumps(overrides, ensure_ascii=False, indent=2)}\n"
            )

        parts.append(
            "Return ONLY the JSON object. No prose before or after. No markdown fences."
        )
        return "\n".join(parts)


__all__ = [
    "DEFAULT_FORBID_PATTERNS",
    "DSLGenerator",
    "GenerationResult",
    "LLMCaller",
]