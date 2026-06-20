"""M12 PR-4 — Backfill ``agents.template_id`` = NULL for existing rows.

Context:
    M12 PR-4 added 3 new columns to the ``agents`` table:
    ``template_id``, ``template_params``, ``dify_generation_meta``.
    All are nullable, so SQLite + SQLAlchemy auto-create them with NULL.
    Existing agents (created before this migration) have NULL ``template_id``
    and that is the **correct** value: they were created via the pre-wizard
    single-form path, not via the new DSLGenerator path. The application code
    treats NULL as "fall back to the PR-0 minimal graph" (see
    ``_provision_dify_app``).

This script is a no-op migration helper:
    1. Counts how many agents have ``template_id IS NULL`` (expected: 100%)
    2. Asserts the column exists (sanity check vs DB schema drift)
    3. Does NOT mass-update existing rows — leaving NULL preserves the
       "which path created this agent?" distinction that the front-end uses.

Idempotent. Safe to re-run. Use ``--dry-run`` for first execution.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make ``backend/`` importable when this file is run as ``python scripts/...``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from models import Agent  # noqa: E402


async def run(dry_run: bool = False) -> int:
    from database import async_session_maker  # local import to avoid early DB open

    total = 0
    null_template_id = 0
    non_null_template_id = 0

    async with async_session_maker() as session:
        stmt = select(Agent.id, Agent.template_id)
        result = await session.execute(stmt)
        rows = result.all()

    total = len(rows)
    null_template_id = sum(1 for _id, tid in rows if tid is None)
    non_null_template_id = total - null_template_id

    print(f"[backfill_template_id] total agents = {total}")
    print(f"[backfill_template_id] NULL template_id = {null_template_id}")
    print(f"[backfill_template_id] non-NULL template_id = {non_null_template_id}")

    if dry_run:
        print("[backfill_template_id] DRY-RUN: no DB writes. Re-run without --dry-run to apply.")
    else:
        # Explicit no-op: existing rows are correct as-is.
        print("[backfill_template_id] no-op: existing rows kept NULL (correct for pre-wizard agents).")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts only; do not modify the database.",
    )
    args = parser.parse_args()
    return asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())