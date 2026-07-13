#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / IAM
Responsibility: Domain events untuk Identity Access Management.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.iam.role_entity import RoleEntity
from domain.iam.session_entity import SessionEntity
from domain.iam.user_entity import UserEntity, UserStatus

logger = logging.getLogger(__name__)

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    """Tipe domain event untuk IAM."""

    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_ACTIVATED = "user_activated"
    USER_DEACTIVATED = "user_deactivated"
    USER_SUSPENDED = "user_suspended"
    USER_UNLOCKED = "user_unlocked"
    USER_PASSWORD_CHANGED = "user_password_changed"
    USER_DELETED = "user_deleted"
    ROLE_CREATED = "role_created"
    ROLE_UPDATED = "role_updated"
    ROLE_DELETED = "role_deleted"
    ROLE_ASSIGNED = "role_assigned"
    ROLE_REVOKED = "role_revoked"
    SESSION_CREATED = "session_created"
    SESSION_REFRESHED = "session_refreshed"
    SESSION_TERMINATED = "session_terminated"
    SESSION_COMPROMISED = "session_compromised"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"

    def display_name(self) -> str:
        names = {
            DomainEventType.USER_CREATED: "User Created",
            DomainEventType.USER_UPDATED: "User Updated",
            DomainEventType.USER_ACTIVATED: "User Activated",
            DomainEventType.USER_DEACTIVATED: "User Deactivated",
            DomainEventType.USER_SUSPENDED: "User Suspended",
            DomainEventType.USER_UNLOCKED: "User Unlocked",
            DomainEventType.USER_PASSWORD_CHANGED: "Password Changed",
            DomainEventType.USER_DELETED: "User Deleted",
            DomainEventType.ROLE_CREATED: "Role Created",
            DomainEventType.ROLE_UPDATED: "Role Updated",
            DomainEventType.ROLE_DELETED: "Role Deleted",
            DomainEventType.ROLE_ASSIGNED: "Role Assigned",
            DomainEventType.ROLE_REVOKED: "Role Revoked",
            DomainEventType.SESSION_CREATED: "Session Created",
            DomainEventType.SESSION_REFRESHED: "Session Refreshed",
            DomainEventType.SESSION_TERMINATED: "Session Terminated",
            DomainEventType.SESSION_COMPROMISED: "Session Compromised",
            DomainEventType.LOGIN_SUCCESS: "Login Success",
            DomainEventType.LOGIN_FAILURE: "Login Failure",
            DomainEventType.PERMISSION_GRANTED: "Permission Granted",
            DomainEventType.PERMISSION_REVOKED: "Permission Revoked",
        }
        return names.get(self, self.value)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event IAM.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (misal "IAM").
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
    """
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_type: str
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "IAM"),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# User Events
# ============================================================================


@dataclass(frozen=True)
class UserCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user baru dibuat.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User yang dibuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "email": user.email,
            "full_name": user.profile.full_name,
            "legal_entity_id": str(user.legal_entity_id),
            "status": user.status.value,
            "role_ids": [str(rid) for rid in user.role_ids],
            "created_by": user.audit.created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika data user diubah.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User yang diubah.
        changes: Dictionary perubahan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        changes: dict[str, Any],
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "email": user.email,
            "changes": changes,
            "updated_by": user.audit.updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserActivatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user diaktifkan.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        activated_by: User ID yang mengaktifkan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "previous_status": "pending",
            "new_status": UserStatus.ACTIVE.value,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserDeactivatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user dinonaktifkan.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        deactivated_by: User ID yang menonaktifkan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        deactivated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "previous_status": UserStatus.ACTIVE.value,
            "new_status": UserStatus.INACTIVE.value,
            "deactivated_by": deactivated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_DEACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserSuspendedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user ditangguhkan.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        suspended_by: User ID yang menangguhkan.
        reason: Alasan penangguhan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        suspended_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "previous_status": user.status.value,
            "new_status": UserStatus.SUSPENDED.value,
            "suspended_by": suspended_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_SUSPENDED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserUnlockedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user dibuka kuncinya.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        unlocked_by: User ID yang membuka kunci.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        unlocked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "previous_status": UserStatus.LOCKED.value,
            "new_status": UserStatus.ACTIVE.value,
            "unlocked_by": unlocked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_UNLOCKED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserPasswordChangedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika password user diubah.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        changed_by: User ID yang mengubah password.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "changed_by": changed_by,
            "changed_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_PASSWORD_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class UserDeletedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika user dihapus.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        deleted_by: User ID yang menghapus.
        reason: Alasan penghapusan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        deleted_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "deleted_by": deleted_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.USER_DELETED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Role Events
# ============================================================================


@dataclass(frozen=True)
class RoleCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika role baru dibuat.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        role: Entity Role.
        created_by: User ID pembuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        role: RoleEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "description": role.description,
            "permissions": list(role.permissions),
            "parent_role_id": str(role.parent_role_id) if role.parent_role_id else None,
            "is_default": role.is_default,
            "is_system": role.is_system,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ROLE_CREATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RoleUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika data role diubah.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        role: Entity Role.
        changes: Dictionary perubahan.
        updated_by: User ID pengubah.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        role: RoleEntity,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ROLE_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RoleDeletedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika role dihapus.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        role: Entity Role.
        deleted_by: User ID penghapus.
        reason: Alasan penghapusan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        role: RoleEntity,
        deleted_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "deleted_by": deleted_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ROLE_DELETED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RoleAssignedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika role diberikan ke user.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        user: Entity User penerima.
        role: Entity Role.
        assigned_by: User ID pemberi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        role: RoleEntity,
        assigned_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "assigned_by": assigned_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ROLE_ASSIGNED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class RoleRevokedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika role dicabut dari user.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        user: Entity User.
        role: Entity Role.
        revoked_by: User ID pencabut.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        role: RoleEntity,
        revoked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "role_id": str(role.role_id),
            "role_name": role.role_name,
            "revoked_by": revoked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ROLE_REVOKED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Session Events
# ============================================================================


@dataclass(frozen=True)
class SessionCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika session baru dibuat.

    Attributes:
        aggregate_id: ID agregat session.
        aggregate_version: Versi agregat.
        session: Entity Session.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        session: SessionEntity,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "session_id": str(session.session_id),
            "user_id": str(session.user_id),
            "device_type": session.device_type.value,
            "device_name": session.metadata.device_name,
            "ip_address": session.metadata.ip_address,
            "user_agent": session.metadata.user_agent,
            "location": session.metadata.location,
            "expires_at": session.expires_at.isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SESSION_CREATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class SessionRefreshedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika session di-refresh.

    Attributes:
        aggregate_id: ID agregat session.
        aggregate_version: Versi agregat.
        session: Entity Session.
        refreshed_by: User ID yang me-refresh.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        session: SessionEntity,
        refreshed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "session_id": str(session.session_id),
            "user_id": str(session.user_id),
            "refreshed_by": refreshed_by,
            "new_expires_at": session.expires_at.isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SESSION_REFRESHED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class SessionTerminatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika session dihentikan.

    Attributes:
        aggregate_id: ID agregat session.
        aggregate_version: Versi agregat.
        session: Entity Session.
        terminated_by: User ID penghenti.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        session: SessionEntity,
        terminated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "session_id": str(session.session_id),
            "user_id": str(session.user_id),
            "terminated_by": terminated_by,
            "reason": session.status.value,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SESSION_TERMINATED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class SessionCompromisedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika session terindikasi dikompromikan.

    Attributes:
        aggregate_id: ID agregat session.
        aggregate_version: Versi agregat.
        session: Entity Session.
        reason: Alasan indikasi kompromi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        session: SessionEntity,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "session_id": str(session.session_id),
            "user_id": str(session.user_id),
            "reason": reason,
            "compromised_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SESSION_COMPROMISED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Authentication Events
# ============================================================================


@dataclass(frozen=True)
class LoginSuccessEvent(DomainEvent):
    """
    Event yang diterbitkan ketika login berhasil.

    Attributes:
        aggregate_id: ID agregat user.
        aggregate_version: Versi agregat.
        user: Entity User.
        ip_address: Alamat IP login.
        user_agent: User agent login.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        user: UserEntity,
        ip_address: str | None,
        user_agent: str | None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "user_id": str(user.user_id),
            "username": user.username,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "login_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LOGIN_SUCCESS,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class LoginFailureEvent(DomainEvent):
    """
    Event yang diterbitkan ketika login gagal.

    Attributes:
        aggregate_id: ID agregat user (atau UUID random jika user tidak ditemukan).
        aggregate_version: Versi agregat.
        username: Username yang dicoba.
        failure_reason: Alasan kegagalan.
        ip_address: Alamat IP login.
        user_agent: User agent login.
        user_id: (opsional) ID pengguna (jika diketahui).
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        username: str,
        failure_reason: str,
        ip_address: str | None,
        user_agent: str | None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "username": username,
            "failure_reason": failure_reason,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "attempted_at": datetime.now(UTC).isoformat(),
        }
        if user_id:
            event_data["user_id"] = user_id
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LOGIN_FAILURE,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Permission Events
# ============================================================================


@dataclass(frozen=True)
class PermissionGrantedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika permission diberikan ke role.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        role_id: ID role.
        role_name: Nama role.
        permission: Permission yang diberikan.
        granted_by: User ID pemberi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        role_id: UUID,
        role_name: str,
        permission: str,
        granted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "role_id": str(role_id),
            "role_name": role_name,
            "permission": permission,
            "granted_by": granted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERMISSION_GRANTED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PermissionRevokedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika permission dicabut dari role.

    Attributes:
        aggregate_id: ID agregat role.
        aggregate_version: Versi agregat.
        role_id: ID role.
        role_name: Nama role.
        permission: Permission yang dicabut.
        revoked_by: User ID pencabut.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        role_id: UUID,
        role_name: str,
        permission: str,
        revoked_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "role_id": str(role_id),
            "role_name": role_name,
            "permission": permission,
            "revoked_by": revoked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERMISSION_REVOKED,
            aggregate_id=aggregate_id,
            aggregate_type="IAM",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    """
    Publisher untuk domain event IAM.
    Menyimpan event yang dipublikasikan untuk keperluan testing atau replay.
    """
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publish a single domain event."""
        cls._published_events.append(event)
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await cls.publish(event)

    @classmethod
    def get_published_events(cls) -> list[DomainEvent]:
        """Get all published events."""
        return cls._published_events.copy()

    @classmethod
    def clear(cls) -> None:
        """Clear published events."""
        cls._published_events.clear()


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    """Deserialize JSON string to DomainEvent."""
    return DomainEvent.from_json(json_str)


def serialize_domain_event(event: DomainEvent) -> str:
    """Serialize DomainEvent to JSON string."""
    return event.to_json()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "LoginFailureEvent",
    "LoginSuccessEvent",
    "PermissionGrantedEvent",
    "PermissionRevokedEvent",
    "RoleAssignedEvent",
    "RoleCreatedEvent",
    "RoleDeletedEvent",
    "RoleRevokedEvent",
    "RoleUpdatedEvent",
    "SessionCompromisedEvent",
    "SessionCreatedEvent",
    "SessionRefreshedEvent",
    "SessionTerminatedEvent",
    "UserActivatedEvent",
    "UserCreatedEvent",
    "UserDeactivatedEvent",
    "UserDeletedEvent",
    "UserPasswordChangedEvent",
    "UserSuspendedEvent",
    "UserUnlockedEvent",
    "UserUpdatedEvent",
    "deserialize_domain_event",
    "serialize_domain_event",
]
