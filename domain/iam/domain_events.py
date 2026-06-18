#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / IAM
Responsibility: Domain events untuk Identity Access Management.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.iam.role_entity import RoleEntity
from domain.iam.session_entity import SessionEntity
from domain.iam.user_entity import UserEntity, UserStatus

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


@dataclass
class DomainEvent:
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


@dataclass
class UserCreatedEvent(DomainEvent):
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


@dataclass
class UserUpdatedEvent(DomainEvent):
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


@dataclass
class UserActivatedEvent(DomainEvent):
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


@dataclass
class UserDeactivatedEvent(DomainEvent):
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


@dataclass
class UserSuspendedEvent(DomainEvent):
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


@dataclass
class UserUnlockedEvent(DomainEvent):
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


@dataclass
class UserPasswordChangedEvent(DomainEvent):
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


@dataclass
class UserDeletedEvent(DomainEvent):
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


@dataclass
class RoleCreatedEvent(DomainEvent):
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


@dataclass
class RoleUpdatedEvent(DomainEvent):
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


@dataclass
class RoleDeletedEvent(DomainEvent):
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


@dataclass
class RoleAssignedEvent(DomainEvent):
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


@dataclass
class RoleRevokedEvent(DomainEvent):
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


@dataclass
class SessionCreatedEvent(DomainEvent):
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


@dataclass
class SessionRefreshedEvent(DomainEvent):
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


@dataclass
class SessionTerminatedEvent(DomainEvent):
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


@dataclass
class SessionCompromisedEvent(DomainEvent):
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


@dataclass
class LoginSuccessEvent(DomainEvent):
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


@dataclass
class LoginFailureEvent(DomainEvent):
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


@dataclass
class PermissionGrantedEvent(DomainEvent):
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


@dataclass
class PermissionRevokedEvent(DomainEvent):
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
