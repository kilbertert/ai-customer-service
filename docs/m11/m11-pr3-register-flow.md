# M11 PR3 — basjoo 注册流后端

> **依赖**:PR1 + PR2
> **工作量**:0.8 周 1 人

---

## 1. 范围

实现 B 端租户自助注册的后端链路:
- `/api/v1/tenants/register` POST 端点
- `TenantService` 业务逻辑(2 阶段提交 + Dify 调用)
- 后台重试 cron
- `DifyAdminClient` 调用 wrapper

**总改动**:~+400 行 Python,5 个新文件 + 3 个改文件。

---

## 2. 新增文件

### 2.1 `backend/api/v1/tenants.py`(端点)

```python
"""B 端租户自助注册 API。

仅在系统 bootstrap 后开放(检测 AdminUser 总数 >= 1 时关闭 /register)。
与现有 /api/v1/auth/register(bootstrap)解耦,各自独立。
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.deps import get_db, get_current_user_optional
from models import AdminUser, Workspace
from services.tenant_service import TenantService
from middleware.rate_limit import rate_limit_by_ip_and_email
from security.email_blacklist import is_blacklisted_email


router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])


class TenantRegisterRequest(BaseModel):
    workspace_name: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    terms_accepted: bool = Field(default=False)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        from libs.password import valid_password  # noqa
        if not valid_password(v):
            raise ValueError("password complexity insufficient")
        return v


class TenantRegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    workspace_id: int
    dify_initial_password: str
    provisioning_status: str
    correlation_id: str


@router.post("/register", response_model=TenantRegisterResponse)
@rate_limit_by_ip_and_email(ip_limit=5, email_limit=3, window_seconds=3600)
async def register_tenant(
    req: TenantRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    if is_blacklisted_email(req.email):
        raise HTTPException(status_code=400, detail="Email domain not allowed")
    if not req.terms_accepted:
        raise HTTPException(status_code=400, detail="Terms must be accepted")

    existing = await db.execute(select(AdminUser).where(AdminUser.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    signup_idempotency_key = str(uuid.uuid7())
    correlation_id = str(uuid.uuid7())
    service = TenantService(db)
    result = await service.register_tenant(
        workspace_name=req.workspace_name,
        owner_name=req.name,
        owner_email=req.email,
        owner_password=req.password,
        signup_idempotency_key=signup_idempotency_key,
        correlation_id=correlation_id,
    )
    return TenantRegisterResponse(**result)


@router.get("/{workspace_id}/provisioning-status")
async def get_provisioning_status(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user_optional),
):
    if not current_user or current_user.workspace_id != workspace_id:
        raise HTTPException(status_code=403)
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404)
    return {
        "workspace_id": workspace_id,
        "dify_provisioning_status": ws.dify_provisioning_status,
        "dify_provisioning_attempts": ws.dify_provisioning_attempts,
        "dify_provisioning_last_error": ws.dify_provisioning_last_error,
    }


@router.post("/{workspace_id}/retry-provisioning")
async def retry_provisioning(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user_optional),
):
    if not current_user or current_user.workspace_id != workspace_id:
        raise HTTPException(status_code=403)
    if current_user.role not in ("tenant_owner", "super_admin"):
        raise HTTPException(status_code=403)

    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.dify_provisioning_status not in ("failed", "failed_permanent"):
        raise HTTPException(status_code=409, detail="Workspace not in retryable state")

    correlation_id = str(uuid.uuid7())
    service = TenantService(db)
    return await service.retry_provisioning(workspace_id, correlation_id)
```

### 2.2 `backend/services/tenant_service.py`(业务核心)

