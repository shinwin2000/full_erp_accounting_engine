# tests/event_gateway/test_event_source_authenticator.py
"""
Comprehensive unit tests for event_gateway/event_source_authenticator.py.
Covers enums, exceptions, AuthenticatedSource, and EventSourceAuthenticator.
Includes direct tests for private authentication methods and exception paths.
"""

import base64
import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from event_gateway.event_source_authenticator import (
    AuthenticatedSource,
    AuthMethod,
    EventAuthenticationError,
    EventSourceAuthenticator,
)

# ============================================================================
# TESTS FOR AUTHMETHOD
# ============================================================================

class TestAuthMethod:
    def test_members_exist(self):
        assert hasattr(AuthMethod, 'HMAC_SHA256')
        assert hasattr(AuthMethod, 'API_KEY')
        assert hasattr(AuthMethod, 'JWT')
        assert hasattr(AuthMethod, 'IP_WHITELIST')
        assert hasattr(AuthMethod, 'SERVICE_NAME')

    def test_member_is_instance(self):
        assert isinstance(AuthMethod.HMAC_SHA256, AuthMethod)

    def test_display_name(self):
        assert AuthMethod.HMAC_SHA256.display_name() == "HMAC-SHA256"
        assert AuthMethod.API_KEY.display_name() == "API Key"
        assert AuthMethod.JWT.display_name() == "JWT"
        assert AuthMethod.IP_WHITELIST.display_name() == "IP Whitelist"
        assert AuthMethod.SERVICE_NAME.display_name() == "Service Name"


# ============================================================================
# TESTS FOR EVENTAUTHENTICATIONERROR
# ============================================================================

class TestEventAuthenticationError:
    def test_construction(self):
        exc = EventAuthenticationError("message")
        assert isinstance(exc, Exception)
        assert str(exc) == "message"

    def test_construction_without_message(self):
        exc = EventAuthenticationError()
        assert str(exc) == ""


# ============================================================================
# TESTS FOR AUTHENTICATEDSOURCE
# ============================================================================

