#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / IAM
Responsibility: Aggregate root untuk Identity Access Management dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.iam.domain_events import (
    DomainEvent,
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
from domain.iam.permission_vo import PermissionVO
from domain.iam.role_entity import RoleEntity
from domain.iam.session_entity import SessionEntity
from domain.iam.user_entity import UserEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class IAMStatus(Enum):
    ACTIVE = "active"
    LOCKDOWN = "lockdown"
    MAINTENANCE = "maintenance"

    def display_name(self) -> str:
        names = {
            IAMStatus.ACTIVE: "Aktif",
            IAMStatus.LOCKDOWN: "Terkunci",
            IAMStatus.MAINTENANCE: "Pemeliharaan",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class IAMError(ValueError):
    pass


class UserNotFoundError(IAMError):
    pass


class RoleNotFoundError(IAMError):
    pass


class DuplicateUsernameError(IAMError):
    pass


class DuplicateEmailError(IAMError):
    pass


class DuplicateRoleNameError(IAMError):
    pass


class InsufficientPermissionsError(IAMError):
    pass


class AuthenticationError(IAMError):
    pass


# ============================================================================
# IAM Aggregate Root
# ============================================================================


@dataclass
class IAM:
    iam_id: UUID
    legal_entity_id: UUID
    status: IAMStatus = IAMStatus.ACTIVE
    users: dict[UUID, UserEntity] = field(default_factory=dict)
    roles: dict[UUID, RoleEntity] = field(default_factory=dict)
    sessions: dict[UUID, SessionEntity] = field(default_factory=dict)
    permissions: dict[str, PermissionVO] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    _events: ClassVar[list[DomainEvent]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._take_snapshot()
        if not self.roles:
            self._init_default_roles()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "iam_id": str(self.iam_id),
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.value,
            "user_count": len(self.users),
            "role_count": len(self.roles),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "iam_id": str(self.iam_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def _init_default_roles(self) -> None:
        """Initialize default system roles."""
        now = datetime.now(UTC)

        super_admin = RoleEntity(
            role_id=uuid4(),
            role_name="super_admin",
            description="Super Administrator with full system access",
            permissions={"*:*"},
            is_default=False,
            is_system=True,
            created_at=now,
            created_by="system",
            version=1,
        )
        self.roles[super_admin.role_id] = super_admin

        admin = RoleEntity(
            role_id=uuid4(),
            role_name="admin",
            description="Administrator with extensive permissions",
            permissions={"user:*", "role:*", "permission:*", "system_config:*", "audit:*"},
            is_default=False,
            is_system=True,
            created_at=now,
            created_by="system",
            version=1,
        )
        self.roles[admin.role_id] = admin

        user_role = RoleEntity(
            role_id=uuid4(),
            role_name="user",
            description="Standard user with basic permissions",
            permissions={
                "journal:create",
                "journal:read",
                "invoice:create",
                "invoice:read",
                "payment:create",
                "payment:read",
                "customer:read",
                "supplier:read",
                "report:read",
            },
            is_default=True,
            is_system=True,
            created_at=now,
            created_by="system",
            version=1,
        )
        self.roles[user_role.role_id] = user_role

        auditor = RoleEntity(
            role_id=uuid4(),
            role_name="auditor",
            description="Auditor with read-only access to audit trails",
            permissions={"journal:read", "account:read", "audit:*", "report:export"},
            is_default=False,
            is_system=True,
            created_at=now,
            created_by="system",
            version=1,
        )
        self.roles[auditor.role_id] = auditor

        approver = RoleEntity(
            role_id=uuid4(),
            role_name="approver",
            description="Approver for journals and invoices",
            permissions={
                "journal:read",
                "journal:approve",
                "journal:reject",
                "invoice:read",
                "invoice:approve",
                "invoice:reject",
                "payment:read",
                "payment:approve",
            },
            is_default=False,
            is_system=True,
            created_at=now,
            created_by="system",
            version=1,
        )
        self.roles[approver.role_id] = approver

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> IAM:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> IAM:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("iam_id", "created_at", "created_by", "version"):
                data[key] = value
        new_iam = IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=IAMStatus(data.get("status", self.status.value)),
            users=self.users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )
        new_iam._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_iam

    def delete(self, deleted_by: str, reason: str | None = None) -> IAM:
        if len(self.users) > 0:
            raise IAMError("Cannot delete IAM aggregate with existing users")
        new_iam = self._copy()
        new_iam.status = IAMStatus.LOCKDOWN
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_iam

    def restore(self, restored_by: str) -> IAM:
        new_iam = self._copy()
        new_iam.status = IAMStatus.ACTIVE
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("RESTORE", restored_by, {})
        return new_iam

    def activate(self, activated_by: str) -> IAM:
        if self.status == IAMStatus.ACTIVE:
            return self
        new_iam = self._copy()
        new_iam.status = IAMStatus.ACTIVE
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("ACTIVATE", activated_by, {})
        return new_iam

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IAM:
        new_iam = self._copy()
        new_iam.status = IAMStatus.MAINTENANCE
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_iam

    def lock(self, locked_by: str, reason: str) -> IAM:
        new_iam = self._copy()
        new_iam.status = IAMStatus.LOCKDOWN
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("LOCK", locked_by, {"reason": reason})
        return new_iam

    def unlock(self, unlocked_by: str) -> IAM:
        if self.status != IAMStatus.LOCKDOWN:
            raise IAMError(f"Cannot unlock IAM in status {self.status.value}")
        new_iam = self._copy()
        new_iam.status = IAMStatus.ACTIVE
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("UNLOCK", unlocked_by, {})
        return new_iam

    def validate(self) -> dict[str, Any]:
        errors = []
        usernames = set()
        emails = set()
        role_names = set()

        for user in self.users.values():
            if user.username in usernames:
                errors.append(f"Duplicate username: {user.username}")
            usernames.add(user.username)
            if user.email in emails:
                errors.append(f"Duplicate email: {user.email}")
            emails.add(user.email)

        for role in self.roles.values():
            if role.role_name in role_names:
                errors.append(f"Duplicate role name: {role.role_name}")
            role_names.add(role.role_name)

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "iam_id": str(self.iam_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "iam_id": str(self.iam_id),
            "legal_entity_id": str(self.legal_entity_id),
            "status": self.status.value,
            "user_count": len(self.users),
            "role_count": len(self.roles),
            "session_count": len(self.sessions),
            "permission_count": len(self.permissions),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IAM:
        status = IAMStatus(data["status"])
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            iam_id=UUID(data["iam_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> IAM:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = IAM(
            iam_id=new_id,
            legal_entity_id=self.legal_entity_id,
            status=IAMStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        # Clone roles
        for role in self.roles.values():
            cloned_role = role.clone()
            cloned.roles[cloned_role.role_id] = cloned_role
        # Clone users (without passwords)
        for user in self.users.values():
            cloned_user = user.clone()
            cloned.users[cloned_user.user_id] = cloned_user
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.iam_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "iam_id": str(self.iam_id),
            "status": self.status.value,
            "user_count": len(self.users),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IAM:
        new_iam = self._copy()
        new_iam.updated_at = datetime.now(UTC)
        new_iam.version = self.version + 1
        new_iam._record_audit("TOUCH", touched_by, {})
        return new_iam

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, entity: Any, created_by: str) -> IAM:
        if isinstance(entity, UserEntity):
            return self.add_user(entity, created_by)
        elif isinstance(entity, RoleEntity):
            return self.add_role(entity, created_by)
        elif isinstance(entity, SessionEntity):
            return self.add_session(entity, created_by)
        else:
            raise IAMError(f"Unknown entity type: {type(entity)}")

    def remove_child(self, entity_id: UUID, entity_type: str, removed_by: str) -> IAM:
        if entity_type == "user":
            return self.delete_user(entity_id, removed_by)
        elif entity_type == "role":
            return self.delete_role(entity_id, removed_by)
        elif entity_type == "session":
            return self.revoke_session(entity_id, removed_by)
        else:
            raise IAMError(f"Unknown entity type: {entity_type}")

    def can_post(self, user_id: UUID, permission: str) -> bool:
        return self.has_permission(user_id, permission)

    def post(self, user_id: UUID, permission: str, posted_by: str) -> IAM:
        if not self.can_post(user_id, permission):
            raise InsufficientPermissionsError(f"User {user_id} lacks permission {permission}")
        self._record_audit("POST", posted_by, {"user_id": str(user_id), "permission": permission})
        return self

    def can_approve(self, user_id: UUID, resource: str, user_role: str = "user") -> bool:
        return self.has_permission(user_id, f"{resource}:approve")

    def approve(self, user_id: UUID, resource: str, approved_by: str) -> IAM:
        if not self.can_approve(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot approve {resource}")
        self._record_audit("APPROVE", approved_by, {"user_id": str(user_id), "resource": resource})
        return self

    def can_reject(self, user_id: UUID, resource: str, user_role: str = "user") -> bool:
        return self.has_permission(user_id, f"{resource}:reject")

    def reject(self, user_id: UUID, resource: str, rejected_by: str, reason: str) -> IAM:
        if not self.can_reject(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot reject {resource}")
        self._record_audit(
            "REJECT", rejected_by, {"user_id": str(user_id), "resource": resource, "reason": reason}
        )
        return self

    def can_cancel(self, user_id: UUID, resource: str) -> bool:
        return self.has_permission(user_id, f"{resource}:delete")

    def cancel(self, user_id: UUID, resource: str, cancelled_by: str, reason: str) -> IAM:
        if not self.can_cancel(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot cancel {resource}")
        self._record_audit(
            "CANCEL",
            cancelled_by,
            {"user_id": str(user_id), "resource": resource, "reason": reason},
        )
        return self

    def can_reverse(self, user_id: UUID, resource: str) -> bool:
        return self.has_permission(user_id, f"{resource}:reverse")

    def reverse(self, user_id: UUID, resource: str, reversed_by: str, reason: str) -> IAM:
        if not self.can_reverse(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot reverse {resource}")
        self._record_audit(
            "REVERSE",
            reversed_by,
            {"user_id": str(user_id), "resource": resource, "reason": reason},
        )
        return self

    def can_close(self, user_id: UUID, resource: str) -> bool:
        return self.has_permission(user_id, f"{resource}:close")

    def close(self, user_id: UUID, resource: str, closed_by: str, reason: str) -> IAM:
        if not self.can_close(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot close {resource}")
        self._record_audit(
            "CLOSE", closed_by, {"user_id": str(user_id), "resource": resource, "reason": reason}
        )
        return self

    def can_reopen(self, user_id: UUID, resource: str) -> bool:
        return self.has_permission(user_id, f"{resource}:reopen")

    def reopen(self, user_id: UUID, resource: str, reopened_by: str, reason: str) -> IAM:
        if not self.can_reopen(user_id, resource):
            raise InsufficientPermissionsError(f"User {user_id} cannot reopen {resource}")
        self._record_audit(
            "REOPEN", reopened_by, {"user_id": str(user_id), "resource": resource, "reason": reason}
        )
        return self

    def can_archive(self, user_id: UUID) -> bool:
        return self.has_permission(user_id, "user:delete")

    def archive(self, user_id: UUID, archived_by: str, reason: str | None = None) -> IAM:
        if not self.can_archive(user_id):
            raise InsufficientPermissionsError(f"User {user_id} cannot archive")
        return self.delete_user(user_id, archived_by)

    def can_unarchive(self, user_id: UUID) -> bool:
        return self.has_permission(user_id, "user:create")

    def unarchive(self, user_id: UUID, unarchived_by: str) -> IAM:
        if not self.can_unarchive(user_id):
            raise InsufficientPermissionsError(f"User {user_id} cannot unarchive")
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")
        activated_user = user.activate(unarchived_by)
        return self.update_user(activated_user, unarchived_by)

    # ==================== EVENT METHODS ====================

    def register_event(self, event: DomainEvent) -> None:
        self._register_event(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== USER MANAGEMENT ====================

    def add_user(self, user: UserEntity, created_by: str) -> IAM:
        if user.user_id in self.users:
            raise IAMError(f"User {user.user_id} already exists")

        for existing in self.users.values():
            if existing.username == user.username:
                raise DuplicateUsernameError(f"Username '{user.username}' already exists")
            if existing.email == user.email:
                raise DuplicateEmailError(f"Email '{user.email}' already exists")

        new_users = dict(self.users)
        new_users[user.user_id] = user

        self._register_event(
            UserCreatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=user,
                user_id=str(created_by),
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=created_by,
            version=self.version + 1,
        )

    def update_user(self, user: UserEntity, updated_by: str) -> IAM:
        if user.user_id not in self.users:
            raise UserNotFoundError(f"User {user.user_id} not found")

        for existing in self.users.values():
            if existing.user_id != user.user_id and existing.email == user.email:
                raise DuplicateEmailError(f"Email '{user.email}' already used by another user")

        new_users = dict(self.users)
        new_users[user.user_id] = user

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def delete_user(self, user_id: UUID, deleted_by: str) -> IAM:
        if user_id not in self.users:
            raise UserNotFoundError(f"User {user_id} not found")

        user = self.users[user_id]
        deactivated_user = user.deactivate(deleted_by)
        new_users = dict(self.users)
        new_users[user_id] = deactivated_user

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=deleted_by,
            version=self.version + 1,
        )

    def activate_user(self, user_id: UUID, activated_by: str) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        activated_user = user.activate(activated_by)
        new_users = dict(self.users)
        new_users[user_id] = activated_user

        self._register_event(
            UserActivatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=activated_user,
                activated_by=activated_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version=self.version + 1,
        )

    def deactivate_user(self, user_id: UUID, deactivated_by: str) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        deactivated_user = user.deactivate(deactivated_by)
        new_users = dict(self.users)
        new_users[user_id] = deactivated_user

        self._register_event(
            UserDeactivatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=deactivated_user,
                deactivated_by=deactivated_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=deactivated_by,
            version=self.version + 1,
        )

    def unlock_user(self, user_id: UUID, unlocked_by: str) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        unlocked_user = user.unlock()
        new_users = dict(self.users)
        new_users[user_id] = unlocked_user

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=unlocked_by,
            version=self.version + 1,
        )

    def change_user_password(
        self, user_id: UUID, new_password_hash: PasswordHashedVO, changed_by: str
    ) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        updated_user = user.change_password(new_password_hash, changed_by)
        new_users = dict(self.users)
        new_users[user_id] = updated_user

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=changed_by,
            version=self.version + 1,
        )

    # ==================== ROLE MANAGEMENT ====================

    def add_role(self, role: RoleEntity, created_by: str) -> IAM:
        if role.role_id in self.roles:
            raise IAMError(f"Role {role.role_id} already exists")

        for existing in self.roles.values():
            if existing.role_name == role.role_name:
                raise DuplicateRoleNameError(f"Role name '{role.role_name}' already exists")

        new_roles = dict(self.roles)
        new_roles[role.role_id] = role

        self._register_event(
            RoleCreatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                role=role,
                created_by=created_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=new_roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=created_by,
            version=self.version + 1,
        )

    def update_role(self, role: RoleEntity, updated_by: str) -> IAM:
        if role.role_id not in self.roles:
            raise RoleNotFoundError(f"Role {role.role_id} not found")

        existing = self.roles[role.role_id]
        if existing.is_system and role.role_name != existing.role_name:
            raise IAMError(f"Cannot rename system role {existing.role_name}")

        new_roles = dict(self.roles)
        new_roles[role.role_id] = role

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=new_roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def delete_role(self, role_id: UUID, deleted_by: str) -> IAM:
        role = self.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")

        if role.is_system:
            raise IAMError(f"Cannot delete system role {role.role_name}")

        for user in self.users.values():
            if role_id in user.role_ids:
                raise IAMError(
                    f"Cannot delete role {role.role_name} because it is assigned to user {user.username}"
                )

        new_roles = {k: v for k, v in self.roles.items() if k != role_id}

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=new_roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=deleted_by,
            version=self.version + 1,
        )

    def assign_role_to_user(self, user_id: UUID, role_id: UUID, assigned_by: str) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        role = self.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")

        if role_id in user.role_ids:
            return self

        new_role_ids = list(user.role_ids) + [role_id]
        updated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=user.password_hash,
            status=user.status,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=new_role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
            last_login_at=user.last_login_at,
            last_login_ip=user.last_login_ip,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
        )
        new_users = dict(self.users)
        new_users[user_id] = updated_user

        self._register_event(
            RoleAssignedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=updated_user,
                role=role,
                assigned_by=assigned_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=assigned_by,
            version=self.version + 1,
        )

    def remove_role_from_user(self, user_id: UUID, role_id: UUID, removed_by: str) -> IAM:
        user = self.users.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found")

        role = self.roles.get(role_id)
        if not role:
            raise RoleNotFoundError(f"Role {role_id} not found")

        if role_id not in user.role_ids:
            return self

        if len(user.role_ids) <= 1:
            raise IAMError(f"Cannot remove last role from user {user.username}")

        new_role_ids = [rid for rid in user.role_ids if rid != role_id]
        updated_user = UserEntity(
            user_id=user.user_id,
            username=user.username,
            email=user.email,
            password_hash=user.password_hash,
            status=user.status,
            full_name=user.full_name,
            legal_entity_id=user.legal_entity_id,
            role_ids=new_role_ids,
            created_at=user.created_at,
            updated_at=datetime.now(UTC),
            created_by=user.created_by,
            version=user.version + 1,
            last_login_at=user.last_login_at,
            last_login_ip=user.last_login_ip,
            failed_login_attempts=user.failed_login_attempts,
            locked_until=user.locked_until,
        )
        new_users = dict(self.users)
        new_users[user_id] = updated_user

        self._register_event(
            RoleRevokedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=updated_user,
                role=role,
                revoked_by=removed_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    # ==================== SESSION MANAGEMENT ====================

    def add_session(self, session: SessionEntity, created_by: str) -> IAM:
        if session.session_id in self.sessions:
            raise IAMError(f"Session {session.session_id} already exists")

        user = self.users.get(session.user_id)
        if not user:
            raise UserNotFoundError(f"User {session.user_id} not found")

        if not user.is_active():
            raise IAMError(f"Cannot create session for inactive user {user.username}")

        new_sessions = dict(self.sessions)
        new_sessions[session.session_id] = session

        self._register_event(
            SessionCreatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                session=session,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=self.roles,
            sessions=new_sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=created_by,
            version=self.version + 1,
        )

    def revoke_session(self, session_id: UUID, revoked_by: str) -> IAM:
        session = self.sessions.get(session_id)
        if not session:
            return self

        revoked_session = session.revoke(revoked_by)
        new_sessions = dict(self.sessions)
        new_sessions[session_id] = revoked_session

        self._register_event(
            SessionTerminatedEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                session=revoked_session,
                terminated_by=revoked_by,
            )
        )

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=self.roles,
            sessions=new_sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=revoked_by,
            version=self.version + 1,
        )

    def revoke_all_user_sessions(self, user_id: UUID, revoked_by: str) -> IAM:
        new_sessions = dict(self.sessions)
        for session_id, session in self.sessions.items():
            if session.user_id == user_id and session.is_active():
                revoked_session = session.revoke(revoked_by)
                new_sessions[session_id] = revoked_session

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=self.roles,
            sessions=new_sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=revoked_by,
            version=self.version + 1,
        )

    def refresh_session(self, session_id: UUID, refreshed_by: str) -> IAM:
        session = self.sessions.get(session_id)
        if not session:
            raise IAMError(f"Session {session_id} not found")

        if not session.is_refresh_valid():
            raise IAMError("Refresh token expired")

        refreshed_session = session.refresh()
        new_sessions = dict(self.sessions)
        new_sessions[session_id] = refreshed_session

        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users,
            roles=self.roles,
            sessions=new_sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=refreshed_by,
            version=self.version + 1,
        )

    # ==================== AUTHENTICATION ====================

    def authenticate(
        self,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[IAM, UserEntity | None]:
        user = None
        for u in self.users.values():
            if u.username == username:
                user = u
                break

        if not user:
            self._register_event(
                LoginFailureEvent(
                    aggregate_id=self.iam_id,
                    aggregate_version=self.version,
                    username=username,
                    failure_reason="user_not_found",
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )
            return self, None

        if not user.is_active():
            self._register_event(
                LoginFailureEvent(
                    aggregate_id=self.iam_id,
                    aggregate_version=self.version,
                    username=username,
                    failure_reason="account_inactive",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    user_id=str(user.user_id),
                )
            )
            return self, None

        if user.is_locked():
            self._register_event(
                LoginFailureEvent(
                    aggregate_id=self.iam_id,
                    aggregate_version=self.version,
                    username=username,
                    failure_reason="account_locked",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    user_id=str(user.user_id),
                )
            )
            return self, None

        if not user.password_hash.verify(password):
            updated_user = user.record_login_failure()
            new_users = dict(self.users)
            new_users[user.user_id] = updated_user

            self._register_event(
                LoginFailureEvent(
                    aggregate_id=self.iam_id,
                    aggregate_version=self.version + 1,
                    username=username,
                    failure_reason="wrong_password",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    user_id=str(user.user_id),
                )
            )

            new_iam = IAM(
                iam_id=self.iam_id,
                legal_entity_id=self.legal_entity_id,
                status=self.status,
                users=new_users,
                roles=self.roles,
                sessions=self.sessions,
                permissions=self.permissions,
                created_at=self.created_at,
                updated_at=datetime.now(UTC),
                created_by=self.created_by,
                version=self.version + 1,
            )
            return new_iam, None

        updated_user = user.record_login_success(ip_address or "unknown")
        new_users = dict(self.users)
        new_users[user.user_id] = updated_user

        self._register_event(
            LoginSuccessEvent(
                aggregate_id=self.iam_id,
                aggregate_version=self.version + 1,
                user=updated_user,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        new_iam = IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=new_users,
            roles=self.roles,
            sessions=self.sessions,
            permissions=self.permissions,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )
        return new_iam, updated_user

    # ==================== PERMISSION CHECKING ====================

    def has_permission(self, user_id: UUID, permission: str) -> bool:
        user = self.users.get(user_id)
        if not user:
            return False

        target_permission = PermissionVO.from_string(permission)

        for role_id in user.role_ids:
            role = self.roles.get(role_id)
            if role:
                for role_perm_str in role.permissions:
                    role_perm = PermissionVO.from_string(role_perm_str)
                    if role_perm.matches(target_permission):
                        return True
        return False

    def get_user_permissions(self, user_id: UUID) -> set[str]:
        user = self.users.get(user_id)
        if not user:
            return set()

        permissions = set()
        for role_id in user.role_ids:
            role = self.roles.get(role_id)
            if role:
                permissions.update(role.permissions)
        return permissions

    def get_user_effective_permissions(self, user_id: UUID) -> set[str]:
        user = self.users.get(user_id)
        if not user:
            return set()

        permissions = set()
        for role_id in user.role_ids:
            role = self.roles.get(role_id)
            if role:
                permissions.update(role.get_all_permissions(lambda rid: self.roles.get(rid)))
        return permissions

    def get_user_roles(self, user_id: UUID) -> list[RoleEntity]:
        user = self.users.get(user_id)
        if not user:
            return []

        roles = []
        for role_id in user.role_ids:
            role = self.roles.get(role_id)
            if role:
                roles.append(role)
        return roles

    # ==================== QUERY METHODS ====================

    def get_user(self, user_id: UUID) -> UserEntity | None:
        return self.users.get(user_id)

    def get_user_by_username(self, username: str) -> UserEntity | None:
        for user in self.users.values():
            if user.username == username:
                return user
        return None

    def get_user_by_email(self, email: str) -> UserEntity | None:
        for user in self.users.values():
            if user.email == email:
                return user
        return None

    def get_role(self, role_id: UUID) -> RoleEntity | None:
        return self.roles.get(role_id)

    def get_role_by_name(self, role_name: str) -> RoleEntity | None:
        for role in self.roles.values():
            if role.role_name == role_name:
                return role
        return None

    def get_session(self, session_id: UUID) -> SessionEntity | None:
        return self.sessions.get(session_id)

    def get_session_by_token(self, token: str) -> SessionEntity | None:
        for session in self.sessions.values():
            if session.token == token:
                return session
        return None

    def get_active_sessions(self, user_id: UUID) -> list[SessionEntity]:
        return [s for s in self.sessions.values() if s.user_id == user_id and s.is_active()]

    def get_all_users(self) -> list[UserEntity]:
        return list(self.users.values())

    def get_active_users(self) -> list[UserEntity]:
        return [u for u in self.users.values() if u.is_active()]

    def get_all_roles(self) -> list[RoleEntity]:
        return list(self.roles.values())

    def get_users_by_role(self, role_id: UUID) -> list[UserEntity]:
        return [u for u in self.users.values() if role_id in u.role_ids]

    # ==================== STATISTICS ====================

    def get_statistics(self) -> dict[str, Any]:
        active_users = len(self.get_active_users())
        total_users = len(self.users)
        return {
            "total_users": total_users,
            "active_users": active_users,
            "inactive_users": total_users - active_users,
            "total_roles": len(self.roles),
            "total_sessions": len(self.sessions),
            "active_sessions": len([s for s in self.sessions.values() if s.is_active()]),
            "total_permissions": len(self.permissions),
            "status": self.status.value,
        }

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> IAM:
        return IAM(
            iam_id=self.iam_id,
            legal_entity_id=self.legal_entity_id,
            status=self.status,
            users=self.users.copy(),
            roles=self.roles.copy(),
            sessions=self.sessions.copy(),
            permissions=self.permissions.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# ============================================================================
# Alias untuk kompatibilitas
# ============================================================================

UserAggregate = IAM


# ============================================================================
# Repository Implementation
# ============================================================================


class IAMRepository:
    _storage: ClassVar[dict[UUID, IAM]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> IAM | None:
        for iam in cls._storage.values():
            if iam.legal_entity_id == legal_entity_id:
                return iam
        return None

    @classmethod
    async def get_by_id(cls, iam_id: UUID) -> IAM | None:
        return cls._storage.get(iam_id)

    @classmethod
    async def get_all(cls) -> list[IAM]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, iam: IAM) -> None:
        cls._storage[iam.iam_id] = iam

    @classmethod
    async def update(cls, iam: IAM) -> None:
        cls._storage[iam.iam_id] = iam

    @classmethod
    async def delete(cls, iam_id: UUID) -> None:
        cls._storage.pop(iam_id, None)

    @classmethod
    async def exists(cls, iam_id: UUID) -> bool:
        return iam_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[IAM]:
        iams = list(cls._storage.values())
        return iams[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "IAM",
    "AuthenticationError",
    "DuplicateEmailError",
    "DuplicateRoleNameError",
    "DuplicateUsernameError",
    "IAMError",
    "IAMRepository",
    "IAMStatus",
    "InsufficientPermissionsError",
    "RoleNotFoundError",
    "UserAggregate",
    "UserNotFoundError",
]
