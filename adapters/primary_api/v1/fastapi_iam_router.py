#!/usr/bin/env python3
"""
Module: fastapi_iam_router.py
Layer: Adapters (Primary API - v1)
Responsibility: IAM REST API endpoints.
               Setiap endpoint memanggil service.set_context(session, legal_entity_id)
               sebelum menggunakan service.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid5, NAMESPACE_DNS

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from application.service_layer.service_iam import AuthenticationError
from domain.iam.user_entity import UserStatus
from domain.iam.permission_vo import PermissionUtils

# Import async_session_maker dari lokasi yang benar
from infrastructure.persistence_orm.database import async_session_maker

logger = logging.getLogger(__name__)

# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
    """In-memory idempotency manager dengan TTL 24 jam."""

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now(UTC))


_idempotency_manager = IdempotencyManager()


# ============================================================================
# DATABASE SESSION DEPENDENCY
# ============================================================================

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency yang menyediakan session database untuk setiap request."""
    async with async_session_maker() as session:
        yield session


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================

class RoleStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEPRECATED = "deprecated"


class MFAType(str, Enum):
    TOTP = "totp"
    SMS = "sms"
    EMAIL = "email"
    BACKUP_CODE = "backup_code"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    LOGGED_OUT = "logged_out"


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
    model_config = ConfigDict(from_attributes=True)

    username: str = Field(..., min_length=3, max_length=100)
    email: str = Field(..., max_length=200)
    full_name: str = Field(..., min_length=3, max_length=200)
    password: str = Field(..., min_length=8)
    must_change_password: bool = Field(True)
    legal_entity_ids: list[UUID] | None = None
    role_ids: list[UUID] | None = None
    department: str | None = Field(None, max_length=100)
    job_title: str | None = Field(None, max_length=100)
    phone_number: str | None = Field(None, max_length=20)
    is_superuser: bool = False
    notes: str | None = Field(None, max_length=500)

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
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(..., min_length=3, max_length=100)
    description: str | None = Field(None, max_length=500)
    parent_role_id: UUID | None = None
    is_system_role: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Role name is required")
        return v.upper()


class RoleUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    description: str | None = Field(None, max_length=500)
    status: RoleStatus | None = None
    parent_role_id: UUID | None = None


class RoleResponseSchema(BaseModel):
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
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    resource: str
    action: str
    description: str | None
    is_system: bool
    created_at: datetime


class UserRoleAssignSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_ids: list[UUID] = Field(..., min_length=1)


class RolePermissionAssignSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    permission_ids: list[UUID] = Field(..., min_length=1)


# ========================================================================
# PERUBAHAN UTAMA: legal_entity_id dijadikan WAJIB (bukan None)
# ========================================================================
class LoginRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    password: str
    mfa_code: str | None = Field(None, min_length=6, max_length=6)
    legal_entity_id: UUID = Field(..., description="Legal entity context is required")


class LoginResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponseSchema


class RefreshTokenRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    refresh_token: str