class TestAuthenticatedSource:
    def test_construction_valid(self):
        source = AuthenticatedSource(
            source_id="src-1",
            method=AuthMethod.API_KEY,
            roles=["admin"],
            permissions=["read", "write"],
            metadata={"env": "test"},
        )
        assert source.source_id == "src-1"
        assert source.method == AuthMethod.API_KEY
        assert source.roles == ["admin"]
        assert source.permissions == ["read", "write"]
        assert source.metadata == {"env": "test"}
        assert source._version == 1
        assert source._id is not None
        assert len(source._snapshots) == 1  # __post_init__ calls _take_snapshot

    def test_construction_missing_source_id_raises(self):
        with pytest.raises(ValueError, match="source_id is required"):
            AuthenticatedSource(source_id="", method=AuthMethod.API_KEY)

    def test_construction_invalid_method_raises(self):
        with pytest.raises(ValueError, match="method must be AuthMethod enum"):
            AuthenticatedSource(source_id="src-1", method="invalid")  # type: ignore

    def test_validate(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        result = source.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        source = AuthenticatedSource(source_id="", method=AuthMethod.API_KEY)
        # We need to bypass __post_init__ validation to test validate directly.
        # We can create an instance and then manually call _validate.
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        source._validate = MagicMock(side_effect=ValueError("Invalid"))
        result = source.validate()
        assert result["is_valid"] is False
        assert "Invalid" in result["errors"][0]

    def test_to_dict(self):
        source = AuthenticatedSource(
            source_id="src-1",
            method=AuthMethod.JWT,
            roles=["user"],
            permissions=["view"],
            metadata={"foo": "bar"},
        )
        d = source.to_dict()
        assert d["id"] == source._id
        assert d["source_id"] == "src-1"
        assert d["method"] == "jwt"
        assert d["roles"] == ["user"]
        assert d["permissions"] == ["view"]
        assert d["metadata"] == {"foo": "bar"}
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "id": "custom-id",
            "source_id": "src-2",
            "method": "hmac_sha256",
            "roles": ["editor"],
            "permissions": ["edit"],
            "metadata": {"key": "val"},
            "version": 3,
        }
        source = AuthenticatedSource.from_dict(data)
        assert source._id == "custom-id"
        assert source.source_id == "src-2"
        assert source.method == AuthMethod.HMAC_SHA256
        assert source.roles == ["editor"]
        assert source.permissions == ["edit"]
        assert source.metadata == {"key": "val"}
        assert source._version == 3

    def test_from_dict_with_defaults(self):
        data = {"source_id": "src-3", "method": "api_key"}
        source = AuthenticatedSource.from_dict(data)
        assert source.source_id == "src-3"
        assert source.method == AuthMethod.API_KEY
        assert source.roles == []
        assert source.permissions == []
        assert source.metadata == {}
        assert source._version == 1
        assert source._id is not None

    def test_clone(self):
        source = AuthenticatedSource(
            source_id="src-1",
            method=AuthMethod.API_KEY,
            roles=["admin"],
            permissions=["*"],
            metadata={"env": "prod"},
        )
        clone = source.clone()
        assert clone is not source
        assert clone.source_id == source.source_id
        assert clone.method == source.method
        assert clone.roles == source.roles
        assert clone.permissions == source.permissions
        assert clone.metadata == source.metadata
        assert clone._version == source._version + 1
        # Audit trail should have CLONE entry
        assert len(clone._audit_trail) == 1
        assert clone._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        snap = source.snapshot()
        assert snap["version"] == 1
        assert snap["id"] == source._id
        assert snap["source_id"] == "src-1"
        assert snap["method"] == "api_key"
        assert "timestamp" in snap

    def test_version(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        assert source.version() == 1
        source._version = 5
        assert source.version() == 5

    def test_audit_trail(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        source._record_audit("ACTION1", "user1", {"detail": "a"})
        source._record_audit("ACTION2", "user2", {"detail": "b"})
        trail = source.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "ACTION1"
        assert trail[1]["action"] == "ACTION2"

    def test_audit_trail_limit(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        for i in range(150):
            source._record_audit(f"ACTION{i}", "user", {})
        trail = source.audit_trail(limit=100)
        assert len(trail) == 100

    def test_touch(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        old_version = source.version()
        result = source.touch("admin")
        assert result is source
        assert source.version() == old_version + 1
        assert len(source._audit_trail) == 1
        assert source._audit_trail[0]["action"] == "TOUCH"

    def test_take_snapshot(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        # Already one snapshot from __post_init__
        assert len(source._snapshots) == 1
        source._take_snapshot()
        assert len(source._snapshots) == 2
        # Test limit
        for _ in range(20):
            source._take_snapshot()
        assert len(source._snapshots) <= 10

    def test_record_audit(self):
        source = AuthenticatedSource(source_id="src-1", method=AuthMethod.API_KEY)
        source._record_audit("TEST", "actor", {"key": "value"})
        assert len(source._audit_trail) == 1
        entry = source._audit_trail[0]
        assert entry["action"] == "TEST"
        assert entry["performed_by"] == "actor"
        assert entry["details"] == {"key": "value"}
        assert "timestamp" in entry


# ============================================================================
# TESTS FOR EVENTSOURCEAUTHENTICATOR
# ============================================================================

@pytest.fixture
def config():
    return {
        "api_keys": {"api-source": "secret-api-key"},
        "hmac_secrets": {"hmac-source": "hmac-secret"},
        "jwt_public_keys": {
            "jwt-source": "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----"
        },
        "ip_whitelist": {"ip-source": ["192.168.1.0/24"]},
        "service_whitelist": ["service-a", "service-b"],
        "enable_timestamp_check": True,
        "max_skew_seconds": 60,
    }


@pytest.fixture
def authenticator(config):
    return EventSourceAuthenticator(config)


class TestEventSourceAuthenticator:
    def test_construction(self, config):
        auth = EventSourceAuthenticator(config)
        assert auth.api_keys == config["api_keys"]
        assert auth.hmac_secrets == config["hmac_secrets"]
        assert auth.jwt_public_keys == config["jwt_public_keys"]
        assert auth.ip_whitelist == config["ip_whitelist"]
        assert auth.service_whitelist == config["service_whitelist"]
        assert auth.enable_timestamp_check is True
        assert auth.max_skew_seconds == 60
        assert auth._version == 1
        assert len(auth._snapshots) == 1

    def test_authenticate_api_key_success(self, authenticator):
        event = {"headers": {"X-API-Key": "secret-api-key"}}
        source_metadata = {"ip_address": "192.168.1.1"}
        result = authenticator.authenticate(event, source_metadata)
        assert isinstance(result, AuthenticatedSource)
        assert result.source_id == "api-source"
        assert result.method == AuthMethod.API_KEY
        assert result.metadata == {"ip": "192.168.1.1"}
        # Check audit trail
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_API_KEY_SUCCESS" for e in trail)

    def test_authenticate_api_key_failure(self, authenticator):
        event = {"headers": {"X-API-Key": "wrong-key"}}
        with pytest.raises(EventAuthenticationError, match="Invalid API Key"):
            authenticator.authenticate(event, {})
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_API_KEY_FAILURE" for e in trail)

    def test_authenticate_hmac_success(self, authenticator):
        # Prepare HMAC
        source_id = "hmac-source"
        secret = "hmac-secret"
        timestamp = int(time.time())
        method = "POST"
        path = "/events"
        body = {"data": "test"}
        body_json = json.dumps(body, sort_keys=True)
        message = f"{timestamp}{method}{path}{body_json}".encode()
        sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()

        event = {
            "source": source_id,
            "timestamp": timestamp,
            "method": method,
            "path": path,
            "body": body,
            "headers": {"Authorization": f"HMAC {sig_b64}"},
        }
        result = authenticator.authenticate(event, {})
        assert isinstance(result, AuthenticatedSource)
        assert result.source_id == source_id
        assert result.method == AuthMethod.HMAC_SHA256
        assert result.metadata == {"timestamp": timestamp}
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_HMAC_SUCCESS" for e in trail)

    def test_authenticate_hmac_invalid_signature(self, authenticator):
        event = {
            "source": "hmac-source",
            "timestamp": int(time.time()),
            "method": "POST",
            "path": "/events",
            "body": {"data": "test"},
            "headers": {"Authorization": "HMAC invalidbase64"},
        }
        with pytest.raises(EventAuthenticationError, match="Invalid HMAC signature format"):
            authenticator.authenticate(event, {})

    def test_authenticate_hmac_unknown_source(self, authenticator):
        event = {
            "source": "unknown",
            "headers": {"Authorization": "HMAC dGVzdA=="},  # base64 of "test"
        }
        with pytest.raises(EventAuthenticationError, match="Unknown source for HMAC"):
            authenticator.authenticate(event, {})

    def test_authenticate_hmac_mismatch(self, authenticator):
        # Wrong signature
        event = {
            "source": "hmac-source",
            "timestamp": int(time.time()),
            "method": "POST",
            "path": "/events",
            "body": {"data": "test"},
            "headers": {"Authorization": "HMAC dGVzdA=="},  # base64 of "test"
        }
        with pytest.raises(EventAuthenticationError, match="HMAC signature mismatch"):
            authenticator.authenticate(event, {})

    def test_authenticate_hmac_timestamp_too_old(self, authenticator):
        # Set max_skew_seconds to small value
        authenticator.max_skew_seconds = 10
        old_timestamp = int(time.time()) - 100
        secret = "hmac-secret"
        body = {"data": "test"}
        body_json = json.dumps(body, sort_keys=True)
        message = f"{old_timestamp}POST/events{body_json}".encode()
        sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()
        event = {
            "source": "hmac-source",
            "timestamp": old_timestamp,
            "method": "POST",
            "path": "/events",
            "body": body,
            "headers": {"Authorization": f"HMAC {sig_b64}"},
        }
        with pytest.raises(EventAuthenticationError, match="Timestamp too old"):
            authenticator.authenticate(event, {})

    def test_authenticate_hmac_timestamp_check_disabled(self, authenticator):
        authenticator.enable_timestamp_check = False
        old_timestamp = int(time.time()) - 100
        secret = "hmac-secret"
        body = {"data": "test"}
        body_json = json.dumps(body, sort_keys=True)
        message = f"{old_timestamp}POST/events{body_json}".encode()
        sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()
        event = {
            "source": "hmac-source",
            "timestamp": old_timestamp,
            "method": "POST",
            "path": "/events",
            "body": body,
            "headers": {"Authorization": f"HMAC {sig_b64}"},
        }
        result = authenticator.authenticate(event, {})
        assert result.source_id == "hmac-source"

    def test_authenticate_jwt_success(self, authenticator):
        # Mock jwt.decode to return a payload
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {
                "sub": "jwt-source",
                "roles": ["admin"],
                "perms": ["read", "write"],
            }
            event = {"headers": {"Authorization": "Bearer some.jwt.token"}}
            result = authenticator.authenticate(event, {})
            assert isinstance(result, AuthenticatedSource)
            assert result.source_id == "jwt-source"
            assert result.method == AuthMethod.JWT
            assert result.roles == ["admin"]
            assert result.permissions == ["read", "write"]
            assert "jwt_payload" in result.metadata
            trail = authenticator.audit_trail()
            assert any(e["action"] == "AUTH_JWT_SUCCESS" for e in trail)

    def test_authenticate_jwt_failure(self, authenticator):
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            mock_jwt.decode.side_effect = Exception("Invalid token")
            event = {"headers": {"Authorization": "Bearer invalid"}}
            with pytest.raises(EventAuthenticationError, match="Invalid JWT"):
                authenticator.authenticate(event, {})
            trail = authenticator.audit_trail()
            assert any(e["action"] == "AUTH_JWT_FAILURE" for e in trail)

    def test_authenticate_service_name_success(self, authenticator):
        event = {"source": "service-a"}
        result = authenticator.authenticate(event, {})
        assert isinstance(result, AuthenticatedSource)
        assert result.source_id == "service-a"
        assert result.method == AuthMethod.SERVICE_NAME
        assert result.metadata == {"service": "service-a"}
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_SERVICE_SUCCESS" for e in trail)

    def test_authenticate_service_name_failure(self, authenticator):
        event = {"source": "service-unknown"}
        with pytest.raises(EventAuthenticationError, match="Service name service-unknown not allowed"):
            authenticator.authenticate(event, {})
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_SERVICE_FAILURE" for e in trail)

    def test_authenticate_ip_success(self, authenticator):
        event = {}
        source_metadata = {"ip_address": "192.168.1.50"}
        result = authenticator.authenticate(event, source_metadata)
        assert isinstance(result, AuthenticatedSource)
        assert result.source_id == "ip-source"
        assert result.method == AuthMethod.IP_WHITELIST
        assert result.metadata == {"ip": "192.168.1.50", "cidr": "192.168.1.0/24"}
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_IP_SUCCESS" for e in trail)

    def test_authenticate_ip_failure(self, authenticator):
        event = {}
        source_metadata = {"ip_address": "10.0.0.1"}
        with pytest.raises(EventAuthenticationError, match="IP 10.0.0.1 not allowed"):
            authenticator.authenticate(event, source_metadata)
        trail = authenticator.audit_trail()
        assert any(e["action"] == "AUTH_IP_FAILURE" for e in trail)

    def test_authenticate_no_method_raises(self, authenticator):
        event = {"headers": {}}  # no auth info
        source_metadata = {}
        with pytest.raises(EventAuthenticationError, match="No authentication method available"):
            authenticator.authenticate(event, source_metadata)

    def test_authenticate_uses_api_key_from_body(self, authenticator):
        event = {"api_key": "secret-api-key"}
        result = authenticator.authenticate(event, {})
        assert result.source_id == "api-source"

    def test_authenticate_prefers_bearer_over_api_key(self, authenticator):
        # If both Bearer and API key present, Bearer should win
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "jwt-source"}
            event = {
                "headers": {
                    "Authorization": "Bearer jwt.token",
                    "X-API-Key": "secret-api-key",
                }
            }
            result = authenticator.authenticate(event, {})
            assert result.source_id == "jwt-source"
            assert result.method == AuthMethod.JWT

    #def test_authenticate_prefers_hmac_over_bearer(self, authenticator):
        # If HMAC and Bearer both present, HMAC should win? The order is: Bearer first, then HMAC, then API key, then service, then IP.
        # So HMAC is after Bearer.
        # Let's test that HMAC is used when Bearer is not present.
        # This is covered by other tests. We'll just ensure the flow works.

    # ---- Private methods direct tests ----
    def test_authenticate_api_key_direct(self, authenticator):
        result = authenticator._authenticate_api_key("secret-api-key", {"ip_address": "1.2.3.4"})
        assert result.source_id == "api-source"
        assert result.method == AuthMethod.API_KEY
        assert result.metadata == {"ip": "1.2.3.4"}

    def test_authenticate_api_key_direct_failure(self, authenticator):
        with pytest.raises(EventAuthenticationError, match="Invalid API Key"):
            authenticator._authenticate_api_key("wrong", {})

    def test_authenticate_hmac_direct_success(self, authenticator):
        source_id = "hmac-source"
        secret = "hmac-secret"
        timestamp = int(time.time())
        method = "POST"
        path = "/events"
        body = {"data": "test"}
        body_json = json.dumps(body, sort_keys=True)
        message = f"{timestamp}{method}{path}{body_json}".encode()
        sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
        sig_b64 = base64.b64encode(sig).decode()
        event = {
            "source": source_id,
            "timestamp": timestamp,
            "method": method,
            "path": path,
            "body": body,
        }
        result = authenticator._authenticate_hmac(event, sig_b64, {})
        assert result.source_id == source_id
        assert result.method == AuthMethod.HMAC_SHA256
        assert result.metadata == {"timestamp": timestamp}

    def test_authenticate_hmac_direct_wrong_signature(self, authenticator):
        event = {"source": "hmac-source", "timestamp": int(time.time()), "method": "POST", "path": "/", "body": {}}
        with pytest.raises(EventAuthenticationError, match="HMAC signature mismatch"):
            authenticator._authenticate_hmac(event, base64.b64encode(b"wrong").decode(), {})

    def test_authenticate_jwt_direct_success(self, authenticator):
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            mock_jwt.decode.return_value = {"sub": "jwt-source", "roles": ["user"]}
            result = authenticator._authenticate_jwt("token", {})
            assert result.source_id == "jwt-source"
            assert result.method == AuthMethod.JWT
            assert result.roles == ["user"]

    def test_authenticate_jwt_direct_failure(self, authenticator):
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            mock_jwt.decode.side_effect = Exception("Invalid")
            with pytest.raises(EventAuthenticationError, match="Invalid JWT"):
                authenticator._authenticate_jwt("token", {})

    def test_authenticate_service_name_direct(self, authenticator):
        result = authenticator._authenticate_service_name("service-a", {})
        assert result.source_id == "service-a"
        assert result.method == AuthMethod.SERVICE_NAME

    def test_authenticate_service_name_direct_failure(self, authenticator):
        with pytest.raises(EventAuthenticationError, match="Service name unknown not allowed"):
            authenticator._authenticate_service_name("unknown", {})

    def test_authenticate_ip_direct_success(self, authenticator):
        result = authenticator._authenticate_ip("192.168.1.50", {})
        assert result.source_id == "ip-source"
        assert result.method == AuthMethod.IP_WHITELIST

    def test_authenticate_ip_direct_failure(self, authenticator):
        with pytest.raises(EventAuthenticationError, match="IP 10.0.0.1 not allowed"):
            authenticator._authenticate_ip("10.0.0.1", {})

    # ---- Validate, to_dict, from_dict, etc. ----
    def test_validate_success(self, authenticator):
        result = authenticator.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_max_skew(self, authenticator):
        authenticator.max_skew_seconds = -1
        result = authenticator.validate()
        assert result["is_valid"] is False
        assert "max_skew_seconds must be positive" in result["errors"]

    def test_to_dict(self, authenticator):
        d = authenticator.to_dict()
        assert d["api_keys_count"] == len(authenticator.api_keys)
        assert d["hmac_secrets_count"] == len(authenticator.hmac_secrets)
        assert d["jwt_keys_count"] == len(authenticator.jwt_public_keys)
        assert d["ip_whitelist_count"] == len(authenticator.ip_whitelist)
        assert d["service_whitelist"] == authenticator.service_whitelist
        assert d["enable_timestamp_check"] is True
        assert d["max_skew_seconds"] == 60
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "api_keys": {"key1": "val1"},
            "hmac_secrets": {"hmac1": "sec1"},
            "jwt_public_keys": {"jwt1": "pub1"},
            "ip_whitelist": {"ip1": ["10.0.0.0/8"]},
            "service_whitelist": ["svc1"],
            "enable_timestamp_check": False,
            "max_skew_seconds": 120,
            "version": 5,
        }
        auth = EventSourceAuthenticator.from_dict(data)
        assert auth.api_keys == {"key1": "val1"}
        assert auth.hmac_secrets == {"hmac1": "sec1"}
        assert auth.jwt_public_keys == {"jwt1": "pub1"}
        assert auth.ip_whitelist == {"ip1": ["10.0.0.0/8"]}
        assert auth.service_whitelist == ["svc1"]
        assert auth.enable_timestamp_check is False
        assert auth.max_skew_seconds == 120
        assert auth._version == 5

    def test_clone(self, authenticator):
        clone = authenticator.clone()
        assert clone is not authenticator
        assert clone.api_keys == authenticator.api_keys
        assert clone.hmac_secrets == authenticator.hmac_secrets
        assert clone.jwt_public_keys == authenticator.jwt_public_keys
        assert clone.ip_whitelist == authenticator.ip_whitelist
        assert clone.service_whitelist == authenticator.service_whitelist
        assert clone.enable_timestamp_check == authenticator.enable_timestamp_check
        assert clone.max_skew_seconds == authenticator.max_skew_seconds
        assert clone._version == authenticator._version + 1

    def test_snapshot(self, authenticator):
        snap = authenticator.snapshot()
        assert snap["version"] == 1
        assert "timestamp" in snap

    def test_version(self, authenticator):
        assert authenticator.version() == 1
        authenticator._version = 10
        assert authenticator.version() == 10

    def test_audit_trail(self, authenticator):
        authenticator._record_audit("A1", "u1", {"d": "a"})
        authenticator._record_audit("A2", "u2", {"d": "b"})
        trail = authenticator.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "A1"

    def test_audit_trail_limit(self, authenticator):
        for i in range(150):
            authenticator._record_audit(f"A{i}", "u", {})
        trail = authenticator.audit_trail(limit=100)
        assert len(trail) == 100

    def test_touch(self, authenticator):
        old_version = authenticator.version()
        result = authenticator.touch("admin")
        assert result is authenticator
        assert authenticator.version() == old_version + 1
        trail = authenticator.audit_trail()
        assert any(e["action"] == "TOUCH" for e in trail)

    def test_reset_stats(self, authenticator):
        # Add some audit entries
        authenticator._record_audit("A1", "u1", {})
        authenticator._record_audit("A2", "u2", {})
        old_version = authenticator.version()
        authenticator.reset_stats()
        assert authenticator.version() == old_version + 1
        assert authenticator.audit_trail() == []  # cleared
        # But there should be a RESET_STATS entry
        trail = authenticator.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "RESET_STATS"

    # ---- Additional edge cases ----
    def test_authenticate_with_empty_event_and_no_metadata(self, authenticator):
        with pytest.raises(EventAuthenticationError, match="No authentication method available"):
            authenticator.authenticate({}, {})

    def test_authenticate_ip_with_empty_ip_whitelist(self, authenticator):
        authenticator.ip_whitelist = {}
        event = {}
        source_metadata = {"ip_address": "192.168.1.1"}
        with pytest.raises(EventAuthenticationError, match="IP 192.168.1.1 not allowed"):
            authenticator.authenticate(event, source_metadata)

    def test_authenticate_service_name_with_empty_whitelist(self, authenticator):
        authenticator.service_whitelist = []
        event = {"source": "service-a"}
        with pytest.raises(EventAuthenticationError, match="Service name service-a not allowed"):
            authenticator.authenticate(event, {})

    def test_authenticate_jwt_with_multiple_keys(self, authenticator):
        # Add another key that fails first, then succeeds
        authenticator.jwt_public_keys["key2"] = "another-pubkey"
        with patch("event_gateway.event_source_authenticator.jwt") as mock_jwt:
            # First decode call raises, second succeeds
            mock_jwt.decode.side_effect = [
                Exception("Invalid for key1"),
                {"sub": "key2", "roles": []}
            ]
            event = {"headers": {"Authorization": "Bearer token"}}
            result = authenticator.authenticate(event, {})
            assert result.source_id == "key2"
            # Two decode calls attempted
            assert mock_jwt.decode.call_count == 2
