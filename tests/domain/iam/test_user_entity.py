# test_user_entity.py
# Comprehensive tests for user_entity.py

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.iam.user_entity import (
    InvalidUserStatusTransitionError,
    UserAudit,
    UserEntity,
    UserError,
    UserProfile,
    UserRepository,
    UserStatus,
)
from domain.iam.password_hashed_vo import PasswordHashedVO


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_storage():
    """Reset class variables before each test."""
    UserEntity._audit_trail = []
    UserEntity._snapshots = []
    UserEntity._instances = {}
    UserRepository._storage = {}
    UserRepository._storage_by_username = {}
    UserRepository._storage_by_email = {}
    yield
    UserEntity._audit_trail = []
    UserEntity._snapshots = []
    UserEntity._instances = {}
    UserRepository._storage = {}
    UserRepository._storage_by_username = {}
    UserRepository._storage_by_email = {}


@pytest.fixture
def valid_password_hash():
    """Create a valid password hash."""
    return PasswordHashedVO("hashed_password", "bcrypt")


@pytest.fixture
def valid_user_profile():
    """Create a valid UserProfile."""
    return UserProfile(
        full_name="John Doe",
        email="john.doe@example.com",
        phone="08123456789",
        mobile="08123456789",
        department="IT",
        position="Software Engineer",
        avatar_url="https://example.com/avatar.jpg",
        timezone="Asia/Jakarta",
        language="id",
        metadata={"key": "value"},
    )


@pytest.fixture
def valid_user_audit():
    """Create a valid UserAudit."""
    return UserAudit(
        last_login_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        last_login_ip="192.168.1.1",
        last_password_change_at=datetime(2024, 12, 1, 10, 0, 0, tzinfo=UTC),
        last_password_change_by="admin",
        created_at=datetime(2024, 11, 1, 10, 0, 0, tzinfo=UTC),
        created_by="system",
        updated_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        updated_by="admin",
        deleted_at=None,
        deleted_by=None,
        version=1,
    )


@pytest.fixture
def valid_user(valid_password_hash, valid_user_profile, valid_user_audit):
    """Create a valid UserEntity."""
    return UserEntity(
        user_id=uuid4(),
        username="johndoe",
        email="john.doe@example.com",
        password_hash=valid_password_hash,
        status=UserStatus.ACTIVE,
        profile=valid_user_profile,
        legal_entity_id=uuid4(),
        role_ids=[uuid4(), uuid4()],
        failed_login_attempts=0,
        locked_until=None,
        mfa_enabled=False,
        mfa_secret=None,
        audit=valid_user_audit,
    )


@pytest.fixture
def pending_user(valid_password_hash, valid_user_profile):
    """Create a pending user."""
    return UserEntity(
        user_id=uuid4(),
        username="pendinguser",
        email="pending@example.com",
        password_hash=valid_password_hash,
        status=UserStatus.PENDING_ACTIVATION,
        profile=valid_user_profile,
        legal_entity_id=uuid4(),
        role_ids=[],
        failed_login_attempts=0,
        locked_until=None,
        mfa_enabled=False,
        mfa_secret=None,
        audit=UserAudit(created_by="system"),
    )


@pytest.fixture
def inactive_user(valid_user):
    """Create an inactive user."""
    return valid_user.deactivate("admin", "Test deactivation")


@pytest.fixture
def locked_user(valid_user):
    """Create a locked user."""
    return valid_user.lock("admin", "Security reason")


@pytest.fixture
def suspended_user(valid_user):
    """Create a suspended user."""
    return valid_user.suspend("admin", "Test suspension")


@pytest.fixture
def deleted_user(valid_user):
    """Create a deleted user."""
    return valid_user.delete("admin", "Test deletion")


# ============================================================================
# Tests for Enums
# ============================================================================

