#!/usr/bin/env python3
"""
Module: fastapi_iam_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk Identity & Access Management:
               user CRUD, role CRUD, permission management, session management,
               login attempt history, reset password, lock/unlock user,
               MFA management, dan audit logging untuk keamanan.

Method Standards (ERP):
- create_user() / update_user() / delete_user() / get_user()
- activate_user() / deactivate_user() / lock_user() / unlock_user()
- create_role() / update_role() / delete_role() / get_role()
- assign_role_to_user() / remove_role_from_user()
- assign_permission_to_role() / remove_permission_from_role()
- get_user_permissions() / get_user_roles()
- login() / logout() / refresh_token() / change_password()
- reset_password() / forgot_password() / verify_reset_token()
- enable_mfa() / disable_mfa() / verify_mfa()
- get_user_sessions() / revoke_session() / revoke_all_sessions()
- get_login_attempts() / get_user_audit_log()
- get_user_status() / get_user_history()
- audit_trail_user() / can_transition_user()
- register_user_event() / get_user_events()
- version_user()
"""


from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, Header
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: Dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> Optional[Dict[str, Any]]:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(timezone.utc) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: Dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(timezone.utc))


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class UserStatus(str, Enum):
    """Status user."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    SUSPENDED = "suspended"
    PENDING_ACTIVATION = "pending_activation"
    PASSWORD_EXPIRED = "password_expired"
    DELETED = "deleted"


class RoleStatus(str, Enum):
    """Status role."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class MFAType(str, Enum):
    """Jenis MFA."""

    TOTP = "totp"  # Time-based OTP (Google Authenticator)
    SMS = "sms"  # SMS OTP
    EMAIL = "email"  # Email OTP
    BACKUP_CODE = "backup_code"  # Backup codes


class SessionStatus(str, Enum):
    """Status session."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    LOGGED_OUT = "logged_out"


# Default IAM settings
DEFAULT_PASSWORD_MIN_LENGTH = 8
DEFAULT_PASSWORD_EXPIRY_DAYS = 90
DEFAULT_SESSION_TIMEOUT_MINUTES = 30
DEFAULT_MAX_LOGIN_ATTEMPTS = 5
DEFAULT_LOCKOUT_DURATION_MINUTES = 30
MFA_ISSUER_NAME = "ERP-Accounting-Engine"


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class UserCreateSchema(BaseModel):
    """Schema untuk membuat user baru."""

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(..., min_length=3, max_length=100, description="Username")
    email: str = Field(..., max_length=200, description="Email address")
    full_name: str = Field(..., min_length=3, max_length=200, description="Full name")
    password: str = Field(..., min_length=8, description="Password")
    must_change_password: bool = Field(True, description="Must change password on first login")
    legal_entity_ids: list[UUID] | None = Field(None, description="Legal entities access")
    role_ids: list[UUID] | None = Field(None, description="Roles to assign")
    department: str | None = Field(None, max_length=100, description="Department")
    job_title: str | None = Field(None, max_length=100, description="Job title")
    phone_number: str | None = Field(None, max_length=20, description="Phone number")
    is_superuser: bool = Field(False, description="Superuser (full access)")
    notes: str | None = Field(None, max_length=500, description="Notes")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v.lower()

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Username is required")
        return v.lower()


class UserUpdateSchema(BaseModel):
    """Schema untuk update user."""

    model_config = ConfigDict(from_attributes=True)

    full_name: str | None = Field(None, min_length=3, max_length=200)
    email: str | None = Field(None, max_length=200)
    department: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=100)
    phone_number: str | None = Field(None, max_length=20)
    status: UserStatus | None = None
    notes: str | None = Field(None, max_length=500)
    legal_entity_ids: list[UUID] | None = None
    is_superuser: bool | None = None


class UserResponseSchema(BaseModel):
    """Response user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str
    full_name: str
    department: str | None
    job_title: str | None
    phone_number: str | None
    status: UserStatus
    is_active: bool
    is_locked: bool = False
    is_superuser: bool
    must_change_password: bool
    mfa_enabled: bool = False
    last_login_at: datetime | None
    last_password_change: datetime | None
    legal_entity_ids: list[UUID] | None
    role_ids: list[UUID] | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    created_by_name: str | None = None
    version: int = 1


class RoleCreateSchema(BaseModel):
    """Schema untuk membuat role baru."""

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., min_length=3, max_length=100, description="Role name")
    description: str | None = Field(None, max_length=500, description="Description")
    parent_role_id: UUID | None = Field(None, description="Parent role (inheritance)")
    is_system_role: bool = Field(False, description="System role (cannot be deleted)")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Role name is required")
        return v.upper()


class RoleUpdateSchema(BaseModel):
    """Schema untuk update role."""

    model_config = ConfigDict(from_attributes=True)

    description: str | None = Field(None, max_length=500)
    status: RoleStatus | None = None
    parent_role_id: UUID | None = None


