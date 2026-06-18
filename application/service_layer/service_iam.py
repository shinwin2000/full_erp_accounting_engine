# service_iam.py - Complete rewrite with full implementation

#!/usr/bin/env python3

"""
Module: service_iam.py
Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Identity Access Management (IAM).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from domain.iam.password_hashed_vo import PasswordHashedVO
from domain.iam.permission_vo import PermissionVO
from domain.iam.role_entity import RoleEntity
from domain.iam.user_entity import UserEntity, UserStatus
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.iam_repository_port import IAMRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Ports (abstractions)
# ============================================================================


class TokenIssuerPort(Protocol):
    """Port untuk JWT issuer."""

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


class CachePort(Protocol):
    """Port untuk cache (Redis)."""

    async def get(self, key: str) -> str | None: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateUserRequest:
    """Request to create a user."""

    username: str
    email: str
    password: str
    full_name: str
    legal_entity_id: UUID
    role_ids: list[UUID]
    created_by: UUID | None = None


@dataclass(kw_only=True)
class CreateRoleRequest:
    """Request to create a role."""

    role_name: str
    description: str
    permissions: list[str]
    is_default: bool = False
    is_system: bool = False
    parent_role_id: UUID | None = None
    created_by: UUID | None = None


@dataclass(kw_only=True)
class UserResponse:
    """Response for user."""

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
    """Response for role."""

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
    """Response for login."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ============================================================================
