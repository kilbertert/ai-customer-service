"""basjoo M11 PR1 — Pydantic schemas for admin tenant provisioning.

Lives in `services/` (not `controllers/`) to avoid the circular import chain:
  controllers.console.__init__ -> workspace -> models -> ... -> libs.login -> services.account_service
Pydantic models can be safely imported by both services and tests without
loading the entire Flask controller tree.
"""

from pydantic import BaseModel, Field


class TenantProvisionPayload(BaseModel):
    workspace_name: str = Field(..., min_length=3, max_length=50)
    owner_email: str = Field(..., min_length=3, max_length=255)
    owner_name: str = Field(..., min_length=1, max_length=100)
    owner_password: str = Field(..., min_length=8, max_length=64)
    idempotency_key: str = Field(..., min_length=36, max_length=36)


class TenantProvisionResponse(BaseModel):
    workspace_id: str
    owner_account_id: str
    initial_password: str
    status: str
    idempotent_replay: bool
