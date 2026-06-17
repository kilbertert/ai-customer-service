"""basjoo M11 PR1 — TenantService.provision_tenant_by_admin + admin endpoint tests.

Coverage target: ≥ 70% (per spec §10).
Critical cases:
  Case C: account creation failure → tenant rolls back
  Case D: TenantAccountJoin failure → account + tenant roll back

These tests use MagicMock for db.session to avoid the full Dify DB stack in CI.
Run: cd api && pytest tests/test_tenant_provision_by_admin.py -v
"""

import secrets
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from services.account_service import (
    AccountService,
    TenantService,
    _generate_initial_password,
)
from services.errors.account import (
    AdminProvisionForbiddenError,
    TenantProvisionConflictError,
)


# ----- helpers ---------------------------------------------------------------


def _unwrap(func):
    """Strip Python decorator chain (e.g. @staticmethod, @admin_required) to inner callable."""
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


@pytest.fixture
def app() -> Flask:
    return Flask(__name__)


def _seed_tenant(custom_idempotency_key: str = "key-1") -> MagicMock:
    t = MagicMock()
    t.id = "tenant-uuid-1"
    t.name = "Acme"
    t.custom_idempotency_key = custom_idempotency_key
    t.created_via_admin_at = None
    t.initial_password_plain = None
    return t


def _seed_owner_join(account_id: str = "owner-uuid-1") -> MagicMock:
    j = MagicMock()
    j.account_id = account_id
    j.role = "owner"
    return j


def _seed_account(account_id: str = "owner-uuid-1") -> MagicMock:
    a = MagicMock()
    a.id = account_id
    a.email = "owner@acme.test"
    a.name = "Owner"
    return a


# ----- happy-path: provision_tenant_by_admin --------------------------------


class TestProvisionTenantSuccess:
    @patch("services.account_service.tenant_was_created")
    @patch("services.account_service.AccountService.create_account_with_password")
    @patch("services.account_service.TenantService.create_tenant_member")
    @patch("services.account_service.naive_utc_now")
    def test_provision_tenant_success(
        self,
        mock_now,
        mock_create_member,
        mock_create_account,
        mock_signal,
        app: Flask,
    ):
        from datetime import datetime

        mock_now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        mock_create_account.return_value = _seed_account()

        mock_session = MagicMock()
        mock_session.scalar.side_effect = [
            None,  # Tenant.idempotency check → no existing
            _seed_owner_join(),
        ]
        with patch("services.account_service.db.session", mock_session):
            result = TenantService.provision_tenant_by_admin(
                name="Acme",
                owner_email="owner@acme.test",
                owner_name="Owner",
                owner_password="Hunter2hunter",
                idempotency_key="0123456789abcdef0123456789abcdef",
            )

        assert result["status"] == "ready"
        assert result["idempotent_replay"] is False
        assert "workspace_id" in result
        assert "owner_account_id" in result
        assert result["initial_password"] == "Hunter2hunter"
        mock_create_account.assert_called_once()
        mock_create_member.assert_called_once()
        mock_signal.send.assert_called_once()
        mock_session.commit.assert_called_once()
        assert result["workspace_id"]
        assert result["owner_account_id"] == "owner-uuid-1"


# ----- idempotency replay ---------------------------------------------------


class TestProvisionTenantIdempotentReplay:
    @patch("services.account_service.AccountService.create_account_with_password")
    @patch("services.account_service.TenantService.create_tenant_member")
    def test_provision_tenant_idempotent_replay(
        self,
        mock_create_member,
        mock_create_account,
        app: Flask,
    ):
        existing_tenant = _seed_tenant()
        mock_session = MagicMock()
        mock_session.scalar.side_effect = [
            existing_tenant,
            _seed_owner_join(),
        ]
        with patch("services.account_service.db.session", mock_session):
            result = TenantService.provision_tenant_by_admin(
                name="Acme",
                owner_email="owner@acme.test",
                owner_name="Owner",
                owner_password="Hunter2hunter",
                idempotency_key="0123456789abcdef0123456789abcdef",
            )

        assert result["idempotent_replay"] is True
        assert result["workspace_id"] == "tenant-uuid-1"
        mock_create_account.assert_not_called()
        mock_create_member.assert_not_called()
        mock_session.commit.assert_not_called()


