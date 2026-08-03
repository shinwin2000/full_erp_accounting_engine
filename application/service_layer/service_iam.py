#!/usr/bin/env python3
"""
Module: service_iam.py
Layer: Application / Service Layer
Responsibility: IAM service (identity and access management).
               Memperbaiki: set_context(), login(), authenticate(),
               dan konversi UserAggregate -> UserEntity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

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
from domain.iam.password_hashed_vo import PasswordHashedVO
from domain.iam.permission_vo import PermissionVO
from domain.iam.role_entity import RoleEntity
from domain.iam.user_entity import UserAudit, UserEntity, UserProfile, UserStatus
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.iam_repository_port import IAMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


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
        if hasattr(self._iam_repo, "set_session"):
            self._iam_repo.set_session(session)
        else:
            logger.warning("Repository does not support set_session")

        if hasattr(self._iam_repo, "set_legal_entity_id"):
            self._iam_repo.set_legal_entity_id(legal_entity_id)
        else:
            logger.warning("Repository does not support set_legal_entity_id")

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
        """Convert UserAggregate to proper UserEntity with profile and audit."""
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
            mfa_enabled=False,
            mfa_secret=None,
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

        password_hash = PasswordHashedVO.from_plain(request.password)
        # Buat UserEntity langsung (untuk ditambahkan ke IAM)
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

        # Convert ke UserAggregate untuk repository
        user_agg = UserAggregate(
            id=user_entity.user_id,
            username=user_entity.username,
            email=user_entity.email,
            full_name=user_entity.profile.full_name,
            hashed_password=user_entity.password_hash.hash,
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
        await self._uow.commit()

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

        # Ambil data dari user entity
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

        # Update UserAggregate
        agg = UserAggregate(
            id=user.user_id,
            username=user.username,
            email=new_email,
            full_name=new_full_name,
            hashed_password=user.password_hash.hash,
            status=user.status,
            is_superuser=user.is_superuser if hasattr(user, 'is_superuser') else False,
            is_active=user.is_active if hasattr(user, 'is_active') else True,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password if hasattr(user, 'must_change_password') else False,
            password_changed_at=user.audit.last_password_change_at,
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version + 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._uow.commit()

        self._stats["users_updated"] += 1

        # Konversi kembali ke UserEntity untuk return
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
            hashed_password=user.password_hash.hash,
            status=UserStatus.ACTIVE,
            is_superuser=user.is_superuser if hasattr(user, 'is_superuser') else False,
            is_active=True,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password if hasattr(user, 'must_change_password') else False,
            password_changed_at=user.audit.last_password_change_at,
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version + 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._uow.commit()

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
            hashed_password=user.password_hash.hash,
            status=UserStatus.INACTIVE,
            is_superuser=user.is_superuser if hasattr(user, 'is_superuser') else False,
            is_active=False,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password if hasattr(user, 'must_change_password') else False,
            password_changed_at=user.audit.last_password_change_at,
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version + 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._uow.commit()

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
        self._check_authority(locked_by, "lock_user")
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        if user.locked_until and user.locked_until > datetime.now(UTC):
            return

        # Lock via repository method
        await self._iam_repo.lock_user(user_id, locked_by, reason)
        await self._uow.commit()

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
        await self._uow.commit()

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
            hashed_password=user.password_hash.hash,
            status=UserStatus.SUSPENDED,
            is_superuser=user.is_superuser if hasattr(user, 'is_superuser') else False,
            is_active=False,
            last_login_at=user.audit.last_login_at,
            last_login_ip=user.audit.last_login_ip,
            failed_login_count=user.failed_login_attempts,
            locked_until=user.locked_until,
            must_change_password=user.must_change_password if hasattr(user, 'must_change_password') else False,
            password_changed_at=user.audit.last_password_change_at,
            created_at=user.audit.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.audit.created_by,
            version=user.audit.version + 1,
            legal_entity_ids=[user.legal_entity_id] if user.legal_entity_id else [],
            role_ids=user.role_ids,
        )
        await self._iam_repo.update(agg)
        await self._uow.commit()

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
        await self._uow.commit()

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

        perm_objects = [PermissionVO(name=p) for p in request.permissions]
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

        # Convert to domain Role for repository
        from domain.iam.role_entity import Role as DomainRole
        domain_role = DomainRole(
            id=role.role_id,
            name=role.role_name,
            description=role.description,
            permissions=[PermissionVO(name=p) for p in request.permissions],
            created_at=role.created_at,
            created_by=request.created_by,
        )
        await self._iam_repo.create_role(
            role_code=role.role_name,
            role_name=role.role_name,
            permissions=[PermissionVO(name=p) for p in request.permissions],
            created_by=request.created_by or UUID(int=0),
            description=role.description,
        )
        await self._uow.commit()

        self._stats["roles_created"] += 1

        if self._event_publisher:
            event_role = RoleCreatedEvent(
                aggregate_id=role.role_id,
                aggregate_version=role.version,
                role_id=role.role_id,
                role_name=role.role_name,
                description=role.description,
                permissions=[p.name for p in role.permissions],
                is_default=role.is_default,
                is_system=role.is_system,
                parent_role_id=role.parent_role_id,
                created_by=str(request.created_by) if request.created_by else None,
                user_id=str(request.created_by) if request.created_by else None,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event_role)

            for perm in role.permissions:
                event_perm = PermissionGrantedEvent(
                    aggregate_id=role.role_id,
                    aggregate_version=role.version,
                    permission_name=perm.name,
                    granted_to=role.role_name,
                    granted_by=str(request.created_by) if request.created_by else None,
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

    async def update_role(self, role_id: UUID, request: UpdateRoleRequest, updated_by: UUID,
                          correlation_id: str | None = None) -> RoleEntity:
        self._check_authority(updated_by, "update_role")
        iam = await self._iam_repo.get()
        role = iam.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")
        if role.is_system:
            raise IAMServiceError("Cannot update system role")

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
            old_perms = {p.name for p in role.permissions}
            new_perms = set(request.permissions)
            added = new_perms - old_perms
            removed = old_perms - new_perms
            if added or removed:
                changes["permissions"] = {"old": list(old_perms), "new": list(new_perms)}
                role.permissions = [PermissionVO(name=p) for p in new_perms]
                for perm in added:
                    event = PermissionGrantedEvent(
                        aggregate_id=role.role_id,
                        aggregate_version=role.version + 1,
                        permission_name=perm,
                        granted_to=role.role_name,
                        granted_by=str(updated_by),
                        user_id=str(updated_by),
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)
                for perm in removed:
                    event = PermissionRevokedEvent(
                        aggregate_id=role.role_id,
                        aggregate_version=role.version + 1,
                        permission_name=perm,
                        revoked_from=role.role_name,
                        revoked_by=str(updated_by),
                        user_id=str(updated_by),
                        correlation_id=correlation_id,
                    )
                    await self._event_publisher.publish(event)

        if not changes:
            return role

        # Update via repository
        await self._iam_repo.update_role(
            role_id=role_id,
            new_name=request.role_name or role.role_name,
            new_permissions=role.permissions,
            updated_by=updated_by,
        )
        await self._uow.commit()

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
        await self._uow.commit()

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
        await self._uow.commit()

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
        await self._uow.commit()

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
        ip_address: str | None = None,
        user_agent: str | None = None,
        correlation_id: str | None = None,
    ) -> LoginResponse:
        if self._token_issuer is None:
            raise AuthenticationError("Token issuer not configured")

        # Repository authenticate mengembalikan UserAggregate
        user_agg = await self._iam_repo.authenticate(
            username=username,
            password=password,
            ip_address=ip_address or "0.0.0.0",
            legal_entity_id=legal_entity_id,
        )

        if not user_agg:
            self._stats["login_failures"] += 1
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

        # Konversi UserAggregate ke UserEntity
        user = self._to_user_entity(user_agg)

        if user.status != UserStatus.ACTIVE:
            self._stats["login_failures"] += 1
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

        # Dapatkan permissions dari IAM aggregate
        iam = await self._iam_repo.get()
        all_perms = iam.get_user_permissions(user.user_id)
        role_names = []
        for rid in user.role_ids:
            role = iam.roles.get(rid)
            if role:
                role_names.append(role.role_name)

        access_token = await self._token_issuer.create_access_token(
            user_id=user.user_id,
            username=user.username,
            legal_entity_id=user.legal_entity_id,
            roles=role_names,
            permissions=list(all_perms),
        )
        refresh_token = await self._token_issuer.create_refresh_token(
            user_id=user.user_id,
            username=user.username,
            legal_entity_id=user.legal_entity_id,
            roles=role_names,
            permissions=list(all_perms),
        )

        self._stats["logins"] += 1

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

        logger.info("Access issued")
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=3600,
            user=user,
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

        # Verify password via repository or aggregate
        if not user.password_hash.verify(old_password):
            raise AuthenticationError("Old password is incorrect")

        # Update password via repository
        await self._iam_repo.change_password(
            user_id=user_id,
            old_password=old_password,
            new_password=new_password,
            actor_id=changed_by,
        )
        await self._uow.commit()

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

        # Use repository's change_password with force mode (old_password empty)
        await self._iam_repo.change_password(
            user_id=user_id,
            old_password="",
            new_password=new_password,
            actor_id=reset_by,
        )
        await self._uow.commit()

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
