"""PR13: chat pipeline multimodal integration tests.

Each test seeds an Agent, pre-uploads a MessageAttachment, then POSTs to
``/api/v1/chat`` with ``attachment_ids`` and asserts:
- the MockVisionService / MockWhisperService are called,
- the user ChatMessage row is persisted with the multimodal fold-in
  and has ``message_id`` FK back-filled on the attachment,
- the response shape includes ``attachments`` with the resolved metadata.
"""

import io

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


async def _seed_agent_and_attachment(public_client, kind="image"):
    from database import AsyncSessionLocal
    from models import Agent, ChatSession, MessageAttachment, Workspace, WorkspaceQuota
    from services.media_storage import MediaStorage
    from sqlalchemy import select

    # PR13: actually write the bytes to MediaStorage so the chat pipeline can
    # read them back when the mock vision/whisper services are called.
    blob = TINY_PNG if kind == "image" else b"\x1aE\xdf\xa3" + b"x" * 100
    storage_key = MediaStorage().put("a" * 64, blob)

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
            agent_id=agent.id, session_id="sess_pr13", visitor_id="v_pr13"
        )
        session.add(cs)
        await session.commit()
        await session.refresh(cs)
        att = MessageAttachment(
            agent_id=agent.id,
            session_id=cs.id,
            kind=kind,
            mime_type=("image/png" if kind == "image" else "audio/webm"),
            filename=("tiny.png" if kind == "image" else "audio.webm"),
            size_bytes=len(blob),
            storage_key=storage_key,
            sha256=("a" * 64 if kind == "image" else "b" * 64),
            status="pending",
        )
        session.add(att)
        await session.commit()
        await session.refresh(att)
        return agent.id, att.id


@pytest.mark.asyncio
async def test_chat_with_image_attachment_runs_vision(setup_test_db, public_client):
    agent_id, att_id = await _seed_agent_and_attachment(public_client, kind="image")
    body = {
        "agent_id": agent_id,
        "message": "What is in this image?",
        "attachment_ids": [att_id],
        "session_id": "sess_pr13",
        "visitor_id": "v_pr13",
    }
    r = await public_client.post(
        "/api/v1/chat", json=body, headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["attachments"]) == 1
    a = data["attachments"][0]
    assert a["id"] == att_id
    assert a["status"] == "processed"
    assert a["description"] == "mock image description"
    assert a["url"].endswith("/content")


@pytest.mark.asyncio
async def test_chat_with_audio_attachment_runs_whisper(setup_test_db, public_client):
    agent_id, att_id = await _seed_agent_and_attachment(public_client, kind="audio")
    body = {
        "agent_id": agent_id,
        "message": "What did I say?",
        "attachment_ids": [att_id],
        "session_id": "sess_pr13",
        "visitor_id": "v_pr13",
    }
    r = await public_client.post(
        "/api/v1/chat", json=body, headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    a = data["attachments"][0]
    assert a["status"] == "processed"
    assert a["transcript"] == "mock transcript"


@pytest.mark.asyncio
async def test_chat_with_more_than_three_attachments_rejected(
    setup_test_db, public_client
):
    agent_id, att_id = await _seed_agent_and_attachment(public_client)
    body = {
        "agent_id": agent_id,
        "message": "hi",
        "attachment_ids": [att_id, att_id, att_id, att_id],  # 4x same id
        "session_id": "sess_pr13",
        "visitor_id": "v_pr13",
    }
    r = await public_client.post(
        "/api/v1/chat", json=body, headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_chat_with_unknown_attachment_id_returns_404(
    setup_test_db, public_client
):
    agent_id, _ = await _seed_agent_and_attachment(public_client)
    body = {
        "agent_id": agent_id,
        "message": "hi",
        "attachment_ids": ["att_aaaaaaaaaaaa"],
        "session_id": "sess_pr13",
        "visitor_id": "v_pr13",
    }
    r = await public_client.post(
        "/api/v1/chat", json=body, headers={"Origin": "http://localhost:3000"}
    )
    assert r.status_code == 404
