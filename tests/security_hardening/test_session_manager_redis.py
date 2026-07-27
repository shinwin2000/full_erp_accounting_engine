# tests/security_hardening/test_session_manager_redis.py
"""
Comprehensive tests for session_manager_redis.py
Covers all methods including entity methods, session lifecycle, and edge cases.
"""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from security_hardening.security_exceptions import SessionExpiredError
from security_hardening.session_manager_redis import (
    RedisSessionManager,
    SessionData,
    SessionManagerError,
    SessionNotFoundError,
    SessionRevokedError,
)


# ============================================================================
# Exception Tests
# ============================================================================

class TestSessionManagerError:
    def test_construction(self):
        error = SessionManagerError("test error")
        assert str(error) == "test error"
        assert isinstance(error, Exception)

    def test_inheritance(self):
        assert issubclass(SessionNotFoundError, SessionManagerError)
        assert issubclass(SessionRevokedError, SessionManagerError)


class TestSessionNotFoundError:
    def test_construction(self):
        error = SessionNotFoundError("session not found")
        assert str(error) == "session not found"


class TestSessionRevokedError:
    def test_construction_and_raise(self):
        with pytest.raises(SessionRevokedError, match="session revoked"):
            raise SessionRevokedError("session revoked")


# ============================================================================
# SessionData Tests
# ============================================================================

class TestSessionData:
    @pytest.fixture
    def valid_session_data(self):
        now = datetime.now(UTC)
        return SessionData(
            session_id="sess123",
            user_id="user456",
            user_data={"role": "admin", "name": "John"},
            client_fingerprint="fp789",
            ip_address="192.168.1.100",
            user_agent="Mozilla/5.0",
            created_at=now,
            last_activity=now,
            expires_at=now + timedelta(hours=1),
            is_revoked=False,
        )

    def test_construction(self, valid_session_data):
        assert valid_session_data.session_id == "sess123"
        assert valid_session_data.user_id == "user456"
        assert valid_session_data.user_data == {"role": "admin", "name": "John"}
        assert valid_session_data.client_fingerprint == "fp789"
        assert valid_session_data.ip_address == "192.168.1.100"
        assert valid_session_data.user_agent == "Mozilla/5.0"
        assert valid_session_data.is_revoked is False
        assert valid_session_data._version == 1
        assert len(valid_session_data._snapshots) == 1

    def test_validate_valid(self, valid_session_data):
        result = valid_session_data.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_missing_session_id(self, valid_session_data):
        valid_session_data.session_id = ""
        result = valid_session_data.validate()
        assert result["is_valid"] is False
        assert "session_id is required" in result["errors"]

    def test_validate_missing_user_id(self, valid_session_data):
        valid_session_data.user_id = ""
        result = valid_session_data.validate()
        assert result["is_valid"] is False
        assert "user_id is required" in result["errors"]

    def test_validate_naive_datetime(self, valid_session_data):
        valid_session_data.created_at = datetime.now()  # naive
        result = valid_session_data.validate()
        assert result["is_valid"] is False
        assert "created_at must be timezone-aware" in result["errors"]

    def test_validate_expires_before_created(self, valid_session_data):
        valid_session_data.expires_at = valid_session_data.created_at - timedelta(hours=1)
        result = valid_session_data.validate()
        assert result["is_valid"] is False
        assert "expires_at must be after created_at" in result["errors"]

    def test_to_dict(self, valid_session_data):
        d = valid_session_data.to_dict()
        assert d["session_id"] == "sess123"
        assert d["user_id"] == "user456"
        assert d["user_data"] == {"role": "admin", "name": "John"}
        assert d["client_fingerprint"] == "fp789"
        assert d["ip_address"] == "192.168.1.100"
        assert d["user_agent"] == "Mozilla/5.0"
        assert "created_at" in d
        assert "last_activity" in d
        assert "expires_at" in d
        assert d["is_revoked"] is False
        assert d["version"] == 1

    def test_from_dict(self):
        now = datetime.now(UTC)
        data = {
            "session_id": "sess789",
            "user_id": "user101",
            "user_data": {"role": "viewer"},
            "client_fingerprint": "fp999",
            "ip_address": "10.0.0.1",
            "user_agent": "Chrome",
            "created_at": now.isoformat(),
            "last_activity": now.isoformat(),
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "is_revoked": False,
            "version": 3,
        }
        session = SessionData.from_dict(data)
        assert session.session_id == "sess789"
        assert session.user_id == "user101"
        assert session.user_data == {"role": "viewer"}
        assert session._version == 3
        assert session.created_at == now

    def test_clone(self, valid_session_data):
        cloned = valid_session_data.clone()
        assert cloned is not valid_session_data
        assert cloned.user_id == valid_session_data.user_id
        assert cloned.user_data == valid_session_data.user_data
        assert cloned.client_fingerprint == valid_session_data.client_fingerprint
        assert cloned.ip_address == valid_session_data.ip_address
        assert cloned.user_agent == valid_session_data.user_agent
        assert cloned.is_revoked is False
        assert cloned.session_id != valid_session_data.session_id
        assert cloned._version == valid_session_data._version + 1
        # Check timestamps
        assert cloned.created_at > valid_session_data.created_at
        assert cloned.expires_at > valid_session_data.expires_at

    def test_snapshot(self, valid_session_data):
        snap = valid_session_data.snapshot()
        assert snap["version"] == 1
        assert snap["session_id"] == "sess123"
        assert snap["user_id"] == "user456"
        assert snap["is_revoked"] is False
        assert "timestamp" in snap

    def test_version(self, valid_session_data):
        assert valid_session_data.version() == 1
        valid_session_data._version = 5
        assert valid_session_data.version() == 5

    def test_audit_trail(self, valid_session_data):
        # Initially empty
        assert valid_session_data.audit_trail() == []
        # Record some audit entries
        valid_session_data._record_audit("ACTION1", "user1", {"detail": "test1"})
        valid_session_data._record_audit("ACTION2", "user2", {"detail": "test2"})
        trail = valid_session_data.audit_trail()
        assert len(trail) == 2
        assert trail[0]["action"] == "ACTION1"
        assert trail[1]["action"] == "ACTION2"
        # Test limit
        limited = valid_session_data.audit_trail(limit=1)
        assert len(limited) == 1
        assert limited[0]["action"] == "ACTION2"

    def test_touch(self, valid_session_data):
        initial_version = valid_session_data.version()
        result = valid_session_data.touch("tester")
        assert result is valid_session_data
        assert valid_session_data.version() == initial_version + 1
        # Check audit trail has TOUCH entry
        trail = valid_session_data.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"

    def test_snapshot_limit(self, valid_session_data):
        # Should have 1 snapshot from __post_init__
        assert len(valid_session_data._snapshots) == 1
        # Add many snapshots
        for i in range(15):
            valid_session_data._take_snapshot()
        # Should be limited to 10
        assert len(valid_session_data._snapshots) == 10


