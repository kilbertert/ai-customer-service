"""Exceptions raised by the DSL generator pipeline."""

from __future__ import annotations


class DSLGenerationError(RuntimeError):
    """Raised when DSL generation fails after exhausting all retries.

    Causes:
      - LLM call failed (network / auth / API error)
      - LLM returned text that could not be parsed as JSON
      - LLM JSON did not match the template's `params_schema`
      - Built workflow failed `YmlValidator.validate_yaml`
      - The yml contains a forbidden pattern (e.g. `{{#env.X#}}`)
    """

    def __init__(
        self,
        message: str,
        *,
        attempt: int | None = None,
        cause: str | None = None,
    ) -> None:
        super().__init__(message)
        self.attempt = attempt
        self.cause = cause