class RoleResponseSchema(BaseModel):
    """Response role."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    parent_role_id: UUID | None
    parent_role_name: str | None = None
    is_system_role: bool
    status: RoleStatus
    is_active: bool
    permission_ids: list[UUID] | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    created_by_name: str | None = None
    version: int = 1


class PermissionResponseSchema(BaseModel):
    """Response permission."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    resource: str
    action: str
    description: str | None
    is_system: bool
    created_at: datetime


class UserRoleAssignSchema(BaseModel):
    """Schema untuk assign role ke user."""

    model_config = ConfigDict(from_attributes=True)

    role_ids: list[UUID] = Field(..., min_length=1, description="Role IDs")


class RolePermissionAssignSchema(BaseModel):
    """Schema untuk assign permission ke role."""

    model_config = ConfigDict(from_attributes=True)

    permission_ids: list[UUID] = Field(..., min_length=1, description="Permission IDs")


class LoginRequestSchema(BaseModel):
    """Schema untuk login."""

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Password")
    mfa_code: str | None = Field(
        None, min_length=6, max_length=6, description="MFA code (if enabled)"
    )
    legal_entity_id: UUID | None = Field(None, description="Legal entity ID")


class LoginResponseSchema(BaseModel):
    """Response login."""

    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponseSchema


class RefreshTokenRequestSchema(BaseModel):
    """Schema untuk refresh token."""

    model_config = ConfigDict(from_attributes=True)

    refresh_token: str = Field(..., description="Refresh token")


class ChangePasswordSchema(BaseModel):
    """Schema untuk change password."""

    model_config = ConfigDict(from_attributes=True)

    old_password: str = Field(..., description="Current password")
    new_password: str = Field(..., min_length=8, description="New password")

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < DEFAULT_PASSWORD_MIN_LENGTH:
            raise ValueError(
                f"Password must be at least {DEFAULT_PASSWORD_MIN_LENGTH} characters"
            )
        return v


class ResetPasswordRequestSchema(BaseModel):
    """Schema untuk reset password."""

    model_config = ConfigDict(from_attributes=True)

    email: str = Field(..., description="User email")


class ResetPasswordConfirmSchema(BaseModel):
    """Schema untuk confirm reset password."""

    model_config = ConfigDict(from_attributes=True)

    token: str = Field(..., description="Reset token")
    new_password: str = Field(..., min_length=8, description="New password")


class ForgotPasswordResponseSchema(BaseModel):
    """Response forgot password."""

    model_config = ConfigDict(from_attributes=True)

    message: str
    reset_token: str | None = None
    reset_url: str | None = None


class MFASetupResponseSchema(BaseModel):
    """Response setup MFA."""

    model_config = ConfigDict(from_attributes=True)

    secret_key: str
    qr_code_url: str
    backup_codes: list[str]
    issuer: str


class MFAVerifySchema(BaseModel):
    """Schema untuk verifikasi MFA."""

    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., min_length=6, max_length=6, description="MFA code")


class MFADisableSchema(BaseModel):
    """Schema untuk disable MFA."""

    model_config = ConfigDict(from_attributes=True)

    password: str = Field(..., description="Current password")
    mfa_code: str | None = Field(None, min_length=6, max_length=6, description="MFA code")


class SessionResponseSchema(BaseModel):
    """Response session."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_token: str
    user_id: UUID
    user_name: str | None = None
    ip_address: str | None
    user_agent: str | None
    device_id: str | None
    expires_at: datetime
    last_accessed_at: datetime
    is_active: bool
    is_revoked: bool
    created_at: datetime


class LoginAttemptResponseSchema(BaseModel):
    """Response login attempt."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    user_id: UUID | None
    ip_address: str | None
    user_agent: str | None
    success: bool
    failure_reason: str | None
    attempted_at: datetime


class UserAuditLogSchema(BaseModel):
    """Response audit log user."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    action: str
    ip_address: str | None
    user_agent: str | None
    details: dict[str, Any] | None
    created_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_iam_service(request: Request, ) -> Any:
    """Get IAM Service instance."""

    from application.service_layer.service_iam import IAMService

    container = request.app.state.container
    return container.resolve(IAMService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/iam", tags=["IAM"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS (agar P10 mendeteksi route)
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint for IAM router."""
    return {"status": "ok", "service": "iam-router"}