# ============================================================================
# RedisSessionManager Tests
# ============================================================================

class TestRedisSessionManager:
    @pytest.fixture
    def mock_redis_client(self):
        with patch('security_hardening.session_manager_redis.redis.Redis') as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    @pytest.fixture
    def manager(self, mock_redis_client):
        return RedisSessionManager(
            redis_host="localhost",
            redis_port=6379,
            redis_db=0,
            session_ttl_seconds=3600,
            idle_timeout_seconds=1800,
            max_sessions_per_user=5,
            enable_fingerprint=True,
            enable_ip_check=True,
        )

    def create_session_data_dict(self, session_id="sess123", user_id="user123", is_revoked=False):
        now = datetime.now(UTC)
        future = now + timedelta(hours=1)
        return {
            "session_id": session_id,
            "user_id": user_id,
            "user_data": {"role": "user"},
            "client_fingerprint": "fp123",
            "ip_address": "127.0.0.1",
            "user_agent": "Mozilla/5.0",
            "created_at": now.isoformat(),
            "last_activity": now.isoformat(),
            "expires_at": future.isoformat(),
            "is_revoked": is_revoked,
            "version": 1,
        }

    def mock_get_session(self, mock_redis_client, session_data_dict):
        mock_redis_client.get.return_value = json.dumps(session_data_dict)

    # ---- Initialization and helpers ----

    def test_construction(self, mock_redis_client):
        manager = RedisSessionManager(
            redis_host="localhost",
            redis_port=6379,
            session_ttl_seconds=3600,
            idle_timeout_seconds=1800,
            max_sessions_per_user=5,
            enable_fingerprint=True,
            enable_ip_check=False,
        )
        assert manager._session_ttl == 3600
        assert manager._idle_timeout == 1800
        assert manager._max_sessions == 5
        assert manager._enable_fingerprint is True
        assert manager._enable_ip is False
        assert manager._version == 1
        assert len(manager._snapshots) == 1
        mock_redis_client.assert_called_once()

    def test_get_session_key(self, manager):
        key = manager._get_session_key("sess123")
        assert key == "session:sess123"

    def test_get_user_sessions_key(self, manager):
        key = manager._get_user_sessions_key("user123")
        assert key == "user_sessions:user123"

    def test_validate(self, manager):
        result = manager.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_ttl(self, manager):
        manager._session_ttl = 0
        result = manager.validate()
        assert result["is_valid"] is False
        assert "session_ttl_seconds must be positive" in result["errors"]

    def test_validate_invalid_idle(self, manager):
        manager._idle_timeout = -1
        result = manager.validate()
        assert result["is_valid"] is False
        assert "idle_timeout_seconds must be positive" in result["errors"]

    def test_validate_invalid_max_sessions(self, manager):
        manager._max_sessions = 0
        result = manager.validate()
        assert result["is_valid"] is False
        assert "max_sessions_per_user must be positive" in result["errors"]

    def test_to_dict(self, manager):
        d = manager.to_dict()
        assert d["session_ttl_seconds"] == 3600
        assert d["idle_timeout_seconds"] == 1800
        assert d["max_sessions_per_user"] == 5
        assert d["enable_fingerprint"] is True
        assert d["enable_ip_check"] is True
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "redis_host": "redis.example.com",
            "redis_port": 6380,
            "redis_db": 1,
            "redis_password": "secret",
            "session_ttl_seconds": 7200,
            "idle_timeout_seconds": 3600,
            "max_sessions_per_user": 10,
            "enable_fingerprint": False,
            "enable_ip_check": True,
            "version": 5,
        }
        with patch('security_hardening.session_manager_redis.redis.Redis'):
            manager = RedisSessionManager.from_dict(data)
            assert manager._session_ttl == 7200
            assert manager._idle_timeout == 3600
            assert manager._max_sessions == 10
            assert manager._enable_fingerprint is False
            assert manager._enable_ip is True
            assert manager._version == 5

    def test_clone(self, mock_redis_client):
        with patch('security_hardening.session_manager_redis.redis.Redis'):
            manager = RedisSessionManager()
            original_version = manager.version()
            cloned = manager.clone()
            assert cloned is not manager
            assert cloned._session_ttl == manager._session_ttl
            assert cloned._idle_timeout == manager._idle_timeout
            assert cloned._max_sessions == manager._max_sessions
            assert cloned.version() == original_version + 1

    def test_snapshot(self, manager):
        snap = manager.snapshot()
        assert snap["version"] == 1
        assert snap["session_ttl_seconds"] == 3600
        assert snap["idle_timeout_seconds"] == 1800
        assert snap["max_sessions_per_user"] == 5
        assert "timestamp" in snap

    def test_version(self, manager):
        assert manager.version() == 1
        manager._version = 10
        assert manager.version() == 10

    def test_audit_trail(self, manager):
        assert manager.audit_trail() == []
        manager._record_audit("TEST", "user", {"detail": "value"})
        trail = manager.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, manager):
        initial_version = manager.version()
        result = manager.touch("tester")
        assert result is manager
        assert manager.version() == initial_version + 1
        trail = manager.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_reset(self, manager):
        manager._record_audit("TEST", "user", {})
        manager._version = 5
        manager.reset()
        assert manager._version == 1
        assert manager._audit_trail == []
        manager._redis.flushdb.assert_called_once()

    # ---- Session Lifecycle ----

    def test_create_session(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        session_id = manager.create_session(
            user_id="user123",
            user_data={"role": "admin"},
            client_fingerprint="fp123",
            ip_address="127.0.0.1",
            user_agent="Mozilla",
            ttl_seconds=3600,
        )
        assert session_id is not None
        assert len(session_id) > 0
        # Verify setex called
        mock_redis_client.setex.assert_called_once()
        # Verify sadd called
        mock_redis_client.sadd.assert_called_once()
        # Verify expire called
        mock_redis_client.expire.assert_called_once()

    def test_create_session_evicts_oldest(self, manager, mock_redis_client):
        # Simulate active sessions
        manager.get_active_sessions_for_user = MagicMock(return_value=[
            SessionData(session_id="old1", user_id="user123", user_data={}),
            SessionData(session_id="old2", user_id="user123", user_data={}),
            SessionData(session_id="old3", user_id="user123", user_data={}),
            SessionData(session_id="old4", user_id="user123", user_data={}),
            SessionData(session_id="old5", user_id="user123", user_data={}),
        ])
        mock_redis_client.get.return_value = None
        # Should evict oldest (revoke)
        with patch.object(manager, 'revoke_session') as mock_revoke:
            session_id = manager.create_session(
                user_id="user123",
                user_data={},
                client_fingerprint="fp",
                ip_address="127.0.0.1",
                user_agent="Mozilla",
            )
            mock_revoke.assert_called_once()

    def test_get_session_success(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)

        session = manager.get_session(
            session_id="sess123",
            client_fingerprint="fp123",
            ip_address="127.0.0.1",
            extend_ttl=True,
        )
        assert session.session_id == "sess123"
        assert session.user_id == "user123"
        assert session.is_revoked is False
        # Verify setex called for TTL extension
        mock_redis_client.setex.assert_called()

    def test_get_session_not_found(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        with pytest.raises(SessionExpiredError, match="not found or expired"):
            manager.get_session("nonexistent")

    def test_get_session_revoked(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict(is_revoked=True)
        self.mock_get_session(mock_redis_client, session_data)

        with pytest.raises(SessionRevokedError, match="has been revoked"):
            manager.get_session("sess123")

    def test_get_session_expired(self, manager, mock_redis_client):
        now = datetime.now(UTC)
        past = now - timedelta(hours=2)
        session_data = {
            "session_id": "sess123",
            "user_id": "user123",
            "user_data": {},
            "client_fingerprint": "fp123",
            "ip_address": "127.0.0.1",
            "user_agent": "Mozilla",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "last_activity": (now - timedelta(hours=2)).isoformat(),
            "expires_at": past.isoformat(),
            "is_revoked": False,
        }
        self.mock_get_session(mock_redis_client, session_data)

        with patch.object(manager, 'delete_session') as mock_delete:
            with pytest.raises(SessionExpiredError, match="absolute timeout"):
                manager.get_session("sess123", extend_ttl=False)
            mock_delete.assert_called_once_with("sess123")

    def test_get_session_idle_timeout(self, manager, mock_redis_client):
        now = datetime.now(UTC)
        session_data = {
            "session_id": "sess123",
            "user_id": "user123",
            "user_data": {},
            "client_fingerprint": "fp123",
            "ip_address": "127.0.0.1",
            "user_agent": "Mozilla",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "last_activity": (now - timedelta(hours=2)).isoformat(),
            "expires_at": (now + timedelta(hours=1)).isoformat(),
            "is_revoked": False,
        }
        self.mock_get_session(mock_redis_client, session_data)
        manager._idle_timeout = 1800  # 30 minutes, but last_activity is 2 hours ago

        with patch.object(manager, 'delete_session') as mock_delete:
            with pytest.raises(SessionExpiredError, match="idle timeout"):
                manager.get_session("sess123", extend_ttl=False)
            mock_delete.assert_called_once_with("sess123")

    def test_get_session_fingerprint_mismatch(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)

        with patch.object(manager, 'revoke_session') as mock_revoke:
            with pytest.raises(SessionExpiredError, match="fingerprint mismatch"):
                manager.get_session(
                    "sess123",
                    client_fingerprint="wrong_fp",
                    ip_address="127.0.0.1",
                    extend_ttl=False,
                )
            mock_revoke.assert_called_once_with("sess123", "user123", reason="fingerprint_mismatch")

    def test_get_session_ip_mismatch_warning(self, manager, mock_redis_client):
        manager._enable_ip = True
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)

        with patch('security_hardening.session_manager_redis.logger') as mock_logger:
            session = manager.get_session(
                "sess123",
                client_fingerprint="fp123",
                ip_address="10.0.0.5",  # different IP
                extend_ttl=False,
            )
            # Should still succeed but log warning
            assert session is not None
            mock_logger.warning.assert_called_once()

    def test_get_session_ip_mismatch_when_ip_present(self, manager, mock_redis_client):
        # Test when ip_address in session is None and we compare
        manager._enable_ip = True
        session_data = self.create_session_data_dict()
        session_data["ip_address"] = None
        self.mock_get_session(mock_redis_client, session_data)

        with patch('security_hardening.session_manager_redis.logger') as mock_logger:
            session = manager.get_session(
                "sess123",
                client_fingerprint="fp123",
                ip_address="10.0.0.5",
                extend_ttl=False,
            )
            assert session is not None
            # No warning because session.ip_address is None, so we skip check
            mock_logger.warning.assert_not_called()

    def test_update_session_data_success(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)
        mock_redis_client.ttl.return_value = 3600

        result = manager.update_session_data("sess123", {"role": "admin", "permission": "write"})
        assert result is True
        # Check that setex was called with updated data
        mock_redis_client.setex.assert_called_once()
        # Verify audit recorded
        assert len(manager._audit_trail) > 0

    def test_update_session_data_not_found(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        result = manager.update_session_data("nonexistent", {"key": "value"})
        assert result is False

    def test_update_session_data_expired(self, manager, mock_redis_client):
        now = datetime.now(UTC)
        past = now - timedelta(hours=2)
        session_data = {
            "session_id": "sess123",
            "user_id": "user123",
            "user_data": {},
            "client_fingerprint": "fp123",
            "ip_address": "127.0.0.1",
            "user_agent": "Mozilla",
            "created_at": (now - timedelta(hours=3)).isoformat(),
            "last_activity": (now - timedelta(hours=2)).isoformat(),
            "expires_at": past.isoformat(),
            "is_revoked": False,
        }
        self.mock_get_session(mock_redis_client, session_data)

        result = manager.update_session_data("sess123", {"key": "value"})
        assert result is False

    def test_delete_session_success(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)

        result = manager.delete_session("sess123")
        assert result is True
        mock_redis_client.delete.assert_called()
        mock_redis_client.srem.assert_called()

    def test_delete_session_not_found(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        result = manager.delete_session("nonexistent")
        assert result is False

    def test_revoke_session_success(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)
        mock_redis_client.ttl.return_value = 3600

        result = manager.revoke_session("sess123", "user123", reason="security_breach")
        assert result is True
        # Verify setex called with updated is_revoked=True
        mock_redis_client.setex.assert_called_once()
        # Verify audit recorded
        assert len(manager._audit_trail) > 0

    def test_revoke_session_not_found(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        result = manager.revoke_session("nonexistent", "user123")
        assert result is False

    def test_revoke_all_user_sessions(self, manager, mock_redis_client):
        mock_redis_client.smembers.return_value = {"sess1", "sess2", "sess3"}
        with patch.object(manager, 'revoke_session') as mock_revoke:
            mock_revoke.return_value = True
            count = manager.revoke_all_user_sessions("user123", reason="logout")
            assert count == 3
            assert mock_revoke.call_count == 3

    # ---- Query Methods ----

    def test_get_active_sessions_for_user(self, manager, mock_redis_client):
        mock_redis_client.smembers.return_value = {"sess1", "sess2"}

        # Mock get_session to return valid sessions
        with patch.object(manager, 'get_session') as mock_get:
            session1 = SessionData(session_id="sess1", user_id="user123", user_data={})
            session2 = SessionData(session_id="sess2", user_id="user123", user_data={})
            mock_get.side_effect = [session1, session2]

            sessions = manager.get_active_sessions_for_user("user123")
            assert len(sessions) == 2
            assert sessions[0].session_id == "sess1"
            assert sessions[1].session_id == "sess2"

    def test_get_active_sessions_for_user_expired(self, manager, mock_redis_client):
        mock_redis_client.smembers.return_value = {"sess1", "sess2"}

        with patch.object(manager, 'get_session') as mock_get:
            mock_get.side_effect = SessionExpiredError("expired")
            sessions = manager.get_active_sessions_for_user("user123")
            assert len(sessions) == 0

    def test_is_session_valid_true(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)

        result = manager.is_session_valid("sess123")
        assert result is True

    def test_is_session_valid_false(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None

        result = manager.is_session_valid("nonexistent")
        assert result is False

    def test_get_session_count(self, manager, mock_redis_client):
        mock_redis_client.scard.return_value = 5
        count = manager.get_session_count("user123")
        assert count == 5
        mock_redis_client.scard.assert_called_once_with("user_sessions:user123")

    def test_extend_ttl_success(self, manager, mock_redis_client):
        session_data = self.create_session_data_dict()
        self.mock_get_session(mock_redis_client, session_data)
        mock_redis_client.ttl.return_value = 3600

        result = manager.extend_ttl("sess123", additional_seconds=7200)
        assert result is True
        mock_redis_client.setex.assert_called_once()
        # Verify audit recorded
        assert len(manager._audit_trail) > 0

    def test_extend_ttl_not_found(self, manager, mock_redis_client):
        mock_redis_client.get.return_value = None
        result = manager.extend_ttl("nonexistent", 3600)
        assert result is False

    # ---- Maintenance ----

    def test_cleanup_expired_sessions(self, manager, mock_redis_client):
        # Simulate scan returning some user keys
        mock_redis_client.scan.side_effect = [
            (0, ["user_sessions:user1", "user_sessions:user2"]),
            (0, []),  # second call returns empty
        ]
        # Simulate smembers returning session IDs
        mock_redis_client.smembers.side_effect = [
            {"sess1", "sess2"},
            {"sess3"},
        ]
        # Simulate exists (first two exist, third doesn't)
        mock_redis_client.exists.side_effect = [1, 0, 0]

        count = manager.cleanup_expired_sessions()
        assert count == 2  # sess2 and sess3 cleaned
        # Check srem was called for cleaned sessions
        mock_redis_client.srem.assert_any_call("user_sessions:user1", "sess2")
        mock_redis_client.srem.assert_any_call("user_sessions:user2", "sess3")

    def test_start_cleanup_thread(self, manager, mock_redis_client):
        manager._running = False
        manager._start_cleanup_thread(interval_seconds=1)
        assert manager._running is True
        assert manager._cleanup_thread is not None
        assert isinstance(manager._cleanup_thread, threading.Thread)
        # Stop cleanup to avoid thread interference
        manager.stop_cleanup()

    def test_stop_cleanup(self, manager):
        manager._running = True
        manager._cleanup_thread = MagicMock()
        manager.stop_cleanup()
        assert manager._running is False

    # ---- Health Check ----

    def test_health_check_healthy(self, manager, mock_redis_client):
        result = manager.health_check()
        assert result["healthy"] is True
        assert result["redis_connected"] is True

    def test_health_check_unhealthy(self, manager, mock_redis_client):
        mock_redis_client.ping.side_effect = Exception("Connection failed")
        result = manager.health_check()
        assert result["healthy"] is False
        assert "Connection failed" in result["error"]

    # ---- Reporting ----

    def test_generate_report(self, manager, mock_redis_client):
        mock_redis_client.keys.return_value = ["session:sess1", "session:sess2", "session:sess3"]
        report = manager.generate_report()
        assert report["total_sessions"] == 3
        assert report["unique_users"] == 3  # 3 keys with prefix
        assert report["max_sessions_per_user"] == 5
        assert report["session_ttl_seconds"] == 3600
        assert report["idle_timeout_seconds"] == 1800
        assert "health" in report
        assert report["version"] == 1

    def test_get_statistics(self, manager, mock_redis_client):
        mock_redis_client.keys.return_value = ["session:sess1", "session:sess2"]
        stats = manager.get_statistics()
        assert stats["total_sessions"] == 2
        assert stats["unique_users"] == 2