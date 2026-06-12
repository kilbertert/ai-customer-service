"""PR13: GET /api/v1/chat/messages returns per-message attachments."""

import io
import json

import pytest

from tests.conftest import public_client, setup_test_db  # noqa: F401

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x12\x99\x88"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_history_returns_per_message_attachments(setup_test_db, public_client):
    from database import AsyncSessionLocal
    from models import (
        Agent, ChatMessage, ChatSession, MessageAttachment,
        Workspace, WorkspaceQuota,
    )
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        ws = (await session.execute(select(Workspace).limit(1))).scalars().first()
        if ws is None:
            ws = Workspace(name="t", owner_email="t@t.com")
            session.add(ws)
            await session.flush()
            session.add(WorkspaceQuota(workspace_id=ws.id))
            await session.commit()
        agent = Agent(
            workspace_id=ws.id, name="t", model="gpt-4o-mini",
            api_base="https://api.openai.com/v1", provider_type="openai",
            jina_api_key="t", allowed_widget_origins=["http://localhost:3000"],
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        cs = ChatSession(
            agent_id=agent.id, session_id="sess_hist", visitor_id="v_hist"
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)
        user_msg = ChatMessage(session_id=cs.id, role="user", content="see image")
        session.add(user_msg)
        await session.commit()
        await session.refresh(user_msg)
        att = MessageAttachment(
            message_id=user_msg.id, agent_id=agent.id, session_id=cs.id,
            kind="image", mime_type="image/png", filename="tiny.png",
            size_bytes=len(TINY_PNG), storage_key="xx/yy", sha256="z" * 64,
            status="processed", description="A tiny test image",
        )
        session.add(att)
        await session.commit()

    r = await public_client.get(
        "/api/v1/chat/messages",
        params={"session_id": "sess_hist"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data) == 1
    assert len(data[0]["attachments"]) == 1
    a = data[0]["attachments"][0]
    assert a["id"] == att.id
    assert a["kind"] == "image"
    assert a["description"] == "A tiny test image"
    assert a["url"].endswith("/content")


@pytest.mark.asyncio
async def test_history_returns_empty_attachments_when_none(
    setup_test_db, public_client
):
    from database import AsyncSessionLocal
    from models import (
        Agent, ChatMessage, ChatSession, Workspace, WorkspaceQuota,
    )
    from sqlalchemy import select

    async with AsyncSessionLocal() as session:
        ws = (await session.execute(select(Workspace).limit(1))).scalars().first()
        if ws is None:
            ws = Workspace(name="t", owner_email="t@t.com")
            session.add(ws)
            await session.flush()
            session.add(WorkspaceQuota(workspace_id=ws.id))
            await session.commit()
        agent = Agent(
            workspace_id=ws.id, name="t", model="gpt-4o-mini",
            api_base="https://api.openai.com/v1", provider_type="openai",
            jina_api_key="t", allowed_widget_origins=["http://localhost:3000"],
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        cs = ChatSession(
            agent_id=agent.id, session_id="sess_noatt", visitor_id="v_hist"
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)
        session.add(ChatMessage(session_id=cs.id, role="user", content="no attachments"))
        await session.commit()

    r = await public_client.get(
        "/api/v1/chat/messages",
        params={"session_id": "sess_noatt"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data[0]["attachments"] == []
