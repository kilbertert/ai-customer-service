"""M10+1: Dify exception class family (centralized re-exports + new DifyConfigError).

M2/China_charge_kf had ``DifyError`` / ``DifyAuthError`` / ``DifyBadRequestError`` /
``DifyUpstreamError`` defined inline in ``services/dify/dify_client.py`` (lines
29-58). M10+1 keeps those definitions in place (no breaking change to existing
callers: ``SseProxyLayer`` / ``DifyClient.run_workflow_stream`` still import from
``dify_client``) and re-exports them here for the *new* production-side
DifyAdminClient + future M10+2 create_agent integration.

This module also adds one new exception ``DifyConfigError`` used by
``DifyAdminClient.__post_init__`` to fail-fast on missing admin credentials
(workspace.dify_admin_email / .dify_admin_password_ref). The M10+2 endpoint
catches ``DifyConfigError`` and surfaces it as a 400 (not 502) so admin can
fix config without leaving an orphan basjoo Agent row.

D9(c) note: ``publish_workflow`` validation failures (HTTP 400/422) are NOT
exceptions; the admin client returns ``False`` and the endpoint persists
``agent.dify_publish_status = 'publish_failed'``. Only 5xx raises
``DifyUpstreamError`` which the endpoint treats as a hard failure (rollback).
"""
from __future__ import annotations

from services.dify.dify_client import (
    DifyAuthError,
    DifyBadRequestError,
    DifyError,
    DifyUpstreamError,
)

__all__ = [
    "DifyError",
    "DifyAuthError",
    "DifyBadRequestError",
    "DifyUpstreamError",
    "DifyConfigError",
]


class DifyConfigError(DifyError):
    """Dify configuration invalid — fail-fast on missing admin credentials.

    Distinct from ``DifyAuthError`` (which is HTTP 401/403 from Dify) and
    ``DifyBadRequestError`` (which is HTTP 400 from Dify): ``DifyConfigError``
    is raised *before* any HTTP call when basjoo-side config is incomplete
    (e.g. ``workspace.dify_enabled = True`` but ``dify_admin_email = None``).

    M10+2 endpoint maps this to HTTP 400 (caller's fault, not upstream),
    while ``DifyUpstreamError`` maps to HTTP 502 (upstream's fault).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=None)
