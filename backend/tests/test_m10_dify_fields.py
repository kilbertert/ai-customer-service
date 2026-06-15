"""M10 G3 tests — Workspace/Agent Dify 4+4 字段。

覆盖范围 (M10-PROMPT.md §4):
    1. Migration 升级: 旧 DB 加 4 workspaces + 4 agents 字段
    2. Migration 幂等: 多次跑不报错
    3. 字段 default 值正确
    4. Plan A/B 拓扑判定:dify_api_key IS NULL → Plan B,IS NOT NULL → Plan A
"""

import sqlite3

import pytest

from models import Agent, Workspace
from sqlite_migrations import (
    _migrate_agents,
    _migrate_workspaces_dify_fields,
)


# ─── 1 & 2. Migration 升级 + 幂等 ─────────────────────────────────────────


def test_migration_adds_workspaces_dify_fields(setup_test_db):
    """M10 G3 迁移:旧 DB (无 dify_* 字段) 升级后 4 字段齐备。"""
    raw = sqlite3.connect(":memory:")
    cur = raw.cursor()
    cur.executescript("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL
        );
    """)
    _migrate_workspaces_dify_fields(cur)
    _migrate_agents(cur)
    raw.commit()

    cur.execute("PRAGMA table_info(workspaces)")
    ws_cols = {row[1] for row in cur.fetchall()}
    assert {"dify_api_base", "dify_api_key", "dify_workspace_id", "dify_enabled"} <= ws_cols, (
        f"workspaces 缺 dify 字段,got {ws_cols}"
    )

    cur.execute("PRAGMA table_info(agents)")
    agent_cols = {row[1] for row in cur.fetchall()}
    assert {
        "dify_workflow_id",
        "dify_user_prefix",
        "dify_inputs_schema",
        "dify_end_user_strategy",
    } <= agent_cols, (
        f"agents 缺 dify 字段,got {agent_cols}"
    )
    raw.close()


def test_migration_idempotent_workspaces(setup_test_db):
    """M10 G3 迁移:多次跑幂等(无 ALTER 错误)。"""
    raw = sqlite3.connect(":memory:")
    cur = raw.cursor()
    cur.executescript("""
        CREATE TABLE workspaces (
            id INTEGER PRIMARY KEY,
            name TEXT,
            owner_email TEXT UNIQUE
        );
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            workspace_id INTEGER NOT NULL
        );
    """)

    _migrate_workspaces_dify_fields(cur)
    _migrate_workspaces_dify_fields(cur)
    _migrate_workspaces_dify_fields(cur)
    raw.commit()

    cur.execute("PRAGMA table_info(workspaces)")
    ws_cols = {row[1] for row in cur.fetchall()}
    assert "dify_enabled" in ws_cols
    raw.close()


# ─── 3. 字段 default 值 ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_dify_enabled_default_false(setup_test_db):
    """新 Workspace 不设 dify_enabled → 默认 False (Plan B / 关闭)。"""
    from sqlalchemy import select

    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ws = Workspace(
            name="G3 Test WS",
            owner_email="g3-test@example.com",
        )
        session.add(ws)
        await session.commit()
        await session.refresh(ws)

        assert ws.dify_enabled is False
        assert ws.dify_api_base is None
        assert ws.dify_api_key is None
        assert ws.dify_workspace_id is None


@pytest.mark.asyncio
async def test_agent_dify_user_prefix_default(setup_test_db):
    """新 Agent 不设 dify_user_prefix → 默认 'agent-' (G1 双层编码)。"""
    from sqlalchemy import select

    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ws = (await session.execute(select(Workspace).order_by(Workspace.id).limit(1))).scalar_one()

        agent = Agent(
            workspace_id=ws.id,
            name="G3 Test Agent",
        )
        session.add(agent)
        await session.commit()
        await session.refresh(agent)

        assert agent.dify_user_prefix == "agent-"
        assert agent.dify_end_user_strategy == "dual_layer"
        assert agent.dify_workflow_id is None
        assert agent.dify_inputs_schema is None


# ─── 4. Plan A / Plan B 拓扑判定 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_workspace_plan_a_vs_plan_b_determination(setup_test_db):
    """dify_api_key IS NULL → Plan B (共享);IS NOT NULL → Plan A (独占)。"""
    from sqlalchemy import select

    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        ws_b = Workspace(
            name="G3 PlanB WS",
            owner_email="g3-planb@example.com",
            dify_api_key=None,
        )
        session.add(ws_b)
        await session.commit()
        await session.refresh(ws_b)
        assert ws_b.dify_api_key is None  # Plan B

        ws_a = Workspace(
            name="G3 PlanA WS",
            owner_email="g3-plana@example.com",
            dify_api_key="enc:gAAAAA-test-ciphertext",
            dify_workspace_id="dify-ws-uuid-001",
            dify_enabled=True,
        )
        session.add(ws_a)
        await session.commit()
        await session.refresh(ws_a)
        assert ws_a.dify_api_key is not None  # Plan A
        assert ws_a.dify_workspace_id == "dify-ws-uuid-001"
        assert ws_a.dify_enabled is True
