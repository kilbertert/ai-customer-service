"""M11 PR3 — B 端租户自助注册 API。

3 个端点:
    POST /api/v1/tenants/register
    GET  /api/v1/tenants/{workspace_id}/provisioning-status
    POST /api/v1/tenants/{workspace_id}/retry-provisioning

注册端点: 公开, 走 IP+email 双限速, 邮箱黑名单, terms 校验。
后两个端点: 需登录, 仅 workspace owner / super_admin 可访问。
"""
import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from middleware.rate_limit import rate_limit_by_ip_and_email
from models import AdminUser, Workspace
from security.email_blacklist import is_blacklisted_email
from services.tenant_service import TenantService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])

_bearer = HTTPBearer(auto_error=False)


class TenantRegisterRequest(BaseModel):
    workspace_name: str = Field(..., min_length=3, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    terms_accepted: bool = Field(default=False)

    @field_validator("password")
    @classmethod
    def validate_password_complexity(cls, v: str) -> str:
        from libs.password import valid_password  # noqa: WPS433
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


async def _get_optional_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AdminUser | None:
    """可选鉴权 — 匿名返回 None, 有 Bearer 则返回 AdminUser。

    复用 ``api.endpoints.auth.get_current_admin``, 该函数在 token 非法时抛
    HTTPException(401), 我们 catch 后降级为 None。
    """
    from api.endpoints.auth import get_current_admin  # noqa: WPS433

    creds: HTTPAuthorizationCredentials | None = await _bearer(request)
    if creds is None or not creds.credentials:
        return None
    try:
        return await get_current_admin(request, creds, db)
    except HTTPException:
        return None
    except Exception:
        return None


def _require_workspace_member(
    current_user: AdminUser | None, workspace_id: int
) -> AdminUser:
    if current_user is None or current_user.workspace_id != workspace_id:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    return current_user


@router.post("/register", response_model=TenantRegisterResponse)
@rate_limit_by_ip_and_email(ip_limit=5, email_limit=3, window_seconds=3600)
async def register_tenant(
    req: TenantRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TenantRegisterResponse:
    if is_blacklisted_email(req.email):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email domain not allowed",
        )
    if not req.terms_accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Terms must be accepted",
        )

    existing = await db.execute(
        select(AdminUser).where(AdminUser.email == req.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    signup_idempotency_key = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    service = TenantService(db)
    try:
        result = await service.register_tenant(
            workspace_name=req.workspace_name,
            owner_name=req.name,
            owner_email=req.email,
            owner_password=req.password,
            signup_idempotency_key=signup_idempotency_key,
            correlation_id=correlation_id,
        )
    except IntegrityError:
        # 并发同 email: pre-check 都通过, 但 workspaces.owner_email UNIQUE 兜底
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    return TenantRegisterResponse(**result)


@router.get("/{workspace_id}/provisioning-status")
async def get_provisioning_status(
    workspace_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser | None = Depends(_get_optional_admin),
) -> dict:
    _require_workspace_member(current_user, workspace_id)
    ws = await db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
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
    current_user: AdminUser | None = Depends(_get_optional_admin),
) -> dict:
    user = _require_workspace_member(current_user, workspace_id)
    if user.role not in ("tenant_owner", "super_admin"):
        raise HTTPException(status_code=403, detail="Insufficient role")

    ws = await db.get(Workspace, workspace_id)
    if not ws or ws.dify_provisioning_status not in ("failed", "failed_permanent"):
        raise HTTPException(
            status_code=409, detail="Workspace not in retryable state"
        )

    correlation_id = str(uuid.uuid4())
    service = TenantService(db)
    return await service.retry_provisioning(workspace_id, correlation_id)