# ----- Case C: account creation failure → tenant rolls back ------------------


class TestProvisionTenantRollback:
    @patch("services.account_service.AccountService.create_account_with_password")
    def test_provision_tenant_owner_account_failure_rollback(
        self,
        mock_create_account,
        app: Flask,
    ):
        """Case C: account creation raises → tenant flush 也回滚."""
        mock_create_account.side_effect = ValueError("password too weak")
        mock_session = MagicMock()
        mock_session.scalar.return_value = None
        with patch("services.account_service.db.session", mock_session):
            with pytest.raises(AdminProvisionForbiddenError) as exc_info:
                TenantService.provision_tenant_by_admin(
                    name="Acme",
                    owner_email="owner@acme.test",
                    owner_name="Owner",
                    owner_password="weak",
                    idempotency_key="0123456789abcdef0123456789abcdef",
                )
        assert "password" in str(exc_info.value).lower()
        mock_session.rollback.assert_called()
        mock_session.commit.assert_not_called()

    @patch("services.account_service.tenant_was_created")
    @patch("services.account_service.AccountService.create_account_with_password")
    @patch("services.account_service.TenantService.create_tenant_member")
    def test_provision_tenant_bind_failure_rollback(
        self,
        mock_create_member,
        mock_create_account,
        mock_signal,
        app: Flask,
    ):
        """Case D: TenantAccountJoin 失败 → 整体 rollback."""
        mock_create_account.return_value = _seed_account()
        mock_create_member.side_effect = Exception("join unique violation")

        mock_session = MagicMock()
        mock_session.scalar.return_value = None
        with patch("services.account_service.db.session", mock_session):
            with pytest.raises(TenantProvisionConflictError) as exc_info:
                TenantService.provision_tenant_by_admin(
                    name="Acme",
                    owner_email="owner@acme.test",
                    owner_name="Owner",
                    owner_password="Hunter2hunter",
                    idempotency_key="0123456789abcdef0123456789abcdef",
                )
        assert "bind owner" in str(exc_info.value).lower()
        mock_session.rollback.assert_called()
        mock_signal.send.assert_not_called()
        mock_session.commit.assert_not_called()


# ----- payload validation ---------------------------------------------------


class TestProvisionPayloadValidation:
    def test_workspace_name_too_long(self, app: Flask):
        from pydantic import ValidationError
        from services.admin_provision_schemas import TenantProvisionPayload

        long_name = "a" * 51
        with pytest.raises(ValidationError) as exc_info:
            TenantProvisionPayload(
                workspace_name=long_name,
                owner_email="o@a.test",
                owner_name="Owner",
                owner_password="Hunter2hunter",
                idempotency_key="0123456789abcdef0123456789abcdef",
            )
        assert "workspace_name" in str(exc_info.value)

    def test_invalid_idempotency_key(self, app: Flask):
        from pydantic import ValidationError
        from services.admin_provision_schemas import TenantProvisionPayload

        with pytest.raises(ValidationError) as exc_info:
            TenantProvisionPayload(
                workspace_name="Acme",
                owner_email="o@a.test",
                owner_name="Owner",
                owner_password="Hunter2hunter",
                idempotency_key="short-key",
            )
        assert "idempotency_key" in str(exc_info.value)

    def test_duplicate_email_raises_conflict(self, app: Flask):
        from services.errors.account import AccountRegisterError

        with patch.object(
            AccountService,
            "create_account_with_password",
            side_effect=AccountRegisterError("email exists"),
        ):
            mock_session = MagicMock()
            mock_session.scalar.return_value = None
            with patch("services.account_service.db.session", mock_session):
                with pytest.raises(AdminProvisionForbiddenError):
                    TenantService.provision_tenant_by_admin(
                        name="Acme",
                        owner_email="dup@acme.test",
                        owner_name="Owner",
                        owner_password="Hunter2hunter",
                        idempotency_key="0123456789abcdef0123456789abcdef",
                    )