class TokenRefreshResponseSchema(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600


class ChangePasswordSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    old_password: str
    new_password: str = Field(..., min_length=8)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        if len(v) < DEFAULT_PASSWORD_MIN_LENGTH:
            raise ValueError(
                f"Password must be at least {DEFAULT_PASSWORD_MIN_LENGTH} characters"
            )
        return v


class ResetPasswordRequestSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    email: str


class ResetPasswordConfirmSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    new_password: str = Field(..., min_length=8)


class ForgotPasswordResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message: str
    reset_token: str | None = None
    reset_url: str | None = None


class MFASetupResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    secret_key: str
    qr_code_url: str
    backup_codes: list[str]
    issuer: str


class MFAVerifySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str = Field(..., min_length=6, max_length=6)


class MFADisableSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    password: str
    mfa_code: str | None = Field(None, min_length=6, max_length=6)


class SessionResponseSchema(BaseModel):
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

async def get_iam_service(request: Request) -> Any:
    """Get IAM Service instance from app.state."""
    return request.app.state.iam_service


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(tags=["IAM"])

_PERMISSION_UUID_NAMESPACE = NAMESPACE_DNS


def _permission_to_uuid(permission: str) -> UUID:
    """Permission di sistem ini disimpan sebagai string "resource:action"
    (lihat PermissionUtils.STANDARD_PERMISSIONS), bukan UUID. Endpoint
    /iam/iam/permissions dan /iam/iam/roles butuh bentuk UUID, jadi kita
    turunkan UUID yang stabil (deterministik) dari string permission-nya
    supaya konsisten antar-request/antar-endpoint."""
    return uuid5(_PERMISSION_UUID_NAMESPACE, permission)


# ----------------------------------------------------------------------------
# HEALTH CHECKS
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "iam-router"}


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/info")
def info() -> dict[str, str]:
    return {"version": "1.0", "name": "IAM Router"}


# ----------------------------------------------------------------------------
# USER MANAGEMENT
# ----------------------------------------------------------------------------

