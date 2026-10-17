#!/usr/bin/env python3
"""
Module: service_iam.py
Layer: Application / Service Layer
Responsibility: IAM service (identity and access management).

FIX v13 (2026-10-14): _to_user_entity() sekarang MEMBACA mfa_enabled dan
    mfa_secret dari UserAggregate (bukan hardcode False/None), sehingga blok
    MFA check di authenticate() benar-benar jalan saat login.
FIX v12: Fallback lock_user di service kalau repository tidak punya method itu.
FIX v11: Normalisasi is_active/is_superuser/is_locked (method → bool) sebelum
    dikirim ke UserAggregate, mencegah error SQLAlchemy "Not a boolean value".
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

try:
    import pyotp
    HAS_PYOTP = True
except ImportError:
    HAS_PYOTP = False

from sqlalchemy.ext.asyncio import AsyncSession

from application.events import (
    AccountCreatedEvent,
    AccountDeactivatedEvent,
    AccountLockedEvent,
    AccountReactivatedEvent,
    AccountUnlockedEvent,
    AccountUpdatedEvent,
    LoginFailureEvent,
    LoginSuccessEvent,
    PermissionGrantedEvent,
    PermissionRevokedEvent,
    RoleAssignedEvent,
    RoleCreatedEvent,
    RoleDeletedEvent,
    RoleRevokedEvent,
    RoleUpdatedEvent,
    SessionCompromisedEvent,
    SessionCreatedEvent,
    SessionRefreshedEvent,
    SessionTerminatedEvent,
    UserActivatedEvent,
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserDeletedEvent,
    UserPasswordChangedEvent,
    UserSuspendedEvent,
    UserUnlockedEvent,
    UserUpdatedEvent,
)
from domain.iam.aggregate_root import UserAggregate
from domain.iam.password_hashed_vo import PasswordHashedVO, verify_password
from domain.iam.permission_vo import PermissionVO
from domain.iam.role_entity import RoleEntity
from domain.iam.user_entity import UserAudit, UserEntity, UserProfile, UserStatus
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.iam_repository_port import IAMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


def _extract_password_hash_str(password_hash: PasswordHashedVO) -> str:
    """Ambil string hash dari PasswordHashedVO (atribut: hashed_value)."""
    return password_hash.hashed_value


def _to_bool(value: Any, default: bool = False) -> bool:
    """Normalisasi nilai yang mungkin berupa method/atribut menjadi bool.

    UserEntity.is_active, .is_locked, dan .is_superuser didefinisikan sebagai
    METHOD (bukan atribut/property). Kalau nilai ini dikirim apa adanya ke
    UserAggregate(...), yang tersimpan adalah bound method — dan SQLAlchemy
    akan gagal saat flush ke kolom BOOLEAN dengan error:
        TypeError: Not a boolean value: <bound method UserEntity.is_active ...>
    """
    if value is None:
        return default
    if callable(value):
        try:
            value = value()
        except Exception:
            logger.debug("Gagal memanggil callable saat normalisasi bool", exc_info=True)
            return default
    if isinstance(value, bool):
        return value
    try:
        return bool(value)
    except Exception:
        return default


class TokenIssuerPort(Protocol):
    async def create_access_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None,
        roles: list[str],
        permissions: list[str],
        expires_delta: timedelta | None = None,
    ) -> str: ...
    async def create_refresh_token(
        self,
        user_id: UUID,
        username: str,
        legal_entity_id: UUID | None,
        roles: list[str],
        permissions: list[str],
        expires_delta: timedelta | None = None,
    ) -> str: ...
    async def verify_token(self, token: str, token_type: str = "access") -> dict[str, Any]: ...


class CachePort:
    async def get(self, key: str) -> str | None:
        raise NotImplementedError
    async def setex(self, key: str, ttl: int, value: str) -> None:
        raise NotImplementedError
    async def exists(self, key: str) -> bool:
        raise NotImplementedError
    async def delete(self, key: str) -> None:
        raise NotImplementedError


# ============================================================================
# DTOs
# ============================================================================

@dataclass(kw_only=True)
class CreateUserRequest:
    username: str
    email: str
    password: str
    full_name: str
    legal_entity_id: UUID
    role_ids: list[UUID]
    created_by: UUID | None = None


@dataclass(kw_only=True)
class CreateRoleRequest:
    role_name: str
    description: str
    permissions: list[str]
    is_default: bool = False
    is_system: bool = False
    parent_role_id: UUID | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class UpdateRoleRequest:
    role_name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None
    is_default: bool | None = None
    parent_role_id: UUID | None = None


@dataclass(kw_only=True)
class UserResponse:
    user_id: UUID
    username: str
    email: str
    full_name: str
    status: str
    legal_entity_id: UUID
    role_ids: list[UUID]
    created_at: datetime


@dataclass(kw_only=True)
class RoleResponse:
    role_id: UUID
    role_name: str
    description: str
    permissions: list[str]
    is_default: bool
    is_system: bool
    parent_role_id: UUID | None
    created_at: datetime


@dataclass(kw_only=True)
class LoginResponse:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    user: Any = None


class IAMServiceError(Exception):
    pass


class UserNotFoundError(IAMServiceError):
    pass


class RoleNotFoundError(IAMServiceError):
    pass


class AuthenticationError(IAMServiceError):
    pass


class MFARequiredError(AuthenticationError):
    """Password benar, tapi akun ini butuh kode MFA yang belum/tidak valid dikirim."""
    pass


class MFAError(IAMServiceError):
    """Error umum untuk operasi setup/verify/disable MFA (bukan alur login)."""
    pass


class PermissionDeniedError(IAMServiceError):
    pass

# ============================================================================
# Main Service
# ============================================================================

class IAMService:
    def __init__(
        self,
        iam_repo: IAMRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
        token_issuer: TokenIssuerPort | None = None,
        cache: CachePort | None = None,
    ):
        if iam_repo is None:
            raise ValueError("iam_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self._iam_repo = iam_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._token_issuer = token_issuer
        self._cache = cache
        # Session request-scoped yang di-set lewat set_context(). Ini session
        # SESUNGGUHNYA yang dipakai untuk semua operasi DB.
        self._session: AsyncSession | None = None
        self._stats = {
            "users_created": 0,
            "users_updated": 0,
            "users_deactivated": 0,
            "users_activated": 0,
            "users_locked": 0,
            "users_unlocked": 0,
            "users_suspended": 0,
            "users_deleted": 0,
            "roles_created": 0,
            "roles_updated": 0,
            "roles_deleted": 0,
            "logins": 0,
            "login_failures": 0,
        }
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("IAM service initialized")

    # ========================================================================
    # REQUEST CONTEXT (session & legal_entity_id)
    # ========================================================================

    def set_context(self, session: AsyncSession, legal_entity_id: UUID) -> None:
        """
        Set session and legal_entity_id for the current request.
        Must be called before any repository operation.
        """
        self._session = session

        if hasattr(self._iam_repo, "set_session"):
            self._iam_repo.set_session(session)
        else:
            logger.warning("Repository does not support set_session")

        if hasattr(self._iam_repo, "set_legal_entity_id"):
            self._iam_repo.set_legal_entity_id(legal_entity_id)
        else:
            logger.warning("Repository does not support set_legal_entity_id")

    async def _commit(self) -> None:
        """Commit perubahan ke DB.

        FIX: commit session yang sesungguhnya dipakai (self._session).
        Fallback ke self._uow.commit() hanya untuk jaga-jaga kalau ada caller
        yang belum sempat panggil set_context().
        """
        if self._session is not None:
            await self._session.commit()
        else:
            await self._uow.commit()

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "IAMService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ========================================================================
    # Helper: convert UserAggregate -> UserEntity
    # ========================================================================

    def _to_user_entity(self, agg: UserAggregate) -> UserEntity:
        """Convert UserAggregate to proper UserEntity with profile and audit.

        FIX v13 (2026-10-14): SEBELUMNYA `mfa_enabled=False` dan
        `mfa_secret=None` di-HARDCODE di sini, sehingga walaupun DB sudah
        update jadi True (via verify_and_enable_mfa), entity yang dikembalikan
        ke authenticate() selalu punya mfa_enabled=False dan blok MFA check
        di-skip → login tanpa minta kode MFA. Sekarang dibaca dari aggregate.
        """
        profile = UserProfile(
            full_name=agg.full_name,
            email=agg.email,
            phone=None,
            mobile=None,
            department=None,
            position=None,
            avatar_url=None,
            timezone="Asia/Jakarta",
            language="id",
            metadata={},
        )
        audit = UserAudit(
            last_login_at=agg.last_login_at,
            last_login_ip=agg.last_login_ip,
            last_password_change_at=agg.password_changed_at,
            last_password_change_by=agg.created_by,
            created_at=agg.created_at,
            created_by=agg.created_by or "system",
            updated_at=agg.updated_at,
            updated_by=agg.created_by or "system",
            deleted_at=None,
            deleted_by=None,
            version=agg.version,
        )
        return UserEntity(
            user_id=agg.id,
            username=agg.username,
            email=agg.email,
            password_hash=PasswordHashedVO(agg.hashed_password),
            status=agg.status,
            profile=profile,
            legal_entity_id=agg.legal_entity_ids[0] if agg.legal_entity_ids else None,
            role_ids=agg.role_ids,
            failed_login_attempts=agg.failed_login_count,
            locked_until=agg.locked_until,
            # FIX v13: baca mfa_* dari aggregate (bukan hardcode False/None)
            mfa_enabled=bool(getattr(agg, "mfa_enabled", False)),
            mfa_secret=getattr(agg, "mfa_secret", None),
            audit=audit,
        )

    # ========================================================================
    # User Management
    # ========================================================================

    async def create_user(self, request: CreateUserRequest, correlation_id: str | None = None) -> UserEntity:
        self._check_authority(request.created_by, "create_user")
        iam = await self._iam_repo.get()
        for existing in iam.users.values():
            if existing.username == request.username:
                raise IAMServiceError(f"Username '{request.username}' already exists")
            if existing.email == request.email:
                raise IAMServiceError(f"Email '{request.email}' already exists")

        password_hash = PasswordHashedVO.create_from_plain(
            request.password, username=request.username,
        )
        user_entity = UserEntity(
            user_id=uuid4(),
            username=request.username,
            email=request.email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            profile=UserProfile(full_name=request.full_name, email=request.email),
            legal_entity_id=request.legal_entity_id,
            role_ids=request.role_ids,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=False,
            mfa_secret=None,
            audit=UserAudit(
                created_at=datetime.now(UTC),
                created_by=str(request.created_by) if request.created_by else "system",
                updated_at=datetime.now(UTC),
                updated_by=str(request.created_by) if request.created_by else "system",
                version=1,
            ),
        )

        user_agg = UserAggregate(
            id=user_entity.user_id,
            username=user_entity.username,
            email=user_entity.email,
            full_name=user_entity.profile.full_name,
            hashed_password=_extract_password_hash_str(user_entity.password_hash),
            status=user_entity.status,
            is_superuser=False,
            is_active=True,
            created_at=user_entity.audit.created_at,
            updated_at=user_entity.audit.updated_at,
            created_by=user_entity.audit.created_by,
            version=user_entity.audit.version,
            legal_entity_ids=[user_entity.legal_entity_id],
            role_ids=user_entity.role_ids,
        )
        await self._iam_repo.add(user_agg)
        await self._commit()

        self._stats["users_created"] += 1

        if self._event_publisher:
            event_user = UserCreatedEvent(
                aggregate_id=user_entity.user_id,
                aggregate_version=user_entity.audit.version,
                user_id=str(request.created_by) if request.created_by else None,
                username=user_entity.username,
                email=user_entity.email,
                full_name=user_entity.profile.full_name,
                legal_entity_id=user_entity.legal_entity_id,
                created_by=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

            event_account = AccountCreatedEvent(
                aggregate_id=user_entity.user_id,
                aggregate_version=user_entity.audit.version,
                account_id=user_entity.user_id,
                account_name=user_entity.username,
                account_type="user",
                legal_entity_id=user_entity.legal_entity_id,
                created_by=str(request.created_by) if request.created_by else None,
                user_id=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("create_user", {
            "user_id": str(user_entity.user_id),
            "username": user_entity.username,
            "created_by": str(request.created_by) if request.created_by else None,
        })

        logger.info("User record added")
        return user_entity

    async def get_user(self, user_id: UUID) -> UserEntity | None:
        iam = await self._iam_repo.get()
        return iam.users.get(user_id)

    async def update_user(self, user_id: UUID, updated_by: UUID, full_name: str | None = None,
                         email: str | None = None, correlation_id: str | None = None) -> UserEntity:
        self._check_authority(updated_by, "update_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        current_full_name = user.profile.full_name
        current_email = user.email
        new_full_name = full_name or current_full_name
        new_email = email or current_email
        changes = {}

        if new_full_name != current_full_name:
            changes["full_name"] = {"old": current_full_name, "new": new_full_name}
        if new_email != current_email:
            for existing in iam.users.values():
                if existing.user_id != user_id and existing.email == new_email:
                    raise IAMServiceError(f"Email '{new_email}' already used")
            changes["email"] = {"old": current_email, "new": new_email}

        if not changes:
            return user

        # FIX v11: is_active/is_superuser di UserEntity adalah METHOD (bukan
        # atribut), jadi `user.is_active` mengembalikan bound method — bukan
        # bool. _to_bool() menormalkan baik method maupun atribut ke bool.
        # FIX v13: bawa juga mfa_* dari user lama supaya tidak reset.
        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=new_email,
            full_name=new_full_name,
            hashed_password=_extract_password_hash_str(user.password_hash),
            status=user.status,
            is_superuser=_to_bool(getattr(user, 'is_superuser', False), default=False),
            is_active=_to_bool(getattr(user, 'is_active', True), default=True),
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=_to_bool(getattr(user, 'must_change_password', False), default=False),
            password_changed_at=user.audit.last_password_change_at,
            mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
            mfa_secret=getattr(user, "mfa_secret", None),
            mfa_backup_codes=list(getattr(user, "mfa_backup_codes", []) or []),
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._commit()

        self._stats["users_updated"] += 1

        updated_user_entity = self._to_user_entity(agg)

        if self._event_publisher:
            event_user = UserUpdatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                user_id=str(updated_by),
                changes=changes,
                updated_by=str(updated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

            event_account = AccountUpdatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                account_id=user_id,
                changes=changes,
                updated_by=str(updated_by),
                user_id=str(updated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("update_user", {
            "user_id": str(user_id),
            "changes": changes,
            "updated_by": str(updated_by),
        })

        logger.info("User record updated")
        return updated_user_entity

    async def activate_user(self, user_id: UUID, activated_by: UUID, correlation_id: str | None = None) -> None:
        self._check_authority(activated_by, "activate_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if user.status == UserStatus.ACTIVE:
            return

        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            hashed_password=_extract_password_hash_str(user.password_hash),
            status=UserStatus.ACTIVE,
            is_superuser=_to_bool(getattr(user, 'is_superuser', False), default=False),
            is_active=True,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=_to_bool(getattr(user, 'must_change_password', False), default=False),
            password_changed_at=user.audit.last_password_change_at,
            mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
            mfa_secret=getattr(user, "mfa_secret", None),
            mfa_backup_codes=list(getattr(user, "mfa_backup_codes", []) or []),
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._commit()

        self._stats["users_activated"] += 1

        if self._event_publisher:
            event_user = UserActivatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                user_id=str(activated_by),
                username=user.username,
                activated_by=str(activated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

            event_account = AccountReactivatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                account_id=user_id,
                account_name=user.username,
                reactivated_by=str(activated_by),
                user_id=str(activated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("activate_user", {
            "user_id": str(user_id),
            "activated_by": str(activated_by),
        })

        logger.info("User record activated")

    async def deactivate_user(self, user_id: UUID, deactivated_by: UUID, reason: str | None = None,
                              correlation_id: str | None = None) -> None:
        self._check_authority(deactivated_by, "deactivate_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if user.status == UserStatus.INACTIVE:
            return

        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            hashed_password=_extract_password_hash_str(user.password_hash),
            status=UserStatus.INACTIVE,
            is_superuser=_to_bool(getattr(user, 'is_superuser', False), default=False),
            is_active=False,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=_to_bool(getattr(user, 'must_change_password', False), default=False),
            password_changed_at=user.audit.last_password_change_at,
            mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
            mfa_secret=getattr(user, "mfa_secret", None),
            mfa_backup_codes=list(getattr(user, "mfa_backup_codes", []) or []),
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._commit()

        self._stats["users_deactivated"] += 1

        if self._event_publisher:
            event_user = UserDeactivatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                user_id=str(deactivated_by),
                reason=reason,
                deactivated_by=str(deactivated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

            event_account = AccountDeactivatedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                account_id=user_id,
                reason=reason,
                deactivated_by=str(deactivated_by),
                user_id=str(deactivated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("deactivate_user", {
            "user_id": str(user_id),
            "reason": reason,
            "deactivated_by": str(deactivated_by),
        })

        logger.info("User record deactivated")

    async def lock_user(self, user_id: UUID, locked_by: UUID, reason: str | None = None,
                        correlation_id: str | None = None) -> None:
        """Lock user account.

        FIX v12: repository IAM (SQLAlchemyIAMRepository) TIDAK punya method
        `lock_user` — hanya `unlock_user`. Solusi: implementasi fallback di
        service ini sendiri, memakai `update()` standar yang sudah ada.
        """
        self._check_authority(locked_by, "lock_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if user.locked_until and user.locked_until > datetime.now(UTC):
            return

        lock_until = datetime.now(UTC) + timedelta(minutes=30)

        if hasattr(self._iam_repo, "lock_user") and callable(getattr(self._iam_repo, "lock_user")):
            await self._iam_repo.lock_user(user_id, locked_by, reason)
        else:
            agg = UserAggregate(
                id=user.user_id,
                username=user.username,
                email=user.email,
                full_name=user.profile.full_name,
                hashed_password=_extract_password_hash_str(user.password_hash),
                status=UserStatus.LOCKED,
                is_superuser=_to_bool(getattr(user, 'is_superuser', False), default=False),
                is_active=False,
                last_login_at=user.audit.last_login_at,
                last_login_ip=user.audit.last_login_ip,
                failed_login_count=user.failed_login_attempts,
                locked_until=lock_until,
                must_change_password=_to_bool(getattr(user, 'must_change_password', False), default=False),
                password_changed_at=user.audit.last_password_change_at,
                mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
                mfa_secret=getattr(user, "mfa_secret", None),
                mfa_backup_codes=list(getattr(user, "mfa_backup_codes", []) or []),
                created_at=user.audit.created_at,
                updated_at=datetime.now(UTC),
                created_by=user.audit.created_by,
                version=user.audit.version,
                legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
                role_ids=user.role_ids,
            )
            await self._iam_repo.update(agg)

        await self._commit()

        self._stats["users_locked"] += 1

        if self._event_publisher:
            event_account = AccountLockedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                account_id=user_id,
                reason=reason,
                locked_by=str(locked_by),
                user_id=str(locked_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("lock_user", {
            "user_id": str(user_id),
            "reason": reason,
            "locked_by": str(locked_by),
        })

        logger.info("User account locked")

    async def unlock_user(self, user_id: UUID, unlocked_by: UUID, correlation_id: str | None = None) -> None:
        self._check_authority(unlocked_by, "unlock_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if not (user.locked_until and user.locked_until > datetime.now(UTC)):
            return

        await self._iam_repo.unlock_user(user_id, unlocked_by)
        await self._commit()

        self._stats["users_unlocked"] += 1

        if self._event_publisher:
            event_account = AccountUnlockedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                account_id=user_id,
                unlocked_by=str(unlocked_by),
                user_id=str(unlocked_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

            event_user = UserUnlockedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(unlocked_by),
                username=user.username,
                unlocked_by=str(unlocked_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

        self._record_audit("unlock_user", {
            "user_id": str(user_id),
            "unlocked_by": str(unlocked_by),
        })

        logger.info("User account unlocked")

    async def suspend_user(self, user_id: UUID, suspended_by: UUID, reason: str | None = None,
                           correlation_id: str | None = None) -> None:
        self._check_authority(suspended_by, "suspend_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if user.status == UserStatus.SUSPENDED:
            return

        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=user.email,
            full_name=user.profile.full_name,
            hashed_password=_extract_password_hash_str(user.password_hash),
            status=UserStatus.SUSPENDED,
            is_superuser=_to_bool(getattr(user, 'is_superuser', False), default=False),
            is_active=False,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=_to_bool(getattr(user, 'must_change_password', False), default=False),
            password_changed_at=user.audit.last_password_change_at,
            mfa_enabled=bool(getattr(user, "mfa_enabled", False)),
            mfa_secret=getattr(user, "mfa_secret", None),
            mfa_backup_codes=list(getattr(user, "mfa_backup_codes", []) or []),
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._commit()

        self._stats["users_suspended"] += 1

        if self._event_publisher:
            event = UserSuspendedEvent(
                aggregate_id=user_id,
                aggregate_version=agg.version,
                user_id=str(suspended_by),
                username=user.username,
                reason=reason,
                suspended_by=str(suspended_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("suspend_user", {
            "user_id": str(user_id),
            "reason": reason,
            "suspended_by": str(suspended_by),
        })

        logger.info("User account suspended")

    async def delete_user(self, user_id: UUID, deleted_by: UUID, correlation_id: str | None = None) -> None:
        self._check_authority(deleted_by, "delete_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        await self._iam_repo.delete(user_id, deleted_by, permanent=False)
        await self._commit()

        self._stats["users_deleted"] += 1

        if self._event_publisher:
            event_user = UserDeletedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(deleted_by),
                username=user.username,
                deleted_by=str(deleted_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_user)

            event_account = AccountDeactivatedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                account_id=user_id,
                reason="User deleted",
                deactivated_by=str(deleted_by),
                user_id=str(deleted_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_account)

        self._record_audit("delete_user", {
            "user_id": str(user_id),
            "deleted_by": str(deleted_by),
        })

        logger.info("User record deleted")

    # ========================================================================
    # Role Management
    # ========================================================================

    async def create_role(self, request: CreateRoleRequest, correlation_id: str | None = None) -> RoleEntity:
        self._check_authority(request.created_by, "create_role")
        iam = await self._iam_repo.get()

        for existing in iam.roles.values():
            if existing.role_name == request.role_name:
                raise IAMServiceError(f"Role name '{request.role_name}' already exists")

        perm_objects = [PermissionVO.from_string(p) for p in request.permissions]
        role = RoleEntity(
            role_id=uuid4(),
            role_name=request.role_name,
            description=request.description,
            permissions=perm_objects,
            parent_role_id=request.parent_role_id,
            is_default=request.is_default,
            is_system=request.is_system,
            created_by=str(request.created_by) if request.created_by else None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

        await self._iam_repo.create_role(
            role_code=role.role_name,
            role_name=role.role_name,
            permissions=[PermissionVO.from_string(p) for p in request.permissions],
            created_by=request.created_by or UUID(int=0),
            description=role.description,
        )
        await self._commit()

        self._stats["roles_created"] += 1

        if self._event_publisher:
            event_role = RoleCreatedEvent(
                aggregate_id=role.role_id,
                aggregate_version=role.version,
                role=role,
                created_by=str(request.created_by) if request.created_by else "system",
                user_id=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_role)

            for perm in role.permissions:
                event_perm = PermissionGrantedEvent(
                    aggregate_id=role.role_id,
                    aggregate_version=role.version,
                    role_id=role.role_id,
                    role_name=role.role_name,
                    permission=perm.to_string,
                    granted_by=str(request.created_by) if request.created_by else "system",
                    user_id=str(request.created_by) if request.created_by else None,
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event_perm)

        self._record_audit("create_role", {
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "created_by": str(request.created_by) if request.created_by else None,
        })

        logger.info("Role record added")
        return role

    async def get_role(self, role_id: UUID) -> RoleEntity | None:
        iam = await self._iam_repo.get()
        return iam.roles.get(role_id)

    async def list_roles(self) -> list[RoleEntity]:
        iam = await self._iam_repo.get()
        return list(iam.roles.values())

    async def get_user_roles(self, user_id: UUID) -> list[RoleEntity]:
        """Ambil semua Role yang di-assign ke seorang user."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found")
        return [iam.roles[rid] for rid in user.role_ids if rid in iam.roles]

    async def update_role(self, role_id: UUID, request: UpdateRoleRequest, updated_by: UUID,
                          correlation_id: str | None = None) -> RoleEntity:
        self._check_authority(updated_by, "update_role")
        iam = await self._iam_repo.get()
        role = iam.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")

        is_structural_change = (
            (request.role_name is not None and request.role_name != role.role_name)
            or (request.description is not None and request.description != role.description)
            or (request.is_default is not None and request.is_default != role.is_default)
            or (request.parent_role_id != role.parent_role_id)
        )
        if role.is_system and is_structural_change:
            raise IAMServiceError(
                "Cannot rename, redescribe, or reparent a system role "
                "(permission assignment on system roles is still allowed)"
            )

        changes = {}
        if request.role_name is not None and request.role_name != role.role_name:
            changes["role_name"] = {"old": role.role_name, "new": request.role_name}
            role.role_name = request.role_name
        if request.description is not None and request.description != role.description:
            changes["description"] = {"old": role.description, "new": request.description}
            role.description = request.description
        if request.is_default is not None and request.is_default != role.is_default:
            changes["is_default"] = {"old": role.is_default, "new": request.is_default}
            role.is_default = request.is_default
        if request.parent_role_id != role.parent_role_id:
            changes["parent_role_id"] = {"old": role.parent_role_id, "new": request.parent_role_id}
            role.parent_role_id = request.parent_role_id

        if request.permissions is not None:
            old_perms = {p.to_string for p in role.permissions}
            new_perms = set(request.permissions)
            added = new_perms - old_perms
            removed = old_perms - new_perms
            if added or removed:
                changes["permissions"] = {"old": list(old_perms), "new": list(new_perms)}
                role.permissions = [PermissionVO.from_string(p) for p in new_perms]
                if self._event_publisher:
                    for perm in added:
                        event = PermissionGrantedEvent(
                            aggregate_id=role.role_id,
                            aggregate_version=role.version + 1,
                            role_id=role.role_id,
                            role_name=role.role_name,
                            permission=perm,
                            granted_by=str(updated_by),
                            user_id=str(updated_by),
                            correlation_id=correlation_id,
                        )
                        await self._event_publisher.publish(event)
                    for perm in removed:
                        event = PermissionRevokedEvent(
                            aggregate_id=role.role_id,
                            aggregate_version=role.version + 1,
                            role_id=role.role_id,
                            role_name=role.role_name,
                            permission=perm,
                            revoked_by=str(updated_by),
                            user_id=str(updated_by),
                            correlation_id=correlation_id,
                        )
                        await self._event_publisher.publish(event)

        if not changes:
            return role

        role.updated_by = str(updated_by)
        role.updated_at = datetime.now(UTC)
        await self._iam_repo.update_role(role)
        await self._commit()

        self._stats["roles_updated"] += 1

        if self._event_publisher:
            event = RoleUpdatedEvent(
                aggregate_id=role.role_id,
                aggregate_version=role.version + 1,
                role_id=role.role_id,
                role_name=role.role_name,
                changes=changes,
                updated_by=str(updated_by),
                user_id=str(updated_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("update_role", {
            "role_id": str(role_id),
            "changes": changes,
            "updated_by": str(updated_by),
        })

        logger.info("Role record updated")
        return role

    async def delete_role(self, role_id: UUID, deleted_by: UUID, correlation_id: str | None = None) -> None:
        self._check_authority(deleted_by, "delete_role")
        iam = await self._iam_repo.get()
        role = iam.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")
        if role.is_system:
            raise IAMServiceError("Cannot delete system role")
        for user in iam.users.values():
            if role_id in user.role_ids:
                raise IAMServiceError(f"Role {role.role_name} is assigned to users")

        await self._iam_repo.delete_role(role_id, deleted_by)
        await self._commit()

        self._stats["roles_deleted"] += 1

        if self._event_publisher:
            event = RoleDeletedEvent(
                aggregate_id=role_id,
                aggregate_version=role.version + 1,
                role_id=role_id,
                role_name=role.role_name,
                deleted_by=str(deleted_by),
                user_id=str(deleted_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("delete_role", {
            "role_id": str(role_id),
            "role_name": role.role_name,
            "deleted_by": str(deleted_by),
        })

        logger.info("Role record deleted")

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID, assigned_by: UUID,
                                  correlation_id: str | None = None) -> None:
        self._check_authority(assigned_by, "assign_role_to_user")
        iam = await self._iam_repo.get()
        if role_id not in iam.roles:
            raise RoleNotFoundError(f"Role {role_id} not found")
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        role = iam.roles.get(role_id)
        await self._iam_repo.assign_role(user_id, role.role_name, assigned_by)
        await self._commit()

        if self._event_publisher:
            event = RoleAssignedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(assigned_by),
                role_id=role_id,
                role_name=role.role_name if role else "unknown",
                assigned_by=str(assigned_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("assign_role_to_user", {
            "user_id": str(user_id),
            "role_id": str(role_id),
            "assigned_by": str(assigned_by),
        })

        logger.info("Role assignment completed")

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID, revoked_by: UUID,
                                    correlation_id: str | None = None) -> None:
        self._check_authority(revoked_by, "revoke_role_from_user")
        iam = await self._iam_repo.get()
        if role_id not in iam.roles:
            raise RoleNotFoundError(f"Role {role_id} not found")
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        role = iam.roles.get(role_id)
        await self._iam_repo.revoke_role(user_id, role.role_name, revoked_by)
        await self._commit()

        if self._event_publisher:
            event = RoleRevokedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(revoked_by),
                role_id=role_id,
                role_name=role.role_name if role else "unknown",
                revoked_by=str(revoked_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("revoke_role_from_user", {
            "user_id": str(user_id),
            "role_id": str(role_id),
            "revoked_by": str(revoked_by),
        })

        logger.info("Role revocation completed")

    # ========================================================================
    # Authentication & Authorization
    # ========================================================================

    async def login(
        self,
        username: str,
        password: str,
        mfa_code: str | None = None,
        legal_entity_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        correlation_id: str | None = None,
    ) -> LoginResponse:
        if legal_entity_id is None:
            raise AuthenticationError("Legal entity context is required for login")
        return await self.authenticate(
            username=username,
            password=password,
            mfa_code=mfa_code,
            legal_entity_id=legal_entity_id,
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=correlation_id,
        )

    async def authenticate(
        self,
        username: str,
        password: str,
        legal_entity_id: UUID,
        mfa_code: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        correlation_id: str | None = None,
    ) -> LoginResponse:
        if self._token_issuer is None:
            raise AuthenticationError("Token issuer not configured")

        user_agg = await self._iam_repo.authenticate(
            username=username,
            password=password,
            ip_address=ip_address or "0.0.0.0",
            legal_entity_id=legal_entity_id,
        )

        if not user_agg:
            self._stats["login_failures"] += 1
            await self._safe_record_login_attempt(username, False, ip_address, "invalid_credentials", user_agent)
            if self._event_publisher:
                event = LoginFailureEvent(
                    aggregate_id=uuid4(),
                    aggregate_version=1,
                    username=username,
                    reason="invalid_credentials",
                    timestamp=datetime.now(UTC),
                )
                await self._event_publisher.publish(event)
            raise AuthenticationError("Invalid username or password")

        user = self._to_user_entity(user_agg)

        if user.status != UserStatus.ACTIVE:
            self._stats["login_failures"] += 1
            await self._safe_record_login_attempt(username, False, ip_address, f"account_{user.status.value}", user_agent)
            if self._event_publisher:
                event = LoginFailureEvent(
                    aggregate_id=user.user_id,
                    aggregate_version=user.audit.version,
                    username=username,
                    reason=f"account_{user.status.value}",
                    timestamp=datetime.now(UTC),
                )
                await self._event_publisher.publish(event)
            raise AuthenticationError(f"User account is {user.status.value}")

        if user.locked_until and user.locked_until > datetime.now(UTC):
            self._stats["login_failures"] += 1
            await self._safe_record_login_attempt(username, False, ip_address, "account_locked", user_agent)
            if self._event_publisher:
                event = LoginFailureEvent(
                    aggregate_id=user.user_id,
                    aggregate_version=user.audit.version,
                    username=username,
                    reason="account_locked",
                    timestamp=datetime.now(UTC),
                )
                await self._event_publisher.publish(event)
            raise AuthenticationError("User account is locked")

        # ============================================================
        # MFA CHECK
        # ============================================================
        if user.mfa_enabled:
            if not mfa_code:
                self._stats["login_failures"] += 1
                await self._safe_record_login_attempt(username, False, ip_address, "mfa_code_required", user_agent)
                raise MFARequiredError("Kode MFA diperlukan untuk akun ini")
            if not self._verify_totp_code(user.mfa_secret, mfa_code, getattr(user_agg, "mfa_backup_codes", None)):
                self._stats["login_failures"] += 1
                await self._safe_record_login_attempt(username, False, ip_address, "mfa_code_invalid", user_agent)
                raise MFARequiredError("Kode MFA tidak valid")

        iam = await self._iam_repo.get()
        all_perms = iam.get_user_permissions(user.user_id)
        role_names = []
        for rid in user.role_ids:
            role = iam.roles.get(rid)
            if role:
                role_names.append(role.role_name)

        permissions_list = [p.to_string for p in all_perms] if all_perms else []

        logger.info(f"User {username} (id={user.user_id}) permissions: {permissions_list}")
        logger.info(f"User {username} roles: {role_names}")
        if not permissions_list:
            logger.warning(
                f"User {username} has NO permissions! Check role assignments and permission mappings."
            )

        access_token = await self._token_issuer.create_access_token(
            user_id=user.user_id,
            username=user.username,
            legal_entity_id=user.legal_entity_id,
            roles=role_names,
            permissions=permissions_list,
        )
        refresh_token = await self._token_issuer.create_refresh_token(
            user_id=user.user_id,
            username=user.username,
            legal_entity_id=user.legal_entity_id,
            roles=role_names,
            permissions=permissions_list,
        )

        self._stats["logins"] += 1

        await self._safe_record_login_attempt(username, True, ip_address, None, user_agent)
        try:
            await self._iam_repo.create_session(
                user_id=user.user_id,
                ip_address=ip_address or "0.0.0.0",
                user_agent=user_agent or "unknown",
            )
        except Exception:
            logger.exception("Failed to persist login session record (non-fatal)")

        if self._event_publisher:
            event_success = LoginSuccessEvent(
                aggregate_id=user.user_id,
                aggregate_version=user.audit.version,
                user_id=user.user_id,
                username=user.username,
                timestamp=datetime.now(UTC),
            )
            await self._event_publisher.publish(event_success)

            session_id = uuid4()
            event_session = SessionCreatedEvent(
                aggregate_id=user.user_id,
                aggregate_version=user.audit.version,
                session_id=session_id,
                user_id=user.user_id,
                username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                timestamp=datetime.now(UTC),
            )
            await self._event_publisher.publish(event_session)

        self._record_audit("authenticate", {
            "username": username,
            "user_id": str(user.user_id),
            "success": True,
        })

        await self._commit()
        logger.info("Access issued")
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=3600,
            user=user,
        )

    # ========================================================================
    # MFA helpers (dipakai internal oleh authenticate() & method setup/verify/disable)
    # ========================================================================

    async def _safe_record_login_attempt(
        self,
        username: str,
        success: bool,
        ip_address: str | None,
        failure_reason: str | None,
        user_agent: str | None,
    ) -> None:
        """Catat percobaan login & commit segera, tanpa pernah membuat proses
        login gagal gara-gara audit trail-nya sendiri error."""
        try:
            await self._iam_repo.record_login_attempt(
                username=username,
                success=success,
                ip_address=ip_address or "0.0.0.0",
                failure_reason=failure_reason,
                user_agent=user_agent,
            )
            await self._commit()
        except Exception:
            logger.exception("Failed to record login attempt (non-fatal)")

    def _verify_totp_code(self, secret: str | None, code: str, backup_codes: list[str] | None = None) -> bool:
        """Verifikasi kode 6-digit TOTP, dengan fallback ke backup code sekali-pakai."""
        if not secret or not code:
            return False
        code = code.strip()
        if HAS_PYOTP:
            totp = pyotp.TOTP(secret)
            if totp.verify(code, valid_window=1):
                return True
        if backup_codes and code.upper() in [c.upper() for c in backup_codes]:
            return True
        return False

    def _generate_backup_codes(self, count: int = 10) -> list[str]:
        return [secrets.token_hex(4).upper() for _ in range(count)]

    # ========================================================================
    # MFA (Multi-Factor Authentication) — setup / verify / disable
    # ========================================================================

    async def setup_mfa(self, user_id: UUID, username: str) -> dict[str, Any]:
        """Langkah 1: generate secret TOTP baru + backup codes, simpan sebagai
        PENDING (mfa_enabled masih False sampai user verifikasi kode pertama
        lewat verify_and_enable_mfa)."""
        if not HAS_PYOTP:
            raise MFAError("Dependency 'pyotp' belum terpasang di server (pip install pyotp)")

        user_agg = await self._iam_repo.get_by_id(user_id)
        if not user_agg:
            raise UserNotFoundError(f"User {user_id} not found")

        secret = pyotp.random_base32()
        backup_codes = self._generate_backup_codes()

        await self._iam_repo.set_mfa_secret(user_id, secret, backup_codes)
        await self._commit()

        issuer = "ERP-Accounting-Engine"
        totp = pyotp.TOTP(secret)
        qr_code_url = totp.provisioning_uri(name=username, issuer_name=issuer)

        self._record_audit("setup_mfa", {"user_id": str(user_id), "username": username})
        logger.info("MFA setup initiated for user %s (belum aktif sampai diverifikasi)", user_id)

        return {
            "secret_key": secret,
            "qr_code_url": qr_code_url,
            "backup_codes": backup_codes,
            "issuer": issuer,
        }

    async def verify_and_enable_mfa(self, user_id: UUID, code: str) -> bool:
        """Langkah 2: user memasukkan kode 6-digit dari authenticator app untuk
        membuktikan setup-nya benar, baru mfa_enabled di-set True."""
        user_agg = await self._iam_repo.get_by_id(user_id)
        if not user_agg:
            raise UserNotFoundError(f"User {user_id} not found")

        if not user_agg.mfa_secret:
            raise MFAError("Belum ada setup MFA yang pending untuk user ini. Panggil setup_mfa dulu.")

        if not self._verify_totp_code(user_agg.mfa_secret, code):
            self._record_audit("verify_mfa_failed", {"user_id": str(user_id)})
            return False

        await self._iam_repo.set_mfa_enabled(user_id, True)
        await self._commit()
        self._record_audit("verify_mfa_enabled", {"user_id": str(user_id)})
        logger.info("MFA enabled for user %s", user_id)
        return True

    async def disable_mfa(self, user_id: UUID, password: str, mfa_code: str | None = None) -> None:
        """Nonaktifkan MFA. Selalu butuh password saat ini untuk konfirmasi;
        kalau MFA masih aktif, kode MFA juga divalidasi (defense in depth)."""
        user_agg = await self._iam_repo.get_by_id(user_id)
        if not user_agg:
            raise UserNotFoundError(f"User {user_id} not found")

        if not verify_password(password, PasswordHashedVO(user_agg.hashed_password)):
            self._record_audit("disable_mfa_failed", {"user_id": str(user_id), "reason": "wrong_password"})
            raise MFAError("Password salah")

        if user_agg.mfa_enabled:
            if not mfa_code or not self._verify_totp_code(user_agg.mfa_secret, mfa_code, getattr(user_agg, "mfa_backup_codes", None)):
                self._record_audit("disable_mfa_failed", {"user_id": str(user_id), "reason": "invalid_mfa_code"})
                raise MFAError("Kode MFA tidak valid")

        await self._iam_repo.set_mfa_enabled(user_id, False)
        await self._commit()
        self._record_audit("disable_mfa", {"user_id": str(user_id)})
        logger.info("MFA disabled for user %s", user_id)

    # ========================================================================
    # Session management (halaman "Sesi Login Aktif")
    # ========================================================================

    async def get_user_sessions(self, user_id: UUID):
        return await self._iam_repo.list_sessions_for_user(user_id)

    async def revoke_session(self, session_id: UUID, user_id: UUID) -> bool:
        ok = await self._iam_repo.revoke_session_for_user(session_id, user_id)
        await self._commit()
        self._record_audit("revoke_session", {"user_id": str(user_id), "session_id": str(session_id)})
        return ok

    async def revoke_all_other_sessions(self, user_id: UUID, keep_session_id: UUID | None = None) -> int:
        count = await self._iam_repo.revoke_all_other_sessions_for_user(user_id, keep_session_id)
        await self._commit()
        self._record_audit("revoke_all_other_sessions", {"user_id": str(user_id), "count": count})
        return count

    # ========================================================================
    # Login attempts (tab "Riwayat Percobaan Login")
    # ========================================================================

    async def get_login_attempts(
        self,
        username: str | None = None,
        success: bool | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ):
        offset = max(page - 1, 0) * page_size
        return await self._iam_repo.get_login_attempts(
            username=username,
            success=success,
            start_date=start_date,
            end_date=end_date,
            limit=page_size,
            offset=offset,
        )

    async def refresh_access_token(self, refresh_token: str, correlation_id: str | None = None) -> str:
        if self._token_issuer is None:
            raise AuthenticationError("Token issuer not configured")

        try:
            payload = await self._token_issuer.verify_token(refresh_token, token_type="refresh")
            user_id = UUID(payload["sub"])
            username = payload["username"]
            legal_entity_id = UUID(payload["legal_entity_id"]) if payload.get("legal_entity_id") else None
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", [])

            new_access = await self._token_issuer.create_access_token(
                user_id=user_id,
                username=username,
                legal_entity_id=legal_entity_id,
                roles=roles,
                permissions=permissions,
            )

            if self._event_publisher:
                event = SessionRefreshedEvent(
                    aggregate_id=user_id,
                    aggregate_version=1,
                    user_id=user_id,
                    username=username,
                    timestamp=datetime.now(UTC),
                )
                await self._event_publisher.publish(event)

            self._record_audit("refresh_access_token", {"user_id": str(user_id)})

            logger.info("Access renewed")
            return new_access
        except Exception as e:
            raise AuthenticationError(f"Invalid refresh request: {type(e).__name__}")

    async def logout(self, user_id: UUID, jti: str, correlation_id: str | None = None) -> None:
        if self._cache is None:
            logger.warning("Cache not configured, revocation disabled")
            return

        key = f"blacklist:item:{jti}"
        await self._cache.setex(key, 86400, "revoked")

        if self._event_publisher:
            event = SessionTerminatedEvent(
                aggregate_id=user_id,
                aggregate_version=1,
                user_id=user_id,
                session_id=jti,
                timestamp=datetime.now(UTC),
            )
            await self._event_publisher.publish(event)

        self._record_audit("logout", {"user_id": str(user_id)})

        logger.info("Access revoked")

    async def report_session_compromised(self, user_id: UUID, session_id: str, reason: str,
                                         reported_by: UUID | None = None, correlation_id: str | None = None) -> None:
        if self._event_publisher:
            try:
                event = SessionCompromisedEvent(
                    aggregate_id=user_id,
                    aggregate_version=1,
                    user_id=str(reported_by) if reported_by else None,
                    session_id=session_id,
                    reason=reason,
                    reported_by=str(reported_by) if reported_by else "system",
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id)
            except Exception as e:
                logger.warning(f"Failed to publish SessionCompromisedEvent: {e}")

    # ========================================================================
    # Password Management
    # ========================================================================

    async def change_password(self, user_id: UUID, old_password: str, new_password: str,
                              changed_by: UUID, correlation_id: str | None = None) -> None:
        self._check_authority(changed_by, "change_password")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        if not user.password_hash.verify(old_password):
            raise AuthenticationError("Old password is incorrect")

        await self._iam_repo.change_password(
            user_id=user_id,
            old_password=old_password,
            new_password=new_password,
            actor_id=changed_by,
        )
        await self._commit()

        if self._event_publisher:
            event = UserPasswordChangedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(changed_by),
                username=user.username,
                changed_by=str(changed_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("change_password", {
            "user_id": str(user_id),
            "changed_by": str(changed_by),
        })

        logger.info("Security record updated")

    async def reset_password(self, user_id: UUID, new_password: str, reset_by: UUID,
                             correlation_id: str | None = None) -> None:
        self._check_authority(reset_by, "reset_password")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        await self._iam_repo.change_password(
            user_id=user_id,
            old_password="",
            new_password=new_password,
            actor_id=reset_by,
        )
        await self._commit()

        if self._event_publisher:
            event = UserPasswordChangedEvent(
                aggregate_id=user_id,
                aggregate_version=user.audit.version + 1,
                user_id=str(reset_by),
                username=user.username,
                reset_by=str(reset_by),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        self._record_audit("reset_password", {
            "user_id": str(user_id),
            "reset_by": str(reset_by),
        })

        logger.info("Security record reset")

    # ========================================================================
    # Password reset via token (alur self-service "Lupa Password")
    # ========================================================================

    RESET_TOKEN_TTL_MINUTES = 60

    @staticmethod
    def _hash_reset_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def request_password_reset(self, email: str) -> dict[str, str | None]:
        generic_message = "Jika email terdaftar, link reset password sudah dikirim."

        user_agg = await self._iam_repo.get_by_email(email)
        if not user_agg:
            logger.info("Password reset requested for unknown email")
            return {"message": generic_message, "reset_token": None, "reset_url": None}

        token = secrets.token_urlsafe(32)
        token_hash = self._hash_reset_token(token)
        expires_at = datetime.now(UTC) + timedelta(minutes=self.RESET_TOKEN_TTL_MINUTES)

        await self._iam_repo.set_password_reset_token(user_agg.id, token_hash, expires_at)
        await self._commit()

        self._record_audit("request_password_reset", {"user_id": str(user_agg.id)})
        logger.info("Password reset token issued for user %s", user_agg.id)

        return {
            "message": generic_message,
            "reset_token": token,
            "reset_url": f"/reset-password?token={token}",
        }

    async def confirm_password_reset(self, token: str, new_password: str) -> None:
        token_hash = self._hash_reset_token(token)
        user_agg = await self._iam_repo.get_by_password_reset_token_hash(token_hash)

        if not user_agg or not user_agg.password_reset_token_hash:
            raise AuthenticationError("Token reset password tidak valid atau sudah dipakai")

        expires_at = user_agg.password_reset_expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at is None or expires_at < datetime.now(UTC):
            raise AuthenticationError("Token reset password sudah kedaluwarsa, minta link baru")

        await self._iam_repo.set_password_direct(user_agg.id, new_password)
        await self._commit()

        self._record_audit("confirm_password_reset", {"user_id": str(user_agg.id)})
        logger.info("Password reset confirmed via token for user %s", user_agg.id)

    # ========================================================================
    # Permissions
    # ========================================================================

    async def get_user_permissions(self, user_id: UUID) -> set[str]:
        iam = await self._iam_repo.get()
        return iam.get_user_permissions(user_id)

    async def has_permission(self, user_id: UUID, permission: str) -> bool:
        iam = await self._iam_repo.get()
        return iam.has_permission(user_id, permission)

    # ========================================================================
    # Queries
    # ========================================================================

    async def list_users(self, legal_entity_id: UUID | None = None, status: UserStatus | None = None,
                         limit: int = 100, offset: int = 0) -> list[UserEntity]:
        iam = await self._iam_repo.get()
        users = list(iam.users.values())
        if legal_entity_id:
            users = [u for u in users if u.legal_entity_id == legal_entity_id]
        if status:
            users = [u for u in users if u.status == status]
        users.sort(key=lambda u: u.audit.created_at, reverse=True)
        return users[offset:offset+limit]

    async def get_user_by_username(self, username: str) -> UserEntity | None:
        iam = await self._iam_repo.get()
        for user in iam.users.values():
            if user.username == username:
                return user
        return None

    async def get_user_by_email(self, email: str) -> UserEntity | None:
        iam = await self._iam_repo.get()
        for user in iam.users.values():
            if user.email == email:
                return user
        return None

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


async def create_iam_service(
    iam_repo: IAMRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
    token_issuer: TokenIssuerPort | None = None,
    cache: CachePort | None = None,
) -> IAMService:
    return IAMService(iam_repo, uow, event_publisher, token_issuer, cache)


__all__ = [
    "AuthenticationError",
    "CreateRoleRequest",
    "CreateUserRequest",
    "IAMService",
    "IAMServiceError",
    "LoginResponse",
    "PermissionDeniedError",
    "RoleNotFoundError",
    "RoleResponse",
    "UpdateRoleRequest",
    "UserNotFoundError",
    "UserResponse",
    "create_iam_service",
]