```python
"""B 端租户注册业务逻辑,2 阶段事务 + Dify HTTP 调用"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

from models import Workspace, WorkspaceQuota, AdminUser, AuditLog
from services.dify.tenant_provisioner import DifyTenantProvisioner
from services.auth_service import AuthService


logger = logging.getLogger(__name__)


class TenantService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.provisioner = DifyTenantProvisioner()
        self.auth_service = AuthService(db)

    async def register_tenant(
        self, workspace_name, owner_name, owner_email, owner_password,
        signup_idempotency_key, correlation_id,
    ) -> dict:
        # 阶段 1:basjoo DB 写(原子)
        async with self.db.begin():
            workspace = Workspace(
                name=workspace_name,
                owner_email=owner_email,
                dify_provisioning_status="provisioning",
                dify_provisioning_attempts=1,
                signup_idempotency_key=signup_idempotency_key,
            )
            self.db.add(workspace)
            await self.db.flush()

            quota = WorkspaceQuota(workspace_id=workspace.id)
            self.db.add(quota)

            admin = await self.auth_service.create_admin(
                email=owner_email, password=owner_password, name=owner_name,
                role="tenant_owner", workspace_id=workspace.id,
            )

            self.db.add(AuditLog(
                tenant_id=str(workspace.id), actor_user_id=admin.id,
                action="tenant.create", correlation_id=correlation_id, status="success",
            ))
            workspace_id = workspace.id
            admin_id = admin.id

        # 阶段 2:调 Dify(事务外)
        try:
            dify_result = await self.provisioner.provision_tenant(
                workspace_name=workspace_name, owner_email=owner_email,
                owner_name=owner_name, owner_password=owner_password,
                idempotency_key=signup_idempotency_key, correlation_id=correlation_id,
            )
        except Exception as e:
            logger.exception("Dify provision failed workspace_id=%s: %s", workspace_id, e)
            async with self.db.begin():
                ws = await self.db.get(Workspace, workspace_id)
                ws.dify_provisioning_status = "failed"
                ws.dify_provisioning_last_error = str(e)[:1000]
                self.db.add(AuditLog(
                    tenant_id=str(workspace_id), actor_user_id=admin_id,
                    action="tenant.provision", correlation_id=correlation_id,
                    status="failed", error_detail=str(e)[:2000],
                ))
            access_token = self.auth_service.create_access_token(data={"sub": str(admin_id)})
            return {
                "access_token": access_token, "workspace_id": workspace_id,
                "dify_initial_password": "", "provisioning_status": "failed",
                "correlation_id": correlation_id,
            }

        # 阶段 3:写 Dify 成功结果回 basjoo DB
        async with self.db.begin():
            ws = await self.db.get(Workspace, workspace_id)
            ws.dify_tenant_id = dify_result["workspace_id"]
            ws.dify_account_id = dify_result["owner_account_id"]
            ws.dify_provisioning_status = "ready"
            ws.dify_provisioning_last_error = None
            self.db.add(AuditLog(
                tenant_id=str(workspace_id), actor_user_id=admin_id,
                action="tenant.provision", correlation_id=correlation_id,
                dify_request_id=dify_result.get("dify_request_id"), status="success",
            ))

        access_token = self.auth_service.create_access_token(data={"sub": str(admin_id)})
        return {
            "access_token": access_token, "workspace_id": workspace_id,
            "dify_initial_password": dify_result["initial_password"],
            "provisioning_status": "ready", "correlation_id": correlation_id,
        }

    async def retry_provisioning(self, workspace_id: int, correlation_id: str) -> dict:
        ws = await self.db.get(Workspace, workspace_id)
        if not ws:
            return {"success": False, "error": "Workspace not found"}

        ws.dify_provisioning_status = "provisioning"
        ws.dify_provisioning_attempts += 1
        await self.db.commit()

        try:
            dify_result = await self.provisioner.provision_tenant(
                workspace_name=ws.name, owner_email=ws.owner_email,
                owner_name=ws.name, owner_password="<stored_hash_unusable>",
                idempotency_key=ws.signup_idempotency_key, correlation_id=correlation_id,
            )
        except Exception as e:
            ws.dify_provisioning_status = (
                "failed_permanent" if ws.dify_provisioning_attempts >= 3 else "failed"
            )
            ws.dify_provisioning_last_error = str(e)[:1000]
            await self.db.commit()
            return {"success": False, "error": str(e)}

        ws.dify_tenant_id = dify_result["workspace_id"]
        ws.dify_account_id = dify_result["owner_account_id"]
        ws.dify_provisioning_status = "ready"
        ws.dify_provisioning_last_error = None
        await self.db.commit()
        return {"success": True, "provisioning_status": "ready"}
```

