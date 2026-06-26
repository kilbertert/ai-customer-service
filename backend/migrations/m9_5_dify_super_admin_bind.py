"""M9.5+ migration — Super admin Dify auto-bind from settings.

Idempotent: 把 Default Workspace (id=1) 绑到 settings 里的 Dify 配置。
如果 workspace 已经是 dify_enabled=1,跳过(force=False);如要重新绑定传 force=True。

依赖 settings 的字段:
    - settings.dify_enable_auto_provision (master switch)
    - settings.dify_api_base
    - settings.dify_admin_email
    - settings.dify_admin_password
    - settings.dify_default_workspace_id

如果 settings 没配置(默认值空字符串/False),migration 是 no-op(只打 log,不报错)。
这是 fail-graceful 的设计:Dify 配置缺失不应该阻塞数据库迁移。

执行:
    docker exec basjoo-backend-dev python3 /app/migrations/m9_5_dify_super_admin_bind.py
    # 或通过 alembic 框架 (未来)
"""

import os
import sqlite3
import sys


def get_db_path():
    candidates = ["/app/data/basjoo.db", "./data/basjoo.db", "./test.db"]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def get_settings():
    """从环境变量读 Dify 配置(避免直接依赖 pydantic_settings 在 migration 里)。

    M9.5+ 与 backend/.env 的 key 对齐:
        DIFY_API_BASE / DIFY_ADMIN_EMAIL / DIFY_ADMIN_PASSWORD / DIFY_DEFAULT_WORKSPACE_ID / DIFY_ENABLE_AUTO_PROVISION
    """
    return {
        "enable": os.environ.get("DIFY_ENABLE_AUTO_PROVISION", "").lower() == "true",
        "api_base": os.environ.get("DIFY_API_BASE", ""),
        "admin_email": os.environ.get("DIFY_ADMIN_EMAIL", ""),
        "admin_password": os.environ.get("DIFY_ADMIN_PASSWORD", ""),
        "default_workspace_id": os.environ.get("DIFY_DEFAULT_WORKSPACE_ID", ""),
    }


def encrypt_password(plaintext: str) -> str:
    """Fernet 加密。复用 backend.core.encryption.encrypt_api_key 逻辑。

    这里复制一份而不是 import,是因为 alembic migration 通常在 sys.path 之外的早期环境跑。
    """
    from cryptography.fernet import Fernet

    enc_key_path = os.environ.get(
        "ENCRYPTION_KEY_FILE", "/app/data/.encryption_key"
    )
    if not os.path.exists(enc_key_path):
        # Auto-generate if missing
        from cryptography.fernet import Fernet as _F

        key = _F.generate_key()
        os.makedirs(os.path.dirname(enc_key_path), exist_ok=True)
        with open(enc_key_path, "wb") as f:
            f.write(key)
        # chmod 0600 (best effort, may fail as non-root)
        try:
            os.chmod(enc_key_path, 0o600)
        except OSError:
            pass

    with open(enc_key_path, "rb") as f:
        key = f.read().strip()
    fernet = Fernet(key)
    return f"enc:{fernet.encrypt(plaintext.encode()).decode()}"


def migrate(force: bool = False):
    db_path = get_db_path()
    if not db_path:
        print(f"[M9.5] No basjoo.db found in candidates, skipping", file=sys.stderr)
        return False

    settings = get_settings()
    if not settings["enable"]:
        print(
            "[M9.5] DIFY_ENABLE_AUTO_PROVISION not set to 'true', skipping (no-op)"
        )
        return False

    missing = [k for k in ("api_base", "admin_email", "admin_password", "default_workspace_id") if not settings[k]]
    if missing:
        print(f"[M9.5] Missing required env: {missing}, skipping (no-op)")
        return False

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        # Find Default Workspace (id=1)
        cur.execute("SELECT id, name, dify_enabled, dify_workspace_id FROM workspaces WHERE id=1")
        row = cur.fetchone()
        if not row:
            print("[M9.5] No workspace id=1 found, skipping")
            return False

        ws_id, name, current_enabled, current_dify_ws = row
        if current_enabled and not force:
            print(
                f"[M9.5] Workspace {ws_id} already Plan A "
                f"(dify_workspace_id={current_dify_ws}), skipping. "
                f"Pass force=True to re-bind."
            )
            return False

        encrypted_pw = encrypt_password(settings["admin_password"])

        cur.execute(
            """
            UPDATE workspaces SET
                dify_enabled = 1,
                dify_api_base = ?,
                dify_admin_email = ?,
                dify_admin_password_ref = ?,
                dify_workspace_id = ?,
                dify_provisioning_status = 'ready',
                dify_provisioning_attempts = 0,
                dify_provisioning_last_error = NULL
            WHERE id = 1
            """,
            (
                settings["api_base"],
                settings["admin_email"],
                encrypted_pw,
                settings["default_workspace_id"],
            ),
        )
        conn.commit()
        print(
            f"[M9.5] ✓ Workspace {ws_id} ({name!r}) bound to Dify workspace "
            f"{settings['default_workspace_id']}"
        )
        return True
    except Exception as e:
        conn.rollback()
        print(f"[M9.5] ✗ Migration failed: {e}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    force = "--force" in sys.argv
    success = migrate(force=force)
    sys.exit(0 if success else 1)