class TestUserStatus:
    def test_members(self):
        assert UserStatus.ACTIVE.value == "active"
        assert UserStatus.INACTIVE.value == "inactive"
        assert UserStatus.LOCKED.value == "locked"
        assert UserStatus.PENDING_ACTIVATION.value == "pending"
        assert UserStatus.SUSPENDED.value == "suspended"
        assert UserStatus.DELETED.value == "deleted"

    def test_can_login(self):
        assert UserStatus.ACTIVE.can_login() is True
        assert UserStatus.INACTIVE.can_login() is False
        assert UserStatus.LOCKED.can_login() is False
        assert UserStatus.PENDING_ACTIVATION.can_login() is False
        assert UserStatus.SUSPENDED.can_login() is False
        assert UserStatus.DELETED.can_login() is False

    def test_can_be_modified(self):
        assert UserStatus.ACTIVE.can_be_modified() is True
        assert UserStatus.INACTIVE.can_be_modified() is True
        assert UserStatus.LOCKED.can_be_modified() is True
        assert UserStatus.PENDING_ACTIVATION.can_be_modified() is True
        assert UserStatus.SUSPENDED.can_be_modified() is True
        assert UserStatus.DELETED.can_be_modified() is False

    def test_display_name(self):
        assert UserStatus.ACTIVE.display_name() == "Aktif"
        assert UserStatus.INACTIVE.display_name() == "Tidak Aktif"
        assert UserStatus.LOCKED.display_name() == "Terkunci"
        assert UserStatus.PENDING_ACTIVATION.display_name() == "Menunggu Aktivasi"
        assert UserStatus.SUSPENDED.display_name() == "Ditangguhkan"
        assert UserStatus.DELETED.display_name() == "Dihapus"

    def test_from_string(self):
        assert UserStatus.from_string("active") == UserStatus.ACTIVE
        assert UserStatus.from_string("ACTIVE") == UserStatus.ACTIVE
        assert UserStatus.from_string("inactive") == UserStatus.INACTIVE
        assert UserStatus.from_string("locked") == UserStatus.LOCKED
        assert UserStatus.from_string("pending") == UserStatus.PENDING_ACTIVATION
        assert UserStatus.from_string("suspended") == UserStatus.SUSPENDED
        assert UserStatus.from_string("deleted") == UserStatus.DELETED
        assert UserStatus.from_string("invalid") is None


# ============================================================================
# Tests for UserProfile
# ============================================================================

class TestUserProfile:
    def test_construction_valid(self, valid_user_profile):
        assert valid_user_profile.full_name == "John Doe"
        assert valid_user_profile.email == "john.doe@example.com"
        assert valid_user_profile.phone == "08123456789"
        assert valid_user_profile.timezone == "Asia/Jakarta"

    def test_validation_full_name_too_short(self):
        with pytest.raises(UserError, match="at least 2 characters"):
            UserProfile(
                full_name="A",
                email="test@example.com",
            )

    def test_validation_invalid_email(self):
        with pytest.raises(UserError, match="Valid email is required"):
            UserProfile(
                full_name="John Doe",
                email="invalid",
            )

    def test_validation_phone_too_short(self):
        with pytest.raises(UserError, match="at least 8 characters"):
            UserProfile(
                full_name="John Doe",
                email="john@example.com",
                phone="123",
            )

    def test_to_dict(self, valid_user_profile):
        d = valid_user_profile.to_dict()
        assert d["full_name"] == "John Doe"
        assert d["email"] == "john.doe@example.com"
        assert d["phone"] == "08123456789"
        assert d["timezone"] == "Asia/Jakarta"
        assert d["metadata"] == {"key": "value"}

    def test_from_dict(self):
        data = {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "08123456788",
            "mobile": "08123456788",
            "department": "HR",
            "position": "Manager",
            "avatar_url": "https://example.com/avatar.jpg",
            "timezone": "Asia/Singapore",
            "language": "en",
            "metadata": {"role": "admin"},
        }
        profile = UserProfile.from_dict(data)
        assert profile.full_name == "Jane Doe"
        assert profile.email == "jane@example.com"
        assert profile.timezone == "Asia/Singapore"
        assert profile.metadata == {"role": "admin"}

    def test_from_dict_defaults(self):
        data = {
            "full_name": "Test User",
            "email": "test@example.com",
        }
        profile = UserProfile.from_dict(data)
        assert profile.timezone == "Asia/Jakarta"
        assert profile.language == "id"
        assert profile.metadata == {}


