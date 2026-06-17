"""M11 PR3 — 后台 cron: 每 5 分钟扫描 failed workspace 自动重试 provisioning。

Spec 路径: ``backend/scheduler/tenant_provisioning_retry.py``
注: 现有 scheduler 在 ``backend/services/scheduler.py``(单文件), 新建独立
目录 ``backend/scheduler/`` 是为 M11 起新模块, 不动老 scheduler。
"""
import asyncio
import logging
import uuid

from sqlalchemy import select

from database import AsyncSessionLocal
from models import AuditLog, Workspace
from services.tenant_service import TenantService

logger = logging.getLogger(__name__)

# 默认扫描间隔, 可被 settings.tenant_provisioning_retry_interval_seconds 覆盖
DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 3


async def retry_failed_provisioning() -> int:
    """扫描 ``status == 'failed'`` 且 attempts < 3 的 workspace, 逐个重试。

    返回本轮处理成功的 workspace 数(供 cron 监控)。
    """
    processed = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Workspace).where(
                Workspace.dify_provisioning_status == "failed",
                Workspace.dify_provisioning_attempts < DEFAULT_MAX_ATTEMPTS,
            )
        )
        workspaces = result.scalars().all()
        for ws in workspaces:
            correlation_id = str(uuid.uuid4())
            logger.info(
                "Auto-retry workspace_id=%s attempt=%s",
                ws.id,
                ws.dify_provisioning_attempts + 1,
            )
            service = TenantService(db)
            outcome = await service.retry_provisioning(ws.id, correlation_id)
            db.add(AuditLog(
                tenant_id=str(ws.id),
                actor_user_id=0,
                action="tenant.auto_retry",
                correlation_id=correlation_id,
                status="success" if outcome.get("success") else "failed",
                error_detail=(outcome.get("error") or "")[:2000] or None,
            ))
            await db.commit()
            if outcome.get("success"):
                processed += 1
    return processed


async def schedule_tenant_provisioning_retry(
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
) -> None:
    """长循环: 间隔 ``interval_seconds`` 秒跑一次 ``retry_failed_provisioning``。"""
    while True:
        try:
            await retry_failed_provisioning()
        except Exception as e:
            logger.exception("Auto-retry cron failed: %s", e)
        await asyncio.sleep(interval_seconds)
