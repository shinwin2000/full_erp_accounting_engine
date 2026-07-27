# tests/config/test_vault_integrator.py
"""
Comprehensive unit tests for config/vault_integrator.py.
Covers all public methods, entity methods, and edge cases with mocking.
All datetime is mocked for deterministic results.
"""

import os
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, mock_open, patch

import pytest

from config.vault_integrator import (
    DEFAULT_VAULT_ADDR,
    DEFAULT_VAULT_ROLE_ID_FILE,
    DEFAULT_VAULT_SECRET_ID_FILE,
    DEFAULT_VAULT_TOKEN_FILE,
    SECRET_CACHE_TTL_SECONDS,
    VAULT_AVAILABLE,
    VaultConnectionStatus,
    VaultIntegrator,
    VaultSecret,
    get_secret,
    get_vault_integrator,
    process_vault_secrets,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_FUTURE = FIXED_NOW + timedelta(seconds=SECRET_CACHE_TTL_SECONDS + 10)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("config.vault_integrator.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Fixtures for VaultIntegrator with mocked hvac
# ============================================================================

@pytest.fixture
def mock_hvac_client():
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.sys.read_health_status.return_value = {
        "sealed": False,
        "initialized": True,
        "version": "1.15.0",
    }
    client.auth.token.lookup_self.return_value = {"data": {"ttl": 600}}
    client.auth.token.renew_self.return_value = True
    client.secrets.kv.v2.read_secret_version.return_value = {
        "data": {"data": {"password": "secret123"}, "metadata": {"version": 2}},
        "lease_duration": 3600,
    }
    client.secrets.kv.v2.create_or_update_secret.return_value = True
    client.secrets.kv.v2.delete_metadata_all_versions.return_value = True
    client.secrets.kv.v2.list_secrets.return_value = {"data": {"keys": ["key1", "key2"]}}
    return client


@pytest.fixture
def vault_integrator(mock_hvac_client):
    with patch("config.vault_integrator.VAULT_AVAILABLE", True):
        integrator = VaultIntegrator()
        integrator._client = mock_hvac_client
        integrator._status = VaultConnectionStatus(
            connected=True,
            sealed=False,
            initialized=True,
            version="1.15.0",
            last_checked=FIXED_NOW,
            error_message=None,
        )
        return integrator


# ============================================================================
# Tests for VaultSecret
# ============================================================================

class TestVaultSecret:
    def test_construction_valid(self):
        secret = VaultSecret(
            path="app/db",
            key="password",
            value="secret123",
            lease_duration=3600,
            renewable=True,
            version=1,
            created_at=FIXED_NOW,
            expires_at=FIXED_FUTURE,
        )
        assert secret.path == "app/db"
        assert secret.key == "password"
        assert secret.value == "secret123"
        assert secret._ver == 1
        assert secret._secret_id is not None

    def test_construction_invalid_empty_path(self):
        with pytest.raises(ValueError, match="path is required"):
            VaultSecret(path="", key="k", value="v", lease_duration=1, renewable=False)

    def test_construction_invalid_empty_key(self):
        with pytest.raises(ValueError, match="key is required"):
            VaultSecret(path="p", key="", value="v", lease_duration=1, renewable=False)

    def test_construction_invalid_none_value(self):
        with pytest.raises(ValueError, match="value cannot be None"):
            VaultSecret(path="p", key="k", value=None, lease_duration=1, renewable=False)  # type: ignore

    def test_construction_negative_lease(self):
        with pytest.raises(ValueError, match="lease_duration cannot be negative"):
            VaultSecret(path="p", key="k", value="v", lease_duration=-1, renewable=False)

    def test_construction_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            VaultSecret(path="p", key="k", value="v", lease_duration=1, renewable=False, version=0)

    def test_is_expired(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False,
            expires_at=FIXED_NOW - timedelta(seconds=1)
        )
        assert secret.is_expired() is True
        secret.expires_at = FIXED_NOW + timedelta(seconds=1)
        assert secret.is_expired() is False
        secret.expires_at = None
        assert secret.is_expired() is False

    def test_time_to_expiry_seconds(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False,
            expires_at=FIXED_NOW + timedelta(seconds=100)
        )
        assert secret.time_to_expiry_seconds() == 100
        secret.expires_at = FIXED_NOW - timedelta(seconds=10)
        assert secret.time_to_expiry_seconds() == 0
        secret.expires_at = None
        assert secret.time_to_expiry_seconds() == -1

    def test_validate(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False
        )
        result = secret.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # Invalid
        secret.path = ""
        result = secret.validate()
        assert result["is_valid"] is False
        assert "path is required" in result["errors"][0]

    def test_to_dict(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=3600, renewable=True,
            version=2, created_at=FIXED_NOW, expires_at=FIXED_FUTURE
        )
        d = secret.to_dict()
        assert d["path"] == "p"
        assert d["key"] == "k"
        assert d["lease_duration"] == 3600
        assert d["renewable"] is True
        assert d["version"] == 2
        assert d["created_at"] == FIXED_NOW.isoformat()
        assert d["expires_at"] == FIXED_FUTURE.isoformat()
        assert d["ver"] == 1

    def test_from_dict(self):
        data = {
            "path": "app/db",
            "key": "password",
            "lease_duration": 7200,
            "renewable": False,
            "version": 3,
            "created_at": FIXED_NOW.isoformat(),
            "expires_at": FIXED_FUTURE.isoformat(),
            "ver": 2,
            "secret_id": "custom-id",
        }
        secret = VaultSecret.from_dict(data)
        assert secret.path == "app/db"
        assert secret.key == "password"
        assert secret.value == "***REDACTED***"
        assert secret.lease_duration == 7200
        assert secret.renewable is False
        assert secret.version == 3
        assert secret.created_at == FIXED_NOW
        assert secret.expires_at == FIXED_FUTURE
        assert secret._ver == 2
        assert secret._secret_id == "custom-id"

    def test_clone(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False,
            created_at=FIXED_NOW, expires_at=FIXED_FUTURE
        )
        cloned = secret.clone()
        assert cloned.path == secret.path
        assert cloned.key == secret.key
        assert cloned.value == secret.value
        assert cloned.lease_duration == secret.lease_duration
        assert cloned.renewable == secret.renewable
        assert cloned.version == secret.version + 1
        assert cloned.created_at == FIXED_NOW
        assert cloned.expires_at == secret.expires_at
        assert cloned._ver == secret._ver + 1
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False
        )
        snap = secret.snapshot()
        assert snap["version"] == secret._ver
        assert snap["secret_id"] == secret._secret_id
        assert snap["path"] == "p"
        assert snap["key"] == "k"

    def test_version(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False
        )
        assert secret.version() == 1

    def test_audit_trail(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False
        )
        secret._record_audit("TEST", "system", {"detail": "val"})
        trail = secret.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["details"] == {"detail": "val"}

    def test_touch(self):
        secret = VaultSecret(
            path="p", key="k", value="v", lease_duration=1, renewable=False
        )
        touched = secret.touch("admin")
        assert touched._ver == secret._ver + 1
        trail = touched.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for VaultConnectionStatus
# ============================================================================

class TestVaultConnectionStatus:
    def test_construction_valid(self):
        status = VaultConnectionStatus(
            connected=True,
            sealed=False,
            initialized=True,
            version="1.15.0",
            last_checked=FIXED_NOW,
            error_message=None,
        )
        assert status.connected is True
        assert status.sealed is False
        assert status.initialized is True
        assert status.version == "1.15.0"
        assert status.last_checked == FIXED_NOW
        assert status.error_message is None

    def test_validation_invalid_types(self):
        with pytest.raises(ValueError, match="connected must be boolean"):
            VaultConnectionStatus(
                connected="True", sealed=False, initialized=False, last_checked=FIXED_NOW
            )  # type: ignore
        with pytest.raises(ValueError, match="sealed must be boolean"):
            VaultConnectionStatus(
                connected=True, sealed="False", initialized=False, last_checked=FIXED_NOW
            )  # type: ignore
        with pytest.raises(ValueError, match="initialized must be boolean"):
            VaultConnectionStatus(
                connected=True, sealed=False, initialized="True", last_checked=FIXED_NOW
            )  # type: ignore

    def test_validate(self):
        status = VaultConnectionStatus(
            connected=True, sealed=False, initialized=False, last_checked=FIXED_NOW
        )
        result = status.validate()
        assert result["is_valid"] is True

    def test_to_dict(self):
        status = VaultConnectionStatus(
            connected=True,
            sealed=False,
            initialized=True,
            version="1.15.0",
            last_checked=FIXED_NOW,
            error_message="test error",
        )
        d = status.to_dict()
        assert d["connected"] is True
        assert d["sealed"] is False
        assert d["initialized"] is True
        assert d["version"] == "1.15.0"
        assert d["last_checked"] == FIXED_NOW.isoformat()
        assert d["error_message"] == "test error"
        assert d["ver"] == 1

    def test_from_dict(self):
        data = {
            "connected": True,
            "sealed": False,
            "initialized": True,
            "last_checked": FIXED_NOW.isoformat(),
            "version": "1.15.0",
            "error_message": None,
            "ver": 2,
            "status_id": "custom-id",
        }
        status = VaultConnectionStatus.from_dict(data)
        assert status.connected is True
        assert status.sealed is False
        assert status.initialized is True
        assert status.last_checked == FIXED_NOW
        assert status.version == "1.15.0"
        assert status.error_message is None
        assert status._ver == 2
        assert status._status_id == "custom-id"

    def test_clone(self):
        status = VaultConnectionStatus(
            connected=True, sealed=False, initialized=True, last_checked=FIXED_NOW
        )
        cloned = status.clone()
        assert cloned.connected == status.connected
        assert cloned.sealed == status.sealed
        assert cloned.initialized == status.initialized
        assert cloned.last_checked == FIXED_NOW
        assert cloned._ver == status._ver + 1
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        status = VaultConnectionStatus(
            connected=True, sealed=False, initialized=True, last_checked=FIXED_NOW
        )
        snap = status.snapshot()
        assert snap["connected"] is True
        assert snap["sealed"] is False

    def test_version(self):
        status = VaultConnectionStatus(
            connected=True, sealed=False, initialized=True, last_checked=FIXED_NOW
        )
        assert status.version() == 1

    def test_audit_trail_and_touch(self):
        status = VaultConnectionStatus(
            connected=True, sealed=False, initialized=True, last_checked=FIXED_NOW
        )
        status._record_audit("TEST", "system", {})
        trail = status.audit_trail()
        assert len(trail) == 1
        touched = status.touch("admin")
        assert touched._ver == status._ver + 1


# ============================================================================
# Tests for VaultIntegrator
# ============================================================================

class TestVaultIntegrator:
    def test_singleton(self):
        i1 = VaultIntegrator()
        i2 = VaultIntegrator()
        assert i1 is i2

    # ---- Entity basic methods ----
    def test_validate(self, vault_integrator):
        result = vault_integrator.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        # When VAULT_AVAILABLE is False
        with patch("config.vault_integrator.VAULT_AVAILABLE", False):
            result2 = vault_integrator.validate()
            assert result2["is_valid"] is False
            assert "Vault library not available" in result2["errors"]

    def test_to_dict(self, vault_integrator):
        d = vault_integrator.to_dict()
        assert "integrator_id" in d
        assert "status" in d
        assert "cache_size" in d
        assert "version" in d

    def test_from_dict(self):
        data = {"version": 3, "integrator_id": "test-id"}
        with patch("config.vault_integrator.VAULT_AVAILABLE", True):
            integrator = VaultIntegrator.from_dict(data)
            assert integrator._version == 3
            assert integrator._integrator_id == "test-id"

    def test_clone(self, vault_integrator):
        cloned = vault_integrator.clone()
        assert cloned is not vault_integrator
        assert cloned._version == vault_integrator._version + 1
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, vault_integrator):
        snap = vault_integrator.snapshot()
        assert snap["version"] == vault_integrator._version
        assert snap["integrator_id"] == vault_integrator._integrator_id
        assert snap["connected"] is True

    def test_version(self, vault_integrator):
        assert vault_integrator.version() == 1

    def test_audit_trail(self, vault_integrator):
        vault_integrator._record_audit("TEST", "system", {})
        trail = vault_integrator.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, vault_integrator):
        touched = vault_integrator.touch("admin")
        assert touched._version == vault_integrator._version + 1

    def test_reset(self, vault_integrator):
        vault_integrator._secret_cache["key"] = MagicMock()
        vault_integrator._record_audit("TEST", "system", {})
        vault_integrator.reset()
        assert vault_integrator._secret_cache == {}
        assert vault_integrator._version == 1
        assert vault_integrator._audit_trail == []
        assert vault_integrator._status.connected is False
        assert vault_integrator._client is None

    # ---- connect ----
    def test_connect_success_token(self, vault_integrator, mock_hvac_client):
        with patch.dict(os.environ, {"VAULT_ADDR": "http://vault:8200"}):
            result = vault_integrator.connect(token="test-token")
        assert result is True
        assert vault_integrator._status.connected is True
        assert vault_integrator._status.sealed is False
        mock_hvac_client.is_authenticated.assert_called()
        mock_hvac_client.sys.read_health_status.assert_called()

    def test_connect_success_approle(self, vault_integrator, mock_hvac_client):
        with patch("config.vault_integrator.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.read_text.return_value = "role123"
            result = vault_integrator.connect(use_approle=True)
        assert result is True
        mock_hvac_client.auth.approle.login.assert_called_with(role_id="role123", secret_id=None)

    def test_connect_hvac_not_available(self):
        with patch("config.vault_integrator.VAULT_AVAILABLE", False):
            integrator = VaultIntegrator()
            result = integrator.connect()
        assert result is False
        assert integrator._status.connected is False
        assert "hvac library not installed" in integrator._status.error_message

    def test_connect_approle_missing_role(self, vault_integrator, mock_hvac_client):
        with patch("config.vault_integrator.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            result = vault_integrator.connect(use_approle=True)
        assert result is False
        assert vault_integrator._status.connected is False
        mock_hvac_client.auth.approle.login.assert_not_called()

    def test_connect_token_missing(self, vault_integrator, mock_hvac_client):
        with patch.dict(os.environ, {}, clear=True):
            with patch("config.vault_integrator.Path") as mock_path:
                mock_path.return_value.exists.return_value = False
                result = vault_integrator.connect()
        assert result is False
        assert vault_integrator._status.connected is False

    def test_connect_auth_failure(self, vault_integrator, mock_hvac_client):
        mock_hvac_client.is_authenticated.return_value = False
        result = vault_integrator.connect(token="invalid")
        assert result is False
        assert vault_integrator._status.connected is False
        assert vault_integrator._status.error_message == "Authentication failed"

    def test_connect_sealed(self, vault_integrator, mock_hvac_client):
        mock_hvac_client.sys.read_health_status.return_value = {
            "sealed": True,
            "initialized": True,
            "version": "1.15.0",
        }
        result = vault_integrator.connect(token="test")
        assert result is False
        assert vault_integrator._status.sealed is True

    def test_connect_exception(self, vault_integrator, mock_hvac_client):
        mock_hvac_client.is_authenticated.side_effect = Exception("Connection error")
        result = vault_integrator.connect(token="test")
        assert result is False
        assert "Connection error" in vault_integrator._status.error_message

    # ---- get_secret ----
    def test_get_secret_from_cache(self, vault_integrator):
        secret_obj = VaultSecret(
            path="app/db",
            key="password",
            value="cached_val",
            lease_duration=3600,
            renewable=False,
            expires_at=FIXED_NOW + timedelta(seconds=100),
        )
        vault_integrator._secret_cache["app/db:password"] = secret_obj
        value = vault_integrator.get_secret("app/db", "password", use_cache=True)
        assert value == "cached_val"
        # Should not call vault client
        vault_integrator._client.secrets.kv.v2.read_secret_version.assert_not_called()

    def test_get_secret_cache_expired(self, vault_integrator):
        secret_obj = VaultSecret(
            path="app/db",
            key="password",
            value="old_val",
            lease_duration=3600,
            renewable=False,
            expires_at=FIXED_NOW - timedelta(seconds=1),
        )
        vault_integrator._secret_cache["app/db:password"] = secret_obj
        vault_integrator._client.secrets.kv.v2.read_secret_version.return_value = {
            "data": {"data": {"password": "new_val"}},
            "lease_duration": 3600,
        }
        value = vault_integrator.get_secret("app/db", "password", use_cache=True)
        assert value == "new_val"
        vault_integrator._client.secrets.kv.v2.read_secret_version.assert_called_once()

    def test_get_secret_from_vault(self, vault_integrator):
        value = vault_integrator.get_secret("app/db", "password", use_cache=False)
        assert value == "secret123"
        vault_integrator._client.secrets.kv.v2.read_secret_version.assert_called_once()
        # Cache should be updated
        cache_key = "app/db:password"
        assert cache_key in vault_integrator._secret_cache
        assert vault_integrator._secret_cache[cache_key].value == "secret123"

    def test_get_secret_fallback_env(self, vault_integrator):
        # Make vault unavailable by simulating failure
        vault_integrator._client = None
        with patch.dict(os.environ, {"APP_DB_PASSWORD": "env_val"}):
            value = vault_integrator.get_secret("app/db", "password")
        assert value == "env_val"

    def test_get_secret_fallback_file(self, vault_integrator):
        vault_integrator._client = None
        with patch("config.vault_integrator.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.exists.return_value = True
            mock_file.read_text.return_value = "file_val"
            mock_path.return_value = mock_file
            value = vault_integrator.get_secret("app/db", "password")
        assert value == "file_val"

    def test_get_secret_fallback_not_found(self, vault_integrator):
        vault_integrator._client = None
        with patch.dict(os.environ, {}, clear=True):
            with patch("config.vault_integrator.Path") as mock_path:
                mock_path.return_value.exists.return_value = False
                value = vault_integrator.get_secret("app/db", "password")
        assert value is None

    def test_get_secret_vault_exception(self, vault_integrator):
        vault_integrator._client.secrets.kv.v2.read_secret_version.side_effect = Exception("Vault error")
        with patch.dict(os.environ, {}, clear=True):
            value = vault_integrator.get_secret("app/db", "password")
        assert value is None

    # ---- set_secret ----
    def test_set_secret_success(self, vault_integrator):
        result = vault_integrator.set_secret("app/db", "password", "new123")
        assert result is True
        vault_integrator._client.secrets.kv.v2.create_or_update_secret.assert_called_once()
        call_args = vault_integrator._client.secrets.kv.v2.create_or_update_secret.call_args
        assert call_args[1]["secret"] == {"password": "new123"}

    def test_set_secret_vault_unavailable(self, vault_integrator):
        vault_integrator._client = None
        result = vault_integrator.set_secret("app/db", "password", "new123")
        assert result is False

    def test_set_secret_exception(self, vault_integrator):
        vault_integrator._client.secrets.kv.v2.create_or_update_secret.side_effect = Exception("Vault error")
        result = vault_integrator.set_secret("app/db", "password", "new123")
        assert result is False

    # ---- delete_secret ----
    def test_delete_secret_success(self, vault_integrator):
        # Add to cache first
        secret = VaultSecret(
            path="app/db", key="password", value="val", lease_duration=1, renewable=False
        )
        vault_integrator._secret_cache["app/db:password"] = secret
        result = vault_integrator.delete_secret("app/db", "password")
        assert result is True
        vault_integrator._client.secrets.kv.v2.delete_metadata_all_versions.assert_called_once()
        assert "app/db:password" not in vault_integrator._secret_cache

    def test_delete_secret_vault_unavailable(self, vault_integrator):
        vault_integrator._client = None
        result = vault_integrator.delete_secret("app/db", "password")
        assert result is False

    def test_delete_secret_exception(self, vault_integrator):
        vault_integrator._client.secrets.kv.v2.delete_metadata_all_versions.side_effect = Exception(
            "Vault error"
        )
        result = vault_integrator.delete_secret("app/db", "password")
        assert result is False

    # ---- list_secrets ----
    def test_list_secrets_success(self, vault_integrator):
        keys = vault_integrator.list_secrets("app/db")
        assert keys == ["key1", "key2"]
        vault_integrator._client.secrets.kv.v2.list_secrets.assert_called_once_with(
            path="secret/metadata/app/db"
        )

    def test_list_secrets_vault_unavailable(self, vault_integrator):
        vault_integrator._client = None
        keys = vault_integrator.list_secrets("app/db")
        assert keys == []

    def test_list_secrets_exception(self, vault_integrator):
        vault_integrator._client.secrets.kv.v2.list_secrets.side_effect = Exception("Vault error")
        keys = vault_integrator.list_secrets("app/db")
        assert keys == []

    # ---- get_connection_status ----
    def test_get_connection_status(self, vault_integrator):
        status = vault_integrator.get_connection_status()
        assert status.connected is True
        assert status.sealed is False
        assert status.version == "1.15.0"
        assert status.last_checked == FIXED_NOW

    def test_get_connection_status_exception(self, vault_integrator):
        vault_integrator._client.sys.read_health_status.side_effect = Exception("Health error")
        status = vault_integrator.get_connection_status()
        assert status.connected is True  # still from previous
        assert status.error_message == "Health error"

    # ---- is_available ----
    def test_is_available(self, vault_integrator):
        assert vault_integrator.is_available() is True
        vault_integrator._status.sealed = True
        assert vault_integrator.is_available() is False
        vault_integrator._status.connected = False
        assert vault_integrator.is_available() is False

    # ---- seal ----
    def test_seal_success(self, vault_integrator):
        result = vault_integrator.seal()
        assert result is True
        vault_integrator._client.sys.seal.assert_called_once()
        assert vault_integrator._status.sealed is True

    def test_seal_no_client(self, vault_integrator):
        vault_integrator._client = None
        result = vault_integrator.seal()
        assert result is False

    def test_seal_exception(self, vault_integrator):
        vault_integrator._client.sys.seal.side_effect = Exception("Seal error")
        result = vault_integrator.seal()
        assert result is False

    # ---- unseal ----
    def test_unseal_success(self, vault_integrator):
        result = vault_integrator.unseal("unseal-key")
        assert result is True
        vault_integrator._client.sys.submit_unseal_key.assert_called_once_with("unseal-key")
        assert vault_integrator._status.sealed is False

    def test_unseal_no_client(self, vault_integrator):
        vault_integrator._client = None
        result = vault_integrator.unseal("key")
        assert result is False

    def test_unseal_exception(self, vault_integrator):
        vault_integrator._client.sys.submit_unseal_key.side_effect = Exception("Unseal error")
        result = vault_integrator.unseal("key")
        assert result is False

    # ---- process_config ----
    def test_process_config_simple(self, vault_integrator):
        config = {
            "database": {
                "host": "localhost",
                "password": "${vault:app/db:password}"
            }
        }
        with patch.object(vault_integrator, "get_secret", return_value="secret123"):
            result = vault_integrator.process_config(config)
        assert result["database"]["password"] == "secret123"
        assert result["database"]["host"] == "localhost"

    def test_process_config_recursive(self, vault_integrator):
        config = {
            "services": [
                {"name": "api", "secret": "${vault:app/api:key}"},
                {"name": "worker", "secret": "${vault:app/worker:key}"},
            ]
        }
        def mock_get(path, key):
            return f"val_{path}_{key}"
        with patch.object(vault_integrator, "get_secret", side_effect=mock_get):
            result = vault_integrator.process_config(config)
        assert result["services"][0]["secret"] == "val_app/api_key"
        assert result["services"][1]["secret"] == "val_app/worker_key"

    def test_process_config_no_match(self, vault_integrator):
        config = {"key": "plain_value"}
        with patch.object(vault_integrator, "get_secret") as mock_get:
            result = vault_integrator.process_config(config)
        mock_get.assert_not_called()
        assert result["key"] == "plain_value"

    def test_process_config_secret_not_found(self, vault_integrator):
        config = {"password": "${vault:app/db:password}"}
        with patch.object(vault_integrator, "get_secret", return_value=None):
            result = vault_integrator.process_config(config)
        # Should keep placeholder
        assert result["password"] == "${vault:app/db:password}"

    # ---- clear_cache ----
    def test_clear_cache(self, vault_integrator):
        vault_integrator._secret_cache["key"] = "value"
        vault_integrator.clear_cache()
        assert vault_integrator._secret_cache == {}
        trail = vault_integrator.audit_trail()
        assert any(a["action"] == "CLEAR_CACHE" for a in trail)


# ============================================================================
# Tests for module-level functions
# ============================================================================

def test_get_secret_function(mock_hvac_client):
    with patch("config.vault_integrator.get_vault_integrator") as mock_get:
        integrator = MagicMock()
        integrator.get_secret.return_value = "secret_val"
        mock_get.return_value = integrator
        result = get_secret("path", "key", "default")
        assert result == "secret_val"
        integrator.get_secret.assert_called_once_with("path", "key")
        # default not used because secret found


def test_get_secret_function_default():
    with patch("config.vault_integrator.get_vault_integrator") as mock_get:
        integrator = MagicMock()
        integrator.get_secret.return_value = None
        mock_get.return_value = integrator
        result = get_secret("path", "key", "default_val")
        assert result == "default_val"


def test_process_vault_secrets_function():
    with patch("config.vault_integrator.get_vault_integrator") as mock_get:
        integrator = MagicMock()
        integrator.process_config.return_value = {"processed": True}
        mock_get.return_value = integrator
        result = process_vault_secrets({"test": "data"})
        assert result == {"processed": True}
        integrator.process_config.assert_called_once_with({"test": "data"})


# ============================================================================
# Tests for singleton accessor
# ============================================================================

def test_get_vault_integrator_singleton():
    i1 = get_vault_integrator()
    i2 = get_vault_integrator()
    assert i1 is i2