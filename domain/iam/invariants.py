#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / IAM
Responsibility: Invariants untuk Identity Access Management.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domain.iam.role_entity import RoleEntity, RoleStatus
from domain.iam.session_entity import SessionEntity, SessionStatus
from domain.iam.user_entity import UserEntity, UserStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Result
# ============================================================================


@dataclass
class InvariantResult:
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> InvariantResult:
        return cls(is_valid=True, warnings=warnings or [])

    @classmethod
    def failure(cls, error: str, warnings: list[str] | None = None) -> InvariantResult:
        result = cls(is_valid=False, warnings=warnings or [])
        result.add_error(error)
        return result


# ============================================================================
# Common Validators
# ============================================================================


def validate_username(username: str) -> InvariantResult:
    """Validate username format."""
    if not username or not isinstance(username, str):
        return InvariantResult.failure("Username must be a non-empty string")
    cleaned = username.strip()
    if len(cleaned) < 3:
        return InvariantResult.failure("Username must be at least 3 characters")
    if len(cleaned) > 50:
        return InvariantResult.failure("Username must not exceed 50 characters")
    if not re.match(r"^[a-zA-Z0-9_]+$", cleaned):
        return InvariantResult.failure(
            "Username must contain only letters, numbers, and underscores"
        )
    return InvariantResult.success()


def validate_email(email: str) -> InvariantResult:
    """Validate email format."""
    if not email or not isinstance(email, str):
        return InvariantResult.failure("Email must be a non-empty string")
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email):
        return InvariantResult.failure(f"Invalid email format: {email}")
    return InvariantResult.success()


def validate_full_name(full_name: str) -> InvariantResult:
    """Validate full name."""
    if not full_name or not isinstance(full_name, str):
        return InvariantResult.failure("Full name must be a non-empty string")
    cleaned = full_name.strip()
    if len(cleaned) < 2:
        return InvariantResult.failure("Full name must be at least 2 characters")
    if len(cleaned) > 200:
        return InvariantResult.failure("Full name must not exceed 200 characters")
    return InvariantResult.success()


def validate_version(version: int, expected_version: int | None = None) -> InvariantResult:
    """Validate version number."""
    if version < 1:
        return InvariantResult.failure(f"Version must be >= 1, got {version}")
    if expected_version is not None and version != expected_version:
        return InvariantResult.failure(
            f"Version mismatch: expected {expected_version}, got {version}"
        )
    return InvariantResult.success()


def validate_date_not_future(dt: datetime, field_name: str = "Date") -> InvariantResult:
    """Validate that datetime is not in the future."""
    if dt > datetime.now(UTC):
        return InvariantResult.failure(f"{field_name} cannot be in the future: {dt}")
    return InvariantResult.success()


# ============================================================================
# User Invariants
# ============================================================================


class UserInvariants:
    @staticmethod
    def validate_on_create(
        username: str,
        email: str,
        full_name: str,
        existing_usernames: set[str],
        existing_emails: set[str],
    ) -> InvariantResult:
        result = InvariantResult()
        result.merge(validate_username(username))
        result.merge(validate_email(email))
        result.merge(validate_full_name(full_name))

        if username in existing_usernames:
            result.add_error(f"Username '{username}' already exists")
        if email in existing_emails:
            result.add_error(f"Email '{email}' already exists")

        return result

    @staticmethod
    def validate_on_update(
        user: UserEntity,
        existing_usernames: set[str],
        existing_emails: set[str],
    ) -> InvariantResult:
        result = InvariantResult()
        result.merge(validate_username(user.username))
        result.merge(validate_email(user.email))
        result.merge(validate_full_name(user.profile.full_name))

        if user.username in existing_usernames:
            result.add_error(f"Username '{user.username}' already exists")
        if user.email in existing_emails:
            result.add_error(f"Email '{user.email}' already exists")

        return result

    @staticmethod
    def validate_status_transition(
        current_status: UserStatus,
        new_status: UserStatus,
        user_id: str,
        acting_user_id: str,
        is_self: bool = False,
    ) -> InvariantResult:
        result = InvariantResult()

        if new_status == UserStatus.ACTIVE:
            if current_status == UserStatus.PENDING_ACTIVATION and is_self:
                result.add_error("User cannot activate own account")
            if current_status == UserStatus.SUSPENDED:
                result.add_error("Suspended user must be unsuspended first")
            if current_status == UserStatus.LOCKED:
                result.add_error("Locked user must be unlocked first")

        if new_status in (UserStatus.INACTIVE, UserStatus.SUSPENDED):
            if is_self:
                result.add_error("User cannot deactivate or suspend own account")

        allowed_transitions = {
            UserStatus.PENDING_ACTIVATION: {UserStatus.ACTIVE, UserStatus.INACTIVE},
            UserStatus.ACTIVE: {UserStatus.INACTIVE, UserStatus.SUSPENDED, UserStatus.LOCKED},
            UserStatus.INACTIVE: {UserStatus.ACTIVE},
            UserStatus.LOCKED: {UserStatus.ACTIVE},
            UserStatus.SUSPENDED: {UserStatus.ACTIVE},
            UserStatus.DELETED: set(),
        }
        if new_status not in allowed_transitions.get(current_status, set()):
            result.add_error(f"Cannot transition from {current_status.value} to {new_status.value}")

        return result


