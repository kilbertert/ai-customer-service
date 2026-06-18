"""Click CLI for dify_toolkit (P0-C PR 2)。

C1 安全收敛 (D8): 删 ``--ssh-host / --ssh-user / --ssh-password``,
改 ``--workspace-id``(从 DB 读 workspace 凭据,不走 SSH)。

子命令:
  - validate  <yml_file>              静态校验(纯本地,无凭据)
  - deploy    <yml_file> --workspace-id <id> [--actor-user-id <id>]
                                       部署 yml 到 workspace 关联的 Dify tenant
  - verify    <yml_file> --workspace-id <id> --agent-id <id>
                                       跑 yml 内嵌的 test cases, 调 /v1/chat-messages

``test-code`` 子命令(老 toolkit 用于跑 CodeNode Python 离线)在 PR 2 删 — 改用
``backend/tests/test_dify_toolkit_builder.py`` 的 ``test_yaml_round_trip`` 覆盖,
避免双轨维护。

凭据来源: ``settings.dify_db_url``(psycopg2 直连)+ ``Workspace.dify_api_base`` /
``Workspace.dify_admin_email`` / ``Workspace.dify_admin_password_ref``(Fernet 解密)。
无 env, 无 SSH key 文件, 无 AutoAddPolicy。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

import click
from sqlalchemy import select

from database import async_session_maker
from models import Agent, Workspace

from .deployer import Deployer
from .exceptions import DifyPublishError, DifySchemaError
from .verifier import TestCase, Verifier
from .yml_validator import validate_yaml

logger = logging.getLogger(__name__)


# ── validate ───────────────────────────────────────────────────────────────
@click.command()
@click.argument("yml_file", type=click.Path(exists=True, dir_okay=False))
def validate(yml_file: str) -> None:
    """静态校验 yml 文件 — 纯本地,无凭据。"""
    text = Path(yml_file).read_text(encoding="utf-8")
    try:
        validate_yaml(text)
    except Exception as e:  # noqa: BLE001
        click.echo(f"FAIL: {e}", err=True)
        sys.exit(1)
    click.echo(f"OK: {yml_file}")


# ── deploy ─────────────────────────────────────────────────────────────────
@click.command()
@click.argument("yml_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--workspace-id", required=True, type=int,
              help="basjoo Workspace.id (从 DB 拿 Dify 凭据 + tenant_id)")
@click.option("--actor-user-id", type=int, default=1,
              help="audit actor (默认 1 = system bootstrap user)")
@click.option("--correlation-id", default=None,
              help="audit correlation_id (默认自动生成 UUID)")
def deploy(
    yml_file: str,
    workspace_id: int,
    actor_user_id: int,
    correlation_id: str | None,
) -> None:
    """部署 yml 到 workspace 关联的 Dify tenant (无 SSH)。"""
    text = Path(yml_file).read_text(encoding="utf-8")
    correlation_id = correlation_id or str(uuid.uuid4())

    asyncio.run(_deploy_async(
        yml=text,
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        correlation_id=correlation_id,
    ))


async def _deploy_async(
    *,
    yml: str,
    workspace_id: int,
    actor_user_id: int,
    correlation_id: str,
) -> None:
    async with async_session_maker() as session:
        workspace = await session.get(Workspace, workspace_id)
        if not workspace:
            click.echo(f"workspace_id={workspace_id} not found", err=True)
            sys.exit(2)
        if not getattr(workspace, "dify_enabled", False):
            click.echo(
                f"workspace_id={workspace_id} dify_enabled=False "
                f"(P0-A 未落地 — 跑 scripts/backfill_dify_enabled.py)",
                err=True,
            )
            sys.exit(3)

        # 拿 agent → app_id (取第一个 dify_app_id 非空的 agent 当默认)
        result = await session.execute(
            select(Agent).where(
                Agent.workspace_id == workspace_id,
                Agent.dify_app_id.is_not(None),
            ).limit(1)
        )
        agent = result.scalar_one_or_none()
        if not agent or not agent.dify_app_id:
            click.echo(
                f"workspace_id={workspace_id} 无 dify_app_id 已设置的 agent",
                err=True,
            )
            sys.exit(4)

        deployer = Deployer.from_workspace(workspace)
        try:
            deploy_result = await deployer.deploy(
                yml=yml,
                app_id=agent.dify_app_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
                db_session=session,
                tenant_id_for_audit=str(workspace_id),
            )
        except DifySchemaError as e:
            click.echo(
                f"FAIL: schema mismatch — missing={e.missing} actual={e.actual}",
                err=True,
            )
            sys.exit(10)
        except DifyPublishError as e:
            click.echo(f"FAIL: publish — {e}", err=True)
            sys.exit(11)

        click.echo(
            f"OK: app_id={deploy_result.app_id} nodes={deploy_result.nodes} "
            f"rows_updated={deploy_result.rows_updated} "
            f"correlation_id={correlation_id}"
        )


# ── verify ─────────────────────────────────────────────────────────────────
@click.command()
@click.argument("yml_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--workspace-id", required=True, type=int)
@click.option("--agent-id", required=True, type=int,
              help="Agent.id (拿 dify_api_key)")
def verify(yml_file: str, workspace_id: int, agent_id: int) -> None:
    """跑 yml 内嵌 ``tests:`` 块,调 /v1/chat-messages 校验结果。"""
    text = Path(yml_file).read_text(encoding="utf-8")

    try:
        wf_dict = _Workflow_to_dict(text)
        cases_raw = wf_dict.get("tests", [])
        cases = [_to_test_case(c) for c in cases_raw]
    except Exception as e:  # noqa: BLE001
        click.echo(f"FAIL: parse tests block — {e}", err=True)
        sys.exit(1)

    if not cases:
        click.echo("FAIL: yml 无 tests 块 (或在 tests:[] 里加 cases)", err=True)
        sys.exit(1)

    asyncio.run(_verify_async(
        yml=text, workspace_id=workspace_id,
        agent_id=agent_id, cases=cases,
    ))


async def _verify_async(
    *,
    yml: str,
    workspace_id: int,
    agent_id: int,
    cases: list[TestCase],
) -> None:
    async with async_session_maker() as session:
        workspace = await session.get(Workspace, workspace_id)
        if not workspace:
            click.echo(f"workspace_id={workspace_id} not found", err=True)
            sys.exit(2)
        agent = await session.get(Agent, agent_id)
        if not agent or agent.workspace_id != workspace_id:
            click.echo(
                f"agent_id={agent_id} 不属于 workspace_id={workspace_id}",
                err=True,
            )
            sys.exit(3)
        if not agent.dify_api_key:
            click.echo(
                f"agent_id={agent_id} 缺 dify_api_key (provisioning 未完成)",
                err=True,
            )
            sys.exit(4)

        verifier = Verifier.from_workspace(workspace, api_key=agent.dify_api_key)
        report = await verifier.run(cases)

    click.echo(str(report))
    for r in report.results:
        if not r.passed:
            click.echo(
                f"  [{r.case_id}] FAIL — {r.description}\n"
                f"    mismatches: {r.mismatches}\n"
                f"    actual:     {r.actual}\n"
                f"    error:      {r.error}",
                err=True,
            )
    if report.failed:
        sys.exit(1)


# ── CLI group ──────────────────────────────────────────────────────────────
@click.group()
def cli() -> None:
    """Dify toolkit CLI — build / validate / deploy / verify workflows."""
    pass


cli.add_command(validate)
cli.add_command(deploy)
cli.add_command(verify)


# ── Helpers ────────────────────────────────────────────────────────────────
def _Workflow_to_dict(yml_text: str) -> dict:
    """Parse yml → dict (用 PyYAML 而非 ``Workflow.to_dict()``, 因为 yml 是
    source of truth,可能含 ``tests:`` 块不在 builder 模型里)。
    """
    import yaml as _yaml
    return _yaml.safe_load(yml_text) or {}


def _to_test_case(raw: dict) -> TestCase:
    """Convert a ``tests:`` entry dict → ``TestCase``."""
    return TestCase(
        case_id=raw.get("case_id") or raw.get("id") or "unnamed",
        text=raw.get("text", ""),
        expected=raw.get("expected", {}),
        user_id=raw.get("user_id", ""),
        description=raw.get("description", ""),
    )


# Allow ``python -m services.dify_toolkit.cli``
if __name__ == "__main__":
    cli()