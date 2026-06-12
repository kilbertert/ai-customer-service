"""Vision LLM service (PR13).

Calls a vision-capable chat-completions endpoint (default ``gpt-4o``) via
the existing ``openai==1.54.0`` AsyncOpenAI client. The image is sent
inline as a base64 ``data:`` URL inside the OpenAI multimodal
``content`` array.

Per-agent ``vision_api_key`` / ``vision_base_url`` / ``vision_model``
override the global ``Settings`` fallback. The factory
``get_vision_service(agent)`` returns ``None`` when no key is configured
anywhere; the chat pipeline substitutes a placeholder string in that
case (see ``endpoints._placeholder``).
"""

from __future__ import annotations

import base64
from typing import Optional

from config import settings


class VisionUnavailableError(Exception):
    """Raised when the vision LLM cannot service a request."""


class VisionService:
    _PROMPT = (
        "Describe this image in detail. If it is a screenshot of a UI, list all "
        "visible text. If it is a photo, describe the scene, objects, and any "
        "text. If it is a document, transcribe the text. Be concise but specific."
    )

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
    ):
        if not api_key:
            raise VisionUnavailableError("Vision API key is not configured")
        from openai import AsyncOpenAI  # local import to avoid startup cost

        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=30)
        self.model = model

    async def describe_image(self, image_bytes: bytes, mime_type: str) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{b64}"
                                },
                            },
                        ],
                    }
                ],
                max_tokens=600,
            )
        except Exception as exc:
            raise VisionUnavailableError(f"Vision failed: {exc}") from exc
        content = resp.choices[0].message.content or ""
        return content.strip()


def get_vision_service(agent) -> Optional[VisionService]:
    """Resolve per-agent vision config with env-var fallback.

    Returns ``None`` if no API key is configured anywhere — the chat
    pipeline treats that as "Vision unavailable" and falls back to a
    placeholder user message.
    """
    from api.v1.endpoints import get_agent_plaintext_keys

    api_key = (
        get_agent_plaintext_keys(agent, attr="vision_api_key")
        or settings.vision_api_key
    )
    if not api_key:
        return None
    base_url = (getattr(agent, "vision_base_url", None) or "").strip() or settings.vision_base_url
    model = (getattr(agent, "vision_model", None) or "").strip() or settings.vision_model
    return VisionService(api_key=api_key, base_url=base_url, model=model)