# ============================================================================
# Tests for UserAudit
# ============================================================================

class TestUserAudit:
    def test_construction(self, valid_user_audit):
        assert valid_user_audit.last_login_at == datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert valid_user_audit.last_login_ip == "192.168.1.1"
        assert valid_user_audit.version == 1

    def test_to_dict(self, valid_user_audit):
        d = valid_user_audit.to_dict()
        assert d["last_login_at"] == "2025-01-01T10:00:00+00:00"
        assert d["last_login_ip"] == "192.168.1.1"
        assert d["version"] == 1
        assert d["deleted_at"] is None
        assert d["deleted_by"] is None


# ============================================================================
# Tests for UserEntity Construction and Validation
# ============================================================================

class TestUserEntityConstruction:
    def test_construction_valid(self, valid_user):
        assert valid_user.username == "johndoe"
        assert valid_user.email == "john.doe@example.com"
        assert valid_user.status == UserStatus.ACTIVE
        assert valid_user.failed_login_attempts == 0
        assert valid_user.audit.version == 1
        # Check that instance was stored
        assert UserEntity._instances[str(valid_user.user_id)] is valid_user
        assert UserEntity._instances[valid_user.username] is valid_user

    def test_validation_username_too_short(self, valid_password_hash, valid_user_profile, valid_user_audit):
        with pytest.raises(UserError, match="at least 3 characters"):
            UserEntity(
                user_id=uuid4(),
                username="ab",
                email="test@example.com",
                password_hash=valid_password_hash,
                status=UserStatus.ACTIVE,
                profile=valid_user_profile,
                legal_entity_id=uuid4(),
                role_ids=[],
                audit=valid_user_audit,
            )

    def test_validation_username_too_long(self, valid_password_hash, valid_user_profile, valid_user_audit):
        with pytest.raises(UserError, match="not exceed 50 characters"):
            UserEntity(
                user_id=uuid4(),
                username="a" * 51,
                email="test@example.com",
                password_hash=valid_password_hash,
                status=UserStatus.ACTIVE,
                profile=valid_user_profile,
                legal_entity_id=uuid4(),
                role_ids=[],
                audit=valid_user_audit,
            )

    def test_validation_invalid_email(self, valid_password_hash, valid_user_profile, valid_user_audit):
        with pytest.raises(UserError, match="Valid email is required"):
            UserEntity(
                user_id=uuid4(),
                username="testuser",
                email="invalid",
                password_hash=valid_password_hash,
                status=UserStatus.ACTIVE,
                profile=valid_user_profile,
                legal_entity_id=uuid4(),
                role_ids=[],
                audit=valid_user_audit,
            )

    def test_validation_failed_attempts_negative(self, valid_password_hash, valid_user_profile, valid_user_audit):
        with pytest.raises(UserError, match="cannot be negative"):
            UserEntity(
                user_id=uuid4(),
                username="testuser",
                email="test@example.com",
                password_hash=valid_password_hash,
                status=UserStatus.ACTIVE,
                profile=valid_user_profile,
                legal_entity_id=uuid4(),
                role_ids=[],
                failed_login_attempts=-1,
                audit=valid_user_audit,
            )

    def test_validation_version(self, valid_password_hash, valid_user_profile):
        audit = UserAudit(version=0)
        with pytest.raises(UserError, match="Version must be >= 1"):
            UserEntity(
                user_id=uuid4(),
                username="testuser",
                email="test@example.com",
                password_hash=valid_password_hash,
                status=UserStatus.ACTIVE,
                profile=valid_user_profile,
                legal_entity_id=uuid4(),
                role_ids=[],
                audit=audit,
            )


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestUserEntityBasicMethods:
    def test_create(self, pending_user):
        user = pending_user.create("admin")
        assert user.status == UserStatus.PENDING_ACTIVATION
        assert user.audit.created_by == "admin"
        assert user.audit.version == 1
        trail = user.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"

    def test_update(self, valid_user):
        updated = valid_user.update(
            updated_by="admin",
            username="newusername",
            email="new@example.com",
        )
        assert updated.username == "newusername"
        assert updated.email == "new@example.com"
        assert updated.audit.version == valid_user.audit.version + 1
        assert updated.audit.updated_by == "admin"
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"] == {"username": "newusername", "email": "new@example.com"}

    def test_update_ignores_protected_fields(self, valid_user):
        updated = valid_user.update(
            updated_by="admin",
            user_id=uuid4(),
            password_hash=PasswordHashedVO("new", "bcrypt"),
            username="newname",
        )
        assert updated.user_id == valid_user.user_id
        assert updated.password_hash == valid_user.password_hash
        assert updated.username == "newname"

    def test_update_deleted_raises(self, deleted_user):
        with pytest.raises(InvalidUserStatusTransitionError, match="Cannot update user in status deleted"):
            deleted_user.update("admin", username="test")

    def test_delete(self, valid_user):
        deleted = valid_user.delete("admin", "Reason")
        assert deleted.status == UserStatus.DELETED
        assert deleted.role_ids == []
        assert deleted.failed_login_attempts == 0
        assert deleted.mfa_enabled is False
        assert deleted.mfa_secret is None
        assert deleted.audit.deleted_at is not None
        assert deleted.audit.deleted_by == "admin"
        assert deleted.audit.version == valid_user.audit.version + 1
        trail = deleted.audit_trail()
        assert trail[0]["action"] == "DELETE"

    def test_delete_already_deleted(self, deleted_user):
        result = deleted_user.delete("admin")
        assert result is deleted_user

    def test_restore(self, deleted_user):
        restored = deleted_user.restore("admin")
        assert restored.status == UserStatus.INACTIVE
        assert restored.role_ids == deleted_user.role_ids
        assert restored.audit.deleted_at is None
        assert restored.audit.deleted_by is None
        assert restored.audit.version == deleted_user.audit.version + 1
        trail = restored.audit_trail()
        assert trail[0]["action"] == "RESTORE"

    def test_restore_non_deleted_raises(self, valid_user):
        with pytest.raises(InvalidUserStatusTransitionError, match="Cannot restore user in status active"):
            valid_user.restore("admin")

    def test_activate(self, pending_user):
        activated = pending_user.activate("admin")
        assert activated.status == UserStatus.ACTIVE
        assert activated.failed_login_attempts == 0
        assert activated.locked_until is None
        assert activated.audit.version == pending_user.audit.version + 1
        trail = activated.audit_trail()
        assert trail[0]["action"] == "ACTIVATE"

    def test_activate_inactive(self, inactive_user):
        activated = inactive_user.activate("admin")
        assert activated.status == UserStatus.ACTIVE

    def test_activate_already_active(self, valid_user):
        result = valid_user.activate("admin")
        assert result is valid_user

    def test_activate_invalid_status(self, locked_user):
        with pytest.raises(InvalidUserStatusTransitionError, match="Cannot activate user in status locked"):
            locked_user.activate("admin")

    def test_deactivate(self, valid_user):
        deactivated = valid_user.deactivate("admin", "Reason")
        assert deactivated.status == UserStatus.INACTIVE
        assert deactivated.audit.version == valid_user.audit.version + 1
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_deactivate_already_inactive(self, inactive_user):
        result = inactive_user.deactivate("admin")
        assert result is inactive_user

    def test_deactivate_invalid_status(self, pending_user):
        with pytest.raises(InvalidUserStatusTransitionError, match="Cannot deactivate user in status pending"):
            pending_user.deactivate("admin")

    def test_lock(self, valid_user):
        locked = valid_user.lock("admin", "Security reason")
        assert locked.status == UserStatus.LOCKED
        assert locked.locked_until is not None
        assert locked.audit.version == valid_user.audit.version + 1
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"

    def test_lock_already_locked(self, locked_user):
        result = locked_user.lock("admin", "Again")
        assert result is locked_user

    def test_unlock(self, locked_user):
        unlocked = locked_user.unlock("admin")
        assert unlocked.status == UserStatus.ACTIVE
        assert unlocked.failed_login_attempts == 0
        assert unlocked.locked_until is None
        assert unlocked.audit.version == locked_user.audit.version + 1
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_unlock_non_locked_raises(self, valid_user):
        with pytest.raises(InvalidUserStatusTransitionError, match="Cannot unlock user in status active"):
            valid_user.unlock("admin")

    def test_validate(self, valid_user):
        result = valid_user.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self, valid_password_hash, valid_user_profile):
        user = UserEntity(
            user_id=uuid4(),
            username="ab",  # too short
            email="invalid",
            password_hash=valid_password_hash,
            status=UserStatus.ACTIVE,
            profile=valid_user_profile,
            legal_entity_id=uuid4(),
            role_ids=[],
            audit=UserAudit(),
        )
        result = user.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_failed_attempts_warning(self, valid_user):
        user = valid_user.record_login_failure()
        user = user.record_login_failure()
        user = user.record_login_failure()
        user = user.record_login_failure()
        result = user.validate()
        assert result["is_valid"] is False
        assert any("failed login attempts" in e for e in result["errors"])

    def test_to_dict(self, valid_user):
        d = valid_user.to_dict()
        assert d["user_id"] == str(valid_user.user_id)
        assert d["username"] == "johndoe"
        assert d["email"] == "john.doe@example.com"
        assert d["status"] == "active"
        assert d["profile"]["full_name"] == "John Doe"
        assert d["legal_entity_id"] == str(valid_user.legal_entity_id)
        assert len(d["role_ids"]) == 2
        assert d["failed_login_attempts"] == 0
        assert d["mfa_enabled"] is False
        assert "audit" in d

    def test_from_dict(self, valid_user):
        data = valid_user.to_dict()
        # Password hash needs to be in a format that from_dict can handle
        data["password_hash"] = "hashed_password"
        restored = UserEntity.from_dict(data)
        assert restored.user_id == valid_user.user_id
        assert restored.username == valid_user.username
        assert restored.email == valid_user.email
        assert restored.status == valid_user.status
        assert restored.profile.full_name == valid_user.profile.full_name
        assert restored.legal_entity_id == valid_user.legal_entity_id

    def test_from_dict_with_missing_fields(self):
        data = {
            "user_id": str(uuid4()),
            "username": "testuser",
            "email": "test@example.com",
            "password_hash": "hashed",
            "status": "active",
            "profile": {
                "full_name": "Test User",
                "email": "test@example.com",
            },
            "legal_entity_id": str(uuid4()),
        }
        restored = UserEntity.from_dict(data)
        assert restored.role_ids == []
        assert restored.failed_login_attempts == 0
        assert restored.mfa_enabled is False

    def test_clone(self, valid_user):
        cloned = valid_user.clone()
        assert cloned.user_id != valid_user.user_id
        assert cloned.username == "johndoe_COPY"
        assert cloned.email == "copy_john.doe@example.com"
        assert cloned.status == UserStatus.PENDING_ACTIVATION
        assert cloned.profile.full_name == "John Doe (COPY)"
        assert cloned.role_ids == []
        assert cloned.audit.version == 1
        trail = cloned.audit_trail()
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, valid_user):
        snap = valid_user.snapshot()
        assert snap["version"] == valid_user.audit.version
        assert snap["user_id"] == str(valid_user.user_id)
        assert snap["username"] == "johndoe"
        assert snap["status"] == "active"

    def test_version(self, valid_user):
        assert valid_user.version() == valid_user.audit.version

    def test_audit_trail(self, valid_user):
        valid_user.create("admin")
        valid_user.update("admin", username="new")
        trail = valid_user.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_user):
        touched = valid_user.touch("toucher")
        assert touched.audit.version == valid_user.audit.version + 1
        assert touched.audit.updated_by == "toucher"
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Business Logic
# ============================================================================