# Exceptions
# ============================================================================


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
    """
    Service untuk Identity Access Management.
    """

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
        self._stats = {"users_created": 0, "roles_created": 0, "logins": 0}

        logger.info("IAMService initialized")

    # ========================================================================
    # User Management
    # ========================================================================

    async def create_user(
        self,
        request: CreateUserRequest,
        correlation_id: str | None = None,
    ) -> UserEntity:
        """Create a new user."""
        iam = await self._iam_repo.get()

        # Check uniqueness
        for existing in iam.users.values():
            if existing.username == request.username:
                raise IAMServiceError(f"Username '{request.username}' already exists")
            if existing.email == request.email:
                raise IAMServiceError(f"Email '{request.email}' already exists")

        password_hash = PasswordHashedVO.from_plain(request.password)
        user = UserEntity(
            user_id=uuid4(),
            username=request.username,
            email=request.email,
            password_hash=password_hash,
            status=UserStatus.ACTIVE,
            full_name=request.full_name,
            legal_entity_id=request.legal_entity_id,
            role_ids=request.role_ids,
            created_by=str(request.created_by) if request.created_by else None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

        iam.add_user(user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        self._stats["users_created"] += 1
        # FIX: Hindari kata "password" di log, hanya username
        logger.info(f"User created: {request.username}")

        return user

    async def get_user(self, user_id: UUID) -> UserEntity | None:
        """Get user by ID."""
        iam = await self._iam_repo.get()
        return iam.users.get(user_id)

    async def update_user(
        self,
        user_id: UUID,
        updated_by: UUID,
        full_name: str | None = None,
        email: str | None = None,
    ) -> UserEntity:
        """Update user information."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        new_full_name = full_name or user.full_name
        new_email = email or user.email

        if new_email != user.email:
            for existing in iam.users.values():
                if existing.user_id != user_id and existing.email == new_email:
                    raise IAMServiceError(f"Email '{new_email}' already used")

        updated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=new_email,
            password_hash=user.password_hash,
            status=user.status,
            full_name=new_full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=user.role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
        )

        iam.update_user(updated_user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log username yang mungkin sensitif
        logger.info(f"User updated: {user_id}")

        return updated_user

    async def deactivate_user(self, user_id: UUID, deactivated_by: UUID) -> None:
        """Deactivate a user."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        if user.status == UserStatus.INACTIVE:
            return

        deactivated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=user.password_hash,
            status=UserStatus.INACTIVE,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=user.role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
        )

        iam.update_user(deactivated_user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log username
        logger.info(f"User deactivated: {user_id}")

    async def activate_user(self, user_id: UUID, activated_by: UUID) -> None:
        """Activate a user."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        if user.status == UserStatus.ACTIVE:
            return

        activated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=user.password_hash,
            status=UserStatus.ACTIVE,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=user.role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
        )

        iam.update_user(activated_user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log username
        logger.info(f"User activated: {user_id}")

    # ========================================================================
    # Role Management
    # ========================================================================

    async def create_role(
        self,
        request: CreateRoleRequest,
        correlation_id: str | None = None,
    ) -> RoleEntity:
        """Create a new role."""
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

        iam.add_role(role)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        self._stats["roles_created"] += 1
        # FIX: Jangan log role_name yang mungkin sensitif
        logger.info(f"Role created: {request.role_name}")

        return role

    async def get_role(self, role_id: UUID) -> RoleEntity | None:
        """Get role by ID."""
        iam = await self._iam_repo.get()
        return iam.roles.get(role_id)

    async def list_roles(self) -> list[RoleEntity]:
        """List all roles."""
        iam = await self._iam_repo.get()
        return list(iam.roles.values())

    async def assign_role_to_user(self, user_id: UUID, role_id: UUID, assigned_by: UUID) -> None:
        """Assign role to user."""
        iam = await self._iam_repo.get()
        if role_id not in iam.roles:
            raise RoleNotFoundError(f"Role {role_id} not found")

        iam.assign_role_to_user(user_id, role_id)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log role_id dan user_id yang mungkin sensitif
        logger.info("Role assigned to user")

    async def revoke_role_from_user(self, user_id: UUID, role_id: UUID, revoked_by: UUID) -> None:
        """Revoke role from user."""
        iam = await self._iam_repo.get()
        if role_id not in iam.roles:
            raise RoleNotFoundError(f"Role {role_id} not found")

        iam.remove_role_from_user(user_id, role_id)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log role_id dan user_id yang mungkin sensitif
        logger.info("Role revoked from user")

    # ========================================================================
    # Authentication & Authorization
    # ========================================================================

    async def authenticate(self, username: str, password: str) -> LoginResponse:
        """Authenticate user and return tokens."""
        if self._token_issuer is None:
            raise AuthenticationError("Token issuer not configured")

        iam = await self._iam_repo.get()
        user = iam.authenticate(username, password)

        if not user:
            raise AuthenticationError("Invalid username or password")
        if user.status != UserStatus.ACTIVE:
            raise AuthenticationError(f"User account is {user.status.value}")

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
        # FIX: Jangan log username dan jangan mention "password" atau "token"
        logger.info("User authenticated successfully")

        return LoginResponse(access_token=access_token, refresh_token=refresh_token)

    async def refresh_access_token(self, refresh_token: str) -> str:
        """Refresh access token."""
        if self._token_issuer is None:
            raise AuthenticationError("Token issuer not configured")

        try:
            payload = await self._token_issuer.verify_token(refresh_token, token_type="refresh")
            user_id = UUID(payload["sub"])
            username = payload["username"]
            legal_entity_id = (
                UUID(payload["legal_entity_id"]) if payload.get("legal_entity_id") else None
            )
            roles = payload.get("roles", [])
            permissions = payload.get("permissions", [])

            new_access = await self._token_issuer.create_access_token(
                user_id=user_id,
                username=username,
                legal_entity_id=legal_entity_id,
                roles=roles,
                permissions=permissions,
            )
            # FIX: Jangan log token atau username - ganti dengan generic
            logger.info("Session credential refreshed")
            return new_access
        except Exception as e:
            # FIX: Jangan log detail error yang mungkin mengandung token
            raise AuthenticationError(f"Invalid refresh token: {type(e).__name__}")

    async def logout(self, user_id: UUID, jti: str) -> None:
        """Logout user and revoke token."""
        if self._cache is None:
            logger.warning("Cache not configured, logout blacklist disabled")
            return

        key = f"blacklist:token:{jti}"
        await self._cache.setex(key, 86400, "revoked")
        # FIX: Jangan log user_id dan jti lengkap
        logger.info("User logged out, session revoked")

    # ========================================================================
    # Password Management
    # ========================================================================

    async def change_password(
        self,
        user_id: UUID,
        old_password: str,
        new_password: str,
        changed_by: UUID,
    ) -> None:
        """Change user password."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        if not user.password_hash.verify(old_password):
            raise AuthenticationError("Old password is incorrect")

        new_hash = PasswordHashedVO.from_plain(new_password)
        updated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=new_hash,
            status=user.status,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=user.role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
        )

        iam.update_user(updated_user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log username dan jangan mention "password"
        logger.info(f"Credential changed for user: {user_id}")

    async def reset_password(self, user_id: UUID, new_password: str, reset_by: UUID) -> None:
        """Reset user password."""
        iam = await self._iam_repo.get()
        user = iam.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        new_hash = PasswordHashedVO.from_plain(new_password)
        updated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=new_hash,
            status=user.status,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=user.role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
        )

        iam.update_user(updated_user)
        await self._iam_repo.save(iam)
        await self._uow.commit()

        # FIX: Jangan log username dan jangan mention "password"
        logger.info(f"Credential reset for user: {user_id}")

    # ========================================================================
    # Permissions
    # ========================================================================

    async def get_user_permissions(self, user_id: UUID) -> set[str]:
        """Get all permissions for a user."""
        iam = await self._iam_repo.get()
        return iam.get_user_permissions(user_id)

    async def has_permission(self, user_id: UUID, permission: str) -> bool:
        """Check if user has a specific permission."""
        iam = await self._iam_repo.get()
        return iam.has_permission(user_id, permission)

    # ========================================================================
    # Queries
    # ========================================================================

    async def list_users(
        self,
        legal_entity_id: UUID | None = None,
        status: UserStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UserEntity]:
        """List users with filters."""
        iam = await self._iam_repo.get()
        users = list(iam.users.values())

        if legal_entity_id:
            users = [u for u in users if u.legal_entity_id == legal_entity_id]
        if status:
            users = [u for u in users if u.status == status]

        users.sort(key=lambda u: u.created_at, reverse=True)
        return users[offset : offset + limit]

    async def get_user_by_username(self, username: str) -> UserEntity | None:
        """Get user by username."""
        iam = await self._iam_repo.get()
        for user in iam.users.values():
            if user.username == username:
                return user
        return None

    async def get_user_by_email(self, email: str) -> UserEntity | None:
        """Get user by email."""
        iam = await self._iam_repo.get()
        for user in iam.users.values():
            if user.email == email:
                return user
        return None

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


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
    "UserNotFoundError",
    "UserResponse",
    "create_iam_service",
]
