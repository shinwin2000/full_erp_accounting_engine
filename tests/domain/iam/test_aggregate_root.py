# test_aggregate_root.py
# Comprehensive tests for aggregate_root.py (IAM aggregate)

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.iam.aggregate_root import (
    IAM,
    AuthenticationError,
    DuplicateEmailError,
    DuplicateRoleNameError,
    DuplicateUsernameError,
    IAMError,
    IAMRepository,
    IAMStatus,
    InsufficientPermissionsError,
    RoleNotFoundError,
    UserNotFoundError,
)
from domain.iam.domain_events import (
    LoginFailureEvent,
    LoginSuccessEvent,
    RoleAssignedEvent,
    RoleCreatedEvent,
    RoleRevokedEvent,
    SessionCreatedEvent,
    SessionTerminatedEvent,
    UserActivatedEvent,
    UserCreatedEvent,
    UserDeactivatedEvent,
)
from domain.iam.password_hashed_vo import PasswordHashedVO
from domain.iam.role_entity import RoleEntity, RoleStatus
from domain.iam.session_entity import SessionEntity, SessionStatus
from domain.iam.user_entity import UserEntity, UserProfile, UserStatus

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_storage():
    """Reset class variables before each test."""
    IAM._events = []
    IAM._audit_trail = []
    IAM._snapshots = []
    IAMRepository._storage = {}
    yield
    IAM._events = []
    IAM._audit_trail = []
    IAM._snapshots = []
    IAMRepository._storage = {}


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def iam(legal_entity_id):
    """Create a new IAM aggregate with default roles."""
    return IAM(
        iam_id=uuid4(),
        legal_entity_id=legal_entity_id,
        status=IAMStatus.ACTIVE,
        created_by="system",
    )


@pytest.fixture
def valid_password_hash():
    """Create a valid password hash."""
    return PasswordHashedVO("hashed_password", "bcrypt")


@pytest.fixture
def user_profile():
    """Create a valid user profile."""
    return UserProfile(
        full_name="John Doe",
        email="john.doe@example.com",
        phone="08123456789",
        mobile="08123456789",
        department="IT",
        position="Software Engineer",
        timezone="Asia/Jakarta",
        language="id",
    )


@pytest.fixture
def user_entity(valid_password_hash, user_profile, legal_entity_id):
    """Create a user entity."""
    return UserEntity(
        user_id=uuid4(),
        username="johndoe",
        email="john.doe@example.com",
        password_hash=valid_password_hash,
        status=UserStatus.PENDING_ACTIVATION,
        profile=user_profile,
        legal_entity_id=legal_entity_id,
        role_ids=[],
        failed_login_attempts=0,
        locked_until=None,
        mfa_enabled=False,
        mfa_secret=None,
        audit=MagicMock(),
    )


@pytest.fixture
def active_user(iam, user_entity):
    """Create and activate a user in the IAM aggregate."""
    iam = iam.add_user(user_entity, "system")
    iam = iam.activate_user(user_entity.user_id, "system")
    return iam, user_entity


@pytest.fixture
def role_entity():
    """Create a custom role entity."""
    return RoleEntity(
        role_id=uuid4(),
        role_name="finance",
        description="Finance role",
        permissions={"journal:read", "journal:write"},
        status=RoleStatus.ACTIVE,
        parent_role_id=None,
        is_default=False,
        is_system=False,
        created_by="system",
    )


@pytest.fixture
def iam_with_role(iam, role_entity):
    """IAM with a custom role added."""
    return iam.add_role(role_entity, "system")


@pytest.fixture
def session_entity(active_user):
    """Create a session entity."""
    _iam, user = active_user
    return SessionEntity(
        session_id=uuid4(),
        user_id=user.user_id,
        username=user.username,
        token="test_token",
        refresh_token="test_refresh_token",
        status=SessionStatus.ACTIVE,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        refresh_expires_at=datetime.now(UTC) + timedelta(days=7),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        created_by="system",
    )


# ============================================================================
# Tests for IAMStatus Enum
# ============================================================================

class TestIAMStatus:
    def test_members(self):
        assert IAMStatus.ACTIVE.value == "active"
        assert IAMStatus.LOCKDOWN.value == "lockdown"
        assert IAMStatus.MAINTENANCE.value == "maintenance"

    def test_display_name(self):
        assert IAMStatus.ACTIVE.display_name() == "Aktif"
        assert IAMStatus.LOCKDOWN.display_name() == "Terkunci"
        assert IAMStatus.MAINTENANCE.display_name() == "Pemeliharaan"


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_iam_error_is_value_error():
    assert issubclass(IAMError, ValueError)


def test_user_not_found_error_is_iam_error():
    assert issubclass(UserNotFoundError, IAMError)


def test_role_not_found_error_is_iam_error():
    assert issubclass(RoleNotFoundError, IAMError)


def test_duplicate_username_error_is_iam_error():
    assert issubclass(DuplicateUsernameError, IAMError)


def test_duplicate_email_error_is_iam_error():
    assert issubclass(DuplicateEmailError, IAMError)


def test_duplicate_role_name_error_is_iam_error():
    assert issubclass(DuplicateRoleNameError, IAMError)


