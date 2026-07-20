# tests/adapters/primary_api/v1/test_fastapi_iam_router.py
"""
Comprehensive tests for fastapi_iam_router.py
Covers positive/negative paths, idempotency, user/role/permission management,
authentication, MFA, sessions, audit, and history.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from adapters.primary_api.v1.fastapi_iam_router import (
    ChangePasswordSchema,
    ForgotPasswordResponseSchema,
    IdempotencyManager,
    LoginAttemptResponseSchema,
    LoginRequestSchema,
    LoginResponseSchema,
    MFADisableSchema,
    MFASetupResponseSchema,
    MFAType,
    MFAVerifySchema,
    PermissionResponseSchema,
    RefreshTokenRequestSchema,
    ResetPasswordConfirmSchema,
    ResetPasswordRequestSchema,
    RoleCreateSchema,
    RolePermissionAssignSchema,
    RoleResponseSchema,
    RoleStatus,
    RoleUpdateSchema,
    SessionResponseSchema,
    SessionStatus,
    UserAuditLogSchema,
    UserCreateSchema,
    UserResponseSchema,
    UserRoleAssignSchema,
    UserStatus,
    UserUpdateSchema,
    activate_user,
    assign_permissions_to_role,
    assign_roles_to_user,
    change_password,
    create_role,
    create_user,
    deactivate_user,
    delete_role,
    disable_mfa,
    forgot_password,
    get_iam_service,
    get_login_attempts,
    get_role,
    get_role_permissions,
    get_user,
    get_user_audit_log,
    get_user_by_username,
    get_user_history,
    get_user_roles,
    get_user_sessions,
    get_user_status,
    health,
    info,
    list_permissions,
    list_roles,
    list_users,
    lock_user,
    login,
    logout,
    ping,
    refresh_token,
    remove_permission_from_role,
    remove_role_from_user,
    reset_password,
    revoke_all_other_sessions,
    revoke_session,
    setup_mfa,
    unlock_user,
    update_role,
    update_user,
    verify_mfa,
)


# ---------- Fixtures ----------

@pytest.fixture
def mock_iam_service():
    """Mock IAM service with async methods."""
    service = AsyncMock()

    # Default user object
    default_user = MagicMock(
        id=uuid4(),
        username="testuser",
        email="test@example.com",
        full_name="Test User",
        department="IT",
        job_title="Developer",
        phone_number="08123456789",
        status="active",
        is_active=True,
        is_locked=False,
        is_superuser=False,
        must_change_password=False,
        mfa_enabled=False,
        last_login_at=datetime.now(),
        last_password_change=datetime.now(),
        legal_entity_ids=[uuid4()],
        role_ids=[uuid4()],
        notes="Test note",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        version=1,
    )

    # Default role object
    default_role = MagicMock(
        id=uuid4(),
        name="ADMIN",
        description="Admin role",
        parent_role_id=None,
        parent_role_name=None,
        is_system_role=True,
        status="active",
        is_active=True,
        permission_ids=[uuid4()],
        created_at=datetime.now(),
        updated_at=datetime.now(),
        created_by=uuid4(),
        created_by_name="admin",
        version=1,
    )

    # Default permission object
    default_permission = MagicMock(
        id=uuid4(),
        name="read_users",
        resource="users",
        action="read",
        description="Read users",
        is_system=True,
        created_at=datetime.now(),
    )

    # Default session object
    default_session = MagicMock(
        id=uuid4(),
        session_token="token123",
        user_id=uuid4(),
        user_name="testuser",
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        device_id="device123",
        expires_at=datetime.now() + timedelta(hours=1),
        last_accessed_at=datetime.now(),
        is_active=True,
        is_revoked=False,
        created_at=datetime.now(),
    )

    # Default login attempt
    default_attempt = MagicMock(
        id=uuid4(),
        username="testuser",
        user_id=uuid4(),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        success=True,
        failure_reason=None,
        attempted_at=datetime.now(),
    )

    # Default audit log
    default_audit = MagicMock(
        id=uuid4(),
        user_id=uuid4(),
        action="LOGIN",
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        details={"source": "web"},
        created_at=datetime.now(),
    )

    # Set return values for service methods
    service.create_user = AsyncMock(return_value=default_user)
    service.list_users = AsyncMock(return_value=MagicMock(items=[default_user], total=1))
    service.get_user_by_id = AsyncMock(return_value=default_user)
    service.get_user_by_username = AsyncMock(return_value=default_user)
    service.update_user = AsyncMock(return_value=default_user)
    service.deactivate_user = AsyncMock(return_value=default_user)
    service.delete_user = AsyncMock(return_value=default_user)
    service.activate_user = AsyncMock(return_value=default_user)
    service.lock_user = AsyncMock(return_value=default_user)
    service.unlock_user = AsyncMock(return_value=default_user)

    service.create_role = AsyncMock(return_value=default_role)
    service.list_roles = AsyncMock(return_value=[default_role])
    service.get_role_by_id = AsyncMock(return_value=default_role)
    service.update_role = AsyncMock(return_value=default_role)
    service.delete_role = AsyncMock(return_value=default_role)

    service.assign_roles_to_user = AsyncMock(return_value=[default_role])
    service.get_user_roles = AsyncMock(return_value=[default_role])
    service.remove_role_from_user = AsyncMock(return_value=default_role)

    service.list_permissions = AsyncMock(return_value=[default_permission])
    service.assign_permissions_to_role = AsyncMock(return_value=[default_permission])
    service.get_role_permissions = AsyncMock(return_value=[default_permission])
    service.remove_permission_from_role = AsyncMock(return_value=default_permission)

    service.login = AsyncMock(
        return_value=MagicMock(
            access_token="access_token",
            refresh_token="refresh_token",
            expires_in=3600,
            user=default_user,
        )
    )
    service.logout = AsyncMock(return_value=True)
    service.refresh_token = AsyncMock(
        return_value=MagicMock(
            access_token="new_access_token",
            refresh_token="new_refresh_token",
            expires_in=3600,
            user=default_user,
        )
    )
    service.change_password = AsyncMock(return_value=True)
    service.forgot_password = AsyncMock(
        return_value=MagicMock(
            message="Reset link sent",
            reset_token="reset_token",
            reset_url="https://example.com/reset/token",
        )
    )
    service.reset_password = AsyncMock(return_value=True)

    service.setup_mfa = AsyncMock(
        return_value=MagicMock(
            secret_key="SECRET123",
            qr_code_url="https://example.com/qr",
            backup_codes=["code1", "code2"],
        )
    )
    service.verify_and_enable_mfa = AsyncMock(return_value=True)
    service.disable_mfa = AsyncMock(return_value=True)

    service.get_user_sessions = AsyncMock(return_value=[default_session])
    service.revoke_session = AsyncMock(return_value=True)
    service.revoke_all_other_sessions = AsyncMock(return_value=True)

    service.get_login_attempts = AsyncMock(return_value=[default_attempt])
    service.get_user_audit_log = AsyncMock(return_value=[default_audit])

    service.get_user_status = AsyncMock(
        return_value=MagicMock(
            username="testuser",
            status="active",
            is_active=True,
            is_locked=False,
            is_mfa_enabled=False,
            must_change_password=False,
            password_expiry_days=60,
            last_login_at=datetime.now(),
            last_activity_at=datetime.now(),
            can_login=True,
            can_change_password=True,
        )
    )
    service.get_user_history = AsyncMock(return_value=[])

    return service


@pytest.fixture
def current_user():
    return MagicMock(
        user_id=uuid4(),
        session_id=uuid4(),
        username="current_user",
        legal_entity_id=uuid4(),
    )


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def idempotency_key():
    return "test-idempotency-key"


# ---------- IdempotencyManager Tests ----------

def test_idempotency_manager_construction():
    mgr = IdempotencyManager()
    assert mgr._storage == {}
    assert mgr._ttl_seconds == 86400


def test_idempotency_manager_cache_and_get():
    mgr = IdempotencyManager()
    key = "key1"
    method = "test_method"
    result = {"data": "value"}
    mgr.cache_result(key, method, result)
    storage_key = mgr._get_key(key, method)
    assert storage_key in mgr._storage
    cached = mgr.get_cached_result(key, method)
    assert cached == result


def test_idempotency_manager_get_missing():
    mgr = IdempotencyManager()
    assert mgr.get_cached_result("missing", "method") is None


def test_idempotency_manager_expiry():
    mgr = IdempotencyManager()
    mgr._ttl_seconds = 0
    mgr.cache_result("key", "method", {"x": 1})
    assert mgr.get_cached_result("key", "method") is None


# ---------- Enum Tests (parametrized) ----------

ENUM_CLASSES = [
    (UserStatus, ["ACTIVE", "INACTIVE", "LOCKED", "SUSPENDED", "PENDING_ACTIVATION", "PASSWORD_EXPIRED", "DELETED"]),
    (RoleStatus, ["ACTIVE", "INACTIVE", "DEPRECATED"]),
    (MFAType, ["TOTP", "SMS", "EMAIL", "BACKUP_CODE"]),
    (SessionStatus, ["ACTIVE", "EXPIRED", "REVOKED", "LOGGED_OUT"]),
]


@pytest.mark.parametrize("enum_class,members", ENUM_CLASSES)
def test_enum_members_exist(enum_class, members):
    for member in members:
        assert hasattr(enum_class, member)


@pytest.mark.parametrize("enum_class,_", ENUM_CLASSES)
def test_enum_member_is_instance(enum_class, _):
    first_member = list(enum_class)[0]
    assert isinstance(first_member, enum_class)


# ---------- Schema Validation Negative Tests ----------

def test_user_create_schema_invalid_email():
    with pytest.raises(ValueError, match="Invalid email format"):
        UserCreateSchema(
            username="testuser",
            email="notanemail",
            full_name="Test User",
            password="SecurePass123!",
        )


def test_user_create_schema_username_empty():
    with pytest.raises(ValueError, match="Username is required"):
        UserCreateSchema(
            username="",
            email="test@example.com",
            full_name="Test User",
            password="SecurePass123!",
        )


def test_role_create_schema_name_empty():
    with pytest.raises(ValueError, match="Role name is required"):
        RoleCreateSchema(name="", description="Test")


def test_user_role_assign_schema_empty_role_ids():
    with pytest.raises(ValueError):
        UserRoleAssignSchema(role_ids=[])


def test_role_permission_assign_schema_empty_permission_ids():
    with pytest.raises(ValueError):
        RolePermissionAssignSchema(permission_ids=[])


def test_change_password_schema_short_new_password():
    with pytest.raises(ValueError, match="Password must be at least 8 characters"):
        ChangePasswordSchema(old_password="old", new_password="short")


# ---------- Dependency Injection ----------

@pytest.mark.asyncio
async def test_get_iam_service():
    request = MagicMock()
    request.app.state.iam_service = MagicMock()
    service = await get_iam_service(request)
    assert service is not None


# ---------- Ping/Health/Info (Sync) ----------

def test_ping():
    result = ping()
    assert result == {"status": "ok", "service": "iam-router"}


def test_health():
    result = health()
    assert result == {"status": "healthy"}


def test_info():
    result = info()
    assert result == {"version": "1.0", "name": "IAM Router"}


# ---------- User CRUD ----------

@pytest.mark.asyncio
async def test_create_user_success(mock_iam_service, current_user, legal_entity_id, idempotency_key):
    request = MagicMock(
        username="newuser",
        email="new@example.com",
        full_name="New User",
        password="SecurePass123!",
        must_change_password=True,
        legal_entity_ids=[legal_entity_id],
        role_ids=[uuid4()],
        department="IT",
        job_title="Developer",
        phone_number="08123456789",
        is_superuser=False,
        notes="Note",
    )
    result = await create_user(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        legal_entity_id=legal_entity_id,
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    assert result.username == "testuser"  # from default_user
    mock_iam_service.create_user.assert_called_once()


@pytest.mark.asyncio
async def test_create_user_idempotency_hit(mock_iam_service, current_user, legal_entity_id, idempotency_key):
    mgr = IdempotencyManager()
    with patch("adapters.primary_api.v1.fastapi_iam_router._idempotency_manager", mgr):
        cached = UserResponseSchema(
            id=uuid4(),
            username="cached_user",
            email="cached@example.com",
            full_name="Cached User",
            department=None,
            job_title=None,
            phone_number=None,
            status=UserStatus.ACTIVE,
            is_active=True,
            is_locked=False,
            is_superuser=False,
            must_change_password=False,
            mfa_enabled=False,
            last_login_at=None,
            last_password_change=None,
            legal_entity_ids=[],
            role_ids=[],
            notes=None,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=None,
            created_by_name=None,
            version=1,
        )
        mgr.cache_result(idempotency_key, "create_user", cached.model_dump())
        request = MagicMock()
        result = await create_user(
            request=request,
            idempotency_key=idempotency_key,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_iam_service,
        )
        mock_iam_service.create_user.assert_not_called()
        assert result.username == "cached_user"


@pytest.mark.asyncio
async def test_create_user_value_error(mock_iam_service, current_user, legal_entity_id):
    mock_iam_service.create_user.side_effect = ValueError("Username already exists")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await create_user(
            request=request,
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 422
    assert "Username already exists" in exc.value.detail


@pytest.mark.asyncio
async def test_create_user_general_exception(mock_iam_service, current_user, legal_entity_id):
    mock_iam_service.create_user.side_effect = RuntimeError("DB error")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await create_user(
            request=request,
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            legal_entity_id=legal_entity_id,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_list_users_success(mock_iam_service):
    result = await list_users(
        status=UserStatus.ACTIVE,
        is_active=True,
        search="test",
        role_id=uuid4(),
        legal_entity_id_filter=uuid4(),
        page=1,
        page_size=10,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], UserResponseSchema)
    mock_iam_service.list_users.assert_called_once()


@pytest.mark.asyncio
async def test_list_users_general_exception(mock_iam_service):
    mock_iam_service.list_users.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await list_users(
            status=None,
            is_active=None,
            search=None,
            role_id=None,
            legal_entity_id_filter=None,
            page=1,
            page_size=10,
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_user_success(mock_iam_service):
    user_id = uuid4()
    result = await get_user(
        user_id=user_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    mock_iam_service.get_user_by_id.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_get_user_not_found(mock_iam_service):
    mock_iam_service.get_user_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_user(
            user_id=uuid4(),
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_user_by_username_success(mock_iam_service):
    result = await get_user_by_username(
        username="testuser",
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    mock_iam_service.get_user_by_username.assert_called_once_with("testuser")


@pytest.mark.asyncio
async def test_get_user_by_username_not_found(mock_iam_service):
    mock_iam_service.get_user_by_username.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_user_by_username(
            username="unknown",
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    request = UserUpdateSchema(
        full_name="Updated Name",
        email="updated@example.com",
        department="Finance",
        job_title="Manager",
        phone_number="08123456788",
        status=UserStatus.ACTIVE,
        notes="Updated notes",
        legal_entity_ids=[uuid4()],
        is_superuser=True,
    )
    result = await update_user(
        user_id=user_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    mock_iam_service.update_user.assert_called_once_with(
        user_id=user_id,
        full_name=request.full_name,
        email=request.email,
        department=request.department,
        job_title=request.job_title,
        phone_number=request.phone_number,
        status=request.status.value,
        notes=request.notes,
        legal_entity_ids=request.legal_entity_ids,
        is_superuser=request.is_superuser,
        updated_by=current_user.user_id,
    )


@pytest.mark.asyncio
async def test_update_user_not_found(mock_iam_service, current_user):
    mock_iam_service.update_user.return_value = None
    with pytest.raises(HTTPException) as exc:
        await update_user(
            user_id=uuid4(),
            request=MagicMock(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deactivate_user_soft(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    result = await deactivate_user(
        user_id=user_id,
        permanent=False,
        reason="Inactive",
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["action"] == "deactivated"
    mock_iam_service.deactivate_user.assert_called_once_with(user_id, current_user.user_id, "Inactive")


@pytest.mark.asyncio
async def test_deactivate_user_permanent(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    result = await deactivate_user(
        user_id=user_id,
        permanent=True,
        reason="Permanent",
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["action"] == "deleted"
    mock_iam_service.delete_user.assert_called_once_with(user_id, current_user.user_id, "Permanent")


@pytest.mark.asyncio
async def test_deactivate_user_not_found(mock_iam_service, current_user):
    mock_iam_service.deactivate_user.return_value = None
    with pytest.raises(HTTPException) as exc:
        await deactivate_user(
            user_id=uuid4(),
            permanent=False,
            reason="",
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_activate_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    result = await activate_user(
        user_id=user_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    mock_iam_service.activate_user.assert_called_once_with(user_id, current_user.user_id)


@pytest.mark.asyncio
async def test_activate_user_not_found(mock_iam_service, current_user):
    mock_iam_service.activate_user.return_value = None
    with pytest.raises(HTTPException) as exc:
        await activate_user(
            user_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_lock_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    result = await lock_user(
        user_id=user_id,
        reason="Suspicious",
        duration_minutes=60,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    assert result.is_locked is True
    mock_iam_service.lock_user.assert_called_once_with(
        user_id=user_id,
        reason="Suspicious",
        duration_minutes=60,
        locked_by=current_user.user_id,
    )


@pytest.mark.asyncio
async def test_lock_user_not_found(mock_iam_service, current_user):
    mock_iam_service.lock_user.return_value = None
    with pytest.raises(HTTPException) as exc:
        await lock_user(
            user_id=uuid4(),
            reason="",
            duration_minutes=30,
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unlock_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    result = await unlock_user(
        user_id=user_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, UserResponseSchema)
    assert result.is_locked is False
    mock_iam_service.unlock_user.assert_called_once_with(user_id, current_user.user_id)


# ---------- Role CRUD ----------

@pytest.mark.asyncio
async def test_create_role_success(mock_iam_service, current_user, idempotency_key):
    request = RoleCreateSchema(
        name="MANAGER",
        description="Manager role",
        parent_role_id=None,
        is_system_role=False,
    )
    result = await create_role(
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, RoleResponseSchema)
    mock_iam_service.create_role.assert_called_once()


@pytest.mark.asyncio
async def test_list_roles_success(mock_iam_service):
    result = await list_roles(
        status=RoleStatus.ACTIVE,
        is_active=True,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], RoleResponseSchema)


@pytest.mark.asyncio
async def test_get_role_success(mock_iam_service):
    role_id = uuid4()
    result = await get_role(
        role_id=role_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, RoleResponseSchema)
    mock_iam_service.get_role_by_id.assert_called_once_with(role_id)


@pytest.mark.asyncio
async def test_get_role_not_found(mock_iam_service):
    mock_iam_service.get_role_by_id.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_role(
            role_id=uuid4(),
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_update_role_success(mock_iam_service, current_user, idempotency_key):
    role_id = uuid4()
    request = RoleUpdateSchema(
        description="Updated",
        status=RoleStatus.INACTIVE,
        parent_role_id=uuid4(),
    )
    result = await update_role(
        role_id=role_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, RoleResponseSchema)
    mock_iam_service.update_role.assert_called_once()


@pytest.mark.asyncio
async def test_update_role_not_found(mock_iam_service, current_user):
    mock_iam_service.update_role.return_value = None
    with pytest.raises(HTTPException) as exc:
        await update_role(
            role_id=uuid4(),
            request=MagicMock(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_role_success(mock_iam_service, current_user, idempotency_key):
    role_id = uuid4()
    result = await delete_role(
        role_id=role_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["deleted"] is True
    mock_iam_service.delete_role.assert_called_once_with(role_id, current_user.user_id)


@pytest.mark.asyncio
async def test_delete_role_not_found(mock_iam_service, current_user):
    mock_iam_service.delete_role.return_value = None
    with pytest.raises(HTTPException) as exc:
        await delete_role(
            role_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


# ---------- User-Role Assignment ----------

@pytest.mark.asyncio
async def test_assign_roles_to_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    request = UserRoleAssignSchema(role_ids=[uuid4(), uuid4()])
    result = await assign_roles_to_user(
        user_id=user_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], RoleResponseSchema)
    mock_iam_service.assign_roles_to_user.assert_called_once_with(
        user_id=user_id,
        role_ids=request.role_ids,
        assigned_by=current_user.user_id,
    )


@pytest.mark.asyncio
async def test_get_user_roles_success(mock_iam_service):
    user_id = uuid4()
    result = await get_user_roles(
        user_id=user_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    mock_iam_service.get_user_roles.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_remove_role_from_user_success(mock_iam_service, current_user, idempotency_key):
    user_id = uuid4()
    role_id = uuid4()
    result = await remove_role_from_user(
        user_id=user_id,
        role_id=role_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["removed"] is True
    mock_iam_service.remove_role_from_user.assert_called_once_with(user_id, role_id, current_user.user_id)


@pytest.mark.asyncio
async def test_remove_role_from_user_not_found(mock_iam_service, current_user):
    mock_iam_service.remove_role_from_user.return_value = None
    with pytest.raises(HTTPException) as exc:
        await remove_role_from_user(
            user_id=uuid4(),
            role_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


# ---------- Permissions ----------

@pytest.mark.asyncio
async def test_list_permissions_success(mock_iam_service):
    result = await list_permissions(
        resource="users",
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], PermissionResponseSchema)


@pytest.mark.asyncio
async def test_assign_permissions_to_role_success(mock_iam_service, current_user, idempotency_key):
    role_id = uuid4()
    request = RolePermissionAssignSchema(permission_ids=[uuid4(), uuid4()])
    result = await assign_permissions_to_role(
        role_id=role_id,
        request=request,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    mock_iam_service.assign_permissions_to_role.assert_called_once()


@pytest.mark.asyncio
async def test_get_role_permissions_success(mock_iam_service):
    role_id = uuid4()
    result = await get_role_permissions(
        role_id=role_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    mock_iam_service.get_role_permissions.assert_called_once_with(role_id)


@pytest.mark.asyncio
async def test_remove_permission_from_role_success(mock_iam_service, current_user, idempotency_key):
    role_id = uuid4()
    permission_id = uuid4()
    result = await remove_permission_from_role(
        role_id=role_id,
        permission_id=permission_id,
        idempotency_key=idempotency_key,
        _permission=MagicMock(),
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["removed"] is True
    mock_iam_service.remove_permission_from_role.assert_called_once_with(role_id, permission_id, current_user.user_id)


@pytest.mark.asyncio
async def test_remove_permission_from_role_not_found(mock_iam_service, current_user):
    mock_iam_service.remove_permission_from_role.return_value = None
    with pytest.raises(HTTPException) as exc:
        await remove_permission_from_role(
            role_id=uuid4(),
            permission_id=uuid4(),
            idempotency_key=None,
            _permission=MagicMock(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


# ---------- Authentication ----------

@pytest.mark.asyncio
async def test_login_success(mock_iam_service):
    request = LoginRequestSchema(
        username="testuser",
        password="password",
        mfa_code=None,
        legal_entity_id=uuid4(),
    )
    result = await login(
        request=request,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        service=mock_iam_service,
    )
    assert isinstance(result, LoginResponseSchema)
    assert result.access_token == "access_token"
    mock_iam_service.login.assert_called_once_with(
        username=request.username,
        password=request.password,
        mfa_code=request.mfa_code,
        legal_entity_id=request.legal_entity_id,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
    )


@pytest.mark.asyncio
async def test_login_value_error(mock_iam_service):
    mock_iam_service.login.side_effect = ValueError("Invalid credentials")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await login(
            request=request,
            ip_address=None,
            user_agent=None,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_general_exception(mock_iam_service):
    mock_iam_service.login.side_effect = RuntimeError("Login error")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await login(
            request=request,
            ip_address=None,
            user_agent=None,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_logout_success(mock_iam_service, current_user):
    result = await logout(
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result is None
    mock_iam_service.logout.assert_called_once_with(current_user.user_id, current_user.session_id)


@pytest.mark.asyncio
async def test_logout_exception(mock_iam_service, current_user):
    mock_iam_service.logout.side_effect = RuntimeError("Logout error")
    result = await logout(
        current_user=current_user,
        service=mock_iam_service,
    )
    # logout catches all exceptions and returns None (204)
    assert result is None


@pytest.mark.asyncio
async def test_refresh_token_success(mock_iam_service):
    request = RefreshTokenRequestSchema(refresh_token="old_refresh")
    result = await refresh_token(
        request=request,
        service=mock_iam_service,
    )
    assert isinstance(result, LoginResponseSchema)
    assert result.access_token == "new_access_token"
    mock_iam_service.refresh_token.assert_called_once_with("old_refresh")


@pytest.mark.asyncio
async def test_refresh_token_value_error(mock_iam_service):
    mock_iam_service.refresh_token.side_effect = ValueError("Invalid token")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await refresh_token(
            request=request,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_change_password_success(mock_iam_service, current_user):
    request = ChangePasswordSchema(old_password="old", new_password="newpassword")
    result = await change_password(
        request=request,
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result is None
    mock_iam_service.change_password.assert_called_once_with(
        user_id=current_user.user_id,
        old_password="old",
        new_password="newpassword",
    )


@pytest.mark.asyncio
async def test_change_password_failure(mock_iam_service, current_user):
    mock_iam_service.change_password.return_value = False
    request = ChangePasswordSchema(old_password="wrong", new_password="newpassword")
    with pytest.raises(HTTPException) as exc:
        await change_password(
            request=request,
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 400
    assert "Old password incorrect" in exc.value.detail


@pytest.mark.asyncio
async def test_change_password_value_error(mock_iam_service, current_user):
    mock_iam_service.change_password.side_effect = ValueError("Invalid")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await change_password(
            request=request,
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_forgot_password_success(mock_iam_service):
    request = ResetPasswordRequestSchema(email="test@example.com")
    result = await forgot_password(
        request=request,
        service=mock_iam_service,
    )
    assert isinstance(result, ForgotPasswordResponseSchema)
    assert result.message == "Reset link sent"
    mock_iam_service.forgot_password.assert_called_once_with(email="test@example.com")


@pytest.mark.asyncio
async def test_forgot_password_value_error(mock_iam_service):
    mock_iam_service.forgot_password.side_effect = ValueError("Email not found")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await forgot_password(
            request=request,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reset_password_success(mock_iam_service):
    request = ResetPasswordConfirmSchema(token="reset_token", new_password="newpass")
    result = await reset_password(
        request=request,
        service=mock_iam_service,
    )
    assert result["message"] == "Password reset successfully"
    mock_iam_service.reset_password.assert_called_once_with(token="reset_token", new_password="newpass")


@pytest.mark.asyncio
async def test_reset_password_failure(mock_iam_service):
    mock_iam_service.reset_password.return_value = False
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await reset_password(
            request=request,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 400


# ---------- MFA ----------

@pytest.mark.asyncio
async def test_setup_mfa_success(mock_iam_service, current_user):
    result = await setup_mfa(
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, MFASetupResponseSchema)
    assert result.secret_key == "SECRET123"
    mock_iam_service.setup_mfa.assert_called_once_with(
        user_id=current_user.user_id,
        issuer="ERP-Accounting-Engine",
    )


@pytest.mark.asyncio
async def test_verify_mfa_success(mock_iam_service, current_user):
    request = MFAVerifySchema(code="123456")
    result = await verify_mfa(
        request=request,
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["enabled"] is True
    mock_iam_service.verify_and_enable_mfa.assert_called_once_with(
        user_id=current_user.user_id,
        code="123456",
    )


@pytest.mark.asyncio
async def test_verify_mfa_value_error(mock_iam_service, current_user):
    mock_iam_service.verify_and_enable_mfa.side_effect = ValueError("Invalid code")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await verify_mfa(
            request=request,
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_disable_mfa_success(mock_iam_service, current_user):
    request = MFADisableSchema(password="mypassword", mfa_code="123456")
    result = await disable_mfa(
        request=request,
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result["disabled"] is True
    mock_iam_service.disable_mfa.assert_called_once_with(
        user_id=current_user.user_id,
        password="mypassword",
        code="123456",
    )


@pytest.mark.asyncio
async def test_disable_mfa_value_error(mock_iam_service, current_user):
    mock_iam_service.disable_mfa.side_effect = ValueError("Invalid")
    request = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await disable_mfa(
            request=request,
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 400


# ---------- Sessions ----------

@pytest.mark.asyncio
async def test_get_user_sessions_success(mock_iam_service, current_user):
    result = await get_user_sessions(
        current_user=current_user,
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], SessionResponseSchema)
    mock_iam_service.get_user_sessions.assert_called_once_with(current_user.user_id)


@pytest.mark.asyncio
async def test_revoke_session_success(mock_iam_service, current_user):
    session_id = uuid4()
    result = await revoke_session(
        session_id=session_id,
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result is None
    mock_iam_service.revoke_session.assert_called_once_with(session_id, current_user.user_id)


@pytest.mark.asyncio
async def test_revoke_session_not_found(mock_iam_service, current_user):
    mock_iam_service.revoke_session.return_value = False
    with pytest.raises(HTTPException) as exc:
        await revoke_session(
            session_id=uuid4(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_revoke_session_value_error(mock_iam_service, current_user):
    mock_iam_service.revoke_session.side_effect = ValueError("Cannot revoke current")
    with pytest.raises(HTTPException) as exc:
        await revoke_session(
            session_id=uuid4(),
            current_user=current_user,
            service=mock_iam_service,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_revoke_all_other_sessions_success(mock_iam_service, current_user):
    result = await revoke_all_other_sessions(
        current_user=current_user,
        service=mock_iam_service,
    )
    assert result is None
    mock_iam_service.revoke_all_other_sessions.assert_called_once_with(
        current_user.user_id, current_user.session_id
    )


# ---------- Login Attempts & Audit ----------

@pytest.mark.asyncio
async def test_get_login_attempts_success(mock_iam_service):
    result = await get_login_attempts(
        username="testuser",
        success=True,
        start_date=datetime.now(),
        end_date=datetime.now(),
        page=1,
        page_size=10,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], LoginAttemptResponseSchema)
    mock_iam_service.get_login_attempts.assert_called_once()


@pytest.mark.asyncio
async def test_get_login_attempts_general_exception(mock_iam_service):
    mock_iam_service.get_login_attempts.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await get_login_attempts(
            username=None,
            success=None,
            start_date=None,
            end_date=None,
            page=1,
            page_size=10,
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_get_user_audit_log_success(mock_iam_service):
    user_id = uuid4()
    result = await get_user_audit_log(
        user_id=user_id,
        limit=10,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], UserAuditLogSchema)
    mock_iam_service.get_user_audit_log.assert_called_once_with(user_id, 10)


@pytest.mark.asyncio
async def test_get_user_audit_log_general_exception(mock_iam_service):
    mock_iam_service.get_user_audit_log.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await get_user_audit_log(
            user_id=uuid4(),
            limit=100,
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500


# ---------- User Status & History ----------

@pytest.mark.asyncio
async def test_get_user_status_success(mock_iam_service):
    user_id = uuid4()
    result = await get_user_status(
        user_id=user_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert result["status"] == "active"
    mock_iam_service.get_user_status.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_get_user_status_not_found(mock_iam_service):
    mock_iam_service.get_user_status.return_value = None
    with pytest.raises(HTTPException) as exc:
        await get_user_status(
            user_id=uuid4(),
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_user_history_success(mock_iam_service):
    user_id = uuid4()
    result = await get_user_history(
        user_id=user_id,
        _permission=MagicMock(),
        service=mock_iam_service,
    )
    assert isinstance(result, list)
    mock_iam_service.get_user_history.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_get_user_history_general_exception(mock_iam_service):
    mock_iam_service.get_user_history.side_effect = RuntimeError("Error")
    with pytest.raises(HTTPException) as exc:
        await get_user_history(
            user_id=uuid4(),
            _permission=MagicMock(),
            service=mock_iam_service,
        )
    assert exc.value.status_code == 500