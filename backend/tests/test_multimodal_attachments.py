"""PR13: POST /api/v1/chat/attachments + GET /api/v1/chat/attachments/{id}/content
integration tests against the dev backend via ``public_client``.

Each test gets a fresh isolated SQLite DB via conftest's ``setup_test_db``,
then seeds a default Agent with a permissive ``allowed_widget_origins``.
"""

import hashlib
import io

import pytest

from config import ALLOWED_IMAGE_MIME, MAX_IMAGE_BYTES
from tests.conftest import public_client, setup_test_db  # noqa: F401  (fixtures)


TINY_PNG = (
    b"\x89PNG\r\n\x1a\n"  # PNG magic
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa3\x12\x99\x88"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


async def _seed_agent_with_origins(origins=("http://localhost:3000",)):
    """Insert a test agent with allowed_widget_origins set.

    `enforce_widget_origin_whitelist` matches full origin strings
    (scheme + host + port) — "*" is NOT a wildcard in that match set.
    Pass a tuple of full origins. Defaults to the URL our tests use.
    """
    """Insert a test agent with allowed_widget_origins set."""
    from database import AsyncSessionLocal
    from models import Agent, Workspace, WorkspaceQuota
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
            workspace_id=ws.id,
            name="t",
            model="gpt-4o-mini",
            api_base="https://api.openai.com/v1",
            provider_type="openai",
            jina_api_key="test_jina",
            allowed_widget_origins=list(origins),
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        return agent.id


@pytest.mark.asyncio
async def test_upload_image_happy_path(setup_test_db, public_client, monkeypatch):
    agent_id = await _seed_agent_with_origins()
    files = {"file": ("tiny.png", io.BytesIO(TINY_PNG), "image/png")}
    data = {"agent_id": agent_id, "session_id": "sess_demo", "visitor_id": "v_demo"}
    r = await public_client.post(
        "/api/v1/chat/attachments",
        files=files,
        data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["attachment"]["kind"] == "image"
    assert body["attachment"]["mime_type"] == "image/png"
    assert body["attachment"]["filename"] == "tiny.png"
    assert body["attachment"]["size_bytes"] == len(TINY_PNG)
    assert body["attachment"]["status"] == "pending"
    assert body["attachment"]["id"].startswith("att_")
    assert body["attachment"]["url"].endswith("/content")


@pytest.mark.asyncio
async def test_upload_oversize_rejected(setup_test_db, public_client):
    agent_id = await _seed_agent_with_origins()
    big = b"\x89PNG\r\n\x1a\n" + b"x" * (MAX_IMAGE_BYTES + 1)
    files = {"file": ("big.png", io.BytesIO(big), "image/png")}
    data = {"agent_id": agent_id, "session_id": "sess_demo", "visitor_id": "v_demo"}
    r = await public_client.post(
        "/api/v1/chat/attachments",
        files=files,
        data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 413, r.text


@pytest.mark.asyncio
async def test_upload_unsupported_mime_rejected(setup_test_db, public_client):
    agent_id = await _seed_agent_with_origins()
    files = {"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")}
    data = {"agent_id": agent_id, "session_id": "sess_demo", "visitor_id": "v_demo"}
    r = await public_client.post(
        "/api/v1/chat/attachments",
        files=files,
        data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 415, r.text


@pytest.mark.asyncio
async def test_upload_dedup_within_session(setup_test_db, public_client):
    agent_id = await _seed_agent_with_origins()
    data = {"agent_id": agent_id, "session_id": "sess_dedup", "visitor_id": "v_demo"}
    files = {"file": ("tiny.png", io.BytesIO(TINY_PNG), "image/png")}
    r1 = await public_client.post(
        "/api/v1/chat/attachments", files=files, data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    r2 = await public_client.post(
        "/api/v1/chat/attachments", files=files, data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["attachment"]["id"] == r2.json()["attachment"]["id"]


@pytest.mark.asyncio
async def test_get_content_happy_path(setup_test_db, public_client):
    agent_id = await _seed_agent_with_origins()
    data = {"agent_id": agent_id, "session_id": "sess_get", "visitor_id": "v_demo"}
    files = {"file": ("tiny.png", io.BytesIO(TINY_PNG), "image/png")}
    up = await public_client.post(
        "/api/v1/chat/attachments", files=files, data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    att_id = up.json()["attachment"]["id"]
    r = await public_client.get(
        f"/api/v1/chat/attachments/{att_id}/content",
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.content == TINY_PNG


@pytest.mark.asyncio
async def test_get_content_404_for_unknown_id(setup_test_db, public_client):
    r = await public_client.get(
        "/api/v1/chat/attachments/att_doesnotexist1/content",
        headers={"Origin": "http://localhost:3000"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_upload_missing_session_visitor(setup_test_db, public_client):
    agent_id = await _seed_agent_with_origins()
    files = {"file": ("tiny.png", io.BytesIO(TINY_PNG), "image/png")}
    data = {"agent_id": agent_id}  # missing session_id + visitor_id
    r = await public_client.post(
        "/api/v1/chat/attachments", files=files, data=data,
        headers={"Origin": "http://localhost:3000"},
    )
    # FastAPI's Form() validation rejects missing required fields with 422
    # before the handler runs. (Earlier behavior was 400 from the explicit
    # check in the handler, but Form-level validation fires first.)
    assert r.status_code == 422