def test_insufficient_permissions_error_is_iam_error():
    assert issubclass(InsufficientPermissionsError, IAMError)


def test_authentication_error_is_iam_error():
    assert issubclass(AuthenticationError, IAMError)


# ============================================================================
# Tests for IAM Construction and Default Roles
# ============================================================================

class TestIAMConstruction:
    def test_initial_creation(self, legal_entity_id):
        iam = IAM(
            iam_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_by="system",
        )
        assert iam.status == IAMStatus.ACTIVE
        assert len(iam.roles) == 5  # Default roles: super_admin, admin, user, auditor, approver
        assert len(iam.users) == 0
        assert len(iam.sessions) == 0
        assert len(iam.permissions) == 0
        assert iam.version == 1
        # Check snapshot was taken
        assert len(IAM._snapshots) == 1

    def test_default_roles_exist(self, iam):
        role_names = [r.role_name for r in iam.roles.values()]
        assert "super_admin" in role_names
        assert "admin" in role_names
        assert "user" in role_names
        assert "auditor" in role_names
        assert "approver" in role_names

        # Check super_admin has wildcard permission
        super_admin = iam.get_role_by_name("super_admin")
        assert super_admin is not None
        assert "*:*" in super_admin.permissions

        # Check user is default
        user_role = iam.get_role_by_name("user")
        assert user_role.is_default is True


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestIAMEntityBasicMethods:
    def test_create(self, iam):
        result = iam.create("admin")
        assert result is iam
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"
        assert trail[0]["details"]["legal_entity_id"] == str(iam.legal_entity_id)

    def test_update(self, iam):
        updated = iam.update("admin", status="lockdown")
        assert updated.status == IAMStatus.LOCKDOWN
        assert updated.version == iam.version + 1
        assert updated.updated_at > iam.updated_at
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"] == {"status": "lockdown"}

    def test_update_ignores_protected_fields(self, iam):
        updated = iam.update("admin", iam_id=uuid4(), created_at=datetime.now(UTC), version=999)
        assert updated.iam_id == iam.iam_id
        assert updated.created_at == iam.created_at
        assert updated.version == iam.version + 1  # not 999

    def test_delete_with_users_raises(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        with pytest.raises(IAMError, match="Cannot delete IAM aggregate with existing users"):
            iam.delete("admin")

    def test_delete_without_users(self, iam):
        deleted = iam.delete("admin", "Reason")
        assert deleted.status == IAMStatus.LOCKDOWN
        assert deleted.version == iam.version + 1
        trail = deleted.audit_trail()
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_restore(self, iam):
        deleted = iam.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.status == IAMStatus.ACTIVE
        assert restored.version == deleted.version + 1
        trail = restored.audit_trail()
        assert trail[0]["action"] == "RESTORE"

    def test_activate_already_active(self, iam):
        result = iam.activate("admin")
        assert result is iam

    def test_activate(self, iam):
        deactivated = iam.deactivate("admin")
        activated = deactivated.activate("admin2")
        assert activated.status == IAMStatus.ACTIVE
        assert activated.version == deactivated.version + 1
        trail = activated.audit_trail()
        assert trail[0]["action"] == "ACTIVATE"

    def test_deactivate(self, iam):
        deactivated = iam.deactivate("admin", "Reason")
        assert deactivated.status == IAMStatus.MAINTENANCE
        assert deactivated.version == iam.version + 1
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Reason"

    def test_lock(self, iam):
        locked = iam.lock("admin", "Security")
        assert locked.status == IAMStatus.LOCKDOWN
        assert locked.version == iam.version + 1
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Security"

    def test_unlock(self, iam):
        locked = iam.lock("admin", "Security")
        unlocked = locked.unlock("admin")
        assert unlocked.status == IAMStatus.ACTIVE
        assert unlocked.version == locked.version + 1
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_unlock_not_locked_raises(self, iam):
        with pytest.raises(IAMError, match="Cannot unlock IAM in status active"):
            iam.unlock("admin")

    def test_validate(self, iam):
        result = iam.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_duplicate_username(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        # Add another user with same username (should be blocked by add_user)
        # We'll manually add duplicate to test validation
        user2 = UserEntity(
            user_id=uuid4(),
            username=user_entity.username,  # duplicate
            email="other@example.com",
            password_hash=user_entity.password_hash,
            status=UserStatus.ACTIVE,
            profile=user_entity.profile,
            legal_entity_id=user_entity.legal_entity_id,
            role_ids=[],
        )
        # Directly set users dict to bypass add_user validation
        iam.users[user2.user_id] = user2
        result = iam.validate()
        assert result["is_valid"] is False
        assert any("Duplicate username" in e for e in result["errors"])

    def test_validate_duplicate_role_name(self, iam, role_entity):
        iam = iam.add_role(role_entity, "system")
        # Add another role with same name
        role2 = RoleEntity(
            role_id=uuid4(),
            role_name=role_entity.role_name,  # duplicate
            description="Duplicate",
            permissions=set(),
            status=RoleStatus.ACTIVE,
        )
        iam.roles[role2.role_id] = role2
        result = iam.validate()
        assert result["is_valid"] is False
        assert any("Duplicate role name" in e for e in result["errors"])

    def test_to_dict(self, iam):
        d = iam.to_dict()
        assert d["iam_id"] == str(iam.iam_id)
        assert d["legal_entity_id"] == str(iam.legal_entity_id)
        assert d["status"] == "active"
        assert d["user_count"] == 0
        assert d["role_count"] == 5
        assert d["version"] == 1

    def test_from_dict(self, iam):
        data = iam.to_dict()
        restored = IAM.from_dict(data)
        assert restored.iam_id == iam.iam_id
        assert restored.legal_entity_id == iam.legal_entity_id
        assert restored.status == iam.status
        assert restored.version == iam.version
        # from_dict doesn't restore users/roles, so they are empty

    def test_clone(self, iam, user_entity, role_entity):
        iam = iam.add_user(user_entity, "system")
        iam = iam.add_role(role_entity, "system")
        cloned = iam.clone()
        assert cloned.iam_id != iam.iam_id
        assert cloned.legal_entity_id == iam.legal_entity_id
        assert cloned.status == IAMStatus.ACTIVE
        assert cloned.version == 1
        # Roles and users are cloned
        assert len(cloned.roles) == len(iam.roles)
        assert len(cloned.users) == len(iam.users)
        # Check role names
        cloned_role = cloned.get_role_by_name(role_entity.role_name)
        assert cloned_role is not None
        assert cloned_role.role_id != role_entity.role_id
        # Check user
        cloned_user = cloned.get_user_by_username(user_entity.username)
        assert cloned_user is not None
        assert cloned_user.user_id != user_entity.user_id
        trail = cloned.audit_trail()
        assert trail[0]["action"] == "CLONE"

    def test_snapshot(self, iam):
        snap = iam.snapshot()
        assert snap["version"] == 1
        assert snap["iam_id"] == str(iam.iam_id)
        assert snap["status"] == "active"
        assert snap["user_count"] == 0

    def test_get_version(self, iam):
        assert iam.get_version() == 1

    def test_audit_trail(self, iam):
        iam.create("admin")
        iam.update("admin", status="lockdown")
        trail = iam.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, iam):
        touched = iam.touch("toucher")
        assert touched.version == iam.version + 1
        assert touched.updated_at > iam.updated_at
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Aggregate Root Methods
# ============================================================================

class TestIAMAggregateRootMethods:
    def test_add_child_user(self, iam, user_entity):
        result = iam.add_child(user_entity, "system")
        assert isinstance(result, IAM)
        assert user_entity.user_id in result.users

    def test_add_child_role(self, iam, role_entity):
        result = iam.add_child(role_entity, "system")
        assert isinstance(result, IAM)
        assert role_entity.role_id in result.roles

    def test_add_child_session(self, iam, session_entity, active_user):
        iam, _user = active_user
        result = iam.add_child(session_entity, "system")
        assert isinstance(result, IAM)
        assert session_entity.session_id in result.sessions

    def test_add_child_unknown(self, iam):
        with pytest.raises(IAMError, match="Unknown entity type"):
            iam.add_child("string", "system")

    def test_remove_child_user(self, active_user, iam):
        iam, user = active_user
        # Remove user
        result = iam.remove_child(user.user_id, "user", "admin")
        assert isinstance(result, IAM)
        assert user.user_id not in result.users

    def test_remove_child_role(self, iam_with_role, role_entity):
        result = iam_with_role.remove_child(role_entity.role_id, "role", "admin")
        assert isinstance(result, IAM)
        assert role_entity.role_id not in result.roles

    def test_remove_child_session(self, iam, session_entity, active_user):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        result = iam.remove_child(session_entity.session_id, "session", "admin")
        assert isinstance(result, IAM)
        # Session should be revoked (not removed)
        revoked = result.sessions[session_entity.session_id]
        assert revoked.status == SessionStatus.REVOKED

    def test_remove_child_unknown(self, iam):
        with pytest.raises(IAMError, match="Unknown entity type"):
            iam.remove_child(uuid4(), "unknown", "admin")

    def test_can_post(self, active_user, iam):
        iam, user = active_user
        # user doesn't have any permissions yet
        assert iam.can_post(user.user_id, "journal:create") is False
        # Assign a role with permission
        role = iam.get_role_by_name("user")  # user role has journal:create
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.can_post(user.user_id, "journal:create") is True

    def test_post(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        result = iam.post(user.user_id, "journal:create", "system")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "POST"

    def test_post_insufficient_permission(self, active_user, iam):
        iam, user = active_user
        with pytest.raises(InsufficientPermissionsError, match="lacks permission"):
            iam.post(user.user_id, "journal:create", "system")

    def test_can_approve(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("approver")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.can_approve(user.user_id, "journal") is True
        assert iam.can_approve(user.user_id, "invoice") is True
        assert iam.can_approve(user.user_id, "payment") is True

    def test_approve(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("approver")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        result = iam.approve(user.user_id, "journal", "system")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "APPROVE"

    def test_approve_insufficient(self, active_user, iam):
        iam, user = active_user
        with pytest.raises(InsufficientPermissionsError, match="cannot approve"):
            iam.approve(user.user_id, "journal", "system")

    def test_can_reject(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("approver")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.can_reject(user.user_id, "journal") is True

    def test_reject(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("approver")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        result = iam.reject(user.user_id, "journal", "system", "Reason")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "REJECT"

    def test_can_cancel(self, active_user, iam):
        iam, user = active_user
        # user role has journal:read but not journal:delete
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.can_cancel(user.user_id, "journal") is False
        # admin role has user:*
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_cancel(user.user_id, "user") is True

    def test_cancel(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        result = iam.cancel(user.user_id, "user", "system", "Reason")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "CANCEL"

    def test_can_reverse(self, active_user, iam):
        iam, user = active_user
        # Admin has reverse permission via user:*
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_reverse(user.user_id, "user") is True

    def test_reverse(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        result = iam.reverse(user.user_id, "user", "system", "Reason")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "REVERSE"

    def test_can_close(self, active_user, iam):
        iam, user = active_user
        # Admin has close permission via user:*
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_close(user.user_id, "user") is True

    def test_close(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        result = iam.close(user.user_id, "user", "system", "Reason")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "CLOSE"

    def test_can_reopen(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_reopen(user.user_id, "user") is True

    def test_reopen(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        result = iam.reopen(user.user_id, "user", "system", "Reason")
        assert result is iam
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "REOPEN"

    def test_can_archive(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_archive(user.user_id) is True

    def test_archive(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        result = iam.archive(user.user_id, "system", "Archiving")
        # archive calls delete_user, which deactivates the user
        assert result.users[user.user_id].status == UserStatus.INACTIVE
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "DELETE"

    def test_can_unarchive(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        assert iam.can_unarchive(user.user_id) is True

    def test_unarchive(self, active_user, iam):
        iam, user = active_user
        admin_role = iam.get_role_by_name("admin")
        iam = iam.assign_role_to_user(user.user_id, admin_role.role_id, "system")
        # Deactivate first (archive)
        iam = iam.delete_user(user.user_id, "system")
        # Then unarchive
        result = iam.unarchive(user.user_id, "system")
        assert result.users[user.user_id].status == UserStatus.ACTIVE
        trail = iam.audit_trail()
        assert trail[-1]["action"] == "ACTIVATE"

    def test_unarchive_user_not_found(self, iam):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.unarchive(uuid4(), "system")


# ============================================================================
# Tests for User Management
# ============================================================================

class TestIAMUserManagement:
    def test_add_user(self, iam, user_entity):
        new_iam = iam.add_user(user_entity, "system")
        assert user_entity.user_id in new_iam.users
        assert new_iam.version == iam.version + 1
        # Check event
        events = new_iam.get_events()
        assert any(isinstance(e, UserCreatedEvent) for e in events)

    def test_add_user_duplicate_id(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        with pytest.raises(IAMError, match="already exists"):
            iam.add_user(user_entity, "system")

    def test_add_user_duplicate_username(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        user2 = UserEntity(
            user_id=uuid4(),
            username=user_entity.username,
            email="other@example.com",
            password_hash=user_entity.password_hash,
            status=UserStatus.ACTIVE,
            profile=user_entity.profile,
            legal_entity_id=user_entity.legal_entity_id,
            role_ids=[],
        )
        with pytest.raises(DuplicateUsernameError, match="already exists"):
            iam.add_user(user2, "system")

    def test_add_user_duplicate_email(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        user2 = UserEntity(
            user_id=uuid4(),
            username="otheruser",
            email=user_entity.email,
            password_hash=user_entity.password_hash,
            status=UserStatus.ACTIVE,
            profile=user_entity.profile,
            legal_entity_id=user_entity.legal_entity_id,
            role_ids=[],
        )
        with pytest.raises(DuplicateEmailError, match="already exists"):
            iam.add_user(user2, "system")

    def test_update_user(self, active_user, iam):
        iam, user = active_user
        updated_user = user.update("admin", email="new@example.com")
        new_iam = iam.update_user(updated_user, "admin")
        assert new_iam.users[user.user_id].email == "new@example.com"
        assert new_iam.version == iam.version + 1

    def test_update_user_not_found(self, iam, user_entity):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.update_user(user_entity, "admin")

    def test_update_user_duplicate_email(self, active_user, iam, user_entity):
        iam, user = active_user
        # Add another user
        user2 = UserEntity(
            user_id=uuid4(),
            username="user2",
            email="user2@example.com",
            password_hash=user.password_hash,
            status=UserStatus.ACTIVE,
            profile=user.profile,
            legal_entity_id=user.legal_entity_id,
            role_ids=[],
        )
        iam = iam.add_user(user2, "system")
        # Try to update user with user2's email
        updated_user = user.update("admin", email="user2@example.com")
        with pytest.raises(DuplicateEmailError, match="already used"):
            iam.update_user(updated_user, "admin")

    def test_delete_user(self, active_user, iam):
        iam, user = active_user
        new_iam = iam.delete_user(user.user_id, "admin")
        assert new_iam.users[user.user_id].status == UserStatus.INACTIVE
        assert new_iam.version == iam.version + 1

    def test_delete_user_not_found(self, iam):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.delete_user(uuid4(), "admin")

    def test_activate_user(self, active_user, iam):
        iam, user = active_user
        # Already active, but we can deactivate first
        iam = iam.deactivate_user(user.user_id, "admin")
        new_iam = iam.activate_user(user.user_id, "admin")
        assert new_iam.users[user.user_id].status == UserStatus.ACTIVE
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, UserActivatedEvent) for e in events)

    def test_activate_user_not_found(self, iam):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.activate_user(uuid4(), "admin")

    def test_deactivate_user(self, active_user, iam):
        iam, user = active_user
        new_iam = iam.deactivate_user(user.user_id, "admin")
        assert new_iam.users[user.user_id].status == UserStatus.INACTIVE
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, UserDeactivatedEvent) for e in events)

    def test_deactivate_user_not_found(self, iam):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.deactivate_user(uuid4(), "admin")

    def test_unlock_user(self, active_user, iam):
        iam, user = active_user
        # Lock the user
        locked_user = user.lock("admin", "Reason")
        iam = iam.update_user(locked_user, "admin")
        new_iam = iam.unlock_user(user.user_id, "admin")
        assert new_iam.users[user.user_id].status == UserStatus.ACTIVE
        assert new_iam.users[user.user_id].locked_until is None

    def test_unlock_user_not_found(self, iam):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.unlock_user(uuid4(), "admin")

    def test_change_user_password(self, active_user, iam):
        iam, user = active_user
        new_hash = PasswordHashedVO("new_hashed", "bcrypt")
        new_iam = iam.change_user_password(user.user_id, new_hash, "admin")
        assert new_iam.users[user.user_id].password_hash == new_hash
        assert new_iam.version == iam.version + 1

    def test_change_user_password_not_found(self, iam):
        new_hash = PasswordHashedVO("new", "bcrypt")
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.change_user_password(uuid4(), new_hash, "admin")


# ============================================================================
# Tests for Role Management
# ============================================================================

class TestIAMRoleManagement:
    def test_add_role(self, iam, role_entity):
        new_iam = iam.add_role(role_entity, "system")
        assert role_entity.role_id in new_iam.roles
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, RoleCreatedEvent) for e in events)

    def test_add_role_duplicate_id(self, iam, role_entity):
        iam = iam.add_role(role_entity, "system")
        with pytest.raises(IAMError, match="already exists"):
            iam.add_role(role_entity, "system")

    def test_add_role_duplicate_name(self, iam, role_entity):
        iam = iam.add_role(role_entity, "system")
        role2 = RoleEntity(
            role_id=uuid4(),
            role_name=role_entity.role_name,
            description="Duplicate",
            permissions=set(),
            status=RoleStatus.ACTIVE,
        )
        with pytest.raises(DuplicateRoleNameError, match="already exists"):
            iam.add_role(role2, "system")

    def test_update_role(self, iam_with_role, role_entity):
        iam = iam_with_role
        updated_role = role_entity.update("admin", description="Updated description")
        new_iam = iam.update_role(updated_role, "admin")
        assert new_iam.roles[role_entity.role_id].description == "Updated description"
        assert new_iam.version == iam.version + 1

    def test_update_role_not_found(self, iam, role_entity):
        with pytest.raises(RoleNotFoundError, match="not found"):
            iam.update_role(role_entity, "admin")

    def test_update_system_role_name_raises(self, iam):
        admin_role = iam.get_role_by_name("admin")
        updated = admin_role.update("admin", role_name="newadmin")
        with pytest.raises(IAMError, match="Cannot rename system role"):
            iam.update_role(updated, "admin")

    def test_delete_role(self, iam_with_role, role_entity):
        iam = iam_with_role
        new_iam = iam.delete_role(role_entity.role_id, "admin")
        assert role_entity.role_id not in new_iam.roles
        assert new_iam.version == iam.version + 1

    def test_delete_role_not_found(self, iam):
        with pytest.raises(RoleNotFoundError, match="not found"):
            iam.delete_role(uuid4(), "admin")

    def test_delete_system_role_raises(self, iam):
        admin_role = iam.get_role_by_name("admin")
        with pytest.raises(IAMError, match="Cannot delete system role"):
            iam.delete_role(admin_role.role_id, "admin")

    def test_delete_role_assigned_to_user(self, active_user, iam, role_entity):
        iam, user = active_user
        iam = iam.add_role(role_entity, "system")
        iam = iam.assign_role_to_user(user.user_id, role_entity.role_id, "system")
        with pytest.raises(IAMError, match="assigned to user"):
            iam.delete_role(role_entity.role_id, "admin")

    def test_assign_role_to_user(self, active_user, iam, role_entity):
        iam, user = active_user
        iam = iam.add_role(role_entity, "system")
        new_iam = iam.assign_role_to_user(user.user_id, role_entity.role_id, "admin")
        assert role_entity.role_id in new_iam.users[user.user_id].role_ids
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, RoleAssignedEvent) for e in events)

    def test_assign_role_to_user_already_assigned(self, active_user, iam, role_entity):
        iam, user = active_user
        iam = iam.add_role(role_entity, "system")
        iam = iam.assign_role_to_user(user.user_id, role_entity.role_id, "admin")
        result = iam.assign_role_to_user(user.user_id, role_entity.role_id, "admin")
        # Should return self (no change)
        assert result is iam

    def test_assign_role_to_user_not_found(self, iam, role_entity):
        iam = iam.add_role(role_entity, "system")
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.assign_role_to_user(uuid4(), role_entity.role_id, "admin")

    def test_assign_role_to_role_not_found(self, active_user, iam):
        iam, user = active_user
        with pytest.raises(RoleNotFoundError, match="not found"):
            iam.assign_role_to_user(user.user_id, uuid4(), "admin")

    def test_remove_role_from_user(self, active_user, iam, role_entity):
        iam, user = active_user
        iam = iam.add_role(role_entity, "system")
        iam = iam.assign_role_to_user(user.user_id, role_entity.role_id, "admin")
        new_iam = iam.remove_role_from_user(user.user_id, role_entity.role_id, "admin")
        assert role_entity.role_id not in new_iam.users[user.user_id].role_ids
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, RoleRevokedEvent) for e in events)

    def test_remove_role_from_user_not_assigned(self, active_user, iam, role_entity):
        iam, user = active_user
        iam = iam.add_role(role_entity, "system")
        result = iam.remove_role_from_user(user.user_id, role_entity.role_id, "admin")
        assert result is iam  # no change

    def test_remove_role_from_user_last_role(self, active_user, iam, role_entity):
        iam, user = active_user
        # User only has one role? Actually active_user has no roles. We need to assign a role first.
        # We'll assign a role, then try to remove it when it's the only one.
        iam = iam.add_role(role_entity, "system")
        iam = iam.assign_role_to_user(user.user_id, role_entity.role_id, "admin")
        # Now user has one role
        with pytest.raises(IAMError, match="Cannot remove last role"):
            iam.remove_role_from_user(user.user_id, role_entity.role_id, "admin")


# ============================================================================
# Tests for Session Management
# ============================================================================

class TestIAMSessionManagement:
    def test_add_session(self, active_user, session_entity, iam):
        iam, _user = active_user
        new_iam = iam.add_session(session_entity, "system")
        assert session_entity.session_id in new_iam.sessions
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, SessionCreatedEvent) for e in events)

    def test_add_session_duplicate(self, active_user, session_entity, iam):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        with pytest.raises(IAMError, match="already exists"):
            iam.add_session(session_entity, "system")

    def test_add_session_user_not_found(self, iam, session_entity):
        with pytest.raises(UserNotFoundError, match="not found"):
            iam.add_session(session_entity, "system")

    def test_add_session_inactive_user(self, iam, user_entity, session_entity):
        iam = iam.add_user(user_entity, "system")
        # User is pending activation, not active
        with pytest.raises(IAMError, match="inactive user"):
            iam.add_session(session_entity, "system")

    def test_revoke_session(self, active_user, session_entity, iam):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        new_iam = iam.revoke_session(session_entity.session_id, "admin")
        assert new_iam.sessions[session_entity.session_id].status == SessionStatus.REVOKED
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, SessionTerminatedEvent) for e in events)

    def test_revoke_session_not_found(self, iam):
        result = iam.revoke_session(uuid4(), "admin")
        assert result is iam  # no change

    def test_revoke_all_user_sessions(self, active_user, session_entity, iam):
        iam, user = active_user
        iam = iam.add_session(session_entity, "system")
        # Add another session for same user
        session2 = SessionEntity(
            session_id=uuid4(),
            user_id=user.user_id,
            username=user.username,
            token="token2",
            refresh_token="refresh2",
            status=SessionStatus.ACTIVE,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            refresh_expires_at=datetime.now(UTC) + timedelta(days=7),
            ip_address="192.168.1.2",
            user_agent="Mozilla/5.0",
            created_by="system",
        )
        iam = iam.add_session(session2, "system")
        new_iam = iam.revoke_all_user_sessions(user.user_id, "admin")
        assert new_iam.sessions[session_entity.session_id].status == SessionStatus.REVOKED
        assert new_iam.sessions[session2.session_id].status == SessionStatus.REVOKED
        assert new_iam.version == iam.version + 1

    def test_refresh_session(self, active_user, session_entity, iam):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        # Set refresh_expires_at to future
        # Already set in fixture
        new_iam = iam.refresh_session(session_entity.session_id, "system")
        assert new_iam.sessions[session_entity.session_id].status == SessionStatus.ACTIVE
        # Version increments
        assert new_iam.version == iam.version + 1

    def test_refresh_session_not_found(self, iam):
        with pytest.raises(IAMError, match="not found"):
            iam.refresh_session(uuid4(), "system")

    def test_refresh_session_expired(self, active_user, session_entity, iam):
        iam, _user = active_user
        # Set refresh token expired
        expired_session = SessionEntity(
            session_id=session_entity.session_id,
            user_id=session_entity.user_id,
            username=session_entity.username,
            token=session_entity.token,
            refresh_token=session_entity.refresh_token,
            status=session_entity.status,
            expires_at=session_entity.expires_at,
            refresh_expires_at=datetime.now(UTC) - timedelta(days=1),
            ip_address=session_entity.ip_address,
            user_agent=session_entity.user_agent,
            created_by=session_entity.created_by,
        )
        iam = iam.add_session(expired_session, "system")
        with pytest.raises(IAMError, match="Refresh token expired"):
            iam.refresh_session(expired_session.session_id, "system")


# ============================================================================
# Tests for Authentication
# ============================================================================

class TestIAMAuthentication:
    def test_authenticate_success(self, active_user, iam):
        iam, user = active_user
        # Set password verification to return True
        with patch.object(PasswordHashedVO, 'verify', return_value=True):
            new_iam, authenticated_user = iam.authenticate(
                username=user.username,
                password="correct_password",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        assert authenticated_user is not None
        assert authenticated_user.user_id == user.user_id
        assert new_iam.users[user.user_id].failed_login_attempts == 0
        assert new_iam.users[user.user_id].audit.last_login_ip == "192.168.1.1"
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(isinstance(e, LoginSuccessEvent) for e in events)

    def test_authenticate_user_not_found(self, iam):
        with patch.object(PasswordHashedVO, 'verify', return_value=True):
            new_iam, user = iam.authenticate(
                username="nonexistent",
                password="password",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        assert user is None
        assert new_iam is iam  # no change
        events = iam.get_events()
        assert any(isinstance(e, LoginFailureEvent) for e in events)

    def test_authenticate_inactive_user(self, iam, user_entity):
        iam = iam.add_user(user_entity, "system")
        # User is PENDING_ACTIVATION, not active
        with patch.object(PasswordHashedVO, 'verify', return_value=True):
            _new_iam, user = iam.authenticate(
                username=user_entity.username,
                password="password",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        assert user is None
        events = iam.get_events()
        assert any(e.failure_reason == "account_inactive" for e in events if isinstance(e, LoginFailureEvent))

    def test_authenticate_locked_user(self, active_user, iam):
        iam, user = active_user
        # Lock the user
        locked_user = user.lock("admin", "Reason")
        iam = iam.update_user(locked_user, "admin")
        with patch.object(PasswordHashedVO, 'verify', return_value=True):
            _new_iam, authenticated_user = iam.authenticate(
                username=user.username,
                password="password",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        assert authenticated_user is None
        events = iam.get_events()
        assert any(e.failure_reason == "account_locked" for e in events if isinstance(e, LoginFailureEvent))

    def test_authenticate_wrong_password(self, active_user, iam):
        iam, user = active_user
        with patch.object(PasswordHashedVO, 'verify', return_value=False):
            new_iam, authenticated_user = iam.authenticate(
                username=user.username,
                password="wrong_password",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        assert authenticated_user is None
        # Failed login attempts incremented
        assert new_iam.users[user.user_id].failed_login_attempts == 1
        assert new_iam.version == iam.version + 1
        events = new_iam.get_events()
        assert any(e.failure_reason == "wrong_password" for e in events if isinstance(e, LoginFailureEvent))

    def test_authenticate_wrong_password_locks_after_attempts(self, active_user, iam):
        iam, user = active_user
        # Set max attempts to 3
        with patch.object(PasswordHashedVO, 'verify', return_value=False):
            for _i in range(3):
                iam, _ = iam.authenticate(
                    username=user.username,
                    password="wrong",
                    ip_address="192.168.1.1",
                    user_agent="Mozilla/5.0",
                )
            # After 3 attempts, user should be locked
            assert iam.users[user.user_id].status == UserStatus.LOCKED
            assert iam.users[user.user_id].locked_until is not None


# ============================================================================
# Tests for Permission Checking
# ============================================================================

class TestIAMPermissionChecking:
    def test_has_permission_direct(self, active_user, iam):
        iam, user = active_user
        # Assign a role with permission
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.has_permission(user.user_id, "journal:create") is True
        assert iam.has_permission(user.user_id, "nonexistent") is False

    def test_has_permission_wildcard(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("super_admin")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        assert iam.has_permission(user.user_id, "anything:anything") is True
        assert iam.has_permission(user.user_id, "journal:create") is True

    def test_has_permission_user_not_found(self, iam):
        assert iam.has_permission(uuid4(), "journal:create") is False

    def test_get_user_permissions(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        perms = iam.get_user_permissions(user.user_id)
        assert "journal:create" in perms
        assert "invoice:read" in perms

    def test_get_user_effective_permissions(self, active_user, iam):
        iam, user = active_user
        # Create parent and child roles
        parent = iam.get_role_by_name("admin")
        # Create a child role inheriting from admin
        child = RoleEntity(
            role_id=uuid4(),
            role_name="child",
            description="Child",
            permissions={"custom:perm"},
            status=RoleStatus.ACTIVE,
            parent_role_id=parent.role_id,
            is_system=False,
            created_by="system",
        )
        iam = iam.add_role(child, "system")
        iam = iam.assign_role_to_user(user.user_id, child.role_id, "system")
        effective = iam.get_user_effective_permissions(user.user_id)
        # Should include child's permissions + parent's permissions
        assert "custom:perm" in effective
        # Admin has "user:*", "role:*", etc.
        assert "user:read" in effective
        assert "role:manage" in effective

    def test_get_user_roles(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        roles = iam.get_user_roles(user.user_id)
        assert len(roles) == 1
        assert roles[0].role_id == role.role_id


# ============================================================================
# Tests for Query Methods
# ============================================================================

class TestIAMQueryMethods:
    def test_get_user(self, active_user, iam):
        iam, user = active_user
        retrieved = iam.get_user(user.user_id)
        assert retrieved == user

    def test_get_user_by_username(self, active_user, iam):
        iam, user = active_user
        retrieved = iam.get_user_by_username(user.username)
        assert retrieved == user

    def test_get_user_by_email(self, active_user, iam):
        iam, user = active_user
        retrieved = iam.get_user_by_email(user.email)
        assert retrieved == user

    def test_get_role(self, iam):
        role = iam.get_role_by_name("user")
        retrieved = iam.get_role(role.role_id)
        assert retrieved == role

    def test_get_role_by_name(self, iam):
        role = iam.get_role_by_name("admin")
        assert role is not None
        assert role.role_name == "admin"

    def test_get_session(self, active_user, session_entity, iam):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        retrieved = iam.get_session(session_entity.session_id)
        assert retrieved == session_entity

    def test_get_session_by_token(self, active_user, session_entity, iam):
        iam, _user = active_user
        iam = iam.add_session(session_entity, "system")
        retrieved = iam.get_session_by_token(session_entity.token)
        assert retrieved == session_entity

    def test_get_active_sessions(self, active_user, session_entity, iam):
        iam, user = active_user
        iam = iam.add_session(session_entity, "system")
        active = iam.get_active_sessions(user.user_id)
        assert len(active) == 1
        assert active[0] == session_entity
        # Revoke session
        iam = iam.revoke_session(session_entity.session_id, "admin")
        active2 = iam.get_active_sessions(user.user_id)
        assert len(active2) == 0

    def test_get_all_users(self, active_user, iam):
        iam, user = active_user
        users = iam.get_all_users()
        assert len(users) == 1
        assert users[0] == user

    def test_get_active_users(self, active_user, iam):
        iam, user = active_user
        # Add inactive user
        user2 = UserEntity(
            user_id=uuid4(),
            username="inactive",
            email="inactive@example.com",
            password_hash=user.password_hash,
            status=UserStatus.INACTIVE,
            profile=user.profile,
            legal_entity_id=user.legal_entity_id,
            role_ids=[],
        )
        iam = iam.add_user(user2, "system")
        active_users = iam.get_active_users()
        assert len(active_users) == 1
        assert active_users[0] == user

    def test_get_all_roles(self, iam):
        roles = iam.get_all_roles()
        assert len(roles) == 5

    def test_get_users_by_role(self, active_user, iam):
        iam, user = active_user
        role = iam.get_role_by_name("user")
        iam = iam.assign_role_to_user(user.user_id, role.role_id, "system")
        users = iam.get_users_by_role(role.role_id)
        assert len(users) == 1
        assert users[0] == user


# ============================================================================
# Tests for Statistics
# ============================================================================

class TestIAMStatistics:
    def test_get_statistics(self, active_user, iam):
        iam, _user = active_user
        stats = iam.get_statistics()
        assert stats["total_users"] == 1
        assert stats["active_users"] == 1
        assert stats["inactive_users"] == 0
        assert stats["total_roles"] == 5
        assert stats["total_sessions"] == 0
        assert stats["active_sessions"] == 0
        assert stats["total_permissions"] == 0
        assert stats["status"] == "active"


# ============================================================================
# Tests for IAMRepository
# ============================================================================

class TestIAMRepository:
    async def test_save_and_get_by_id(self, iam):
        await IAMRepository.save(iam)
        retrieved = await IAMRepository.get_by_id(iam.iam_id)
        assert retrieved == iam

    async def test_get_by_legal_entity(self, iam):
        await IAMRepository.save(iam)
        retrieved = await IAMRepository.get_by_legal_entity(iam.legal_entity_id)
        assert retrieved == iam

    async def test_get_by_legal_entity_not_found(self):
        retrieved = await IAMRepository.get_by_legal_entity(uuid4())
        assert retrieved is None

    async def test_get_all(self, iam):
        await IAMRepository.save(iam)
        all_iams = await IAMRepository.get_all()
        assert len(all_iams) == 1
        assert all_iams[0] == iam

    async def test_update(self, iam):
        await IAMRepository.save(iam)
        updated = iam.update("admin", status="lockdown")
        await IAMRepository.update(updated)
        retrieved = await IAMRepository.get_by_id(iam.iam_id)
        assert retrieved.status == IAMStatus.LOCKDOWN

    async def test_delete(self, iam):
        await IAMRepository.save(iam)
        await IAMRepository.delete(iam.iam_id)
        retrieved = await IAMRepository.get_by_id(iam.iam_id)
        assert retrieved is None

    async def test_exists(self, iam):
        await IAMRepository.save(iam)
        assert await IAMRepository.exists(iam.iam_id) is True
        assert await IAMRepository.exists(uuid4()) is False

    async def test_count(self, iam):
        assert await IAMRepository.count() == 0
        await IAMRepository.save(iam)
        assert await IAMRepository.count() == 1

    async def test_list(self, iam):
        await IAMRepository.save(iam)
        iams = await IAMRepository.list(limit=1, offset=0)
        assert len(iams) == 1
        assert iams[0] == iam

    async def test_clear(self, iam):
        await IAMRepository.save(iam)
        await IAMRepository.clear()
        assert len(IAMRepository._storage) == 0
