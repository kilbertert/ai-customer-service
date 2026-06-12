"""PR13: public chat-visitor attachment upload + content streaming.

Two-phase upload (decision #2):
  1. Client POSTs multipart to ``/api/v1/chat/attachments`` — receives
     ``att_<uuid>`` (status=pending).
  2. Client POSTs the regular ``/api/v1/chat`` with
     ``attachment_ids=[...]`` — the chat pipeline runs vision/Whisper
     synchronously and back-fills the message FK.

Public-visitor auth: ``enforce_widget_origin_whitelist`` with no admin
token (mirrors the existing public chat flow). Per-file size cap is
enforced in Python (the 10 MB main.py ``Content-Length`` guard is the
ceiling for the request envelope).
"""

from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import (
    ALLOWED_AUDIO_MIME,
    ALLOWED_IMAGE_MIME,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_DURATION_MS,
    MAX_IMAGE_BYTES,
)
from database import get_db
from models import Agent, ChatSession, MessageAttachment
from services.media_storage import MediaStorage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat-attachments"])


# ── helpers ────────────────────────────────────────────────────────────────


def _classify_mime(content_type: str | None) -> str | None:
    """Return ``"image"`` / ``"audio"`` if *content_type* is allow-listed, else ``None``."""
    if not content_type:
        return None
    ct = content_type.split(";", 1)[0].strip().lower()
    if ct in ALLOWED_IMAGE_MIME:
        return "image"
    if ct in ALLOWED_AUDIO_MIME:
        return "audio"
    return None


def _to_response_dict(att: MessageAttachment) -> dict:
    return {
        "id": att.id,
        "kind": att.kind,
        "mime_type": att.mime_type,
        "filename": att.filename,
        "size_bytes": att.size_bytes,
        "url": f"/api/v1/chat/attachments/{att.id}/content",
        "status": att.status,
        "transcript": att.transcript,
        "description": att.description,
        "duration_ms": att.duration_ms,
        "error_message": att.error_message,
        "created_at": att.created_at,
    }


async def _enforce_origin(agent: Agent, request: Request) -> None:
    from api.v1.endpoints import enforce_widget_origin_whitelist

    enforce_widget_origin_whitelist(agent, request, admin_user=None)


async def _resolve_or_create_chat_session(
    db: AsyncSession,
    agent: Agent,
    business_session_id: str,
    visitor_id: str,
) -> ChatSession:
    """Look up the existing active ChatSession for this visitor, or create one.

    Mirrors ``endpoints.get_or_create_chat_session`` but without the full
    ``ChatRequest`` plumbing — we only have the multipart form fields here.
    """
    result = await db.execute(
        select(ChatSession)
        .where(
            ChatSession.agent_id == agent.id,
            ChatSession.session_id == business_session_id,
            ChatSession.status != "closed",
        )
        .order_by(ChatSession.created_at.desc())
    )
    existing = result.scalars().first()
    if existing:
        return existing

    session = ChatSession(
        agent_id=agent.id,
        session_id=business_session_id,
        locale="zh-CN",
        visitor_id=visitor_id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── POST /api/v1/chat/attachments ──────────────────────────────────────────


@router.post("/chat/attachments", status_code=201)
async def upload_chat_attachment(
    request: Request,
    file=File(...),
    agent_id: str = Form(...),
    session_id: str = Form(...),
    visitor_id: str = Form(...),
    duration_ms: int | None = Form(None),
    db: AsyncSession = Depends(get_db),
):
    """Phase 1: persist raw bytes, return attachment id. No LLM call yet."""
    if not visitor_id.strip() or not session_id.strip():
        raise HTTPException(
            status_code=400, detail="session_id and visitor_id are required"
        )

    agent_row = (
        await db.execute(select(Agent).where(Agent.id == agent_id))
    ).scalar_one_or_none()
    if not agent_row:
        raise HTTPException(status_code=404, detail="Agent not found")
    await _enforce_origin(agent_row, request)

    blob = await file.read()
    kind = _classify_mime(file.content_type)
    if kind is None:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type: {file.content_type!r}",
        )
    if kind == "image" and len(blob) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB",
        )
    if kind == "audio" and len(blob) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds {MAX_AUDIO_BYTES // (1024 * 1024)}MB",
        )
    if (
        kind == "audio"
        and duration_ms is not None
        and duration_ms > MAX_AUDIO_DURATION_MS
    ):
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds {MAX_AUDIO_DURATION_MS // 1000}s",
        )

    session = await _resolve_or_create_chat_session(
        db, agent_row, session_id, visitor_id
    )

    sha = hashlib.sha256(blob).hexdigest()
    storage_key = MediaStorage().put(sha, blob)

    # Dedup within the same session: if the same sha was uploaded before,
    # return the existing row instead of inserting a duplicate.
    existing = (
        await db.execute(
            select(MessageAttachment)
            .where(
                MessageAttachment.session_id == session.id,
                MessageAttachment.sha256 == sha,
            )
            .order_by(MessageAttachment.created_at.desc())
        )
    ).scalars().first()
    if existing:
        return {"attachment": _to_response_dict(existing)}

    att = MessageAttachment(
        id=f"att_{uuid.uuid4().hex[:12]}",
        agent_id=agent_row.id,
        session_id=session.id,
        kind=kind,
        mime_type=(file.content_type or "").split(";", 1)[0].strip().lower(),
        filename=file.filename or "upload",
        size_bytes=len(blob),
        storage_key=storage_key,
        sha256=sha,
        duration_ms=duration_ms,
        status="pending",
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)
    logger.info(
        "attachment upload id=%s kind=%s size=%d agent=%s session=%s",
        att.id, att.kind, att.size_bytes, att.agent_id, att.session_id,
    )
    return {"attachment": _to_response_dict(att)}


# ── GET /api/v1/chat/attachments/{id}/content ──────────────────────────────


@router.get("/chat/attachments/{attachment_id}/content")
async def get_chat_attachment_content(
    attachment_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    att = (
        await db.execute(
            select(MessageAttachment).where(MessageAttachment.id == attachment_id)
        )
    ).scalar_one_or_none()
    if not att:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if att.status == "failed":
        raise HTTPException(status_code=410, detail="Attachment processing failed")

    agent_row = (
        await db.execute(select(Agent).where(Agent.id == att.agent_id))
    ).scalar_one_or_none()
    if not agent_row:
        raise HTTPException(status_code=404, detail="Agent not found")
    await _enforce_origin(agent_row, request)

    storage = MediaStorage()
    return StreamingResponse(
        storage.open_stream(att.storage_key),
        media_type=att.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{att.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
        },
    )


# TODO PR14: DELETE /api/v1/chat/attachments/{id} — not required for §1.6.
