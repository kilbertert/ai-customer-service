"""Whisper ASR service (PR13).

Calls OpenAI's hosted ``audio.transcriptions`` endpoint via the existing
``openai==1.54.0`` AsyncOpenAI client. Per-agent ``whisper_api_key`` /
``whisper_base_url`` / ``whisper_model`` override the global ``Settings``
fallback. The factory ``get_whisper_service(agent)`` returns ``None`` when
no key is configured anywhere; the chat pipeline substitutes a
placeholder string in that case (see ``endpoints._placeholder``).
"""

from __future__ import annotations

import io
from typing import Optional

from config import settings


class WhisperUnavailableError(Exception):
    """Raised when Whisper cannot service a request (no key, network, etc.)."""


class WhisperService:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "whisper-1",
    ):
        if not api_key:
            raise WhisperUnavailableError("Whisper API key is not configured")
        from openai import AsyncOpenAI  # local import to avoid startup cost

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30)
        self.model = model

    async def transcribe(
        self,
        audio_bytes: bytes,
        mime_type: str,
        language: Optional[str] = None,
    ) -> str:
        filename = {
            "audio/webm": "audio.webm",
            "audio/ogg": "audio.ogg",
            "audio/wav": "audio.wav",
            "audio/mpeg": "audio.mp3",
            "audio/mp4": "audio.m4a",
        }.get(mime_type, "audio.bin")
        try:
            resp = await self.client.audio.transcriptions.create(
                model=self.model,
                file=(filename, io.BytesIO(audio_bytes), mime_type),
                response_format="text",
                language=language,
            )
        except Exception as exc:
            raise WhisperUnavailableError(f"Whisper failed: {exc}") from exc
        text = getattr(resp, "text", None)
        if text is None:
            text = str(resp)
        return text.strip()


def get_whisper_service(agent) -> Optional[WhisperService]:
    """Resolve per-agent whisper config with env-var fallback.

    Returns ``None`` if no API key is configured anywhere — the chat
    pipeline treats that as "Whisper unavailable" and falls back to a
    placeholder user message.
    """
    from api.v1.endpoints import get_agent_plaintext_keys

    api_key = (
        get_agent_plaintext_keys(agent, attr="whisper_api_key")
        or settings.whisper_api_key
    )
    if not api_key:
        return None
    base_url = (getattr(agent, "whisper_base_url", None) or "").strip() or settings.whisper_base_url
    model = (getattr(agent, "whisper_model", None) or "").strip() or settings.whisper_model
    return WhisperService(api_key=api_key, base_url=base_url, model=model)