### 2.3 `backend/services/dify/tenant_provisioner.py`(Dify 调用 wrapper)

```python
"""basjoo → Dify admin endpoint 调用,基于 DifyAdminClient 复用"""
import logging
import httpx
from services.dify.admin_client import DifyAdminClient


logger = logging.getLogger(__name__)


class DifyTenantProvisioner:
    def __init__(self):
        self.client = DifyAdminClient()

    async def provision_tenant(
        self, workspace_name, owner_email, owner_name, owner_password,
        idempotency_key, correlation_id,
    ) -> dict:
        client = await self.client._get_client()
        resp = await client.post(
            "/console/api/admin/workspaces",
            json={
                "workspace_name": workspace_name, "owner_email": owner_email,
                "owner_name": owner_name, "owner_password": owner_password,
                "idempotency_key": idempotency_key,
            },
            headers={
                "X-CSRF-Token": client.cookies.get("csrf_token", ""),
                "X-Basjoo-Correlation-Id": correlation_id,
            },
        )
        if resp.status_code == 409:
            raise DifyTenantConflictError(f"Dify returned conflict: {resp.text[:500]}")
        if resp.status_code >= 400:
            raise DifyTenantProvisionError(f"Dify returned {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return {
            "workspace_id": data["workspace_id"],
            "owner_account_id": data["owner_account_id"],
            "initial_password": data["initial_password"],
            "dify_request_id": resp.headers.get("X-Request-Id"),
        }

    async def rollback_tenant(self, workspace_id: str) -> bool:
        try:
            client = await self.client._get_client()
            resp = await client.delete(
                f"/console/api/admin/workspaces/{workspace_id}",
                headers={"X-CSRF-Token": client.cookies.get("csrf_token", "")},
            )
            return resp.status_code in (200, 204, 404)
        except Exception as e:
            logger.exception("Failed to rollback Dify tenant %s: %s", workspace_id, e)
            return False

    async def health_check(self) -> bool:
        try:
            client = await self.client._get_client()
            resp = await client.get("/console/api/admin/workspaces/health")
            return resp.status_code == 200
        except Exception:
            return False


class DifyTenantProvisionError(Exception):
    pass


class DifyTenantConflictError(DifyTenantProvisionError):
    pass
```

### 2.4 `backend/scheduler/tenant_provisioning_retry.py`(后台 cron)

```python
"""每 5 分钟扫描 failed workspace 自动重试 provisioning"""
import asyncio
import logging
import uuid
from sqlalchemy import select
from models import Workspace, AuditLog
from database import async_session
from services.tenant_service import TenantService


logger = logging.getLogger(__name__)


async def retry_failed_provisioning():
    async with async_session() as db:
        result = await db.execute(
            select(Workspace).where(
                Workspace.dify_provisioning_status == "failed",
                Workspace.dify_provisioning_attempts < 3,
            )
        )
        workspaces = result.scalars().all()
        for ws in workspaces:
            correlation_id = str(uuid.uuid7())
            logger.info("Auto-retry workspace_id=%s attempt=%s",
                        ws.id, ws.dify_provisioning_attempts + 1)
            service = TenantService(db)
            await service.retry_provisioning(ws.id, correlation_id)
            await db.add(AuditLog(
                tenant_id=str(ws.id), actor_user_id=0,
                action="tenant.auto_retry", correlation_id=correlation_id, status="success",
            ))


async def schedule_tenant_provisioning_retry():
    while True:
        try:
            await retry_failed_provisioning()
        except Exception as e:
            logger.exception("Auto-retry cron failed: %s", e)
        await asyncio.sleep(300)
```

### 2.5 `backend/security/email_blacklist.txt`

```
# 临时邮箱域名黑名单,每行一个
tempmail.com
guerrillamail.com
mailinator.com
10minutemail.com
throwawaymail.com
yopmail.com
trashmail.com
fakeinbox.com
getnada.com
sharklasers.com
```

---

## 3. 改动文件

### 3.1 `backend/middleware/rate_limit.py` 新增装饰器