@router.post(
    "/iam/users",
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
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
        logger.exception(f"Failed to create user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/iam/users",
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
    page_size: int = Query(20, ge=1, le=500),
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[UserResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        # CATATAN PERBAIKAN: IAMService.list_users() cuma menerima
        # legal_entity_id/status/limit/offset (bukan is_active/search/role_id/
        # legal_entity_id_filter/page/page_size), dan UserEntity punya bentuk
        # yang jauh berbeda dari UserResponseSchema (mis. nama lengkap/
        # department/phone ada di dalam u.profile, timestamp ada di dalam
        # u.audit, dsb). Filter tambahan & mapping field dilakukan di sini.
        raw_users = await service.list_users(
            legal_entity_id=legal_entity_id_filter,
            status=status,
            limit=5000,
            offset=0,
        )

        def _matches(u: Any) -> bool:
            if is_active is not None:
                user_is_active = u.status == UserStatus.ACTIVE
                if user_is_active != is_active:
                    return False
            if role_id is not None and role_id not in (u.role_ids or []):
                return False
            if search:
                needle = search.lower()
                haystacks = [u.username or "", u.email or "", u.profile.full_name or ""]
                if not any(needle in h.lower() for h in haystacks):
                    return False
            return True

        filtered = [u for u in raw_users if _matches(u)]
        start = (page - 1) * page_size
        page_items = filtered[start : start + page_size]

        def _to_response(u: Any) -> UserResponseSchema:
            created_by_uuid: UUID | None
            try:
                created_by_uuid = UUID(u.audit.created_by)
            except (ValueError, TypeError, AttributeError):
                created_by_uuid = None
            return UserResponseSchema(
                id=u.user_id,
                username=u.username,
                email=u.email,
                full_name=u.profile.full_name,
                department=u.profile.department,
                job_title=u.profile.position,
                phone_number=u.profile.phone,
                status=UserStatus(u.status),
                is_active=u.status == UserStatus.ACTIVE,
                is_locked=u.locked_until is not None,
                is_superuser=False,
                must_change_password=False,
                mfa_enabled=u.mfa_enabled,
                last_login_at=u.audit.last_login_at,
                last_password_change=u.audit.last_password_change_at,
                legal_entity_ids=[u.legal_entity_id],
                role_ids=u.role_ids,
                notes=None,
                created_at=u.audit.created_at,
                updated_at=u.audit.updated_at,
                created_by=created_by_uuid,
                created_by_name=u.audit.created_by,
                version=u.audit.version,
            )

        return [_to_response(u) for u in page_items]
    except Exception as e:
        logger.exception(f"Failed to list users: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/iam/users/{user_id}",
    response_model=UserResponseSchema,
    summary="Get user by ID",
    operation_id="get_user",
)
async def get_user(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/by-username/{username}",
    response_model=UserResponseSchema,
    summary="Get user by username",
    operation_id="get_user_by_username",
)
async def get_user_by_username(
    username: str,
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/activate",
    response_model=UserResponseSchema,
    summary="Activate user",
    operation_id="activate_user",
)
async def activate_user(
    user_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/lock",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/unlock",
    response_model=UserResponseSchema,
    summary="Unlock user",
    operation_id="unlock_user",
)
async def unlock_user(
    user_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_lock")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles",
    response_model=list[RoleResponseSchema],
    summary="List roles",
    operation_id="list_roles",
)
async def list_roles(
    status: RoleStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("iam:role_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        # CATATAN PERBAIKAN: IAMService.list_roles() tidak menerima filter
        # apapun (signature aslinya cuma `list_roles(self)`), dan RoleEntity
        # punya nama field beda (role_id/role_name/permissions/is_system,
        # bukan id/name/permission_ids/is_system_role). permissions adalah
        # set[str] "resource:action", jadi di-derive jadi UUID stabil lewat
        # _permission_to_uuid() supaya konsisten dengan /iam/iam/permissions.
        # r.status adalah domain.iam.role_entity.RoleStatus (enum TERPISAH
        # dari RoleStatus lokal router ini), jadi dibandingkan/dikonversi
        # lewat .value, bukan langsung.
        raw_roles = await service.list_roles()

        def _matches(r: Any) -> bool:
            if status is not None and r.status.value != status.value:
                return False
            if is_active is not None:
                role_is_active = r.status.value == "active"
                if role_is_active != is_active:
                    return False
            return True

        roles = [r for r in raw_roles if _matches(r)]

        def _to_role_status(value: str) -> RoleStatus:
            try:
                return RoleStatus(value)
            except ValueError:
                return RoleStatus.INACTIVE

        return [
            RoleResponseSchema(
                id=r.role_id,
                name=r.role_name,
                description=r.description,
                parent_role_id=r.parent_role_id,
                parent_role_name=None,
                is_system_role=r.is_system,
                status=_to_role_status(r.status.value),
                is_active=r.status.value == "active",
                permission_ids=[_permission_to_uuid(p) for p in sorted(r.permissions)],
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=None,
                created_by_name=r.created_by,
                version=r.version,
            )
            for r in roles
        ]
    except Exception as e:
        logger.exception(f"Failed to list roles: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/iam/roles/{role_id}",
    response_model=RoleResponseSchema,
    summary="Get role by ID",
    operation_id="get_role",
)
async def get_role(
    role_id: UUID,
    _permission: None = Depends(require_permission("iam:role_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles/{role_id}",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> RoleResponseSchema:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles/{role_id}",
    response_model=dict[str, Any],
    summary="Delete role",
    operation_id="delete_role",
)
async def delete_role(
    role_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/roles",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    service.set_context(session, legal_entity_id)

    method_name = "assign_roles_to_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
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
    "/iam/users/{user_id}/roles",
    response_model=list[RoleResponseSchema],
    summary="Get user roles",
    operation_id="get_user_roles",
)
async def get_user_roles(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:role_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/roles/{role_id}",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

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
    "/iam/permissions",
    response_model=list[PermissionResponseSchema],
    summary="List all permissions",
    operation_id="list_permissions",
)
async def list_permissions(
    resource: str | None = Query(None, description="Filter by resource"),
    _permission: None = Depends(require_permission("iam:permission_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        # CATATAN PERBAIKAN: IAMService tidak punya method list_permissions()
        # sama sekali (belum diimplementasikan). Katalog permission yang
        # benar-benar ada di sistem ini adalah
        # PermissionUtils.STANDARD_PERMISSIONS (domain/iam/permission_vo.py),
        # daftar string statis berformat "resource:action". Kita pakai itu
        # sebagai sumber data, dengan id UUID stabil (deterministik) via
        # _permission_to_uuid().
        all_permissions = sorted(PermissionUtils.STANDARD_PERMISSIONS)

        def _to_schema(perm: str) -> PermissionResponseSchema:
            res, _, action = perm.partition(":")
            return PermissionResponseSchema(
                id=_permission_to_uuid(perm),
                name=perm,
                resource=res,
                action=action,
                description=None,
                is_system=True,
                created_at=datetime.now(UTC),
            )

        return [
            _to_schema(perm)
            for perm in all_permissions
            if resource is None or perm.split(":", 1)[0] == resource
        ]
    except Exception as e:
        logger.exception(f"Failed to list permissions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/iam/roles/{role_id}/permissions",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles/{role_id}/permissions",
    response_model=list[PermissionResponseSchema],
    summary="Get role permissions",
    operation_id="get_role_permissions",
)
async def get_role_permissions(
    role_id: UUID,
    _permission: None = Depends(require_permission("iam:permission_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    service.set_context(session, legal_entity_id)

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
    "/iam/roles/{role_id}/permissions/{permission_id}",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

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
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> LoginResponseSchema:
    service.set_context(session, request.legal_entity_id)

    try:
        result = await service.login(
            username=request.username,
            password=request.password,
            mfa_code=request.mfa_code,
            legal_entity_id=request.legal_entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        logger.info("User logged in successfully")

        return LoginResponseSchema(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            expires_in=result.expires_in,
            user=UserResponseSchema(
                id=result.user.user_id,
                username=result.user.username,
                email=result.user.email,
                full_name=result.user.profile.full_name,
                department=result.user.profile.department,
                job_title=result.user.profile.position,
                phone_number=result.user.profile.phone,
                status=result.user.status,
                is_active=result.user.status == UserStatus.ACTIVE,
                is_locked=result.user.status == UserStatus.LOCKED,
                is_superuser=bool(result.user.role_ids) and any(str(role_id).endswith("-0000-0000-0000-000000000001") for role_id in result.user.role_ids),
                must_change_password=result.user.password_hash.requires_rehash() if hasattr(result.user.password_hash, 'requires_rehash') else False,
                mfa_enabled=result.user.mfa_enabled,
                last_login_at=result.user.audit.last_login_at,
                last_password_change=result.user.audit.last_password_change_at,
                legal_entity_ids=[result.user.legal_entity_id] if result.user.legal_entity_id else [],
                role_ids=result.user.role_ids,
                notes=None,
                created_at=result.user.audit.created_at,
                updated_at=result.user.audit.updated_at,
                created_by=None,
                created_by_name=None,
                version=result.user.audit.version,
            ),
        )
    except AuthenticationError as e:
        logger.warning(f"Login failed: AuthenticationError - {e!s}")
        raise HTTPException(status_code=401, detail="Invalid username or password")
    except ValueError as e:
        logger.exception(f"Login failed: invalid input - {e!s}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Login failed: Unexpected error - {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="User logout",
    operation_id="logout",
)
async def logout(
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
):
    service.set_context(session, legal_entity_id)

    try:
        await service.logout(current_user.user_id, current_user.session_id)
        logger.info("User logged out")
    except Exception as e:
        logger.exception(f"Logout failed: {type(e).__name__}")
    return None


@router.post(
    "/refresh",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh access token",
    operation_id="refresh_token",
)
async def refresh_token(
    request: RefreshTokenRequestSchema,
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> TokenRefreshResponseSchema:
    service.set_context(session, legal_entity_id)

    try:
        new_access_token = await service.refresh_access_token(request.refresh_token)

        logger.info("Session refreshed successfully")

        return TokenRefreshResponseSchema(
            access_token=new_access_token,
            refresh_token=request.refresh_token,
        )
    except ValueError as e:
        logger.warning("Session refresh failed: invalid refresh credential")
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
):
    service.set_context(session, legal_entity_id)

    try:
        success = await service.change_password(
            user_id=current_user.user_id,
            old_password=request.old_password,
            new_password=request.new_password,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Old password incorrect")

        logger.info(f"Credential updated for user: {current_user.user_id}")
        return None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> ForgotPasswordResponseSchema:
    service.set_context(session, legal_entity_id)

    try:
        result = await service.forgot_password(email=request.email)

        logger.info("Reset request submitted")

        return ForgotPasswordResponseSchema(
            message=result.message,
            reset_token=result.reset_token,
            reset_url=result.reset_url,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, str]:
    service.set_context(session, legal_entity_id)

    try:
        success = await service.reset_password(
            token=request.token,
            new_password=request.new_password,
        )

        if not success:
            raise HTTPException(status_code=400, detail="Invalid or expired token")

        logger.info("Reset completed successfully")
        return {"message": "Password reset successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> MFASetupResponseSchema:
    service.set_context(session, legal_entity_id)

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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, bool]:
    service.set_context(session, legal_entity_id)

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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, bool]:
    service.set_context(session, legal_entity_id)

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
    "/iam/sessions",
    response_model=list[SessionResponseSchema],
    summary="Get user sessions",
    operation_id="get_user_sessions",
)
async def get_user_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[SessionResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        # CATATAN PERBAIKAN: IAMService tidak punya method get_user_sessions(),
        # dan setelah ditelusuri, backend ini memang belum punya penyimpanan
        # riwayat sesi login sama sekali (nggak ada tabel/repo session).
        # Ini bukan bug wiring, tapi fitur yang belum dibangun. Supaya
        # frontend nggak 500, endpoint ini balikin list kosong dulu sampai
        # session tracking benar-benar diimplementasikan di backend.
        logger.warning(
            "get_user_sessions dipanggil tapi IAMService belum punya "
            "penyimpanan sesi login — balikin list kosong (fitur belum "
            "diimplementasikan)."
        )
        return []
    except Exception as e:
        logger.exception(f"Failed to get user sessions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/iam/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a session",
    operation_id="revoke_session",
)
async def revoke_session(
    session_id: UUID,
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
):
    service.set_context(session, legal_entity_id)

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
    "/iam/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke all other sessions",
    operation_id="revoke_all_other_sessions",
)
async def revoke_all_other_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
):
    service.set_context(session, legal_entity_id)

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
    "/iam/login-attempts",
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[LoginAttemptResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        # CATATAN PERBAIKAN: IAMService tidak punya method get_login_attempts(),
        # dan backend ini belum punya penyimpanan riwayat percobaan login
        # (cuma ada counter failed_login_attempts per user, bukan log detail
        # per percobaan). Ini fitur yang belum dibangun, bukan bug wiring.
        # Supaya frontend nggak 500, endpoint ini balikin list kosong dulu
        # sampai audit log login benar-benar diimplementasikan di backend.
        logger.warning(
            "get_login_attempts dipanggil tapi IAMService belum punya "
            "penyimpanan riwayat percobaan login — balikin list kosong "
            "(fitur belum diimplementasikan)."
        )
        return []
    except Exception as e:
        logger.exception(f"Failed to get login attempts: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/iam/users/{user_id}/audit-log",
    response_model=list[UserAuditLogSchema],
    summary="Get user audit log",
    operation_id="get_user_audit_log",
)
async def get_user_audit_log(
    user_id: UUID,
    limit: int = Query(100, ge=1, le=1000, description="Number of records"),
    _permission: None = Depends(require_permission("iam:audit_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[UserAuditLogSchema]:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/status",
    response_model=dict[str, Any],
    summary="Get user status",
    operation_id="get_user_status",
)
async def get_user_status(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

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
    "/iam/users/{user_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get user history",
    operation_id="get_user_history",
)
async def get_user_history(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: Any = Depends(get_iam_service),
) -> list[dict[str, Any]]:
    service.set_context(session, legal_entity_id)

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


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["router"]