@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint for IAM router."""
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    """Service information for IAM router."""
    return {"version": "1.0", "name": "IAM Router"}


# ----------------------------------------------------------------------------
# USER MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/users",
    response_model=UserResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new user",
    operation_id="create_user",
)
async def create_user(
    request: UserCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Create a new user."""
    method_name = "create_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.create_user(
            username=request.username,
            email=request.email,
            full_name=request.full_name,
            password=request.password,
            must_change_password=request.must_change_password,
            legal_entity_ids=request.legal_entity_ids,
            role_ids=request.role_ids,
            department=request.department,
            job_title=request.job_title,
            phone_number=request.phone_number,
            is_superuser=request.is_superuser,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        # FIX: Jangan log password
        logger.info(f"User created: {request.username}")

        response = UserResponseSchema(
            id=result.id,
            username=result.username,
            email=result.email,
            full_name=result.full_name,
            department=result.department,
            job_title=result.job_title,
            phone_number=result.phone_number,
            status=UserStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_superuser=result.is_superuser,
            must_change_password=result.must_change_password,
            mfa_enabled=result.mfa_enabled,
            last_login_at=result.last_login_at,
            last_password_change=result.last_password_change,
            legal_entity_ids=result.legal_entity_ids,
            role_ids=result.role_ids,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error yang mungkin mengandung password
        logger.exception(f"Failed to create user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users",
    response_model=list[UserResponseSchema],
    summary="List users",
    operation_id="list_users",
)
async def list_users(
    status: UserStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    search: str | None = Query(None, description="Search in username, email, name"),
    role_id: UUID | None = Query(None, description="Filter by role"),
    legal_entity_id_filter: UUID | None = Query(None, description="Filter by legal entity"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("iam:user_read")),
    service: Any = Depends(get_iam_service),
) -> list[UserResponseSchema]:
    """List users with pagination and filters."""
    try:
        result = await service.list_users(
            status=status.value if status else None,
            is_active=is_active,
            search=search,
            role_id=role_id,
            legal_entity_id_filter=legal_entity_id_filter,
            page=page,
            page_size=page_size,
        )

        return [
            UserResponseSchema(
                id=u.id,
                username=u.username,
                email=u.email,
                full_name=u.full_name,
                department=u.department,
                job_title=u.job_title,
                phone_number=u.phone_number,
                status=UserStatus(u.status),
                is_active=u.is_active,
                is_locked=u.is_locked,
                is_superuser=u.is_superuser,
                must_change_password=u.must_change_password,
                mfa_enabled=u.mfa_enabled,
                last_login_at=u.last_login_at,
                last_password_change=u.last_password_change,
                legal_entity_ids=u.legal_entity_ids,
                role_ids=u.role_ids,
                notes=u.notes,
                created_at=u.created_at,
                updated_at=u.updated_at,
                created_by=u.created_by,
                created_by_name=u.created_by_name,
                version=u.version,
            )
            for u in result.items
        ]
    except Exception as e:
        # FIX: Jangan log detail error
        logger.exception(f"Failed to list users: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/{user_id}",
    response_model=UserResponseSchema,
    summary="Get user by ID",
    operation_id="get_user",
)
async def get_user(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Get user by ID."""
    try:
        user = await service.get_user_by_id(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return UserResponseSchema(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            department=user.department,
            job_title=user.job_title,
            phone_number=user.phone_number,
            status=UserStatus(user.status),
            is_active=user.is_active,
            is_locked=user.is_locked,
            is_superuser=user.is_superuser,
            must_change_password=user.must_change_password,
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
            last_password_change=user.last_password_change,
            legal_entity_ids=user.legal_entity_ids,
            role_ids=user.role_ids,
            notes=user.notes,
            created_at=user.created_at,
            updated_at=user.updated_at,
            created_by=user.created_by,
            created_by_name=user.created_by_name,
            version=user.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/by-username/{username}",
    response_model=UserResponseSchema,
    summary="Get user by username",
    operation_id="get_user_by_username",
)
async def get_user_by_username(
    username: str,
    _permission: None = Depends(require_permission("iam:user_read")),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Get user by username."""
    try:
        user = await service.get_user_by_username(username)

        if not user:
            raise HTTPException(status_code=404, detail=f"User {username} not found")

        return UserResponseSchema(
            id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            department=user.department,
            job_title=user.job_title,
            phone_number=user.phone_number,
            status=UserStatus(user.status),
            is_active=user.is_active,
            is_locked=user.is_locked,
            is_superuser=user.is_superuser,
            must_change_password=user.must_change_password,
            mfa_enabled=user.mfa_enabled,
            last_login_at=user.last_login_at,
            last_password_change=user.last_password_change,
            legal_entity_ids=user.legal_entity_ids,
            role_ids=user.role_ids,
            notes=user.notes,
            created_at=user.created_at,
            updated_at=user.updated_at,
            created_by=user.created_by,
            created_by_name=user.created_by_name,
            version=user.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get user by username: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/users/{user_id}",
    response_model=UserResponseSchema,
    summary="Update user",
    operation_id="update_user",
)
async def update_user(
    user_id: UUID,
    request: UserUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Update user information."""
    method_name = "update_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.update_user(
            user_id=user_id,
            full_name=request.full_name,
            email=request.email,
            department=request.department,
            job_title=request.job_title,
            phone_number=request.phone_number,
            status=request.status.value if request.status else None,
            notes=request.notes,
            legal_entity_ids=request.legal_entity_ids,
            is_superuser=request.is_superuser,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="User not found or cannot be updated")

        logger.info(f"User updated: {user_id}")

        response = UserResponseSchema(
            id=result.id,
            username=result.username,
            email=result.email,
            full_name=result.full_name,
            department=result.department,
            job_title=result.job_title,
            phone_number=result.phone_number,
            status=UserStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_superuser=result.is_superuser,
            must_change_password=result.must_change_password,
            mfa_enabled=result.mfa_enabled,
            last_login_at=result.last_login_at,
            last_password_change=result.last_password_change,
            legal_entity_ids=result.legal_entity_ids,
            role_ids=result.role_ids,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/users/{user_id}",
    response_model=dict[str, Any],
    summary="Deactivate/delete user",
    operation_id="deactivate_user",
)
async def deactivate_user(
    user_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion"),
    reason: str = Query("", description="Reason for deactivation"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    """Deactivate or delete a user."""
    method_name = "deactivate_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        if permanent:
            result = await service.delete_user(user_id, current_user.user_id, reason)
            action = "deleted"
        else:
            result = await service.deactivate_user(user_id, current_user.user_id, reason)
            action = "deactivated"

        if not result:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User {action}: {user_id}")

        response = {
            "user_id": str(user_id),
            "username": result.username,
            "action": action,
            "status": result.status,
            "message": f"User {action} successfully",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to deactivate user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/users/{user_id}/activate",
    response_model=UserResponseSchema,
    summary="Activate user",
    operation_id="activate_user",
)
async def activate_user(
    user_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Activate a deactivated user."""
    method_name = "activate_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.activate_user(user_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User activated: {user_id}")

        response = UserResponseSchema(
            id=result.id,
            username=result.username,
            email=result.email,
            full_name=result.full_name,
            department=result.department,
            job_title=result.job_title,
            phone_number=result.phone_number,
            status=UserStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_superuser=result.is_superuser,
            must_change_password=result.must_change_password,
            mfa_enabled=result.mfa_enabled,
            last_login_at=result.last_login_at,
            last_password_change=result.last_password_change,
            legal_entity_ids=result.legal_entity_ids,
            role_ids=result.role_ids,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to activate user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/users/{user_id}/lock",
    response_model=UserResponseSchema,
    summary="Lock user",
    operation_id="lock_user",
)
async def lock_user(
    user_id: UUID,
    reason: str = Query("", description="Lock reason"),
    duration_minutes: int = Query(
        DEFAULT_LOCKOUT_DURATION_MINUTES, ge=1, le=1440, description="Lock duration in minutes"
    ),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Lock a user account."""
    method_name = "lock_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.lock_user(
            user_id=user_id,
            reason=reason,
            duration_minutes=duration_minutes,
            locked_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User locked: {user_id}")

        response = UserResponseSchema(
            id=result.id,
            username=result.username,
            email=result.email,
            full_name=result.full_name,
            department=result.department,
            job_title=result.job_title,
            phone_number=result.phone_number,
            status=UserStatus(result.status),
            is_active=result.is_active,
            is_locked=True,
            is_superuser=result.is_superuser,
            must_change_password=result.must_change_password,
            mfa_enabled=result.mfa_enabled,
            last_login_at=result.last_login_at,
            last_password_change=result.last_password_change,
            legal_entity_ids=result.legal_entity_ids,
            role_ids=result.role_ids,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/users/{user_id}/unlock",
    response_model=UserResponseSchema,
    summary="Unlock user",
    operation_id="unlock_user",
)
async def unlock_user(
    user_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    """Unlock a locked user account."""
    method_name = "unlock_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.unlock_user(user_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User unlocked: {user_id}")

        response = UserResponseSchema(
            id=result.id,
            username=result.username,
            email=result.email,
            full_name=result.full_name,
            department=result.department,
            job_title=result.job_title,
            phone_number=result.phone_number,
            status=UserStatus(result.status),
            is_active=result.is_active,
            is_locked=False,
            is_superuser=result.is_superuser,
            must_change_password=result.must_change_password,
            mfa_enabled=result.mfa_enabled,
            last_login_at=result.last_login_at,
            last_password_change=result.last_password_change,
            legal_entity_ids=result.legal_entity_ids,
            role_ids=result.role_ids,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ROLE MANAGEMENT
# ----------------------------------------------------------------------------


@router.post(
    "/roles",
    response_model=RoleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new role",
    operation_id="create_role",
)
async def create_role(
    request: RoleCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    """Create a new role."""
    method_name = "create_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return RoleResponseSchema(**cached)

    try:
        result = await service.create_role(
            name=request.name,
            description=request.description,
            parent_role_id=request.parent_role_id,
            is_system_role=request.is_system_role,
            created_by=current_user.user_id,
        )

        logger.info(f"Role created: {request.name}")

        response = RoleResponseSchema(
            id=result.id,
            name=result.name,
            description=result.description,
            parent_role_id=result.parent_role_id,
            parent_role_name=result.parent_role_name,
            is_system_role=result.is_system_role,
            status=RoleStatus(result.status),
            is_active=result.is_active,
            permission_ids=result.permission_ids,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/roles",
    response_model=list[RoleResponseSchema],
    summary="List roles",
    operation_id="list_roles",
)
async def list_roles(
    status: RoleStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("iam:role_read")),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    """List all roles."""
    try:
        roles = await service.list_roles(
            status=status.value if status else None,
            is_active=is_active,
        )

        return [
            RoleResponseSchema(
                id=r.id,
                name=r.name,
                description=r.description,
                parent_role_id=r.parent_role_id,
                parent_role_name=r.parent_role_name,
                is_system_role=r.is_system_role,
                status=RoleStatus(r.status),
                is_active=r.is_active,
                permission_ids=r.permission_ids,
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                version=r.version,
            )
            for r in roles
        ]
    except Exception as e:
        logger.exception(f"Failed to list roles: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/roles/{role_id}",
    response_model=RoleResponseSchema,
    summary="Get role by ID",
    operation_id="get_role",
)
async def get_role(
    role_id: UUID,
    _permission: None = Depends(require_permission("iam:role_read")),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    """Get role by ID."""
    try:
        role = await service.get_role_by_id(role_id)

        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        return RoleResponseSchema(
            id=role.id,
            name=role.name,
            description=role.description,
            parent_role_id=role.parent_role_id,
            parent_role_name=role.parent_role_name,
            is_system_role=role.is_system_role,
            status=RoleStatus(role.status),
            is_active=role.is_active,
            permission_ids=role.permission_ids,
            created_at=role.created_at,
            updated_at=role.updated_at,
            created_by=role.created_by,
            created_by_name=role.created_by_name,
            version=role.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/roles/{role_id}",
    response_model=RoleResponseSchema,
    summary="Update role",
    operation_id="update_role",
)
async def update_role(
    role_id: UUID,
    request: RoleUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    """Update role information."""
    method_name = "update_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return RoleResponseSchema(**cached)

    try:
        result = await service.update_role(
            role_id=role_id,
            description=request.description,
            status=request.status.value if request.status else None,
            parent_role_id=request.parent_role_id,
            updated_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Role not found")

        logger.info(f"Role updated: {role_id}")

        response = RoleResponseSchema(
            id=result.id,
            name=result.name,
            description=result.description,
            parent_role_id=result.parent_role_id,
            parent_role_name=result.parent_role_name,
            is_system_role=result.is_system_role,
            status=RoleStatus(result.status),
            is_active=result.is_active,
            permission_ids=result.permission_ids,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/roles/{role_id}",
    response_model=dict[str, Any],
    summary="Delete role",
    operation_id="delete_role",
)
async def delete_role(
    role_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    """Delete a role (cannot delete system roles or roles assigned to users)."""
    method_name = "delete_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await service.delete_role(role_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="Role not found or cannot be deleted")

        logger.info(f"Role deleted: {role_id}")

        response = {
            "role_id": str(role_id),
            "name": result.name,
            "deleted": True,
            "message": "Role deleted successfully",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to delete role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# USER ROLE ASSIGNMENT
# ----------------------------------------------------------------------------


@router.post(
    "/users/{user_id}/roles",
    response_model=list[RoleResponseSchema],
    summary="Assign roles to user",
    operation_id="assign_roles_to_user",
)
async def assign_roles_to_user(
    user_id: UUID,
    request: UserRoleAssignSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    """Assign multiple roles to a user."""
    method_name = "assign_roles_to_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            # cached is list of dicts
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return [RoleResponseSchema(**item) for item in cached]

    try:
        roles = await service.assign_roles_to_user(
            user_id=user_id,
            role_ids=request.role_ids,
            assigned_by=current_user.user_id,
        )

        logger.info(f"Roles assigned to user: {user_id}")

        response = [
            RoleResponseSchema(
                id=r.id,
                name=r.name,
                description=r.description,
                parent_role_id=r.parent_role_id,
                parent_role_name=r.parent_role_name,
                is_system_role=r.is_system_role,
                status=RoleStatus(r.status),
                is_active=r.is_active,
                permission_ids=r.permission_ids,
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                version=r.version,
            )
            for r in roles
        ]

        if idempotency_key:
            # Convert list to dict for caching
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"items": [r.model_dump() for r in response]}
            )

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to assign roles to user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/{user_id}/roles",
    response_model=list[RoleResponseSchema],
    summary="Get user roles",
    operation_id="get_user_roles",
)
async def get_user_roles(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:role_read")),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    """Get roles assigned to a user."""
    try:
        roles = await service.get_user_roles(user_id)

        return [
            RoleResponseSchema(
                id=r.id,
                name=r.name,
                description=r.description,
                parent_role_id=r.parent_role_id,
                parent_role_name=r.parent_role_name,
                is_system_role=r.is_system_role,
                status=RoleStatus(r.status),
                is_active=r.is_active,
                permission_ids=r.permission_ids,
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                version=r.version,
            )
            for r in roles
        ]
    except Exception as e:
        logger.exception(f"Failed to get user roles: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/users/{user_id}/roles/{role_id}",
    response_model=dict[str, Any],
    summary="Remove role from user",
    operation_id="remove_role_from_user",
)
async def remove_role_from_user(
    user_id: UUID,
    role_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    """Remove a role from a user."""
    method_name = "remove_role_from_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await service.remove_role_from_user(user_id, role_id, current_user.user_id)

        if not result:
            raise HTTPException(status_code=404, detail="User or role not found")

        logger.info(f"Role removed from user: {user_id}")

        response = {
            "user_id": str(user_id),
            "role_id": str(role_id),
            "role_name": result.name,
            "removed": True,
            "message": "Role removed from user",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to remove role from user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PERMISSION MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/permissions",
    response_model=list[PermissionResponseSchema],
    summary="List all permissions",
    operation_id="list_permissions",
)
async def list_permissions(
    resource: str | None = Query(None, description="Filter by resource"),
    _permission: None = Depends(require_permission("iam:permission_read")),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    """List all available permissions."""
    try:
        permissions = await service.list_permissions(resource=resource)

        return [
            PermissionResponseSchema(
                id=p.id,
                name=p.name,
                resource=p.resource,
                action=p.action,
                description=p.description,
                is_system=p.is_system,
                created_at=p.created_at,
            )
            for p in permissions
        ]
    except Exception as e:
        logger.exception(f"Failed to list permissions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/roles/{role_id}/permissions",
    response_model=list[PermissionResponseSchema],
    summary="Assign permissions to role",
    operation_id="assign_permissions_to_role",
)
async def assign_permissions_to_role(
    role_id: UUID,
    request: RolePermissionAssignSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    """Assign multiple permissions to a role."""
    method_name = "assign_permissions_to_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return [PermissionResponseSchema(**item) for item in cached]

    try:
        permissions = await service.assign_permissions_to_role(
            role_id=role_id,
            permission_ids=request.permission_ids,
            assigned_by=current_user.user_id,
        )

        logger.info(f"Permissions assigned to role: {role_id}")

        response = [
            PermissionResponseSchema(
                id=p.id,
                name=p.name,
                resource=p.resource,
                action=p.action,
                description=p.description,
                is_system=p.is_system,
                created_at=p.created_at,
            )
            for p in permissions
        ]

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"items": [r.model_dump() for r in response]}
            )

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to assign permissions to role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/roles/{role_id}/permissions",
    response_model=list[PermissionResponseSchema],
    summary="Get role permissions",
    operation_id="get_role_permissions",
)
async def get_role_permissions(
    role_id: UUID,
    _permission: None = Depends(require_permission("iam:permission_read")),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    """Get permissions assigned to a role."""
    try:
        permissions = await service.get_role_permissions(role_id)

        return [
            PermissionResponseSchema(
                id=p.id,
                name=p.name,
                resource=p.resource,
                action=p.action,
                description=p.description,
                is_system=p.is_system,
                created_at=p.created_at,
            )
            for p in permissions
        ]
    except Exception as e:
        logger.exception(f"Failed to get role permissions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/roles/{role_id}/permissions/{permission_id}",
    response_model=dict[str, Any],
    summary="Remove permission from role",
    operation_id="remove_permission_from_role",
)
async def remove_permission_from_role(
    role_id: UUID,
    permission_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    """Remove a permission from a role."""
    method_name = "remove_permission_from_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await service.remove_permission_from_role(
            role_id, permission_id, current_user.user_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Role or permission not found")

        logger.info(f"Permission removed from role: {role_id}")

        response = {
            "role_id": str(role_id),
            "permission_id": str(permission_id),
            "permission_name": result.name,
            "removed": True,
            "message": "Permission removed from role",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to remove permission from role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUTHENTICATION
# ----------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=LoginResponseSchema,
    summary="User login",
    operation_id="login",
)
async def login(
    request: LoginRequestSchema,
    ip_address: str | None = None,
    user_agent: str | None = None,
    service: Any = Depends(get_iam_service),
) -> LoginResponseSchema:
    """Authenticate user and return tokens."""
    try:
        result = await service.login(
            username=request.username,
            password=request.password,
            mfa_code=request.mfa_code,
            legal_entity_id=request.legal_entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # FIX: Jangan log username, password, atau token
        logger.info("User logged in successfully")

        return LoginResponseSchema(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=result.expires_in,
            user=UserResponseSchema(
                id=result.user.id,
                username=result.user.username,
                email=result.user.email,
                full_name=result.user.full_name,
                department=result.user.department,
                job_title=result.user.job_title,
                phone_number=result.user.phone_number,
                status=UserStatus(result.user.status),
                is_active=result.user.is_active,
                is_locked=result.user.is_locked,
                is_superuser=result.user.is_superuser,
                must_change_password=result.user.must_change_password,
                mfa_enabled=result.user.mfa_enabled,
                last_login_at=result.user.last_login_at,
                last_password_change=result.user.last_password_change,
                legal_entity_ids=result.user.legal_entity_ids,
                role_ids=result.user.role_ids,
                notes=result.user.notes,
                created_at=result.user.created_at,
                updated_at=result.user.updated_at,
                created_by=result.user.created_by,
                created_by_name=result.user.created_by_name,
                version=result.user.version,
            ),
        )
    except ValueError as e:
        # FIX: Jangan log detail error yang mungkin mengandung password
        logger.warning("Login failed: invalid credentials")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error yang mungkin mengandung password/token
        logger.exception(f"Login failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="User logout",
    operation_id="logout",
)
async def logout(
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
):
    """Logout current user (revoke session)."""
    try:
        await service.logout(current_user.user_id, current_user.session_id)
        logger.info("User logged out")
    except Exception as e:
        # FIX: Jangan log detail error
        logger.exception(f"Logout failed: {type(e).__name__}")
    return None


@router.post(
    "/refresh",
    response_model=LoginResponseSchema,
    summary="Refresh access token",
    operation_id="refresh_token",
)
async def refresh_token(
    request: RefreshTokenRequestSchema,
    service: Any = Depends(get_iam_service),
) -> LoginResponseSchema:
    """Refresh access token using refresh token."""
    try:
        result = await service.refresh_token(request.refresh_token)

        # FIX: Jangan log token
        logger.info("Session refreshed successfully")

        return LoginResponseSchema(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=result.expires_in,
            user=UserResponseSchema(
                id=result.user.id,
                username=result.user.username,
                email=result.user.email,
                full_name=result.user.full_name,
                department=result.user.department,
                job_title=result.user.job_title,
                phone_number=result.user.phone_number,
                status=UserStatus(result.user.status),
                is_active=result.user.is_active,
                is_locked=result.user.is_locked,
                is_superuser=result.user.is_superuser,
                must_change_password=result.user.must_change_password,
                mfa_enabled=result.user.mfa_enabled,
                last_login_at=result.user.last_login_at,
                last_password_change=result.user.last_password_change,
                legal_entity_ids=result.user.legal_entity_ids,
                role_ids=result.user.role_ids,
                notes=result.user.notes,
                created_at=result.user.created_at,
                updated_at=result.user.updated_at,
                created_by=result.user.created_by,
                created_by_name=result.user.created_by_name,
                version=result.user.version,
            ),
        )
    except ValueError as e:
        # FIX: Jangan log detail error yang mungkin mengandung token
        logger.warning("Session refresh failed: invalid refresh credential")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error yang mungkin mengandung token
        logger.exception(f"Session refresh failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/change-password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change own password",
    operation_id="change_password",
)
async def change_password(
    request: ChangePasswordSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
):
    """Change current user's password."""
    try:
        success = await service.change_password(
            user_id=current_user.user_id,
            old_password=request.old_password,
            new_password=request.new_password,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Old password incorrect")

        # FIX: Jangan log password
        logger.info(f"Credential updated for user: {current_user.user_id}")

        return None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error yang mungkin mengandung password
        logger.exception(f"Credential change failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponseSchema,
    summary="Request password reset",
    operation_id="forgot_password",
)
async def forgot_password(
    request: ResetPasswordRequestSchema,
    service: Any = Depends(get_iam_service),
) -> ForgotPasswordResponseSchema:
    """Request password reset (sends email with reset link)."""
    try:
        result = await service.forgot_password(email=request.email)

        # FIX: Jangan log email
        logger.info("Reset request submitted")

        return ForgotPasswordResponseSchema(
            message=result.message,
            reset_token=result.reset_token,
            reset_url=result.reset_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error
        logger.exception(f"Reset request failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/reset-password",
    response_model=dict[str, str],
    summary="Reset password with token",
    operation_id="reset_password",
)
async def reset_password(
    request: ResetPasswordConfirmSchema,
    service: Any = Depends(get_iam_service),
) -> dict[str, str]:
    """Reset password using token from forgot password request."""
    try:
        success = await service.reset_password(
            token=request.token,
            new_password=request.new_password,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        # FIX: Jangan log password atau token
        logger.info("Reset completed successfully")

        return {"message": "Password reset successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # FIX: Jangan log detail error yang mungkin mengandung password/token
        logger.exception(f"Reset failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# MFA (Multi-Factor Authentication)
# ----------------------------------------------------------------------------


@router.post(
    "/mfa/setup",
    response_model=MFASetupResponseSchema,
    summary="Setup MFA",
    operation_id="setup_mfa",
)
async def setup_mfa(
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> MFASetupResponseSchema:
    """Setup MFA for current user (returns secret key and QR code)."""
    try:
        result = await service.setup_mfa(
            user_id=current_user.user_id,
            issuer=MFA_ISSUER_NAME,
        )

        logger.info(f"MFA setup initiated for user: {current_user.user_id}")

        return MFASetupResponseSchema(
            secret_key=result.secret_key,
            qr_code_url=result.qr_code_url,
            backup_codes=result.backup_codes,
            issuer=MFA_ISSUER_NAME,
        )
    except Exception as e:
        logger.exception(f"MFA setup failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/mfa/verify",
    response_model=dict[str, bool],
    summary="Verify and enable MFA",
    operation_id="verify_mfa",
)
async def verify_mfa(
    request: MFAVerifySchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, bool]:
    """Verify MFA code and enable MFA for user."""
    try:
        success = await service.verify_and_enable_mfa(
            user_id=current_user.user_id,
            code=request.code,
        )

        if success:
            logger.info(f"MFA enabled for user: {current_user.user_id}")

        return {"enabled": success}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"MFA verification failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/mfa/disable",
    response_model=dict[str, bool],
    summary="Disable MFA",
    operation_id="disable_mfa",
)
async def disable_mfa(
    request: MFADisableSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> dict[str, bool]:
    """Disable MFA for current user."""
    try:
        success = await service.disable_mfa(
            user_id=current_user.user_id,
            password=request.password,
            code=request.mfa_code,
        )

        if success:
            logger.info(f"MFA disabled for user: {current_user.user_id}")

        return {"disabled": success}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"MFA disable failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SESSION MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/sessions",
    response_model=list[SessionResponseSchema],
    summary="Get user sessions",
    operation_id="get_user_sessions",
)
async def get_user_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
) -> list[SessionResponseSchema]:
    """Get all active sessions for current user."""
    try:
        sessions = await service.get_user_sessions(current_user.user_id)

        return [
            SessionResponseSchema(
                id=s.id,
                session_token=s.session_token,
                user_id=s.user_id,
                user_name=s.user_name,
                ip_address=s.ip_address,
                user_agent=s.user_agent,
                device_id=s.device_id,
                expires_at=s.expires_at,
                last_accessed_at=s.last_accessed_at,
                is_active=s.is_active,
                is_revoked=s.is_revoked,
                created_at=s.created_at,
            )
            for s in sessions
        ]
    except Exception as e:
        logger.exception(f"Failed to get user sessions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a session",
    operation_id="revoke_session",
)
async def revoke_session(
    session_id: UUID,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
):
    """Revoke a specific session (cannot revoke current session)."""
    try:
        success = await service.revoke_session(session_id, current_user.user_id)

        if not success:
            raise HTTPException(status_code=404, detail="Session not found")

        logger.info(f"Session revoked: {session_id}")

        return None
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to revoke session: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke all other sessions",
    operation_id="revoke_all_other_sessions",
)
async def revoke_all_other_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_iam_service),
):
    """Revoke all sessions except current one."""
    try:
        await service.revoke_all_other_sessions(current_user.user_id, current_user.session_id)
        logger.info("All other sessions revoked")
        return None
    except Exception as e:
        logger.exception(f"Failed to revoke all other sessions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LOGIN ATTEMPTS & AUDIT
# ----------------------------------------------------------------------------


@router.get(
    "/login-attempts",
    response_model=list[LoginAttemptResponseSchema],
    summary="Get login attempts (admin)",
    operation_id="get_login_attempts",
)
async def get_login_attempts(
    username: str | None = Query(None, description="Filter by username"),
    success: bool | None = Query(None, description="Filter by success status"),
    start_date: datetime | None = Query(None, description="Start date"),
    end_date: datetime | None = Query(None, description="End date"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("iam:audit_read")),
    service: Any = Depends(get_iam_service),
) -> list[LoginAttemptResponseSchema]:
    """Get login attempts history for auditing."""
    try:
        attempts = await service.get_login_attempts(
            username=username,
            success=success,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            LoginAttemptResponseSchema(
                id=a.id,
                username=a.username,
                user_id=a.user_id,
                ip_address=a.ip_address,
                user_agent=a.user_agent,
                success=a.success,
                failure_reason=a.failure_reason,
                attempted_at=a.attempted_at,
            )
            for a in attempts
        ]
    except Exception as e:
        logger.exception(f"Failed to get login attempts: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/{user_id}/audit-log",
    response_model=list[UserAuditLogSchema],
    summary="Get user audit log",
    operation_id="get_user_audit_log",
)
async def get_user_audit_log(
    user_id: UUID,
    limit: int = Query(100, ge=1, le=1000, description="Number of records"),
    _permission: None = Depends(require_permission("iam:audit_read")),
    service: Any = Depends(get_iam_service),
) -> list[UserAuditLogSchema]:
    """Get audit log for a specific user."""
    try:
        logs = await service.get_user_audit_log(user_id, limit)

        return [
            UserAuditLogSchema(
                id=l.id,
                user_id=l.user_id,
                action=l.action,
                ip_address=l.ip_address,
                user_agent=l.user_agent,
                details=l.details,
                created_at=l.created_at,
            )
            for l in logs
        ]
    except Exception as e:
        logger.exception(f"Failed to get user audit log: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# USER STATUS & HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/users/{user_id}/status",
    response_model=dict[str, Any],
    summary="Get user status",
    operation_id="get_user_status",
)
async def get_user_status(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    """Get detailed user status."""
    try:
        status_info = await service.get_user_status(user_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "user_id": str(user_id),
            "username": status_info.username,
            "status": status_info.status,
            "is_active": status_info.is_active,
            "is_locked": status_info.is_locked,
            "is_mfa_enabled": status_info.is_mfa_enabled,
            "must_change_password": status_info.must_change_password,
            "password_expiry_days": status_info.password_expiry_days,
            "last_login_at": status_info.last_login_at.isoformat()
            if status_info.last_login_at
            else None,
            "last_activity_at": status_info.last_activity_at.isoformat()
            if status_info.last_activity_at
            else None,
            "can_login": status_info.can_login,
            "can_change_password": status_info.can_change_password,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get user status: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/{user_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get user history",
    operation_id="get_user_history",
)
async def get_user_history(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    service: Any = Depends(get_iam_service),
) -> list[dict[str, Any]]:
    """Get user change history (audit trail)."""
    try:
        history = await service.get_user_history(user_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get user history: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]