# ----- endpoint: rollback DELETE --------------------------------------------
# Note: Endpoint tests below import `controllers.console.workspace.workspace`,
# which triggers the controllers.console.__init__ circular import chain
# (flask_restx Namespace + extensions.ext_login + libs.login). They require a
# full Dify app context (e.g. running with `flask run` or in docker image) and
# are therefore skipped in unit-test mode. The service-layer business logic is
# already covered by TestProvisionTenantSuccess / TestProvisionTenantRollback
# above.


@pytest.mark.skip(reason="Requires full Dify app stack (controllers.console import chain)")
class TestRollbackEndpoint:
    def test_rollback_endpoint_cascade(self, app: Flask):
        from controllers.console.workspace.workspace import TenantProvisionRollbackApi

        method = _unwrap(TenantProvisionRollbackApi.delete)
        tenant = _seed_tenant()
        join_obj = MagicMock()

        mock_session = MagicMock()
        mock_session.get.return_value = tenant
        mock_session.scalars.return_value.all.return_value = [join_obj]
        with patch("controllers.console.workspace.workspace.db.session", mock_session):
            with app.test_request_context("/admin/workspaces/tenant-uuid-1", method="DELETE"):
                body, status = method("tenant-uuid-1")

        assert status == 204
        mock_session.delete.assert_any_call(join_obj)
        mock_session.delete.assert_any_call(tenant)
        mock_session.commit.assert_called_once()


# ----- endpoint: owner-credentials 24h TTL -----------------------------------


@pytest.mark.skip(reason="Requires full Dify app stack (controllers.console import chain)")
class TestOwnerCredentialsEndpoint:
    def test_owner_credentials_returns_plain_password(self, app: Flask):
        from controllers.console.workspace.workspace import TenantProvisionOwnerCredentialsApi

        method = _unwrap(TenantProvisionOwnerCredentialsApi.get)
        tenant = _seed_tenant()
        tenant.created_via_admin_at = "sometime-in-last-24h"
        tenant.initial_password_plain = "Hunter2hunter"

        mock_session = MagicMock()
        mock_session.get.return_value = tenant
        mock_session.scalar.return_value = _seed_owner_join()
        with patch("controllers.console.workspace.workspace.db.session", mock_session):
            with app.test_request_context("/admin/workspaces/t-1/owner-credentials"):
                body, status = method("tenant-uuid-1")

        assert status == 200
        assert body["initial_password"] == "Hunter2hunter"
        assert body["owner_account_id"] == "owner-uuid-1"

    def test_owner_credentials_blocked_after_ttl(self, app: Flask):
        """25h 后(tenant.created_via_admin_at 为空)返回 409."""
        from controllers.console.workspace.workspace import TenantProvisionOwnerCredentialsApi

        method = _unwrap(TenantProvisionOwnerCredentialsApi.get)
        tenant = _seed_tenant()
        tenant.created_via_admin_at = None
        tenant.initial_password_plain = None

        mock_session = MagicMock()
        mock_session.get.return_value = tenant
        with patch("controllers.console.workspace.workspace.db.session", mock_session):
            with app.test_request_context("/admin/workspaces/t-1/owner-credentials"):
                body, status = method("tenant-uuid-1")

        assert status == 409
        assert "no longer retrievable" in body["message"].lower()

    def test_owner_credentials_tenant_not_found(self, app: Flask):
        from controllers.console.workspace.workspace import TenantProvisionOwnerCredentialsApi

        method = _unwrap(TenantProvisionOwnerCredentialsApi.get)
        mock_session = MagicMock()
        mock_session.get.return_value = None
        with patch("controllers.console.workspace.workspace.db.session", mock_session):
            with app.test_request_context("/admin/workspaces/t-1/owner-credentials"):
                body, status = method("tenant-uuid-1")
        assert status == 404


