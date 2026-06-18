"""M11+ P0-A PR 3 — Backfill ``workspace.dify_enabled`` from settings.

Context:
    M10 G3 迁移 (migrations/m10_dify_fields.py) 给 ``workspaces`` 加了 4 个 Dify
    集成字段 (``dify_api_base`` / ``dify_api_key`` / ``dify_workspace_id`` /
    ``dify_enabled``),M11 PR2 又加了 6 个 provisioning 字段。但 ``dify_enabled``
    默认 0,只有新走 ``TenantService.register_tenant`` 的 workspace 会被设为 True。
    **历史 workspace**(在 M10 之前已存在,或在 M11 PR2 之前已完成 Dify 注册的)
    现在 ``dify_provisioning_status='ready'`` 但 ``dify_enabled=False`` ——
    Plan A 4-step create_agent 路径被总开关挡掉,dify_toolkit.Deployer 也调不通。

This script:
    1. 选所有 ``dify_provisioning_status='ready' AND dify_enabled=False`` 的 ws
    2. 把 ``dify_enabled`` 翻为 True
    3. 用 ``settings.dify_api_base`` 回填 ``dify_api_base``(若 NULL)
    4. 不回填 ``dify_admin_email`` / ``dify_admin_password_ref`` ——
       历史 ws 没有 system-level Dify admin 凭据,这些字段**必须**通过
       ``TenantService.register_tenant`` 或 M11+1 admin-provision 流程重置,
       backfill 不能伪造凭据。
    5. 写 ``audit_logs`` 一条 ``workspace.backfill_dify_enabled`` 记录
       (actor_user_id=0=system bootstrap user, correlation_id 由调用方传)。
       注:audit_logs.actor_user_id 是 NOT NULL INTEGER,所以用 0 表示系统动作
       (与 M11 PR1 的 system bootstrap user 约定一致)。

设计原则(与 PR 1-2 一致):
    - 不动凭据字段 (admin email/password) —— 这些只能来自真实 Dify 注册流
    - 幂等:重复执行只会让 ``UPDATE ... WHERE dify_enabled=False`` 命中 0 行,返回 success
    - dry-run 模式 (--dry-run) 只打印 SQL 不真写,admin 上线前先看
    - backup-before-write:改 DB 前强制 ``shutil.copy2`` 一份

CLI:
    python scripts/backfill_dify_enabled.py                       # 实跑
    python scripts/backfill_dify_enabled.py --dry-run             # 只打印
    python scripts/backfill_dify_enabled.py --db-path ./data/basjoo.db  # 指定 DB
    python scripts/backfill_dify_enabled.py --correlation-id <uuid>    # 自定义 audit id

Runbook: docs/runbooks/m11plus-p0a-backfill-dify-enabled.md
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone


POSSIBLE_PATHS = [
    "/app/data/basjoo.db",
    "./test.db",
    "./data/basjoo.db",
    "../data/basjoo.db",
]


def _resolve_db_path(explicit: str | None) -> str | None:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    return next((p for p in POSSIBLE_PATHS if os.path.exists(p)), None)


SELECT_SQL = """
    SELECT id, name, dify_tenant_id, dify_api_base, dify_admin_email
    FROM workspaces
    WHERE dify_provisioning_status = 'ready'
      AND dify_enabled = 0
    ORDER BY id
"""

UPDATE_SQL = """
    UPDATE workspaces
    SET dify_enabled = 1,
        dify_api_base = COALESCE(dify_api_base, ?)
    WHERE dify_provisioning_status = 'ready'
      AND dify_enabled = 0
"""

# 旧版 api_base 单独回填(若 dify_api_base 已设值,跳过),保留以防需单独跑
UPDATE_API_BASE_SQL = """
    UPDATE workspaces
    SET dify_api_base = ?
    WHERE dify_api_base IS NULL
      AND dify_provisioning_status = 'ready'
      AND dify_enabled = 1
"""

INSERT_AUDIT_SQL = """
    INSERT INTO audit_logs (
        tenant_id, actor_user_id, action, correlation_id,
        status, error_detail, created_at
    ) VALUES (?, ?, 'workspace.backfill_dify_enabled', ?, 'success', NULL, ?)
