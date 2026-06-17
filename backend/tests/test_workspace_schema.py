"""M10 G3 — Workspace Pydantic schema Fernet 加密测试。

覆盖范围 (M10 §9.1 PR2 hard gate #2):
    - ``Workspace.dify_api_key`` 加密存储,读出解密 = 原值
    - 幂等:重复加密 same ciphertext
    - 空 / None 不加密
    - WorkspaceRead 不暴露密文(只暴露 dify_api_key_set bool)
"""

import pytest

from core.encryption import (
    ENCRYPTION_MARKER,
    decrypt_api_key,
    encrypt_api_key,
)
from schemas.workspace import WorkspaceRead, WorkspaceUpdate


# ─── 1. Fernet 加密 roundtrip (PR2 hard gate #2) ────────────────────────────


def test_workspace_update_encrypts_dify_api_key_on_dump():
    """明文 dify_api_key 经 Pydantic model_dump 后变 ciphertext。"""
    plaintext = "dify-secret-key-abc123-XYZ"
    update = WorkspaceUpdate(dify_api_key=plaintext)

    dumped = update.model_dump()

    assert dumped["dify_api_key"] != plaintext, (
        f"model_dump 后 dify_api_key 应是密文, got {dumped['dify_api_key']!r}"
    )
    assert dumped["dify_api_key"].startswith(ENCRYPTION_MARKER), (
        f"dify_api_key 应有 {ENCRYPTION_MARKER!r} 前缀, "
        f"got {dumped['dify_api_key']!r}"
    )
    assert decrypt_api_key(dumped["dify_api_key"]) == plaintext


def test_workspace_update_encryption_is_idempotent():
    """已加密的 dify_api_key 二次加密是 noop。"""
    ciphertext = encrypt_api_key("round-2-secret")
    update = WorkspaceUpdate(dify_api_key=ciphertext)

    dumped = update.model_dump()
    assert dumped["dify_api_key"] == ciphertext, (
        f"二次加密应是 noop, but got {dumped['dify_api_key']!r} != {ciphertext!r}"
    )
    assert decrypt_api_key(dumped["dify_api_key"]) == "round-2-secret"


def test_workspace_update_none_and_empty_not_encrypted():
    """None / 空串不应被加密。"""
    update_none = WorkspaceUpdate(dify_api_key=None)
    assert update_none.model_dump()["dify_api_key"] is None

    update_empty = WorkspaceUpdate(dify_api_key="")
    assert update_empty.model_dump()["dify_api_key"] == ""


def test_workspace_update_does_not_encrypt_other_fields():
    """非 dify_api_key 字段保持原值,不被加密。"""
    update = WorkspaceUpdate(
        name="My Workspace",
        owner_email="me@example.com",
        dify_workspace_id="dify-ws-001",
        dify_enabled=True,
    )
    dumped = update.model_dump()
    assert dumped["name"] == "My Workspace"
    assert dumped["owner_email"] == "me@example.com"
    assert dumped["dify_workspace_id"] == "dify-ws-001"
    assert dumped["dify_enabled"] is True
    assert dumped["dify_api_key"] is None


# ─── 2. WorkspaceRead 不暴露密文 ────────────────────────────────────────────


def test_workspace_read_does_not_expose_dify_api_key_ciphertext():
    """GET 响应:有 dify_api_key_set bool,无密文字段。"""
    read = WorkspaceRead(
        id=1,
        name="Test WS",
        owner_email="me@example.com",
        dify_api_key_set=True,
        dify_workspace_id="dify-ws-001",
        dify_enabled=True,
    )
    dumped = read.model_dump()
    assert "dify_api_key" not in dumped, (
        f"WorkspaceRead 不应暴露 dify_api_key 字段, got {dumped}"
    )
    assert dumped["dify_api_key_set"] is True
    assert dumped["dify_workspace_id"] == "dify-ws-001"
    assert dumped["dify_enabled"] is True


def test_workspace_read_default_api_key_set_false():
    """没设 dify_api_key 时,dify_api_key_set 默认 False。"""
    read = WorkspaceRead(
        id=2,
        name="Plan B WS",
        owner_email="planb@example.com",
    )
    dumped = read.model_dump()
    assert dumped["dify_api_key_set"] is False
    assert dumped["dify_enabled"] is False


# ─── 3. Plan A / Plan B 拓扑语义 ───────────────────────────────────────────


def test_workspace_update_distinguishes_plan_a_vs_plan_b():
    """Plan A: dify_api_key 非空 + dify_workspace_id 必填。
    Plan B: dify_api_key = None (走共享 key)。
    """
    plan_a = WorkspaceUpdate(
        dify_api_key="real-dify-key-encrypted-on-dump",
        dify_workspace_id="dify-ws-plan-a",
        dify_enabled=True,
    )
    plan_a_dump = plan_a.model_dump()
    assert plan_a_dump["dify_api_key"].startswith(ENCRYPTION_MARKER)
    assert plan_a_dump["dify_workspace_id"] == "dify-ws-plan-a"
    assert plan_a_dump["dify_enabled"] is True

    plan_b = WorkspaceUpdate(
        dify_api_key=None,
        dify_workspace_id=None,
        dify_enabled=False,
    )
    plan_b_dump = plan_b.model_dump()
    assert plan_b_dump["dify_api_key"] is None
    assert plan_b_dump["dify_workspace_id"] is None
    assert plan_b_dump["dify_enabled"] is False
