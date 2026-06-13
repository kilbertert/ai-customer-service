from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ChatResponse(BaseModel):
    """对外响应结构 — 与 app/schemas.py 同形,前端可零改动切换。"""

    assistant_text: str = Field(..., description="Final answer text from Dify workflow")
    image_id: Optional[str] = Field(default=None, description="Uploaded image upload_file_id (if any)")
    audio_id: Optional[str] = Field(default=None, description="Uploaded audio upload_file_id (if any)")
    raw: Optional[dict] = Field(default=None, description="Raw workflow response (optional)")