class TestUserEntityBusinessLogic:
    def test_is_active(self, valid_user, inactive_user, locked_user, suspended_user):
        assert valid_user.is_active() is True
        assert inactive_user.is_active() is False
        assert locked_user.is_active() is False
        assert suspended_user.is_active() is False

        # Locked with future lock_until
        locked_with_future = valid_user.lock("admin", "Reason")
        assert locked_with_future.is_active() is False

    def test_is_locked(self, valid_user, locked_user):
        assert valid_user.is_locked() is False
        assert locked_user.is_locked() is True

    def test_is_locked_with_future_lock_until(self, valid_user):
        user = valid_user.record_login_failure(max_attempts=1, lock_duration_minutes=30)
        assert user.is_locked() is True

    def test_can_login(self, valid_user, inactive_user, locked_user, suspended_user):
        assert valid_user.can_login() is True
        assert inactive_user.can_login() is False
        assert locked_user.can_login() is False
        assert suspended_user.can_login() is False

    def test_record_login_success(self, valid_user):
        ip = "192.168.1.100"
        user = valid_user.record_login_success(ip)
        assert user.audit.last_login_ip == ip
        assert user.audit.last_login_at is not None
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        assert user.audit.version == valid_user.audit.version + 1

    def test_record_login_failure_below_threshold(self, valid_user):
        user = valid_user.record_login_failure(max_attempts=5, lock_duration_minutes=30)
        assert user.failed_login_attempts == 1
        assert user.status == UserStatus.ACTIVE
        assert user.locked_until is None

    def test_record_login_failure_reaches_threshold(self, valid_user):
        user = valid_user
        for _ in range(5):
            user = user.record_login_failure(max_attempts=5, lock_duration_minutes=30)
        assert user.failed_login_attempts == 5
        assert user.status == UserStatus.LOCKED
        assert user.locked_until is not None
        # Locked until should be about 30 minutes in future
        assert user.locked_until > datetime.now(UTC) + timedelta(minutes=29)

    def test_change_password(self, valid_user):
        new_hash = PasswordHashedVO("new_hashed", "bcrypt")
        user = valid_user.change_password(new_hash, "admin")
        assert user.password_hash == new_hash
        assert user.failed_login_attempts == 0
        assert user.locked_until is None
        assert user.audit.last_password_change_at is not None
        assert user.audit.last_password_change_by == "admin"
        assert user.audit.version == valid_user.audit.version + 1

    def test_update_profile(self, valid_user):
        user = valid_user.update_profile(
            full_name="Jane Doe",
            email="jane@example.com",
            updated_by="admin",
            phone="08123456788",
            department="HR",
            position="Manager",
        )
        assert user.profile.full_name == "Jane Doe"
        assert user.profile.email == "jane@example.com"
        assert user.profile.phone == "08123456788"
        assert user.profile.department == "HR"
        assert user.profile.position == "Manager"
        assert user.audit.version == valid_user.audit.version + 1

    def test_suspend(self, valid_user):
        suspended = valid_user.suspend("admin", "Suspension reason")
        assert suspended.status == UserStatus.SUSPENDED
        assert suspended.audit.version == valid_user.audit.version + 1
        trail = suspended.audit_trail()
        assert trail[0]["action"] == "SUSPEND"  # Actually it's SUSPEND

    def test_suspend_already_suspended(self, suspended_user):
        result = suspended_user.suspend("admin", "Again")
        assert result is suspended_user

    def test_enable_mfa(self, valid_user):
        secret = "MFA_SECRET_123"
        user = valid_user.enable_mfa(secret, "admin")
        assert user.mfa_enabled is True
        assert user.mfa_secret == secret
        assert user.audit.version == valid_user.audit.version + 1

    def test_disable_mfa(self, valid_user):
        # First enable
        enabled = valid_user.enable_mfa("secret", "admin")
        # Then disable
        disabled = enabled.disable_mfa("admin")
        assert disabled.mfa_enabled is False
        assert disabled.mfa_secret is None
        assert disabled.audit.version == enabled.audit.version + 1


