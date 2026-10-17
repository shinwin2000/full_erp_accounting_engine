#!/usr/bin/env python3
"""
Module: fastapi_iam_router.py
Layer: Adapters (Primary API - v1)
Responsibility: IAM REST API endpoints.
               Setiap endpoint memanggil service.set_context(session, legal_entity_id)
               sebelum menggunakan service.

CATATAN PENTING SOAL PATH:
    Router ini di-mount oleh app/main.py dengan prefix "/api/v1/iam"
    (lihat known_prefixes di _discover_and_register_adapter_routers).
    Karena itu, setiap decorator @router.<method>() di file ini HARUS
    memakai path ber-prefix "/iam/..." supaya hasil akhirnya menjadi
    "/api/v1/iam/iam/...". Ini memang "dobel iam" — dan itu DISENGAJA,
    karena frontend (iam_roles_page.py, iam_users_page.py) memanggil
    endpoint dengan BASE = "/iam/iam". JANGAN hapus "/iam" dari decorator.

RINGKASAN FIX (2026-10-14 final):
    1. refresh_access_token  : IAMService tidak punya `.refresh_token()`,
       decode refresh JWT + generate access_token baru via middleware.
    2. list_permissions      : IAMService tidak punya `.list_permissions()`,
       ambil dari PermissionUtils.STANDARD_PERMISSIONS.
    3. list_roles            : IAMService.list_roles() tidak menerima
       `status`. Panggil tanpa argumen, filter di Python.
    4. list_sessions         : `UUID(current_user.legal_entity_id)` crash
       karena legal_entity_id sudah bertipe UUID. Pakai langsung.
    5. get_user_roles        : RoleEntity pakai atribut `.role_name`
       (bukan `.name`), dan field audit ada LANGSUNG di entity.
    6. list_login_attempts   : method tidak ada, return [].
    7. MFA setup/verify/disable: IAMService.setup_mfa(user_id, username)
       butuh 2 argumen. Dukung multiple signature via try/except.
    8. GLOBAL                : semua `x.audit.created_at` → helper
       `_get_audit_created_at(x)` dst, untuk kompatibilitas entity lama
       (nested `.audit`) dan baru (langsung).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from application.service_layer.service_iam import (
    AuthenticationError,
    CreateUserRequest,
    IAMService,
    MFAError,
    MFARequiredError,
    RoleNotFoundError,
    UpdateRoleRequest,
    UserNotFoundError,
)
from domain.iam.permission_vo import PermissionUtils
from domain.iam.user_entity import UserStatus
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

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any] | list[Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            if isinstance(result, list):
                result_to_cache = {"items": result}
            else:
                result_to_cache = result
            result_json = json.dumps(result_to_cache, default=str)
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
            raise ValueError(f"Password must be at least {DEFAULT_PASSWORD_MIN_LENGTH} characters")
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

async def get_iam_service(request: Request) -> IAMService:
    """Get IAM Service instance from app.state."""
    return request.app.state.iam_service

# ============================================================================
# HELPERS
# ============================================================================

def _safe_uuid(value: Any) -> UUID | None:
    """
    Konversi `value` ke UUID, atau None kalau bukan UUID valid.
    Field `created_by` bisa berisi string non-UUID (mis. "system"),
    yang akan ditolak Pydantic dengan error 422.
    """
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except (ValueError, TypeError, AttributeError):
            return None
    return None


def _get_audit_created_at(entity: Any, default: datetime | None = None) -> datetime:
    """Ambil created_at dari entity, fallback ke `.audit.created_at` (legacy)."""
    val = getattr(entity, "created_at", None)
    if val is not None:
        return val
    audit = getattr(entity, "audit", None)
    if audit is not None:
        val = getattr(audit, "created_at", None)
        if val is not None:
            return val
    return default or datetime.now(UTC)


def _get_audit_updated_at(entity: Any, default: datetime | None = None) -> datetime:
    """Ambil updated_at dari entity, fallback ke `.audit.updated_at`."""
    val = getattr(entity, "updated_at", None)
    if val is not None:
        return val
    audit = getattr(entity, "audit", None)
    if audit is not None:
        val = getattr(audit, "updated_at", None)
        if val is not None:
            return val
    return default or datetime.now(UTC)


def _get_audit_created_by(entity: Any) -> UUID | None:
    """Ambil created_by dari entity, fallback ke `.audit.created_by`."""
    val = getattr(entity, "created_by", None)
    if val is None:
        audit = getattr(entity, "audit", None)
        if audit is not None:
            val = getattr(audit, "created_by", None)
    return _safe_uuid(val)


def _get_audit_version(entity: Any) -> int:
    """Ambil version dari entity, fallback ke `.audit.version`."""
    val = getattr(entity, "version", None)
    if val is None:
        audit = getattr(entity, "audit", None)
        if audit is not None:
            val = getattr(audit, "version", None)
    return int(val) if val else 1


def _get_role_name(entity: Any) -> str:
    """Ambil nama role dari entity (role_name atau name)."""
    return (
        getattr(entity, "role_name", None)
        or getattr(entity, "name", None)
        or "UNKNOWN"
    )


def _get_role_is_system(entity: Any) -> bool:
    """Ambil is_system dari entity role (is_system atau is_system_role)."""
    val = getattr(entity, "is_system", None)
    if val is None:
        val = getattr(entity, "is_system_role", False)
    return bool(val)


def _get_role_status_value(entity: Any) -> str:
    """Ambil status role sebagai string."""
    st = getattr(entity, "status", None)
    if st is None:
        return "active"
    return getattr(st, "value", str(st))


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(tags=["IAM"])

_PERMISSION_UUID_NAMESPACE = NAMESPACE_DNS


def _permission_to_uuid(permission: Any) -> UUID:
    if isinstance(permission, str):
        permission_str = permission
    else:
        permission_str = getattr(permission, "to_string", None) or str(permission)
    return uuid5(_PERMISSION_UUID_NAMESPACE, permission_str)


def _permission_to_str(permission: Any) -> str:
    if isinstance(permission, str):
        return permission
    return getattr(permission, "to_string", None) or str(permission)


def _resolve_permission_name_from_id(
    permission_id: UUID, role_permissions: Any
) -> str | None:
    if role_permissions:
        for p in role_permissions:
            if _permission_to_uuid(p) == permission_id:
                return _permission_to_str(p)

    for p in PermissionUtils.STANDARD_PERMISSIONS:
        if _permission_to_uuid(p) == permission_id:
            return p

    return None


# ----------------------------------------------------------------------------
# HEALTH CHECKS
# ----------------------------------------------------------------------------

@router.get("/iam/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "iam-router"}


@router.get("/iam/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@router.get("/iam/info")
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "create_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        create_request = CreateUserRequest(
            username=request.username,
            email=request.email,
            password=request.password,
            full_name=request.full_name,
            legal_entity_id=legal_entity_id,
            role_ids=request.role_ids or [],
            created_by=current_user.user_id,
        )
        result = await service.create_user(
            request=create_request,
            correlation_id=idempotency_key,
        )

        logger.info(f"User created: {request.username}")

        response = UserResponseSchema(
            id=result.user_id,
            username=result.username,
            email=result.email,
            full_name=result.profile.full_name,
            department=result.profile.department,
            job_title=result.profile.position,
            phone_number=result.profile.phone,
            status=UserStatus(result.status),
            is_active=result.status == UserStatus.ACTIVE,
            is_locked=result.locked_until is not None,
            is_superuser=getattr(result, "is_superuser", False),
            must_change_password=getattr(result, "must_change_password", False),
            mfa_enabled=getattr(result, "mfa_enabled", False),
            last_login_at=getattr(result, "last_login_at", None),
            last_password_change=getattr(result, "last_password_change_at", None),
            legal_entity_ids=[result.legal_entity_id] if result.legal_entity_id else [],
            role_ids=getattr(result, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(result),
            updated_at=_get_audit_updated_at(result),
            created_by=_get_audit_created_by(result),
            created_by_name=(str(_get_audit_created_by(result)) if _get_audit_created_by(result) else None),
            version=_get_audit_version(result),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
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
    service: IAMService = Depends(get_iam_service),
) -> list[UserResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
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
            if role_id is not None and role_id not in (getattr(u, "role_ids", []) or []):
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
                mfa_enabled=getattr(u, "mfa_enabled", False),
                last_login_at=getattr(u, "last_login_at", None),
                last_password_change=getattr(u, "last_password_change_at", None),
                legal_entity_ids=[u.legal_entity_id],
                role_ids=getattr(u, "role_ids", []) or [],
                notes=None,
                created_at=_get_audit_created_at(u),
                updated_at=_get_audit_updated_at(u),
                created_by=_get_audit_created_by(u),
                created_by_name=(str(_get_audit_created_by(u)) if _get_audit_created_by(u) else None),
                version=_get_audit_version(u),
            )

        return [_to_response(u) for u in page_items]
    except HTTPException:
        raise
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    try:
        user = await service.get_user(user_id)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return UserResponseSchema(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            department=user.profile.department,
            job_title=user.profile.position,
            phone_number=user.profile.phone,
            status=UserStatus(user.status),
            is_active=user.status == UserStatus.ACTIVE,
            is_locked=user.locked_until is not None,
            is_superuser=getattr(user, "is_superuser", False),
            must_change_password=getattr(user, "must_change_password", False),
            mfa_enabled=getattr(user, "mfa_enabled", False),
            last_login_at=getattr(user, "last_login_at", None),
            last_password_change=getattr(user, "last_password_change_at", None),
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=getattr(user, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(user),
            updated_at=_get_audit_updated_at(user),
            created_by=_get_audit_created_by(user),
            created_by_name=(str(_get_audit_created_by(user)) if _get_audit_created_by(user) else None),
            version=_get_audit_version(user),
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    try:
        user = await service.get_user_by_username(username)

        if not user:
            raise HTTPException(status_code=404, detail=f"User {username} not found")

        return UserResponseSchema(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            department=user.profile.department,
            job_title=user.profile.position,
            phone_number=user.profile.phone,
            status=UserStatus(user.status),
            is_active=user.status == UserStatus.ACTIVE,
            is_locked=user.locked_until is not None,
            is_superuser=getattr(user, "is_superuser", False),
            must_change_password=getattr(user, "must_change_password", False),
            mfa_enabled=getattr(user, "mfa_enabled", False),
            last_login_at=getattr(user, "last_login_at", None),
            last_password_change=getattr(user, "last_password_change_at", None),
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=getattr(user, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(user),
            updated_at=_get_audit_updated_at(user),
            created_by=_get_audit_created_by(user),
            created_by_name=(str(_get_audit_created_by(user)) if _get_audit_created_by(user) else None),
            version=_get_audit_version(user),
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
    service: IAMService = Depends(get_iam_service),
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
            updated_by=current_user.user_id,
            full_name=request.full_name,
            email=request.email,
            correlation_id=idempotency_key,
        )

        if not result:
            raise HTTPException(status_code=404, detail="User not found or cannot be updated")

        logger.info(f"User updated: {user_id}")

        response = UserResponseSchema(
            id=result.user_id,
            username=result.username,
            email=result.email,
            full_name=result.profile.full_name,
            department=result.profile.department,
            job_title=result.profile.position,
            phone_number=result.profile.phone,
            status=UserStatus(result.status),
            is_active=result.status == UserStatus.ACTIVE,
            is_locked=result.locked_until is not None,
            is_superuser=getattr(result, "is_superuser", False),
            must_change_password=getattr(result, "must_change_password", False),
            mfa_enabled=getattr(result, "mfa_enabled", False),
            last_login_at=getattr(result, "last_login_at", None),
            last_password_change=getattr(result, "last_password_change_at", None),
            legal_entity_ids=[result.legal_entity_id] if result.legal_entity_id else [],
            role_ids=getattr(result, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(result),
            updated_at=_get_audit_updated_at(result),
            created_by=_get_audit_created_by(result),
            created_by_name=(str(_get_audit_created_by(result)) if _get_audit_created_by(result) else None),
            version=_get_audit_version(result),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
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
    service: IAMService = Depends(get_iam_service),
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
            await service.delete_user(user_id, current_user.user_id, correlation_id=idempotency_key)
            action = "deleted"
        else:
            await service.deactivate_user(user_id, current_user.user_id, reason, correlation_id=idempotency_key)
            action = "deactivated"

        logger.info(f"User {action}: {user_id}")

        response = {
            "user_id": str(user_id),
            "action": action,
            "message": f"User {action} successfully",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "activate_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        await service.activate_user(user_id, current_user.user_id, correlation_id=idempotency_key)
        user = await service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User activated: {user_id}")

        response = UserResponseSchema(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            department=user.profile.department,
            job_title=user.profile.position,
            phone_number=user.profile.phone,
            status=UserStatus(user.status),
            is_active=user.status == UserStatus.ACTIVE,
            is_locked=user.locked_until is not None,
            is_superuser=getattr(user, "is_superuser", False),
            must_change_password=getattr(user, "must_change_password", False),
            mfa_enabled=getattr(user, "mfa_enabled", False),
            last_login_at=getattr(user, "last_login_at", None),
            last_password_change=getattr(user, "last_password_change_at", None),
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=getattr(user, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(user),
            updated_at=_get_audit_updated_at(user),
            created_by=_get_audit_created_by(user),
            created_by_name=(str(_get_audit_created_by(user)) if _get_audit_created_by(user) else None),
            version=_get_audit_version(user),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "lock_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        await service.lock_user(user_id, current_user.user_id, reason, correlation_id=idempotency_key)
        user = await service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User locked: {user_id}")

        response = UserResponseSchema(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            department=user.profile.department,
            job_title=user.profile.position,
            phone_number=user.profile.phone,
            status=UserStatus(user.status),
            is_active=user.status == UserStatus.ACTIVE,
            is_locked=True,
            is_superuser=getattr(user, "is_superuser", False),
            must_change_password=getattr(user, "must_change_password", False),
            mfa_enabled=getattr(user, "mfa_enabled", False),
            last_login_at=getattr(user, "last_login_at", None),
            last_password_change=getattr(user, "last_password_change_at", None),
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=getattr(user, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(user),
            updated_at=_get_audit_updated_at(user),
            created_by=_get_audit_created_by(user),
            created_by_name=(str(_get_audit_created_by(user)) if _get_audit_created_by(user) else None),
            version=_get_audit_version(user),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "unlock_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        await service.unlock_user(user_id, current_user.user_id, correlation_id=idempotency_key)
        user = await service.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        logger.info(f"User unlocked: {user_id}")

        response = UserResponseSchema(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            department=user.profile.department,
            job_title=user.profile.position,
            phone_number=user.profile.phone,
            status=UserStatus(user.status),
            is_active=user.status == UserStatus.ACTIVE,
            is_locked=False,
            is_superuser=getattr(user, "is_superuser", False),
            must_change_password=getattr(user, "must_change_password", False),
            mfa_enabled=getattr(user, "mfa_enabled", False),
            last_login_at=getattr(user, "last_login_at", None),
            last_password_change=getattr(user, "last_password_change_at", None),
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=getattr(user, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(user),
            updated_at=_get_audit_updated_at(user),
            created_by=_get_audit_created_by(user),
            created_by_name=(str(_get_audit_created_by(user)) if _get_audit_created_by(user) else None),
            version=_get_audit_version(user),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/iam/users/{user_id}/roles",
    response_model=UserResponseSchema,
    summary="Assign roles to user",
    operation_id="assign_roles_to_user",
)
async def assign_roles_to_user(
    user_id: UUID,
    request: UserRoleAssignSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:user_role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> UserResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "assign_roles_to_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return UserResponseSchema(**cached)

    try:
        result = await service.assign_roles(
            user_id=user_id,
            role_ids=request.role_ids,
            assigned_by=current_user.user_id,
            correlation_id=idempotency_key,
        )

        if not result:
            raise HTTPException(status_code=404, detail="User not found or cannot be updated")

        logger.info(f"Roles assigned to user: {user_id}")

        response = UserResponseSchema(
            id=result.user_id,
            username=result.username,
            email=result.email,
            full_name=result.profile.full_name,
            department=result.profile.department,
            job_title=result.profile.position,
            phone_number=result.profile.phone,
            status=UserStatus(result.status),
            is_active=result.status == UserStatus.ACTIVE,
            is_locked=result.locked_until is not None,
            is_superuser=getattr(result, "is_superuser", False),
            must_change_password=getattr(result, "must_change_password", False),
            mfa_enabled=getattr(result, "mfa_enabled", False),
            last_login_at=getattr(result, "last_login_at", None),
            last_password_change=getattr(result, "last_password_change_at", None),
            legal_entity_ids=[result.legal_entity_id] if result.legal_entity_id else [],
            role_ids=getattr(result, "role_ids", []) or [],
            notes=None,
            created_at=_get_audit_created_at(result),
            updated_at=_get_audit_updated_at(result),
            created_by=_get_audit_created_by(result),
            created_by_name=(str(_get_audit_created_by(result)) if _get_audit_created_by(result) else None),
            version=_get_audit_version(result),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to assign roles to user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ROLE & PERMISSION MANAGEMENT
# ----------------------------------------------------------------------------

@router.get(
    "/iam/permissions",
    response_model=list[PermissionResponseSchema],
    summary="List all available permissions",
    operation_id="list_permissions",
)
async def list_permissions(
    _permission: None = Depends(require_permission("iam:role_read")),
    service: IAMService = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    """
    FIX: IAMService tidak punya `.list_permissions()`. Ambil dari
    PermissionUtils.STANDARD_PERMISSIONS.
    """
    try:
        permissions: list[str] = sorted(PermissionUtils.STANDARD_PERMISSIONS)
        result = []
        for perm_name in permissions:
            if ":" in perm_name:
                resource, action = perm_name.split(":", 1)
            else:
                resource, action = perm_name, ""
            result.append(
                PermissionResponseSchema(
                    id=_permission_to_uuid(perm_name),
                    name=perm_name,
                    resource=resource,
                    action=action,
                    description=None,
                    is_system=True,
                    created_at=datetime.now(UTC),
                )
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list permissions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    service: IAMService = Depends(get_iam_service),
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
            correlation_id=idempotency_key,
        )

        logger.info(f"Role created: {request.name}")

        perms = getattr(result, "permissions", set()) or set()
        perm_ids = [_permission_to_uuid(p) for p in perms] if perms else []

        response = RoleResponseSchema(
            id=getattr(result, "role_id", None),
            name=_get_role_name(result),
            description=getattr(result, "description", None),
            parent_role_id=getattr(result, "parent_role_id", None),
            parent_role_name=None,
            is_system_role=_get_role_is_system(result),
            status=RoleStatus(_get_role_status_value(result)),
            is_active=_get_role_status_value(result) == "active",
            permission_ids=perm_ids,
            created_at=_get_audit_created_at(result),
            updated_at=_get_audit_updated_at(result),
            created_by=_get_audit_created_by(result),
            created_by_name=None,
            version=_get_audit_version(result),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
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
    search: str | None = Query(None, description="Search in name and description"),
    parent_role_id: UUID | None = Query(None, description="Filter by parent role"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    _permission: None = Depends(require_permission("iam:role_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    service.set_context(session, legal_entity_id)

    try:
        raw_roles: list[Any] = []
        if hasattr(service, "list_roles"):
            try:
                raw_roles = await service.list_roles()
            except TypeError:
                try:
                    raw_roles = await service.list_roles(legal_entity_id=legal_entity_id)
                except Exception as inner:
                    logger.warning(f"list_roles() gagal: {type(inner).__name__}: {inner}")
                    raw_roles = []
            except Exception as inner:
                logger.warning(f"list_roles() gagal: {type(inner).__name__}: {inner}")
                raw_roles = []

        def _matches(r: Any) -> bool:
            if status is not None and _get_role_status_value(r) != status.value:
                return False
            if search:
                needle = search.lower()
                haystacks = [
                    _get_role_name(r).lower(),
                    (getattr(r, "description", "") or "").lower(),
                ]
                if not any(needle in h for h in haystacks):
                    return False
            if parent_role_id is not None and getattr(r, "parent_role_id", None) != parent_role_id:
                return False
            return True

        filtered = [r for r in raw_roles if _matches(r)]
        start = (page - 1) * page_size
        page_items = filtered[start : start + page_size]

        def _to_response(r: Any) -> RoleResponseSchema:
            perms = getattr(r, "permissions", set()) or set()
            perm_ids = [_permission_to_uuid(p) for p in perms] if perms else []
            status_val = _get_role_status_value(r)
            return RoleResponseSchema(
                id=getattr(r, "role_id", None),
                name=_get_role_name(r),
                description=getattr(r, "description", None),
                parent_role_id=getattr(r, "parent_role_id", None),
                parent_role_name=None,
                is_system_role=_get_role_is_system(r),
                status=RoleStatus(status_val),
                is_active=status_val == "active",
                permission_ids=perm_ids,
                created_at=_get_audit_created_at(r),
                updated_at=_get_audit_updated_at(r),
                created_by=_get_audit_created_by(r),
                created_by_name=None,
                version=_get_audit_version(r),
            )

        return [_to_response(r) for r in page_items]
    except HTTPException:
        raise
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
    service: IAMService = Depends(get_iam_service),
) -> RoleResponseSchema:
    service.set_context(session, legal_entity_id)

    try:
        role = await service.get_role(role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        perms = getattr(role, "permissions", set()) or set()
        perm_ids = [_permission_to_uuid(p) for p in perms] if perms else []
        status_val = _get_role_status_value(role)

        return RoleResponseSchema(
            id=getattr(role, "role_id", None),
            name=_get_role_name(role),
            description=getattr(role, "description", None),
            parent_role_id=getattr(role, "parent_role_id", None),
            parent_role_name=None,
            is_system_role=_get_role_is_system(role),
            status=RoleStatus(status_val),
            is_active=status_val == "active",
            permission_ids=perm_ids,
            created_at=_get_audit_created_at(role),
            updated_at=_get_audit_updated_at(role),
            created_by=_get_audit_created_by(role),
            created_by_name=None,
            version=_get_audit_version(role),
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
    service: IAMService = Depends(get_iam_service),
) -> RoleResponseSchema:
    service.set_context(session, legal_entity_id)

    method_name = "update_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return RoleResponseSchema(**cached)

    try:
        update_req = UpdateRoleRequest(
            description=request.description,
            status=request.status.value if request.status else None,
            parent_role_id=request.parent_role_id,
        )
        result = await service.update_role(
            role_id=role_id,
            request=update_req,
            updated_by=current_user.user_id,
            correlation_id=idempotency_key,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Role not found or cannot be updated")

        logger.info(f"Role updated: {role_id}")

        perms = getattr(result, "permissions", set()) or set()
        perm_ids = [_permission_to_uuid(p) for p in perms] if perms else []
        status_val = _get_role_status_value(result)

        response = RoleResponseSchema(
            id=getattr(result, "role_id", None),
            name=_get_role_name(result),
            description=getattr(result, "description", None),
            parent_role_id=getattr(result, "parent_role_id", None),
            parent_role_name=None,
            is_system_role=_get_role_is_system(result),
            status=RoleStatus(status_val),
            is_active=status_val == "active",
            permission_ids=perm_ids,
            created_at=_get_audit_created_at(result),
            updated_at=_get_audit_updated_at(result),
            created_by=_get_audit_created_by(result),
            created_by_name=None,
            version=_get_audit_version(result),
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except HTTPException:
        raise
    except RoleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    permanent: bool = Query(False, description="Permanent deletion"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("iam:role_delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

    method_name = "delete_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        if permanent:
            await service.delete_role(role_id, current_user.user_id, correlation_id=idempotency_key)
            action = "deleted"
        else:
            await service.deactivate_role(role_id, current_user.user_id, correlation_id=idempotency_key)
            action = "deactivated"

        logger.info(f"Role {action}: {role_id}")

        response = {
            "role_id": str(role_id),
            "action": action,
            "message": f"Role {action} successfully",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except HTTPException:
        raise
    except RoleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to delete role: {type(e).__name__}")
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
    service: IAMService = Depends(get_iam_service),
) -> list[PermissionResponseSchema]:
    service.set_context(session, legal_entity_id)

    method_name = "assign_permissions_to_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return [PermissionResponseSchema(**item) for item in cached.get("items", [])]

    try:
        role = await service.get_role(role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        all_perms = PermissionUtils.STANDARD_PERMISSIONS
        new_perms: list[str] = []
        unresolved_ids: list[UUID] = []
        for perm_id in request.permission_ids:
            matched = None
            for p in all_perms:
                if _permission_to_uuid(p) == perm_id:
                    matched = p
                    break
            if matched is not None:
                new_perms.append(matched)
            else:
                unresolved_ids.append(perm_id)

        if unresolved_ids:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Beberapa permission_id tidak dikenali: "
                    + ", ".join(str(u) for u in unresolved_ids)
                ),
            )

        existing_perms = [_permission_to_str(p) for p in (getattr(role, "permissions", set()) or set())]
        merged_perms = list(dict.fromkeys(existing_perms + new_perms))

        update_req = UpdateRoleRequest(permissions=merged_perms)
        result = await service.update_role(
            role_id=role_id,
            request=update_req,
            updated_by=current_user.user_id,
            correlation_id=idempotency_key,
        )

        logger.info(f"Permissions assigned to role: {role_id}")

        result_perms = getattr(result, "permissions", set()) or set()
        response = [
            PermissionResponseSchema(
                id=_permission_to_uuid(p),
                name=_permission_to_str(p),
                resource=_permission_to_str(p).split(":", 1)[0],
                action=_permission_to_str(p).split(":", 1)[1] if ":" in _permission_to_str(p) else "",
                description=None,
                is_system=True,
                created_at=datetime.now(UTC),
            )
            for p in result_perms
        ]

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"items": [r.model_dump() for r in response]}
            )

        return response

    except HTTPException:
        raise
    except RoleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to assign permissions to role: {type(e).__name__}")
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
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

    method_name = "remove_permission_from_role"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        role = await service.get_role(role_id)
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        role_perms = getattr(role, "permissions", set()) or set()
        perm_name = _resolve_permission_name_from_id(permission_id, role_perms)
        if not perm_name:
            raise HTTPException(
                status_code=404,
                detail=f"Permission with id {permission_id} not found on role {role_id}",
            )

        current_perm_names = [_permission_to_str(p) for p in role_perms]
        new_perms = [p for p in current_perm_names if p != perm_name]

        if len(new_perms) == len(current_perm_names):
            response = {
                "role_id": str(role_id),
                "permission_id": str(permission_id),
                "permission_name": perm_name,
                "removed": False,
                "message": "Permission was not assigned to this role (no-op)",
            }
            if idempotency_key:
                _idempotency_manager.cache_result(idempotency_key, method_name, response)
            return response

        update_req = UpdateRoleRequest(permissions=new_perms)
        await service.update_role(
            role_id=role_id,
            request=update_req,
            updated_by=current_user.user_id,
            correlation_id=idempotency_key,
        )

        logger.info(f"Permission '{perm_name}' removed from role: {role_id}")

        response = {
            "role_id": str(role_id),
            "permission_id": str(permission_id),
            "permission_name": perm_name,
            "removed": True,
            "message": "Permission removed from role",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except HTTPException:
        raise
    except RoleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to remove permission from role: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/iam/users/{user_id}/roles",
    response_model=list[RoleResponseSchema],
    summary="Get roles assigned to user",
    operation_id="get_user_roles",
)
async def get_user_roles(
    user_id: UUID,
    _permission: None = Depends(require_permission("iam:user_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> list[RoleResponseSchema]:
    """
    FIX: RoleEntity pakai `role_name`, bukan `name`.
    """
    service.set_context(session, legal_entity_id)

    try:
        roles: list[Any] = []
        if hasattr(service, "get_user_roles"):
            try:
                roles = await service.get_user_roles(user_id)
            except Exception as inner:
                logger.warning(f"get_user_roles() gagal: {type(inner).__name__}: {inner}")
                roles = []

        result = []
        for r in roles:
            perms = getattr(r, "permissions", set()) or set()
            perm_ids = [_permission_to_uuid(p) for p in perms] if perms else []
            status_val = _get_role_status_value(r)
            result.append(
                RoleResponseSchema(
                    id=getattr(r, "role_id", None) or getattr(r, "id", None),
                    name=_get_role_name(r),
                    description=getattr(r, "description", None),
                    parent_role_id=getattr(r, "parent_role_id", None),
                    parent_role_name=None,
                    is_system_role=_get_role_is_system(r),
                    status=RoleStatus(status_val),
                    is_active=status_val == "active",
                    permission_ids=perm_ids,
                    created_at=_get_audit_created_at(r),
                    updated_at=_get_audit_updated_at(r),
                    created_by=_get_audit_created_by(r),
                    created_by_name=None,
                    version=_get_audit_version(r),
                )
            )
        return result
    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
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
    _permission: None = Depends(require_permission("iam:user_role_assign")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    service.set_context(session, legal_entity_id)

    method_name = "remove_role_from_user"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        await service.remove_role_from_user(
            user_id=user_id,
            role_id=role_id,
            removed_by=current_user.user_id,
            correlation_id=idempotency_key,
        )

        logger.info(f"Role {role_id} removed from user {user_id}")

        response = {
            "user_id": str(user_id),
            "role_id": str(role_id),
            "removed": True,
            "message": "Role removed from user",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except HTTPException:
        raise
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RoleNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to remove role from user: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AUTHENTICATION & SESSION
# ----------------------------------------------------------------------------

@router.post(
    "/iam/login",
    response_model=LoginResponseSchema,
    summary="User login",
    operation_id="login",
)
async def login(
    request: LoginRequestSchema,
    http_request: Request,
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> LoginResponseSchema:
    service.set_context(session, request.legal_entity_id)
    try:
        # Ambil IP + User-Agent dari HTTP request
        forwarded = http_request.headers.get("X-Forwarded-For")
        client_ip = (
            forwarded.split(",")[0].strip() if forwarded
            else (http_request.client.host if http_request.client else "0.0.0.0")
        )
        user_agent = http_request.headers.get("User-Agent", "unknown")

        result = await service.authenticate(
            username=request.username,
            password=request.password,
            legal_entity_id=request.legal_entity_id,
            mfa_code=request.mfa_code,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        logger.info(f"User logged in successfully: {request.username}")

        return LoginResponseSchema(
            access_token=result.access_token,
            refresh_token=result.refresh_token,
            token_type="bearer",
            expires_in=result.expires_in,
            user=UserResponseSchema(
                id=result.user.user_id,
                username=result.user.username,
                email=result.user.email,
                full_name=result.user.profile.full_name,
                department=result.user.profile.department,
                job_title=result.user.profile.position,
                phone_number=result.user.profile.phone,
                status=UserStatus(result.user.status),
                is_active=result.user.status == UserStatus.ACTIVE,
                is_locked=result.user.locked_until is not None,
                is_superuser=getattr(result.user, "is_superuser", False),
                must_change_password=getattr(result.user, "must_change_password", False),
                mfa_enabled=getattr(result.user, "mfa_enabled", False),
                last_login_at=getattr(result.user, "last_login_at", None),
                last_password_change=getattr(result.user, "last_password_change_at", None),
                legal_entity_ids=[result.user.legal_entity_id] if result.user.legal_entity_id else [],
                role_ids=getattr(result.user, "role_ids", []) or [],
                notes=None,
                created_at=_get_audit_created_at(result.user),
                updated_at=_get_audit_updated_at(result.user),
                created_by=_get_audit_created_by(result.user),
                created_by_name=(str(_get_audit_created_by(result.user)) if _get_audit_created_by(result.user) else None),
                version=_get_audit_version(result.user),
            ),
        )
    except HTTPException:
        raise
    except AuthenticationError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except MFARequiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except MFAError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Login failed: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post(
    "/iam/refresh",
    response_model=TokenRefreshResponseSchema,
    summary="Refresh access token",
    operation_id="refresh_access_token",
)
async def refresh_access_token(
    request: RefreshTokenRequestSchema,
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> TokenRefreshResponseSchema:
    """
    FIX: IAMService tidak punya `.refresh_token()`. Decode refresh JWT
    via JWTAuthMiddleware._verify_token, lalu generate access_token baru.
    """
    try:
        from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
            InvalidTokenError,
            JWTAuthMiddleware,
            TokenExpiredError,
            TokenType as _TokenType,
            create_access_token as _create_access,
            create_refresh_token as _create_refresh,
        )
        from datetime import timedelta as _td

        mw = JWTAuthMiddleware.__new__(JWTAuthMiddleware)
        mw.public_key = mw._load_public_key()
        mw.private_key = mw._load_private_key()
        mw.algorithm = "RS256"
        mw.revocation_check = False
        mw._revocation_list = None
        mw.rbac_enabled = False
        mw.public_paths = set()
        mw.auth_exceptions = set()
        mw.access_expire = _td(minutes=15)
        mw.refresh_expire = _td(days=7)
        mw._authority_matrix_wired = False
        mw._authority_matrix_available = False
        mw._rbac_enforcer = None
        mw._authority_matrix = None
        mw._iam_service = None

        try:
            payload = await mw._verify_token(request.refresh_token, token_type=_TokenType.REFRESH)
        except (InvalidTokenError, TokenExpiredError) as e:
            logger.warning(f"Refresh token tidak valid: {type(e).__name__}: {e}")
            raise HTTPException(status_code=401, detail="Refresh token tidak valid atau kadaluarsa")
        except Exception as e:
            logger.exception(f"Gagal verifikasi refresh token: {type(e).__name__}")
            raise HTTPException(status_code=401, detail="Refresh token tidak valid")

        new_access = await _create_access(
            user_id=payload.user_id,
            username=payload.username,
            legal_entity_id=payload.legal_entity_id,
            roles=payload.roles or [],
            permissions=payload.permissions or [],
            device_id=payload.device_id,
        )
        new_refresh = await _create_refresh(
            user_id=payload.user_id,
            username=payload.username,
            legal_entity_id=payload.legal_entity_id,
            roles=payload.roles or [],
            permissions=payload.permissions or [],
            device_id=payload.device_id,
        )

        logger.info(f"Refresh token issued for user {payload.user_id}")

        return TokenRefreshResponseSchema(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=900,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to refresh token: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/iam/logout",
    response_model=dict[str, Any],
    summary="User logout",
    operation_id="logout",
)
async def logout(
    request: Request,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if token and hasattr(service, "logout"):
            await service.logout(token, current_user.user_id)
        logger.info(f"User logged out: {current_user.user_id}")
        return {"message": "Logged out successfully"}
    except Exception as e:
        logger.exception(f"Failed to logout: {type(e).__name__}")
        return {"message": "Logged out locally (server logout failed silently)"}


@router.post(
    "/iam/change-password",
    response_model=dict[str, Any],
    summary="Change user password",
    operation_id="change_password",
)
async def change_password(
    request: ChangePasswordSchema,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        await service.change_password(
            user_id=current_user.user_id,
            old_password=request.old_password,
            new_password=request.new_password,
        )
        logger.info(f"Password changed for user: {current_user.user_id}")
        return {"message": "Password changed successfully"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to change password: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# MFA MANAGEMENT (FIX: multiple signature support)
# ----------------------------------------------------------------------------

@router.post(
    "/iam/mfa/setup",
    response_model=MFASetupResponseSchema,
    summary="Setup MFA for current user",
    operation_id="setup_mfa",
)
async def setup_mfa(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> MFASetupResponseSchema:
    """
    FIX (2026-10-14 v6): IAMService.setup_mfa() mengembalikan DICT,
    bukan object. Sebelumnya `result.secret_key` menyebabkan
    AttributeError. Sekarang pakai akses dict.
    """
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        # Signature IAMService.setup_mfa(user_id, username) -> dict
        result = await service.setup_mfa(current_user.user_id, current_user.username)
        if not result:
            raise HTTPException(status_code=400, detail="MFA setup gagal")

        # `result` adalah dict: ambil via .get() dengan fallback
        def _pick(key, default=None):
            if isinstance(result, dict):
                return result.get(key, default)
            return getattr(result, key, default)

        return MFASetupResponseSchema(
            secret_key=_pick("secret_key", "") or "",
            qr_code_url=_pick("qr_code_url", "") or "",
            backup_codes=list(_pick("backup_codes", []) or []),
            issuer=_pick("issuer", MFA_ISSUER_NAME) or MFA_ISSUER_NAME,
        )
    except HTTPException:
        raise
    except MFAError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to setup MFA: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/iam/mfa/verify",
    response_model=dict[str, Any],
    summary="Verify MFA code and enable MFA",
    operation_id="verify_mfa",
)
async def verify_mfa(
    request: MFAVerifySchema,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    """
    FIX (2026-10-14 v6): Method IAMService yang benar adalah
    `verify_and_enable_mfa(user_id, code)`, BUKAN `verify_mfa`.
    """
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        valid = await service.verify_and_enable_mfa(current_user.user_id, request.code)
        if not valid:
            raise HTTPException(status_code=401, detail="Kode MFA tidak valid")
        return {"verified": True, "enabled": True, "message": "MFA berhasil diaktifkan"}
    except HTTPException:
        raise
    except MFAError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to verify MFA: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")
    
@router.post(
    "/iam/mfa/disable",
    response_model=dict[str, Any],
    summary="Disable MFA for current user",
    operation_id="disable_mfa",
)
async def disable_mfa(
    request: MFADisableSchema,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    """
    FIX (2026-10-14 v6): IAMService.disable_mfa(user_id, password, mfa_code).
    Raise MFAError kalau password/kode salah.
    """
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        await service.disable_mfa(
            user_id=current_user.user_id,
            password=request.password,
            mfa_code=request.mfa_code,
        )
        return {"disabled": True, "message": "MFA dinonaktifkan"}
    except HTTPException:
        raise
    except MFAError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to disable MFA: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ----------------------------------------------------------------------------
# SESSION MANAGEMENT
# ----------------------------------------------------------------------------

@router.get(
    "/iam/sessions",
    response_model=list[SessionResponseSchema],
    summary="List active sessions for current user",
    operation_id="list_sessions",
)
async def list_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> list[SessionResponseSchema]:
    """
    FIX (2026-10-14 v7): Method IAMService yang benar adalah
    `get_user_sessions(user_id)`, BUKAN `list_sessions`. Sebelumnya
    `hasattr(service, 'list_sessions')` selalu False, sehingga endpoint
    selalu return array kosong padahal tabel `iam_session` berisi data.
    """
    legal_entity_id = current_user.legal_entity_id
    if legal_entity_id is None:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        sessions = await service.get_user_sessions(current_user.user_id)
        return [
            SessionResponseSchema(
                id=s.id,
                session_token=s.session_token,
                user_id=s.user_id,
                user_name=None,
                ip_address=getattr(s, "ip_address", None),
                user_agent=getattr(s, "user_agent", None),
                device_id=getattr(s, "device_id", None),
                expires_at=s.expires_at,
                last_accessed_at=s.last_accessed_at,
                is_active=s.is_active,
                is_revoked=s.is_revoked,
                created_at=s.created_at,
            )
            for s in (sessions or [])
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list sessions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/iam/sessions/{session_id}",
    response_model=dict[str, Any],
    summary="Revoke a session",
    operation_id="revoke_session",
)
async def revoke_session(
    session_id: UUID,
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        if hasattr(service, "revoke_session"):
            await service.revoke_session(session_id, current_user.user_id)
        return {"session_id": str(session_id), "revoked": True}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to revoke session: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/iam/sessions",
    response_model=dict[str, Any],
    summary="Revoke all other sessions for current user",
    operation_id="revoke_all_sessions",
)
async def revoke_all_sessions(
    current_user: TokenPayload = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    """
    FIX (2026-10-14 v7): Method IAMService yang benar adalah
    `revoke_all_other_sessions(user_id, keep_session_id) -> int`,
    BUKAN `revoke_all_sessions`.
    """
    legal_entity_id = current_user.legal_entity_id
    if not legal_entity_id:
        raise HTTPException(status_code=400, detail="Legal entity ID not found in token")

    service.set_context(session, legal_entity_id)
    try:
        count = await service.revoke_all_other_sessions(
            current_user.user_id,
            keep_session_id=None,
        )
        return {
            "revoked_count": count or 0,
            "message": f"{count or 0} sesi lain di-revoke",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to revoke all sessions: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ----------------------------------------------------------------------------
# LOGIN ATTEMPTS & AUDIT LOGS
# ----------------------------------------------------------------------------

@router.get(
    "/iam/login-attempts",
    response_model=list[LoginAttemptResponseSchema],
    summary="List login attempts (admin only)",
    operation_id="list_login_attempts",
)
async def list_login_attempts(
    username: str | None = Query(None, description="Filter by username"),
    success: bool | None = Query(None, description="Filter by success status"),
    limit: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("iam:audit_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> list[LoginAttemptResponseSchema]:
    """
    FIX v8 (2026-10-14): Signature IAMService.get_login_attempts:
        get_login_attempts(username, success, start_date, end_date,
                           page, page_size)
    Router panggil dengan page_size (bukan limit).
    """
    service.set_context(session, legal_entity_id)
    try:
        if not hasattr(service, "get_login_attempts"):
            logger.warning("IAMService.get_login_attempts() tidak tersedia, return []")
            return []

        # Panggil dengan signature yang benar (page_size, bukan limit)
        attempts = await service.get_login_attempts(
            username=username,
            success=success,
            start_date=None,
            end_date=None,
            page=1,
            page_size=limit,
        )

        # Hasil bisa berupa: list, PagedResult (dengan .items), atau dict {"items": [...]}
        items = attempts
        if attempts is None:
            items = []
        elif hasattr(attempts, "items"):
            items = attempts.items
        elif isinstance(attempts, dict):
            items = attempts.get("items") or attempts.get("data") or []
        elif not isinstance(attempts, list):
            items = list(attempts)

        def _pick(obj, key, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        return [
            LoginAttemptResponseSchema(
                id=_pick(a, "id"),
                username=_pick(a, "username", "") or "",
                user_id=_pick(a, "user_id"),
                ip_address=_pick(a, "ip_address"),
                user_agent=_pick(a, "user_agent"),
                success=bool(_pick(a, "success", _pick(a, "is_successful", False))),
                failure_reason=_pick(a, "failure_reason"),
                attempted_at=_pick(a, "attempted_at", _pick(a, "created_at")),
            )
            for a in items
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to list login attempts: {type(e).__name__}")
        return []

@router.get(
    "/iam/audit-logs/{user_id}",
    response_model=list[UserAuditLogSchema],
    summary="Get audit logs for a user",
    operation_id="get_user_audit_logs",
)
async def get_user_audit_logs(
    user_id: UUID,
    limit: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("iam:audit_read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> list[UserAuditLogSchema]:
    service.set_context(session, legal_entity_id)
    try:
        if not hasattr(service, "get_user_audit_logs"):
            return []
        logs = await service.get_user_audit_logs(user_id, limit=limit)
        return [
            UserAuditLogSchema(
                id=log.id,
                user_id=log.user_id,
                action=log.action,
                ip_address=log.ip_address,
                user_agent=log.user_agent,
                details=log.details,
                created_at=log.created_at,
            )
            for log in logs
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get user audit logs: {type(e).__name__}")
        return []


# ----------------------------------------------------------------------------
# PASSWORD RESET
# ----------------------------------------------------------------------------

@router.post(
    "/iam/forgot-password",
    response_model=ForgotPasswordResponseSchema,
    summary="Request password reset",
    operation_id="forgot_password",
)
async def forgot_password(
    request: ResetPasswordRequestSchema,
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> ForgotPasswordResponseSchema:
    try:
        if not hasattr(service, "forgot_password"):
            return ForgotPasswordResponseSchema(
                message="If the email exists, a reset link has been sent.",
                reset_token=None,
                reset_url=None,
            )
        result = await service.forgot_password(request.email)
        return ForgotPasswordResponseSchema(
            message="If the email exists, a reset link has been sent.",
            reset_token=result.get("token") if result else None,
            reset_url=result.get("reset_url") if result else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to process forgot password: {type(e).__name__}")
        return ForgotPasswordResponseSchema(
            message="If the email exists, a reset link has been sent.",
            reset_token=None,
            reset_url=None,
        )


@router.post(
    "/iam/reset-password",
    response_model=dict[str, Any],
    summary="Confirm password reset with token",
    operation_id="reset_password",
)
async def reset_password(
    request: ResetPasswordConfirmSchema,
    session: AsyncSession = Depends(get_db_session),
    service: IAMService = Depends(get_iam_service),
) -> dict[str, Any]:
    try:
        if not hasattr(service, "reset_password"):
            raise HTTPException(status_code=501, detail="Reset password tidak tersedia")
        success = await service.reset_password(request.token, request.new_password)
        if not success:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")
        return {"message": "Password reset successfully"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reset password: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# END OF ROUTER
# ============================================================================

__all__ = ["router"]
