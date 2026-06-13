from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional


class ChatResponse(BaseModel):
    assistant_text: str = Field(..., description="Answer text from Coze workflow")
    image_id: Optional[str] = Field(default=None, description="Uploaded image file id (if any)")
    audio_id: Optional[str] = Field(default=None, description="Uploaded audio file id (if any)")
    raw: Optional[dict] = Field(default=None, description="Raw workflow response (optional)")