# ============================================================================
# Role Invariants
# ============================================================================


class RoleInvariants:
    @staticmethod
    def validate_on_create(
        role_name: str,
        existing_role_names: set[str],
        parent_role_id: str | None = None,
    ) -> InvariantResult:
        result = InvariantResult()

        if not role_name or len(role_name.strip()) < 2:
            result.add_error("Role name must be at least 2 characters")
        if len(role_name) > 50:
            result.add_error("Role name must not exceed 50 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", role_name):
            result.add_error("Role name must contain only letters, numbers, and underscores")

        if role_name in existing_role_names:
            result.add_error(f"Role name '{role_name}' already exists")

        return result

    @staticmethod
    def validate_on_update(
        role: RoleEntity,
        existing_role_names: set[str],
    ) -> InvariantResult:
        result = InvariantResult()

        if role.is_system and role.role_name in existing_role_names:
            result.add_error(f"Cannot rename system role '{role.role_name}'")

        return result

    @staticmethod
    def validate_on_delete(
        role: RoleEntity,
        assigned_user_count: int,
    ) -> InvariantResult:
        result = InvariantResult()

        if role.is_system:
            result.add_error(f"Cannot delete system role '{role.role_name}'")

        if role.is_default:
            result.add_error(f"Cannot delete default role '{role.role_name}'")

        if assigned_user_count > 0:
            result.add_error(
                f"Role '{role.role_name}' is assigned to {assigned_user_count} user(s)"
            )

        return result

    @staticmethod
    def validate_parent(
        role: RoleEntity,
        parent_role: RoleEntity | None,
    ) -> InvariantResult:
        result = InvariantResult()

        if parent_role and parent_role.status != RoleStatus.ACTIVE:
            result.add_error(f"Parent role '{parent_role.role_name}' is not active")

        if parent_role and parent_role.role_id == role.role_id:
            result.add_error("Role cannot be its own parent")

        return result

    @staticmethod
    def validate_hierarchy_cycle(
        role_id: UUID,
        parent_role_id: UUID | None,
        get_parent_func: Callable[[UUID], RoleEntity | None],
    ) -> InvariantResult:
        result = InvariantResult()

        if parent_role_id:
            current = parent_role_id
            visited = set()
            while current and current not in visited:
                if current == role_id:
                    result.add_error("Setting this parent would create a cycle")
                    break
                visited.add(current)
                parent = get_parent_func(current)
                current = parent.role_id if parent else None

        return result


# ============================================================================
# Session Invariants
# ============================================================================


class SessionInvariants:
    @staticmethod
    def validate_session_creation(
        user: UserEntity,
        device_type: str,
    ) -> InvariantResult:
        result = InvariantResult()

        if not user.is_active():
            result.add_error(f"Cannot create session for user with status {user.status.value}")

        if user.is_locked():
            result.add_error("User account is locked")

        return result

    @staticmethod
    def validate_session_renewal(session: SessionEntity) -> InvariantResult:
        result = InvariantResult()

        if not session.can_refresh():
            if session.is_expired():
                result.add_error("Session has expired")
            elif session.is_refresh_expired():
                result.add_error("Refresh token has expired")
            else:
                result.add_error(f"Cannot refresh session in status {session.status.value}")

        return result

    @staticmethod
    def validate_session_revocation(session: SessionEntity) -> InvariantResult:
        result = InvariantResult()

        if session.status == SessionStatus.REVOKED:
            result.add_warning("Session is already revoked")

        return result


