# tests/domain/iam/test_session_entity.py
"""
Comprehensive unit tests for domain/iam/session_entity.py.
Covers all enums, exceptions, value objects, entity methods, repository,
and DTO. Uses fixed datetime mocking to avoid flakiness.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from domain.iam.session_entity import (
    DeviceType,
    InvalidSessionStatusTransitionError,
    SessionAudit,
    SessionEntity,
    SessionError,
    SessionExpiredError,
    SessionMetadata,
    SessionRepository,
    SessionStatus,
    UserSession,
)

# ============================================================================
# Fixed datetime to avoid flaky tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_FUTURE = FIXED_NOW + timedelta(hours=24)
FIXED_FUTURE_REFRESH = FIXED_NOW + timedelta(days=7)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in session_entity to fixed time."""
    with patch("domain.iam.session_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


@pytest.fixture
def sample_user_id():
    return uuid4()


@pytest.fixture
def sample_session(sample_user_id):
    """Create a valid active session."""
    return SessionEntity.create(
        user_id=sample_user_id,
        device_type=DeviceType.WEB,
        token_ttl_hours=24,
        refresh_ttl_days=7,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        location="Jakarta",
        device_name="Laptop",
        created_by="system",
    )


# ============================================================================
# Enum tests
# ============================================================================

class TestSessionStatus:
    def test_members(self):
        assert SessionStatus.ACTIVE.value == "active"
        assert SessionStatus.EXPIRED.value == "expired"
        assert SessionStatus.REVOKED.value == "revoked"
        assert SessionStatus.COMPROMISED.value == "compromised"
        assert SessionStatus.SUSPENDED.value == "suspended"

    def test_is_active(self):
        assert SessionStatus.ACTIVE.is_active() is True
        assert SessionStatus.EXPIRED.is_active() is False
        assert SessionStatus.REVOKED.is_active() is False
        assert SessionStatus.COMPROMISED.is_active() is False
        assert SessionStatus.SUSPENDED.is_active() is False

    def test_can_refresh(self):
        assert SessionStatus.ACTIVE.can_refresh() is True
        assert SessionStatus.SUSPENDED.can_refresh() is True
        assert SessionStatus.EXPIRED.can_refresh() is False
        assert SessionStatus.REVOKED.can_refresh() is False
        assert SessionStatus.COMPROMISED.can_refresh() is False

    def test_display_name(self):
        assert SessionStatus.ACTIVE.display_name() == "Aktif"
        assert SessionStatus.EXPIRED.display_name() == "Kadaluarsa"
        assert SessionStatus.REVOKED.display_name() == "Dicabut"
        assert SessionStatus.COMPROMISED.display_name() == "Terkompromi"
        assert SessionStatus.SUSPENDED.display_name() == "Ditangguhkan"

    def test_from_string(self):
        assert SessionStatus.from_string("active") == SessionStatus.ACTIVE
        assert SessionStatus.from_string("EXPIRED") == SessionStatus.EXPIRED
        assert SessionStatus.from_string("revoked") == SessionStatus.REVOKED
        assert SessionStatus.from_string("COMPROMISED") == SessionStatus.COMPROMISED
        assert SessionStatus.from_string("suspended") == SessionStatus.SUSPENDED
        assert SessionStatus.from_string("unknown") is None


class TestDeviceType:
    def test_members(self):
        assert DeviceType.WEB.value == "web"
        assert DeviceType.MOBILE.value == "mobile"
        assert DeviceType.TABLET.value == "tablet"
        assert DeviceType.API.value == "api"
        assert DeviceType.DESKTOP.value == "desktop"
        assert DeviceType.UNKNOWN.value == "unknown"

    def test_display_name(self):
        assert DeviceType.WEB.display_name() == "Web Browser"
        assert DeviceType.MOBILE.display_name() == "Mobile App"
        assert DeviceType.TABLET.display_name() == "Tablet"
        assert DeviceType.API.display_name() == "API Client"
        assert DeviceType.DESKTOP.display_name() == "Desktop App"
        assert DeviceType.UNKNOWN.display_name() == "Unknown"

    def test_from_string(self):
        assert DeviceType.from_string("web") == DeviceType.WEB
        assert DeviceType.from_string("MOBILE") == DeviceType.MOBILE
        assert DeviceType.from_string("tablet") == DeviceType.TABLET
        assert DeviceType.from_string("API") == DeviceType.API
        assert DeviceType.from_string("desktop") == DeviceType.DESKTOP
        assert DeviceType.from_string("unknown") == DeviceType.UNKNOWN
        assert DeviceType.from_string("invalid") is None


# ============================================================================
# Exception tests
# ============================================================================

class TestExceptions:
    def test_session_error(self):
        with pytest.raises(SessionError):
            raise SessionError("test")

    def test_invalid_status_transition(self):
        with pytest.raises(InvalidSessionStatusTransitionError):
            raise InvalidSessionStatusTransitionError("test")

    def test_session_expired_error(self):
        with pytest.raises(SessionExpiredError):
            raise SessionExpiredError("test")


# ============================================================================
# SessionMetadata tests
# ============================================================================

class TestSessionMetadata:
    def test_construction(self):
        meta = SessionMetadata(
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            location="Jakarta",
            device_name="Laptop",
            os_name="Windows 10",
            browser_name="Chrome",
        )
        assert meta.ip_address == "192.168.1.1"
        assert meta.user_agent == "Mozilla/5.0"

    def test_to_dict(self):
        meta = SessionMetadata(
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0" * 100,  # long string
        )
        d = meta.to_dict()
        assert d["ip_address"] == "192.168.1.1"
        # user_agent should be truncated to 200 chars
        assert len(d["user_agent"]) <= 200

    def test_from_dict(self):
        data = {
            "ip_address": "192.168.1.1",
            "user_agent": "Mozilla/5.0",
            "location": "Jakarta",
        }
        meta = SessionMetadata.from_dict(data)
        assert meta.ip_address == "192.168.1.1"
        assert meta.user_agent == "Mozilla/5.0"


# ============================================================================
# SessionAudit tests
# ============================================================================

class TestSessionAudit:
    def test_construction(self):
        audit = SessionAudit(
            created_at=FIXED_NOW,
            created_by="user",
            last_activity_at=FIXED_NOW,
            revoked_at=None,
            revoked_by=None,
            compromised_at=None,
            compromised_reason=None,
            version=1,
        )
        assert audit.created_at == FIXED_NOW
        assert audit.version == 1

    def test_to_dict(self):
        audit = SessionAudit(
            created_at=FIXED_NOW,
            created_by="user",
            last_activity_at=FIXED_NOW,
            revoked_at=FIXED_NOW,
            revoked_by="admin",
            compromised_at=FIXED_NOW,
            compromised_reason="suspicious",
            version=2,
        )
        d = audit.to_dict()
        assert d["created_at"] == FIXED_NOW.isoformat()
        assert d["revoked_by"] == "admin"
        assert d["version"] == 2


# ============================================================================
# SessionEntity tests
# ============================================================================

class TestSessionEntity:
    # ------------------------------------------------------------------------
    # Factory: create
    # ------------------------------------------------------------------------

    def test_create(self, sample_user_id):
        session = SessionEntity.create(
            user_id=sample_user_id,
            device_type=DeviceType.WEB,
            token_ttl_hours=24,
            refresh_ttl_days=7,
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            location="Jakarta",
            device_name="Laptop",
            created_by="system",
        )
        assert session.user_id == sample_user_id
        assert session.device_type == DeviceType.WEB
        assert session.status == SessionStatus.ACTIVE
        assert session.token is not None
        assert len(session.token) == 64
        assert session.refresh_token is not None
        assert len(session.refresh_token) == 64
        assert session.expires_at == FIXED_NOW + timedelta(hours=24)
        assert session.refresh_expires_at == FIXED_NOW + timedelta(days=7)
        assert session.metadata.ip_address == "192.168.1.1"
        assert session.metadata.user_agent == "Mozilla/5.0"
        assert session.audit.created_at == FIXED_NOW
        assert session.audit.created_by == "system"

    def test_create_default_ttl(self, sample_user_id):
        session = SessionEntity.create(
            user_id=sample_user_id,
            device_type=DeviceType.MOBILE,
        )
        assert session.expires_at == FIXED_NOW + timedelta(hours=24)
        assert session.refresh_expires_at == FIXED_NOW + timedelta(days=7)

    def test_create_custom_ttl(self, sample_user_id):
        session = SessionEntity.create(
            user_id=sample_user_id,
            device_type=DeviceType.API,
            token_ttl_hours=1,
            refresh_ttl_days=1,
        )
        assert session.expires_at == FIXED_NOW + timedelta(hours=1)
        assert session.refresh_expires_at == FIXED_NOW + timedelta(days=1)

    # ------------------------------------------------------------------------
    # Construction validation
    # ------------------------------------------------------------------------

    def test_construction_valid(self, sample_user_id):
        session = SessionEntity.create(sample_user_id, DeviceType.WEB)
        assert session.session_id is not None
        assert session.token is not None

    def test_construction_invalid_token(self):
        with pytest.raises(SessionError, match="Invalid token"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="short",
                refresh_token="valid_refresh_token_1234567890",
                device_type=DeviceType.WEB,
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_FUTURE_REFRESH,
            )

    def test_construction_invalid_refresh_token(self):
        with pytest.raises(SessionError, match="Invalid refresh token"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="short",
                device_type=DeviceType.WEB,
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_FUTURE_REFRESH,
            )

    def test_construction_invalid_device_type(self):
        with pytest.raises(SessionError, match="Invalid device_type"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="valid_refresh_1234567890",
                device_type="web",  # type: ignore
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_FUTURE_REFRESH,
            )

    def test_construction_invalid_status(self):
        with pytest.raises(SessionError, match="Invalid status"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="valid_refresh_1234567890",
                device_type=DeviceType.WEB,
                status="active",  # type: ignore
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_FUTURE_REFRESH,
            )

    def test_construction_expiry_before_creation(self):
        with pytest.raises(SessionError, match="Expiry time must be after creation time"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="valid_refresh_1234567890",
                device_type=DeviceType.WEB,
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_NOW - timedelta(hours=1),
                refresh_expires_at=FIXED_FUTURE_REFRESH,
            )

    def test_construction_refresh_expiry_before_token_expiry(self):
        with pytest.raises(SessionError, match="Refresh expiry must be after token expiry"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="valid_refresh_1234567890",
                device_type=DeviceType.WEB,
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_NOW + timedelta(hours=12),
            )

    def test_construction_version_zero(self):
        audit = SessionAudit(version=0)
        with pytest.raises(SessionError, match="Version must be >= 1"):
            SessionEntity(
                session_id=uuid4(),
                user_id=uuid4(),
                token="valid_token_1234567890",
                refresh_token="valid_refresh_1234567890",
                device_type=DeviceType.WEB,
                status=SessionStatus.ACTIVE,
                expires_at=FIXED_FUTURE,
                refresh_expires_at=FIXED_FUTURE_REFRESH,
                audit=audit,
            )

    # ------------------------------------------------------------------------
    # Serialization: to_dict / from_dict
    # ------------------------------------------------------------------------

    def test_to_dict(self, sample_session):
        d = sample_session.to_dict()
        assert d["session_id"] == str(sample_session.session_id)
        assert d["user_id"] == str(sample_session.user_id)
        assert d["token"] == sample_session.token
        assert d["refresh_token"] == sample_session.refresh_token
        assert d["device_type"] == sample_session.device_type.value
        assert d["status"] == sample_session.status.value
        assert "expires_at" in d
        assert "refresh_expires_at" in d
        assert "metadata" in d
        assert "audit" in d

    def test_from_dict(self, sample_session):
        d = sample_session.to_dict()
        # Ensure dates are ISO strings
        d["expires_at"] = sample_session.expires_at.isoformat()
        d["refresh_expires_at"] = sample_session.refresh_expires_at.isoformat()
        d["audit"] = sample_session.audit.to_dict()
        d["metadata"] = sample_session.metadata.to_dict()
        restored = SessionEntity.from_dict(d)
        assert restored.session_id == sample_session.session_id
        assert restored.token == sample_session.token
        assert restored.refresh_token == sample_session.refresh_token
        assert restored.device_type == sample_session.device_type
        assert restored.status == sample_session.status
        assert restored.expires_at == sample_session.expires_at
        assert restored.refresh_expires_at == sample_session.refresh_expires_at

    # ------------------------------------------------------------------------
    # Entity basic methods
    # ------------------------------------------------------------------------

    def test_stamp_create_audit(self, sample_session):
        # Initially audit trail might be empty
        sample_session._record_audit = lambda *args: None  # reset
        sample_session._audit_trail = []
        result = sample_session.stamp_create_audit("creator")
        assert result is sample_session
        assert len(sample_session._audit_trail) == 1
        assert sample_session._audit_trail[0]["action"] == "CREATE"

    def test_update_success(self, sample_session):
        new_device = DeviceType.MOBILE
        updated = sample_session.update("updater", device_type=new_device)
        assert updated.device_type == new_device
        assert updated.audit.version == sample_session.audit.version + 1
        assert len(updated._audit_trail) == 1  # because update creates audit entry
        assert updated._audit_trail[0]["action"] == "UPDATE"

    def test_update_invalid_status(self, sample_session):
        # Revoke session first
        revoked = sample_session.revoke("admin")
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot update"):
            revoked.update("updater", device_type=DeviceType.MOBILE)

    def test_delete_revoke(self, sample_session):
        deleted = sample_session.delete("admin", "logout")
        assert deleted.status == SessionStatus.REVOKED
        assert deleted.audit.revoked_by == "admin"
        assert deleted.audit.version == sample_session.audit.version + 1
        assert len(deleted._audit_trail) == 1
        assert deleted._audit_trail[0]["action"] == "DELETE"

    def test_delete_already_revoked(self, sample_session):
        revoked = sample_session.revoke("admin")
        deleted = revoked.delete("other")
        assert deleted is revoked  # already revoked, returns self

    def test_restore_success(self, sample_session):
        revoked = sample_session.revoke("admin")
        restored = revoked.restore("admin")
        assert restored.status == SessionStatus.ACTIVE
        assert restored.token != revoked.token  # new token
        assert restored.refresh_token != revoked.refresh_token
        assert restored.audit.version == revoked.audit.version + 1
        assert len(restored._audit_trail) == 1
        assert restored._audit_trail[0]["action"] == "RESTORE"

    def test_restore_invalid_status(self, sample_session):
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot restore"):
            sample_session.restore("admin")

    def test_activate_success(self, sample_session):
        # Suspend first
        suspended = sample_session.lock("admin", "suspicious")
        activated = suspended.activate("admin")
        assert activated.status == SessionStatus.ACTIVE
        assert activated.audit.version == suspended.audit.version + 1
        assert len(activated._audit_trail) == 1
        assert activated._audit_trail[0]["action"] == "ACTIVATE"

    def test_activate_already_active(self, sample_session):
        activated = sample_session.activate("admin")
        assert activated is sample_session

    def test_activate_invalid_status(self, sample_session):
        revoked = sample_session.revoke("admin")
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot activate"):
            revoked.activate("admin")

    def test_deactivate(self, sample_session):
        deactivated = sample_session.deactivate("admin", "logout")
        assert deactivated.status == SessionStatus.REVOKED
        assert deactivated.audit.revoked_by == "admin"

    def test_lock(self, sample_session):
        locked = sample_session.lock("admin", "suspicious")
        assert locked.status == SessionStatus.SUSPENDED
        assert locked.audit.version == sample_session.audit.version + 1
        assert len(locked._audit_trail) == 1
        assert locked._audit_trail[0]["action"] == "LOCK"

    def test_lock_invalid_status(self, sample_session):
        revoked = sample_session.revoke("admin")
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot lock"):
            revoked.lock("admin", "reason")

    def test_unlock(self, sample_session):
        locked = sample_session.lock("admin", "suspicious")
        unlocked = locked.unlock("admin")
        assert unlocked.status == SessionStatus.ACTIVE
        assert unlocked.audit.version == locked.audit.version + 1
        assert len(unlocked._audit_trail) == 1
        assert unlocked._audit_trail[0]["action"] == "UNLOCK"

    def test_unlock_invalid_status(self, sample_session):
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot unlock"):
            sample_session.unlock("admin")

    def test_validate_valid(self, sample_session):
        result = sample_session.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_expired(self, sample_session):
        # Set expires_at to past
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        result = sample_session.validate()
        assert result["is_valid"] is False
        assert "Session has expired" in result["errors"]

    def test_validate_refresh_expired(self, sample_session):
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(hours=1)
        result = sample_session.validate()
        assert result["is_valid"] is False
        assert "Refresh token has expired" in result["errors"]

    def test_clone(self, sample_session):
        cloned = sample_session.clone()
        assert cloned.session_id != sample_session.session_id
        assert cloned.user_id == sample_session.user_id
        assert cloned.token != sample_session.token
        assert cloned.refresh_token != sample_session.refresh_token
        assert cloned.status == SessionStatus.ACTIVE
        assert cloned.audit.version == 1
        assert cloned.audit.created_at == FIXED_NOW
        assert cloned.expires_at > FIXED_NOW
        assert cloned.refresh_expires_at > FIXED_NOW
        assert len(cloned._audit_trail) == 1
        assert cloned._audit_trail[0]["action"] == "CLONE"

    def test_snapshot(self, sample_session):
        snap = sample_session.snapshot()
        assert snap["version"] == sample_session.audit.version
        assert snap["session_id"] == str(sample_session.session_id)
        assert snap["status"] == sample_session.status.value

    def test_version(self, sample_session):
        assert sample_session.version() == sample_session.audit.version

    def test_audit_trail(self, sample_session):
        sample_session._record_audit("TEST", "user", {})
        trail = sample_session.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    def test_touch(self, sample_session):
        touched = sample_session.touch("user")
        assert touched.audit.version == sample_session.audit.version + 1
        assert touched.audit.last_activity_at == FIXED_NOW
        assert len(touched._audit_trail) == 1
        assert touched._audit_trail[0]["action"] == "TOUCH"

    # ------------------------------------------------------------------------
    # Business logic methods
    # ------------------------------------------------------------------------

    def test_is_active_true(self, sample_session):
        assert sample_session.is_active() is True

    def test_is_active_expired(self, sample_session):
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        assert sample_session.is_active() is False

    def test_is_active_revoked(self, sample_session):
        revoked = sample_session.revoke("admin")
        assert revoked.is_active() is False

    def test_is_expired(self, sample_session):
        assert sample_session.is_expired() is False
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        assert sample_session.is_expired() is True

    def test_is_refresh_valid(self, sample_session):
        assert sample_session.is_refresh_valid() is True
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(hours=1)
        assert sample_session.is_refresh_valid() is False

    def test_is_refresh_expired(self, sample_session):
        assert sample_session.is_refresh_expired() is False
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(hours=1)
        assert sample_session.is_refresh_expired() is True

    def test_can_refresh(self, sample_session):
        assert sample_session.can_refresh() is True
        # Expired token
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        sample_session.refresh_expires_at = FIXED_NOW + timedelta(hours=1)
        assert sample_session.can_refresh() is True  # refresh not expired yet
        # Refresh expired
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(hours=1)
        assert sample_session.can_refresh() is False

    def test_refresh_success(self, sample_session):
        refreshed = sample_session.refresh()
        assert refreshed.session_id == sample_session.session_id
        assert refreshed.user_id == sample_session.user_id
        assert refreshed.token != sample_session.token
        assert refreshed.refresh_token != sample_session.refresh_token
        assert refreshed.status == SessionStatus.ACTIVE
        # Expiry should be extended from now
        # TTL calculated from original creation
        original_ttl_hours = 24
        assert refreshed.expires_at == FIXED_NOW + timedelta(hours=original_ttl_hours)
        original_refresh_days = 7
        assert refreshed.refresh_expires_at == FIXED_NOW + timedelta(days=original_refresh_days)
        assert refreshed.audit.version == sample_session.audit.version + 1

    def test_refresh_expired(self, sample_session):
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        with pytest.raises(SessionExpiredError, match="Session has expired"):
            sample_session.refresh()

    def test_refresh_refresh_expired(self, sample_session):
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(hours=1)
        with pytest.raises(SessionExpiredError, match="Refresh token has expired"):
            sample_session.refresh()

    def test_refresh_invalid_status(self, sample_session):
        revoked = sample_session.revoke("admin")
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot refresh"):
            revoked.refresh()

    def test_revoke(self, sample_session):
        revoked = sample_session.revoke("admin")
        assert revoked.status == SessionStatus.REVOKED
        assert revoked.audit.revoked_by == "admin"
        assert revoked.audit.revoked_at == FIXED_NOW
        assert revoked.audit.version == sample_session.audit.version + 1

    def test_revoke_already_revoked(self, sample_session):
        revoked = sample_session.revoke("admin")
        revoked2 = revoked.revoke("other")
        assert revoked2 is revoked  # already revoked, returns self

    def test_mark_compromised(self, sample_session):
        compromised = sample_session.mark_compromised("suspicious login")
        assert compromised.status == SessionStatus.COMPROMISED
        assert compromised.audit.compromised_at == FIXED_NOW
        assert compromised.audit.compromised_reason == "suspicious login"
        assert compromised.audit.version == sample_session.audit.version + 1

    def test_update_activity(self, sample_session):
        # Simulate activity at a later time
        with patch("domain.iam.session_entity.datetime") as mock_dt:
            later = FIXED_NOW + timedelta(minutes=5)
            mock_dt.now.return_value = later
            updated = sample_session.update_activity()
        assert updated.audit.last_activity_at == later
        assert updated.audit.version == sample_session.audit.version + 1

    def test_extend(self, sample_session):
        extended = sample_session.extend(12)
        assert extended.expires_at == sample_session.expires_at + timedelta(hours=12)
        assert extended.refresh_expires_at == sample_session.refresh_expires_at
        assert extended.audit.version == sample_session.audit.version + 1

    def test_extend_inactive(self, sample_session):
        revoked = sample_session.revoke("admin")
        with pytest.raises(InvalidSessionStatusTransitionError, match="Cannot extend"):
            revoked.extend(12)

    def test_get_remaining_seconds(self, sample_session):
        # Since FIXED_NOW is 0, expiry is 24h from now
        assert sample_session.get_remaining_seconds() == 24 * 3600
        # If expired, should return 0
        sample_session.expires_at = FIXED_NOW - timedelta(seconds=1)
        assert sample_session.get_remaining_seconds() == 0

    def test_get_refresh_remaining_seconds(self, sample_session):
        assert sample_session.get_refresh_remaining_seconds() == 7 * 24 * 3600
        sample_session.refresh_expires_at = FIXED_NOW - timedelta(seconds=1)
        assert sample_session.get_refresh_remaining_seconds() == 0


# ============================================================================
# SessionRepository tests
# ============================================================================

class TestSessionRepository:
    def setup_method(self):
        SessionRepository._storage.clear()
        SessionRepository._storage_by_token.clear()
        SessionRepository._storage_by_refresh_token.clear()

    @pytest.fixture
    def sample_session(self):
        return SessionEntity.create(uuid4(), DeviceType.WEB)

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self, sample_session):
        await SessionRepository.save(sample_session)
        retrieved = await SessionRepository.get_by_id(sample_session.session_id)
        assert retrieved is not None
        assert retrieved.session_id == sample_session.session_id

    @pytest.mark.asyncio
    async def test_get_by_token(self, sample_session):
        await SessionRepository.save(sample_session)
        retrieved = await SessionRepository.get_by_token(sample_session.token)
        assert retrieved is not None
        assert retrieved.session_id == sample_session.session_id
        # Non-existent token
        assert await SessionRepository.get_by_token("invalid") is None

    @pytest.mark.asyncio
    async def test_get_by_refresh_token(self, sample_session):
        await SessionRepository.save(sample_session)
        retrieved = await SessionRepository.get_by_refresh_token(sample_session.refresh_token)
        assert retrieved is not None
        assert retrieved.session_id == sample_session.session_id
        # Non-existent
        assert await SessionRepository.get_by_refresh_token("invalid") is None

    @pytest.mark.asyncio
    async def test_get_active_by_user(self, sample_session):
        user_id = sample_session.user_id
        await SessionRepository.save(sample_session)
        active = await SessionRepository.get_active_by_user(user_id)
        assert len(active) == 1
        assert active[0].session_id == sample_session.session_id

        # Add another session for same user, revoke one
        session2 = SessionEntity.create(user_id, DeviceType.MOBILE)
        await SessionRepository.save(session2)
        revoked = session2.revoke("admin")
        await SessionRepository.save(revoked)
        active2 = await SessionRepository.get_active_by_user(user_id)
        assert len(active2) == 1
        assert active2[0].session_id == sample_session.session_id

    @pytest.mark.asyncio
    async def test_get_all_by_user(self, sample_session):
        user_id = sample_session.user_id
        await SessionRepository.save(sample_session)
        session2 = SessionEntity.create(user_id, DeviceType.MOBILE)
        await SessionRepository.save(session2)
        all_sessions = await SessionRepository.get_all_by_user(user_id)
        assert len(all_sessions) == 2
        # Different user
        assert await SessionRepository.get_all_by_user(uuid4()) == []

    @pytest.mark.asyncio
    async def test_get_by_status(self, sample_session):
        await SessionRepository.save(sample_session)
        active = await SessionRepository.get_by_status(SessionStatus.ACTIVE)
        assert len(active) == 1
        revoked = sample_session.revoke("admin")
        await SessionRepository.save(revoked)
        active2 = await SessionRepository.get_by_status(SessionStatus.ACTIVE)
        assert len(active2) == 0
        revoked_list = await SessionRepository.get_by_status(SessionStatus.REVOKED)
        assert len(revoked_list) == 1

    @pytest.mark.asyncio
    async def test_get_expired(self, sample_session):
        await SessionRepository.save(sample_session)
        # Expire session
        sample_session.expires_at = FIXED_NOW - timedelta(hours=1)
        await SessionRepository.save(sample_session)
        expired = await SessionRepository.get_expired()
        assert len(expired) == 1
        assert expired[0].session_id == sample_session.session_id

    @pytest.mark.asyncio
    async def test_get_all(self, sample_session):
        await SessionRepository.save(sample_session)
        session2 = SessionEntity.create(uuid4(), DeviceType.MOBILE)
        await SessionRepository.save(session2)
        all_sessions = await SessionRepository.get_all()
        assert len(all_sessions) == 2

    @pytest.mark.asyncio
    async def test_update(self, sample_session):
        await SessionRepository.save(sample_session)
        sample_session.status = SessionStatus.SUSPENDED
        await SessionRepository.update(sample_session)
        retrieved = await SessionRepository.get_by_id(sample_session.session_id)
        assert retrieved.status == SessionStatus.SUSPENDED

    @pytest.mark.asyncio
    async def test_delete(self, sample_session):
        await SessionRepository.save(sample_session)
        await SessionRepository.delete(sample_session.session_id)
        assert await SessionRepository.get_by_id(sample_session.session_id) is None
        # Token maps should be cleared
        assert sample_session.token not in SessionRepository._storage_by_token
        assert sample_session.refresh_token not in SessionRepository._storage_by_refresh_token

    @pytest.mark.asyncio
    async def test_revoke_all_user_sessions(self, sample_session):
        user_id = sample_session.user_id
        await SessionRepository.save(sample_session)
        session2 = SessionEntity.create(user_id, DeviceType.MOBILE)
        await SessionRepository.save(session2)
        # Different user session
        session3 = SessionEntity.create(uuid4(), DeviceType.WEB)
        await SessionRepository.save(session3)

        count = await SessionRepository.revoke_all_user_sessions(user_id, "admin")
        assert count == 2
        # Check both revoked
        for s in await SessionRepository.get_all_by_user(user_id):
            assert s.status == SessionStatus.REVOKED
            assert s.audit.revoked_by == "admin"
        # Other user should remain active
        other = await SessionRepository.get_by_id(session3.session_id)
        assert other.status == SessionStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_exists(self, sample_session):
        await SessionRepository.save(sample_session)
        assert await SessionRepository.exists(sample_session.session_id) is True
        assert await SessionRepository.exists(uuid4()) is False

    @pytest.mark.asyncio
    async def test_count(self, sample_session):
        assert await SessionRepository.count() == 0
        await SessionRepository.save(sample_session)
        assert await SessionRepository.count() == 1
        await SessionRepository.save(SessionEntity.create(uuid4(), DeviceType.WEB))
        assert await SessionRepository.count() == 2

    @pytest.mark.asyncio
    async def test_list(self, sample_session):
        await SessionRepository.save(sample_session)
        session2 = SessionEntity.create(uuid4(), DeviceType.WEB)
        await SessionRepository.save(session2)
        session3 = SessionEntity.create(uuid4(), DeviceType.WEB)
        await SessionRepository.save(session3)
        # list returns all sessions sorted in insertion order (dict values)
        all_sessions = await SessionRepository.list(limit=2, offset=0)
        assert len(all_sessions) == 2
        all_sessions2 = await SessionRepository.list(limit=2, offset=2)
        assert len(all_sessions2) == 1

    @pytest.mark.asyncio
    async def test_clear(self, sample_session):
        await SessionRepository.save(sample_session)
        assert await SessionRepository.count() == 1
        await SessionRepository.clear()
        assert await SessionRepository.count() == 0
        assert len(SessionRepository._storage_by_token) == 0
        assert len(SessionRepository._storage_by_refresh_token) == 0