"""


def backfill(
    *,
    db_path: str,
    dify_api_base: str | None,
    correlation_id: str,
    dry_run: bool,
) -> dict:
    summary = {
        "rows_enabled": 0,
        "rows_api_base": 0,
        "audit_written": 0,
        "dry_run": dry_run,
        "db_path": db_path,
        "correlation_id": correlation_id,
    }

    if not dry_run:
        backup = db_path + ".before_backfill_dify_enabled"
        shutil.copy2(db_path, backup)
        print(f"[backup] → {backup}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_logs'"
        )
        audit_table_exists = cursor.fetchone() is not None
        if not audit_table_exists:
            print("[skip] audit_logs 表不存在 — 跳过 audit 写入 (迁移 m11 后重跑)")
            summary["audit_skipped"] = True

        cursor.execute(SELECT_SQL)
        candidates = cursor.fetchall()
        summary["candidates"] = [
            {
                "id": r[0], "name": r[1], "dify_tenant_id": r[2],
                "dify_api_base": r[3], "dify_admin_email": r[4],
            }
            for r in candidates
        ]
        print(f"[scan] 命中 {len(candidates)} 行待 backfill workspace:")
        for c in summary["candidates"]:
            print(
                f"  - id={c['id']:>3} name={c['name']!r:<30} "
                f"tenant={c['dify_tenant_id']} "
                f"api_base={c['dify_api_base']} "
                f"admin_email={c['dify_admin_email']}"
            )

        if dry_run:
            print("[dry-run] 不写 DB,仅展示命中行")
            return summary

        # Combined UPDATE: flip enabled=1 + COALESCE fill api_base in one pass.
        # (COALESCE: only fills when dify_api_base IS NULL, won't overwrite.)
        cursor.execute(UPDATE_SQL, (dify_api_base,))
        summary["rows_enabled"] = cursor.rowcount
        print(f"[update] dify_enabled=0→1 + api_base COALESCE fill: "
              f"{summary['rows_enabled']} 行")

        # rows_api_base 计数:扫一遍 enabled=1 且 api_base IS NULL (回填前状态)
        if dify_api_base:
            cursor.execute(
                "SELECT COUNT(*) FROM workspaces "
                "WHERE dify_provisioning_status='ready' "
                "  AND dify_enabled=1 AND dify_api_base = ?",
                (dify_api_base,),
            )
            summary["rows_api_base"] = cursor.fetchone()[0]
            print(
                f"[update] dify_api_base='{dify_api_base}' "
                f"(本次回填): {summary['rows_api_base']} 行"
            )

        if audit_table_exists:
            now = datetime.now(timezone.utc).isoformat()
            for c in summary["candidates"]:
                cursor.execute(
                    INSERT_AUDIT_SQL,
                    (str(c["id"]), 0, correlation_id, now),
                )
                summary["audit_written"] += 1
            print(f"[audit] 写入 {summary['audit_written']} 条 audit_logs")

        conn.commit()
        print("[commit] ✅ backfill 完成")
        return summary

    except Exception as e:
        conn.rollback()
        if not dry_run:
            print(f"[rollback] ❌ 失败: {e}")
            backup = db_path + ".before_backfill_dify_enabled"
            if os.path.exists(backup):
                shutil.copy2(backup, db_path)
                print(f"[restore] 已从 {backup} 恢复 DB")
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill workspace.dify_enabled for P0-A Plan A 切回。",
    )
    parser.add_argument(
        "--db-path", default=None,
        help="SQLite DB 路径 (默认按 POSSIBLE_PATHS 顺序探测)",
    )
    parser.add_argument(
        "--dify-api-base", default=os.environ.get("DIFY_API_BASE"),
        help="回填 dify_api_base (env DIFY_API_BASE 也可,默认 None = 不回填)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只 scan, 不真写 DB",
    )
    parser.add_argument(
        "--correlation-id", default=None,
        help="audit correlation_id (默认生成 UUID4)",
    )
    args = parser.parse_args()

    correlation_id = args.correlation_id or str(uuid.uuid4())
    db_path = _resolve_db_path(args.db_path)
    if not db_path:
        print(
            f"❌ 找不到 DB (尝试路径: {args.db_path or POSSIBLE_PATHS})",
            file=sys.stderr,
        )
        return 2

    print(f"[db] {db_path}")
    print(f"[correlation_id] {correlation_id}")
    print(f"[dry_run] {args.dry_run}")

    try:
        summary = backfill(
            db_path=db_path,
            dify_api_base=args.dify_api_base,
            correlation_id=correlation_id,
            dry_run=args.dry_run,
        )
    except Exception:
        return 1

    if summary["rows_enabled"] == 0 and not summary["candidates"]:
        print("\n[result] 无待 backfill workspace — DB 已就绪或未完成 M11 PR2")
    else:
        print(
            f"\n[result] enabled={summary['rows_enabled']} "
            f"api_base_filled={summary['rows_api_base']} "
            f"audit={summary['audit_written']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())