# ============================================================================
# IAM Invariant Enforcer
# ============================================================================


class IAMInvariantEnforcer:
    def __init__(
        self,
        existing_usernames_provider: Callable[[], set[str]] | None = None,
        existing_emails_provider: Callable[[], set[str]] | None = None,
        existing_role_names_provider: Callable[[], set[str]] | None = None,
        get_parent_role_func: Callable[[UUID], RoleEntity | None] | None = None,
    ):
        self._usernames_provider = existing_usernames_provider or (lambda: set())
        self._emails_provider = existing_emails_provider or (lambda: set())
        self._role_names_provider = existing_role_names_provider or (lambda: set())
        self._get_parent_role = get_parent_role_func
        self._user_invariants = UserInvariants()
        self._role_invariants = RoleInvariants()
        self._session_invariants = SessionInvariants()

    async def enforce_user_create(
        self,
        username: str,
        email: str,
        full_name: str,
    ) -> InvariantResult:
        existing_usernames = await self._usernames_provider()
        existing_emails = await self._emails_provider()
        return self._user_invariants.validate_on_create(
            username=username,
            email=email,
            full_name=full_name,
            existing_usernames=existing_usernames,
            existing_emails=existing_emails,
        )

    async def enforce_user_update(
        self,
        user: UserEntity,
    ) -> InvariantResult:
        existing_usernames = await self._usernames_provider()
        existing_emails = await self._emails_provider()
        existing_usernames.discard(user.username)
        existing_emails.discard(user.email)
        return self._user_invariants.validate_on_update(
            user=user,
            existing_usernames=existing_usernames,
            existing_emails=existing_emails,
        )

    async def enforce_user_status_transition(
        self,
        current_status: UserStatus,
        new_status: UserStatus,
        user_id: str,
        acting_user_id: str,
        is_self: bool = False,
    ) -> InvariantResult:
        return self._user_invariants.validate_status_transition(
            current_status=current_status,
            new_status=new_status,
            user_id=user_id,
            acting_user_id=acting_user_id,
            is_self=is_self,
        )

    async def enforce_role_create(
        self,
        role_name: str,
        parent_role_id: UUID | None = None,
    ) -> InvariantResult:
        existing_role_names = await self._role_names_provider()
        return self._role_invariants.validate_on_create(
            role_name=role_name,
            existing_role_names=existing_role_names,
            parent_role_id=str(parent_role_id) if parent_role_id else None,
        )

    async def enforce_role_update(
        self,
        role: RoleEntity,
    ) -> InvariantResult:
        existing_role_names = await self._role_names_provider()
        existing_role_names.discard(role.role_name)
        return self._role_invariants.validate_on_update(
            role=role,
            existing_role_names=existing_role_names,
        )

    async def enforce_role_delete(
        self,
        role: RoleEntity,
        assigned_user_count: int,
    ) -> InvariantResult:
        return self._role_invariants.validate_on_delete(
            role=role,
            assigned_user_count=assigned_user_count,
        )

    async def enforce_role_parent(
        self,
        role: RoleEntity,
        parent_role: RoleEntity | None,
    ) -> InvariantResult:
        result = self._role_invariants.validate_parent(role, parent_role)

        if result.is_valid and self._get_parent_role:
            result.merge(
                self._role_invariants.validate_hierarchy_cycle(
                    role.role_id,
                    role.parent_role_id,
                    self._get_parent_role,
                )
            )

        return result

    async def enforce_session_creation(
        self,
        user: UserEntity,
        device_type: str,
    ) -> InvariantResult:
        return self._session_invariants.validate_session_creation(user, device_type)

    async def enforce_session_renewal(
        self,
        session: SessionEntity,
    ) -> InvariantResult:
        return self._session_invariants.validate_session_renewal(session)

    async def enforce_session_revocation(
        self,
        session: SessionEntity,
    ) -> InvariantResult:
        return self._session_invariants.validate_session_revocation(session)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "IAMInvariantEnforcer",
    "InvariantResult",
    "RoleInvariants",
    "SessionInvariants",
    "UserInvariants",
    "validate_date_not_future",
    "validate_email",
    "validate_full_name",
    "validate_username",
    "validate_version",
]