# ============================================================================
# UserSession DTO tests
# ============================================================================

class TestUserSession:
    def test_construction(self):
        user_session = UserSession(
            id=uuid4(),
            user_id=uuid4(),
            session_token="token123",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            is_active=True,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=24),
        )
        assert user_session.id is not None
        assert user_session.session_token == "token123"

    def test_to_entity(self):
        user_session = UserSession(
            id=uuid4(),
            user_id=uuid4(),
            session_token="token123",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            is_active=True,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=24),
        )
        entity = user_session.to_entity()
        assert entity.session_id == user_session.id
        assert entity.user_id == user_session.user_id
        assert entity.token == user_session.session_token
        assert entity.status == SessionStatus.ACTIVE
        assert entity.metadata.ip_address == user_session.ip_address
        assert entity.metadata.user_agent == user_session.user_agent
        assert entity.audit.created_at == user_session.created_at
        assert entity.expires_at == user_session.expires_at
        assert entity.refresh_expires_at is not None

    def test_to_entity_inactive(self):
        user_session = UserSession(
            id=uuid4(),
            user_id=uuid4(),
            session_token="token123",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
            is_active=False,
            created_at=FIXED_NOW,
            expires_at=FIXED_NOW + timedelta(hours=24),
        )
        entity = user_session.to_entity()
        assert entity.status == SessionStatus.REVOKED