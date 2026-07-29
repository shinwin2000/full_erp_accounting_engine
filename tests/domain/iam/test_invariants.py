# domain/iam/test_invariants.py
"""
Comprehensive unit tests for IAM invariants.

Covers:
- InvariantResult (construction, add_error, merge, to_dict, bool, classmethods)
- Validator functions: validate_username, validate_email, validate_full_name,
  validate_version, validate_date_not_future
- UserInvariants: validate_on_create, validate_on_update, validate_status_transition
- RoleInvariants: validate_on_create, validate_on_update, validate_on_delete,
  validate_parent, validate_hierarchy_cycle
- SessionInvariants: validate_session_creation, validate_session_renewal,
  validate_session_revocation
- IAMInvariantEnforcer (async) with mocked providers
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from domain.iam.invariants import (
    IAMInvariantEnforcer,
    InvariantResult,
    RoleInvariants,
    SessionInvariants,
    UserInvariants,
    validate_date_not_future,
    validate_email,
    validate_full_name,
    validate_username,
    validate_version,
)
from domain.iam.role_entity import RoleEntity, RoleStatus
from domain.iam.session_entity import SessionEntity, SessionStatus
from domain.iam.user_entity import UserEntity, UserStatus

# =============================================================================
# Helper: create mock objects (with spec/autospec for better mocking quality)
# =============================================================================

def create_mock_user(
    user_id=uuid4(),
    username="testuser",
    email="test@example.com",
    full_name="Test User",
    status=UserStatus.ACTIVE,
    is_locked=False,
    profile=None,
):
    user = MagicMock(spec=UserEntity)
    user.user_id = user_id
    user.username = username
    user.email = email
    user.profile = MagicMock()
    user.profile.full_name = full_name
    user.status = status
    user.is_active.return_value = status == UserStatus.ACTIVE
    user.is_locked.return_value = is_locked
    return user


def create_mock_role(
    role_id=uuid4(),
    role_name="admin",
    status=RoleStatus.ACTIVE,
    is_system=False,
    is_default=False,
    parent_role_id=None,
):
    role = MagicMock(spec=RoleEntity)
    role.role_id = role_id
    role.role_name = role_name
    role.status = status
    role.is_system = is_system
    role.is_default = is_default
    role.parent_role_id = parent_role_id
    return role


def create_mock_session(
    session_id=uuid4(),
    status=SessionStatus.ACTIVE,
    is_expired=False,
    is_refresh_expired=False,
    can_refresh=True,
):
    session = MagicMock(spec=SessionEntity)
    session.session_id = session_id
    session.status = status
    session.is_expired.return_value = is_expired
    session.is_refresh_expired.return_value = is_refresh_expired
    session.can_refresh.return_value = can_refresh
    return session


# =============================================================================
# Tests for InvariantResult
# =============================================================================

class TestInvariantResult:
    def test_default_initialization(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_initialization_with_values(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["e1"]
        assert result.warnings == ["w1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("invalid")
        assert result.is_valid is False
        assert result.errors == ["invalid"]

    def test_add_warning(self):
        result = InvariantResult()
        result.add_warning("warning")
        assert result.is_valid is True
        assert result.warnings == ["warning"]

    def test_merge_valid(self):
        r1 = InvariantResult()
        r2 = InvariantResult()
        merged = r1.merge(r2)
        assert merged.is_valid is True
        assert merged.errors == []
        assert merged.warnings == []

    def test_merge_invalid(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e2"]
        assert merged.warnings == ["w2"]

    def test_merge_multiple(self):
        r1 = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e1", "e2"]
        assert merged.warnings == ["w1", "w2"]

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False

    def test_success_classmethod(self):
        result = InvariantResult.success()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        result_with_warnings = InvariantResult.success(warnings=["w1"])
        assert result_with_warnings.warnings == ["w1"]

    def test_failure_classmethod(self):
        result = InvariantResult.failure("error", warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["error"]
        assert result.warnings == ["w1"]


# =============================================================================
# Tests for Validator Functions (parametrized to reduce duplication)
# =============================================================================

class TestValidators:
    # ---- validate_username ----
    @pytest.mark.parametrize(
        "username, expected_valid, error_contains",
        [
            ("john_doe", True, None),
            ("ab", False, "at least 3"),
            ("a" * 51, False, "exceed 50"),
            ("john-doe", False, "only letters"),
            ("", False, "non-empty"),
            (None, False, "non-empty"),
        ],
    )
    def test_validate_username(self, username, expected_valid, error_contains):
        result = validate_username(username)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # ---- validate_email ----
    @pytest.mark.parametrize(
        "email, expected_valid, error_contains",
        [
            ("test@example.com", True, None),
            ("test@example", False, "Invalid email"),
            ("", False, "non-empty"),
            (None, False, "non-empty"),
        ],
    )
    def test_validate_email(self, email, expected_valid, error_contains):
        result = validate_email(email)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # ---- validate_full_name ----
    @pytest.mark.parametrize(
        "name, expected_valid, error_contains",
        [
            ("John Doe", True, None),
            ("A", False, "at least 2"),
            ("A" * 201, False, "exceed 200"),
            ("", False, "non-empty"),
            (None, False, "non-empty"),
        ],
    )
    def test_validate_full_name(self, name, expected_valid, error_contains):
        result = validate_full_name(name)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # ---- validate_version ----
    @pytest.mark.parametrize(
        "version, expected_version, expected_valid, error_contains",
        [
            (1, None, True, None),
            (2, 2, True, None),
            (0, None, False, ">= 1"),
            (1, 2, False, "mismatch"),
        ],
    )
    def test_validate_version(self, version, expected_version, expected_valid, error_contains):
        result = validate_version(version, expected_version)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # ---- validate_date_not_future ----
    @pytest.mark.parametrize(
        "dt, expected_valid",
        [
            (datetime(2025, 1, 1, tzinfo=UTC), True),
            (datetime(2030, 1, 1, tzinfo=UTC), False),
        ],
    )
    def test_validate_date_not_future(self, dt, expected_valid):
        result = validate_date_not_future(dt, "Date")
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "cannot be in the future" in result.errors[0]


# =============================================================================
# Tests for UserInvariants
# =============================================================================

class TestUserInvariants:
    def test_validate_on_create_valid(self):
        result = UserInvariants.validate_on_create(
            username="john_doe",
            email="john@example.com",
            full_name="John Doe",
            existing_usernames=set(),
            existing_emails=set(),
        )
        assert result.is_valid is True

    @pytest.mark.parametrize(
        "username, email, existing_usernames, existing_emails, expected_error",
        [
            ("john_doe", "john@example.com", {"john_doe"}, set(), "already exists"),
            ("john_doe", "john@example.com", set(), {"john@example.com"}, "already exists"),
            ("john-doe", "john@example.com", set(), set(), "only letters"),
        ],
    )
    def test_validate_on_create_errors(self, username, email, existing_usernames, existing_emails, expected_error):
        result = UserInvariants.validate_on_create(
            username=username,
            email=email,
            full_name="John Doe",
            existing_usernames=existing_usernames,
            existing_emails=existing_emails,
        )
        assert result.is_valid is False
        assert any(expected_error in e for e in result.errors)

    def test_validate_on_update_valid(self):
        user = create_mock_user(username="john_doe", email="john@example.com")
        result = UserInvariants.validate_on_update(
            user=user,
            existing_usernames=set(),
            existing_emails=set(),
        )
        assert result.is_valid is True

    def test_validate_on_update_duplicate(self):
        user = create_mock_user(username="john_doe")
        result = UserInvariants.validate_on_update(
            user=user,
            existing_usernames={"john_doe"},
            existing_emails=set(),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    # ---- validate_status_transition ----
    @pytest.mark.parametrize(
        "current, new, is_self, expected_valid, error_contains",
        [
            (UserStatus.PENDING_ACTIVATION, UserStatus.ACTIVE, False, True, None),
            (UserStatus.PENDING_ACTIVATION, UserStatus.ACTIVE, True, False, "cannot activate own"),
            (UserStatus.SUSPENDED, UserStatus.ACTIVE, False, False, "unsuspended first"),
            (UserStatus.LOCKED, UserStatus.ACTIVE, False, False, "unlocked first"),
            (UserStatus.ACTIVE, UserStatus.INACTIVE, True, False, "cannot deactivate"),
            (UserStatus.ACTIVE, UserStatus.SUSPENDED, True, False, "cannot deactivate"),
            (UserStatus.ACTIVE, UserStatus.INACTIVE, False, True, None),
            (UserStatus.ACTIVE, UserStatus.SUSPENDED, False, True, None),
            (UserStatus.DELETED, UserStatus.ACTIVE, False, False, "Cannot transition"),
        ],
    )
    def test_validate_status_transition(self, current, new, is_self, expected_valid, error_contains):
        result = UserInvariants.validate_status_transition(
            current_status=current,
            new_status=new,
            user_id="user1",
            acting_user_id="admin" if not is_self else "user1",
            is_self=is_self,
        )
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for RoleInvariants
# =============================================================================

class TestRoleInvariants:
    def test_validate_on_create_valid(self):
        result = RoleInvariants.validate_on_create(
            role_name="admin",
            existing_role_names=set(),
            parent_role_id=None,
        )
        assert result.is_valid is True

    @pytest.mark.parametrize(
        "role_name, existing, expected_error",
        [
            ("a", set(), "at least 2"),
            ("a" * 51, set(), "exceed 50"),
            ("admin-role", set(), "only letters"),
            ("admin", {"admin"}, "already exists"),
        ],
    )
    def test_validate_on_create_errors(self, role_name, existing, expected_error):
        result = RoleInvariants.validate_on_create(
            role_name=role_name,
            existing_role_names=existing,
            parent_role_id=None,
        )
        assert result.is_valid is False
        assert any(expected_error in e for e in result.errors)

    def test_validate_on_update_system_role(self):
        role = create_mock_role(role_name="admin", is_system=True)
        result = RoleInvariants.validate_on_update(
            role=role,
            existing_role_names=set(),
        )
        assert result.is_valid is False
        assert "Cannot rename system role" in result.errors[0]

    def test_validate_on_update_non_system(self):
        role = create_mock_role(role_name="custom", is_system=False)
        result = RoleInvariants.validate_on_update(
            role=role,
            existing_role_names=set(),
        )
        assert result.is_valid is True

    # ---- validate_on_delete ----
    @pytest.mark.parametrize(
        "is_system, is_default, assigned_count, expected_valid, error_contains",
        [
            (True, False, 0, False, "Cannot delete system role"),
            (False, True, 0, False, "Cannot delete default role"),
            (False, False, 5, False, "assigned to 5 user(s)"),
            (False, False, 0, True, None),
        ],
    )
    def test_validate_on_delete(self, is_system, is_default, assigned_count, expected_valid, error_contains):
        role = create_mock_role(role_name="custom", is_system=is_system, is_default=is_default)
        result = RoleInvariants.validate_on_delete(role, assigned_count)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    def test_validate_parent_valid(self):
        role = create_mock_role()
        parent = create_mock_role(status=RoleStatus.ACTIVE)
        result = RoleInvariants.validate_parent(role, parent)
        assert result.is_valid is True

    @pytest.mark.parametrize(
        "parent_status, is_self, expected_error",
        [
            (RoleStatus.INACTIVE, False, "not active"),
            (RoleStatus.ACTIVE, True, "cannot be its own parent"),
        ],
    )
    def test_validate_parent_errors(self, parent_status, is_self, expected_error):
        role = create_mock_role()
        parent = create_mock_role(status=parent_status) if not is_self else role
        result = RoleInvariants.validate_parent(role, parent)
        assert result.is_valid is False
        assert any(expected_error in e for e in result.errors)

    def test_validate_hierarchy_cycle_detection(self):
        def get_parent(role_id):
            if role_id == UUID("11111111-1111-1111-1111-111111111111"):
                return create_mock_role(role_id=UUID("22222222-2222-2222-2222-222222222222"))
            elif role_id == UUID("22222222-2222-2222-2222-222222222222"):
                return create_mock_role(role_id=UUID("11111111-1111-1111-1111-111111111111"))
            return None

        role_id = UUID("11111111-1111-1111-1111-111111111111")
        parent_id = UUID("22222222-2222-2222-2222-222222222222")
        result = RoleInvariants.validate_hierarchy_cycle(role_id, parent_id, get_parent)
        assert result.is_valid is False
        assert "create a cycle" in result.errors[0]

    def test_validate_hierarchy_no_cycle(self):
        def get_parent(role_id):
            return None

        role_id = uuid4()
        parent_id = uuid4()
        result = RoleInvariants.validate_hierarchy_cycle(role_id, parent_id, get_parent)
        assert result.is_valid is True


# =============================================================================
# Tests for SessionInvariants
# =============================================================================

class TestSessionInvariants:
    @pytest.mark.parametrize(
        "status, is_locked, expected_valid, error_contains",
        [
            (UserStatus.ACTIVE, False, True, None),
            (UserStatus.INACTIVE, False, False, "Cannot create session"),
            (UserStatus.ACTIVE, True, False, "locked"),
        ],
    )
    def test_validate_session_creation(self, status, is_locked, expected_valid, error_contains):
        user = create_mock_user(status=status, is_locked=is_locked)
        result = SessionInvariants.validate_session_creation(user, "web")
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    @pytest.mark.parametrize(
        "can_refresh, is_expired, is_refresh_expired, status, expected_valid, error_contains",
        [
            (True, False, False, SessionStatus.ACTIVE, True, None),
            (False, True, False, SessionStatus.ACTIVE, False, "expired"),
            (False, False, True, SessionStatus.ACTIVE, False, "Refresh token has expired"),
            (False, False, False, SessionStatus.REVOKED, False, "Cannot refresh"),
        ],
    )
    def test_validate_session_renewal(
        self, can_refresh, is_expired, is_refresh_expired, status, expected_valid, error_contains
    ):
        session = create_mock_session(
            status=status,
            can_refresh=can_refresh,
            is_expired=is_expired,
            is_refresh_expired=is_refresh_expired,
        )
        result = SessionInvariants.validate_session_renewal(session)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    def test_validate_session_revocation_active(self):
        session = create_mock_session(status=SessionStatus.ACTIVE)
        result = SessionInvariants.validate_session_revocation(session)
        assert result.is_valid is True

    def test_validate_session_revocation_already_revoked(self):
        session = create_mock_session(status=SessionStatus.REVOKED)
        result = SessionInvariants.validate_session_revocation(session)
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "already revoked" in result.warnings[0]


# =============================================================================
# Tests for IAMInvariantEnforcer (Async) - all marked with asyncio
# =============================================================================

@pytest.mark.asyncio
class TestIAMInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        usernames = {"existing_user", "john_doe"}
        emails = {"existing@example.com"}
        role_names = {"admin", "user"}
        return IAMInvariantEnforcer(
            existing_usernames_provider=AsyncMock(return_value=usernames),
            existing_emails_provider=AsyncMock(return_value=emails),
            existing_role_names_provider=AsyncMock(return_value=role_names),
            get_parent_role_func=AsyncMock(return_value=None),
        )

    # ---- enforce_user_create ----
    async def test_enforce_user_create_valid(self, enforcer):
        result = await enforcer.enforce_user_create(
            username="new_user",
            email="new@example.com",
            full_name="New User",
        )
        assert result.is_valid is True

    @pytest.mark.parametrize(
        "username, email, expected_error",
        [
            ("john_doe", "new@example.com", "already exists"),
            ("new_user", "existing@example.com", "already exists"),
        ],
    )
    async def test_enforce_user_create_duplicate(self, enforcer, username, email, expected_error):
        result = await enforcer.enforce_user_create(
            username=username,
            email=email,
            full_name="Some Name",
        )
        assert result.is_valid is False
        assert any(expected_error in e for e in result.errors)

    # ---- enforce_user_update ----
    async def test_enforce_user_update_valid(self, enforcer):
        user = create_mock_user(username="new_user", email="new@example.com")
        result = await enforcer.enforce_user_update(user)
        assert result.is_valid is True

    async def test_enforce_user_update_duplicate(self, enforcer):
        # This should not error because the enforcer discards the user's own data.
        user = create_mock_user(username="existing_user", email="other@example.com")
        result = await enforcer.enforce_user_update(user)
        assert result.is_valid is True

    # ---- enforce_user_status_transition ----
    async def test_enforce_user_status_transition_valid(self, enforcer):
        result = await enforcer.enforce_user_status_transition(
            current_status=UserStatus.ACTIVE,
            new_status=UserStatus.INACTIVE,
            user_id="user1",
            acting_user_id="admin",
            is_self=False,
        )
        assert result.is_valid is True

    async def test_enforce_user_status_transition_self(self, enforcer):
        result = await enforcer.enforce_user_status_transition(
            current_status=UserStatus.ACTIVE,
            new_status=UserStatus.INACTIVE,
            user_id="user1",
            acting_user_id="user1",
            is_self=True,
        )
        assert result.is_valid is False
        assert "cannot deactivate or suspend" in result.errors[0]

    # ---- enforce_role_create ----
    async def test_enforce_role_create_valid(self, enforcer):
        result = await enforcer.enforce_role_create(role_name="manager")
        assert result.is_valid is True

    async def test_enforce_role_create_duplicate(self, enforcer):
        result = await enforcer.enforce_role_create(role_name="admin")
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    # ---- enforce_role_update ----
    async def test_enforce_role_update_valid(self, enforcer):
        role = create_mock_role(role_name="manager", is_system=False)
        result = await enforcer.enforce_role_update(role)
        assert result.is_valid is True

    async def test_enforce_role_update_system(self, enforcer):
        role = create_mock_role(role_name="admin", is_system=True)
        result = await enforcer.enforce_role_update(role)
        assert result.is_valid is False

    # ---- enforce_role_delete ----
    async def test_enforce_role_delete_valid(self, enforcer):
        role = create_mock_role(role_name="custom", is_system=False, is_default=False)
        result = await enforcer.enforce_role_delete(role, assigned_user_count=0)
        assert result.is_valid is True

    async def test_enforce_role_delete_system(self, enforcer):
        role = create_mock_role(role_name="admin", is_system=True)
        result = await enforcer.enforce_role_delete(role, assigned_user_count=0)
        assert result.is_valid is False

    # ---- enforce_role_parent ----
    async def test_enforce_role_parent_valid(self, enforcer):
        role = create_mock_role()
        parent = create_mock_role(status=RoleStatus.ACTIVE)
        # Override get_parent_role to return None to avoid cycle
        enforcer._get_parent_role = AsyncMock(return_value=None)
        result = await enforcer.enforce_role_parent(role, parent)
        assert result.is_valid is True

    async def test_enforce_role_parent_inactive(self, enforcer):
        role = create_mock_role()
        parent = create_mock_role(status=RoleStatus.INACTIVE)
        result = await enforcer.enforce_role_parent(role, parent)
        assert result.is_valid is False

    # ---- enforce_session_creation ----
    async def test_enforce_session_creation_valid(self, enforcer):
        user = create_mock_user(status=UserStatus.ACTIVE, is_locked=False)
        result = await enforcer.enforce_session_creation(user, "web")
        assert result.is_valid is True

    async def test_enforce_session_creation_inactive(self, enforcer):
        user = create_mock_user(status=UserStatus.INACTIVE, is_locked=False)
        result = await enforcer.enforce_session_creation(user, "web")
        assert result.is_valid is False

    # ---- enforce_session_renewal ----
    async def test_enforce_session_renewal_valid(self, enforcer):
        session = create_mock_session(can_refresh=True)
        result = await enforcer.enforce_session_renewal(session)
        assert result.is_valid is True

    async def test_enforce_session_renewal_expired(self, enforcer):
        session = create_mock_session(can_refresh=False, is_expired=True)
        result = await enforcer.enforce_session_renewal(session)
        assert result.is_valid is False

    # ---- enforce_session_revocation ----
    async def test_enforce_session_revocation_valid(self, enforcer):
        session = create_mock_session(status=SessionStatus.ACTIVE)
        result = await enforcer.enforce_session_revocation(session)
        assert result.is_valid is True

    async def test_enforce_session_revocation_already_revoked(self, enforcer):
        session = create_mock_session(status=SessionStatus.REVOKED)
        result = await enforcer.enforce_session_revocation(session)
        assert result.is_valid is True
        assert len(result.warnings) == 1