# ============================================================================
# Tests for Class Methods
# ============================================================================

class TestUserEntityClassMethods:
    def test_register(self, valid_password_hash):
        legal_entity_id = uuid4()
        user = UserEntity.register(
            username="newuser",
            email="new@example.com",
            password_hash=valid_password_hash,
            legal_entity_id=legal_entity_id,
            full_name="New User",
            created_by="system",
        )
        assert user.user_id is not None
        assert user.username == "newuser"
        assert user.email == "new@example.com"
        assert user.status == UserStatus.PENDING_ACTIVATION
        assert user.profile.full_name == "New User"
        assert user.legal_entity_id == legal_entity_id
        assert user.audit.created_by == "system"

    def test_get_instance_by_id(self, valid_user):
        retrieved = UserEntity.get_instance(str(valid_user.user_id))
        assert retrieved == valid_user

    def test_get_instance_by_username(self, valid_user):
        retrieved = UserEntity.get_instance(valid_user.username)
        assert retrieved == valid_user

    def test_get_instance_not_found(self):
        assert UserEntity.get_instance("nonexistent") is None


# ============================================================================
# Tests for UserRepository
# ============================================================================

class TestUserRepository:
    async def test_save_and_get_by_id(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        retrieved = await UserRepository.get_by_id(valid_user.user_id, legal_id)
        assert retrieved == valid_user

    async def test_get_by_id_wrong_legal_entity(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        retrieved = await UserRepository.get_by_id(valid_user.user_id, uuid4())
        assert retrieved is None

    async def test_get_by_username(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        retrieved = await UserRepository.get_by_username(valid_user.username, legal_id)
        assert retrieved == valid_user

    async def test_get_by_email(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        retrieved = await UserRepository.get_by_email(valid_user.email, legal_id)
        assert retrieved == valid_user

    async def test_list_by_legal_entity(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        # Add another user
        user2 = UserEntity.register(
            username="user2",
            email="user2@example.com",
            password_hash=valid_user.password_hash,
            legal_entity_id=legal_id,
            full_name="User Two",
        )
        await UserRepository.save(user2, legal_id)
        users = await UserRepository.list_by_legal_entity(legal_id, limit=1, offset=1)
        assert len(users) == 1
        assert users[0].user_id == user2.user_id

    async def test_list_by_status(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        inactive = valid_user.deactivate("admin")
        await UserRepository.save(inactive, legal_id)
        active_users = await UserRepository.list_by_status(legal_id, UserStatus.ACTIVE)
        assert len(active_users) == 1
        assert active_users[0].user_id == valid_user.user_id
        inactive_users = await UserRepository.list_by_status(legal_id, UserStatus.INACTIVE)
        assert len(inactive_users) == 1
        assert inactive_users[0].user_id == inactive.user_id

    async def test_get_all(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        all_users = await UserRepository.get_all(legal_id)
        assert len(all_users) == 1

    async def test_update(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        updated = valid_user.update("admin", username="newname")
        await UserRepository.update(updated, legal_id)
        retrieved = await UserRepository.get_by_id(valid_user.user_id, legal_id)
        assert retrieved.username == "newname"

    async def test_delete(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        await UserRepository.delete(valid_user.user_id, legal_id)
        retrieved = await UserRepository.get_by_id(valid_user.user_id, legal_id)
        assert retrieved is None
        # Check by-username and by-email indexes were cleaned
        assert valid_user.username not in UserRepository._storage_by_username
        assert valid_user.email not in UserRepository._storage_by_email

    async def test_exists(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        assert await UserRepository.exists(valid_user.user_id, legal_id) is True
        assert await UserRepository.exists(uuid4(), legal_id) is False

    async def test_count(self, valid_user):
        legal_id = valid_user.legal_entity_id
        assert await UserRepository.count(legal_id) == 0
        await UserRepository.save(valid_user, legal_id)
        assert await UserRepository.count(legal_id) == 1

    async def test_list(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        user2 = UserEntity.register(
            username="user2",
            email="user2@example.com",
            password_hash=valid_user.password_hash,
            legal_entity_id=legal_id,
            full_name="User Two",
        )
        await UserRepository.save(user2, legal_id)
        users = await UserRepository.list(legal_id, limit=1, offset=1)
        assert len(users) == 1
        assert users[0].user_id == user2.user_id

    async def test_clear(self, valid_user):
        legal_id = valid_user.legal_entity_id
        await UserRepository.save(valid_user, legal_id)
        await UserRepository.clear(legal_id)
        all_users = await UserRepository.get_all(legal_id)
        assert len(all_users) == 0

    async def test_save_mismatched_legal_entity(self, valid_user):
        wrong_legal_id = uuid4()
        with pytest.raises(UserError, match="User legal entity mismatch"):
            await UserRepository.save(valid_user, wrong_legal_id)