```python
def rate_limit_by_ip_and_email(ip_limit: int, email_limit: int, window_seconds: int):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request = kwargs.get("request") or args[0]
            client_ip = request.client.host
            email = request.headers.get("X-Tenant-Email", "")
            ip_key = f"ratelimit:register_ip:{client_ip}"
            if not await _check_rate_limit(ip_key, ip_limit, window_seconds):
                raise HTTPException(429, "Too many requests from this IP")
            if email:
                email_key = f"ratelimit:register_email:{email}"
                if not await _check_rate_limit(email_key, email_limit, window_seconds):
                    raise HTTPException(429, "Too many requests for this email")
            return await func(*args, **kwargs)
        return wrapper
    return decorator
```

### 3.2 `backend/main.py` 启动时探测

```python
@app.on_event("startup")
async def check_dify_fork_health():
    from services.dify.tenant_provisioner import DifyTenantProvisioner
    provisioner = DifyTenantProvisioner()
    if not await provisioner.health_check():
        logger.warning("Dify fork endpoint not healthy, /tenants/register will return 503")
    asyncio.create_task(schedule_tenant_provisioning_retry())
```

### 3.3 `backend/config.py` 新增 6 项

```python
# M11 新增
dify_tenant_provision_enabled: bool = True
tenant_signup_ip_rate_limit: int = 5
tenant_signup_email_rate_limit: int = 3
tenant_signup_rate_limit_window_seconds: int = 3600
tenant_provisioning_max_attempts: int = 3
tenant_provisioning_retry_interval_seconds: int = 300
```

---

## 4. 测试要点

### 4.1 单元测试(覆盖率 ≥ 80%)

| 测试 | 期望 |
|------|------|
| `test_register_tenant_success` | 200,access_token + workspace_id + initial_password + provisioning_status=ready |
| `test_register_tenant_dify_failure` | 200,provisioning_status=failed,workspace_id 已建 |
| `test_register_tenant_duplicate_email` | 409 |
| `test_register_tenant_blacklisted_email` | 400 |
| `test_register_tenant_password_too_short` | 422 |
| `test_register_tenant_terms_not_accepted` | 400 |
| `test_retry_provisioning_success` | 状态从 failed → ready |
| `test_retry_provisioning_max_attempts` | 第 3 次失败 → failed_permanent |
| `test_auto_retry_cron_picks_failed_workspaces` | 自动重试扫描正确 |
| `test_audit_logs_written_on_success_and_failure` | audit_logs 表有写入 |
| `test_idempotency_key_uniqueness` | 同 key 第二次注册报冲突 |
| `test_rollback_dify_on_dify_partial_failure` | Dify 部分写入 → DELETE rollback |
| `test_concurrent_same_email` | 并发同邮箱 → 1 个成功 1 个 409 |

### 4.2 集成测试

| 测试 | 期望 |
|------|------|
| `test_e2e_register_to_dify` | 真实注册走通 basjoo → Dify |
| `test_e2e_retry_after_dify_restart` | kill Dify → basjoo retry → 重启后成功 |
| `test_e2e_audit_log_correlation` | basjoo audit_log.correlation_id = Dify 侧 correlation_id |

### 4.3 性能

注册 P95 < 3s(basjoo 写 ~200ms + Dify 调用 < 2s + basjoo 写回 ~100ms)

---

## 5. 与 M10+5 兼容性

- `AuthService.create_admin` 接受 `role` 参数 → 直接传 `tenant_owner`
- `DifyAdminClient._get_client()` 复用,无需新 HTTP 客户端
- 现有 JWT 流程不变

---

## 6. PR3 评审 checklist

- [ ] 端点契约与 `m11-spec.md` §3.1 一致
- [ ] 限速装饰器集成 `middleware/rate_limit.py` 现有 Redis 客户端
- [ ] 邮箱黑名单文件已提交
- [ ] 后台 cron 在 main.py 注册
- [ ] 单测覆盖率 ≥ 80%
- [ ] 集成测试在 docker compose dev 环境跑过
- [ ] M10+5 测试套件无回归
- [ ] 审计日志写入所有 provisioning 行为
- [ ] 错误信息不泄漏 Dify 内部细节