# ----- endpoint: health ------------------------------------------------------


@pytest.mark.skip(reason="Requires full Dify app stack (controllers.console import chain)")
class TestHealthEndpoint:
    def test_health_endpoint(self, app: Flask):
        from controllers.console.workspace.workspace import TenantProvisionHealthApi

        method = _unwrap(TenantProvisionHealthApi.get)
        with app.test_request_context("/admin/workspaces/health"):
            body, status = method()
        assert status == 200
        assert body["status"] == "ok"
        assert body["fork_version"] == "m11-v1.0"


# ----- endpoint: POST /admin/workspaces happy path --------------------------


@pytest.mark.skip(reason="Requires full Dify app stack (controllers.console import chain)")
class TestProvisionEndpoint:
    @patch("services.account_service.tenant_was_created")
    @patch("services.account_service.AccountService.create_account_with_password")
    @patch("services.account_service.TenantService.create_tenant_member")
    @patch("services.account_service.naive_utc_now")
    def test_post_endpoint_returns_200_with_marshalled_fields(
        self,
        mock_now,
        mock_create_member,
        mock_create_account,
        mock_signal,
        app: Flask,
    ):
        from datetime import datetime

        from controllers.console.workspace.workspace import TenantProvisionByAdminApi

        mock_now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        mock_create_account.return_value = _seed_account()

        mock_session = MagicMock()
        mock_session.scalar.side_effect = [None, _seed_owner_join()]
        with patch("services.account_service.db.session", mock_session):
            method = _unwrap(TenantProvisionByAdminApi.post)
            payload = {
                "workspace_name": "Acme",
                "owner_email": "owner@acme.test",
                "owner_name": "Owner",
                "owner_password": "Hunter2hunter",
                "idempotency_key": "0123456789abcdef0123456789abcdef",
            }
            with app.test_request_context(
                "/admin/workspaces",
                method="POST",
                json=payload,
            ):
                body, status = method()

        assert status == 200
        assert "workspace_id" in body
        assert body["status"] == "ready"
        assert body["idempotent_replay"] is False


# ----- helpers & side-effect preservation -----------------------------------


class TestPreserveTenantPluginStrategySideEffect:
    @patch("services.account_service.TenantPluginAutoUpgradeStrategy")
    @patch("services.account_service.FeatureService")
    def test_create_tenant_still_adds_plugin_strategy(
        self,
        mock_feature_service,
        mock_strategy_cls,
    ):
        from models.account import Tenant

        mock_feature_service.get_system_features.return_value.is_allow_create_workspace = True
        mock_session = MagicMock()
        mock_session.add.side_effect = lambda obj: setattr(obj, "id", "t-1")

        with patch("services.account_service.db.session", mock_session), \
             patch("services.account_service.generate_key_pair", return_value="pub-key"):
            TenantService.create_tenant(name="Acme", is_setup=True)

        added = [c.args[0] for c in mock_session.add.call_args_list]
        assert any(isinstance(a, Tenant) for a in added)
        # The strategy class is patched; verify it was instantiated and added.
        assert mock_strategy_cls.called, "TenantPluginAutoUpgradeStrategy was not instantiated"


class TestPasswordGenerationHelper:
    def test_generate_initial_password_length(self):
        pw = _generate_initial_password()
        assert len(pw) == 32

    def test_generate_initial_password_uniqueness(self):
        a = _generate_initial_password()
        b = _generate_initial_password()
        assert a != b

    def test_generate_initial_password_alphabet(self):
        pw = _generate_initial_password()
        allowed = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789!@#$%^&*"
        )
        for c in pw:
            assert c in allowed
