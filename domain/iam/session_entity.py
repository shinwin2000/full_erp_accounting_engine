#!/usr/bin/env python3
"""
Module: session_entity.py
Layer: Domain / IAM
Responsibility: Entitas sesi login (token, expiry, perangkat) dengan semua method entity dasar.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class SessionStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    COMPROMISED = "compromised"
    SUSPENDED = "suspended"

    def is_active(self) -> bool:
        return self == SessionStatus.ACTIVE

    def can_refresh(self) -> bool:
        return self in (SessionStatus.ACTIVE, SessionStatus.SUSPENDED)

    def display_name(self) -> str:
        names = {
            SessionStatus.ACTIVE: "Aktif",
            SessionStatus.EXPIRED: "Kadaluarsa",
            SessionStatus.REVOKED: "Dicabut",
            SessionStatus.COMPROMISED: "Terkompromi",
            SessionStatus.SUSPENDED: "Ditangguhkan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> SessionStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


class DeviceType(Enum):
    WEB = "web"
    MOBILE = "mobile"
    TABLET = "tablet"
    API = "api"
    DESKTOP = "desktop"
    UNKNOWN = "unknown"

    def display_name(self) -> str:
        names = {
            DeviceType.WEB: "Web Browser",
            DeviceType.MOBILE: "Mobile App",
            DeviceType.TABLET: "Tablet",
            DeviceType.API: "API Client",
            DeviceType.DESKTOP: "Desktop App",
            DeviceType.UNKNOWN: "Unknown",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> DeviceType | None:
        for d in cls:
            if d.value == value.lower():
                return d
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class SessionError(ValueError):
    pass


class InvalidSessionStatusTransitionError(SessionError):
    pass


class SessionExpiredError(SessionError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class SessionMetadata:
    ip_address: str | None = None
    user_agent: str | None = None
    location: str | None = None
    device_name: str | None = None
    os_name: str | None = None
    browser_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip_address": self.ip_address,
            "user_agent": self.user_agent[:200] if self.user_agent else None,
            "location": self.location,
            "device_name": self.device_name,
            "os_name": self.os_name,
            "browser_name": self.browser_name,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionMetadata:
        return cls(
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
            location=data.get("location"),
            device_name=data.get("device_name"),
            os_name=data.get("os_name"),
            browser_name=data.get("browser_name"),
        )


@dataclass(frozen=True)
class SessionAudit:
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    compromised_at: datetime | None = None
    compromised_reason: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "last_activity_at": self.last_activity_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revoked_by": self.revoked_by,
            "compromised_at": self.compromised_at.isoformat() if self.compromised_at else None,
            "compromised_reason": self.compromised_reason,
            "version": self.version,
        }


# ============================================================================
# Session Entity
# ============================================================================


@dataclass
class SessionEntity:
    session_id: UUID
    user_id: UUID
    token: str
    refresh_token: str
    device_type: DeviceType
    status: SessionStatus
    expires_at: datetime
    refresh_expires_at: datetime
    metadata: SessionMetadata = field(default_factory=SessionMetadata)
    audit: SessionAudit = field(default_factory=SessionAudit)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.token or len(self.token) < 10:
            raise SessionError("Invalid token")
        if not self.refresh_token or len(self.refresh_token) < 10:
            raise SessionError("Invalid refresh token")
        if not isinstance(self.device_type, DeviceType):
            raise SessionError(f"Invalid device_type: {self.device_type}")
        if not isinstance(self.status, SessionStatus):
            raise SessionError(f"Invalid status: {self.status}")
        if self.expires_at <= self.audit.created_at:
            raise SessionError("Expiry time must be after creation time")
        if self.refresh_expires_at <= self.expires_at:
            raise SessionError("Refresh expiry must be after token expiry")
        if self.audit.created_at.tzinfo is None:
            object.__setattr__(
                self, "audit", SessionAudit(created_at=self.audit.created_at.replace(tzinfo=UTC))
            )
        if self.expires_at.tzinfo is None:
            object.__setattr__(self, "expires_at", self.expires_at.replace(tzinfo=UTC))
        if self.refresh_expires_at.tzinfo is None:
            object.__setattr__(
                self, "refresh_expires_at", self.refresh_expires_at.replace(tzinfo=UTC)
            )
        if self.audit.version < 1:
            raise SessionError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.audit.version,
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "status": self.status.value,
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
            "version": self.audit.version,
            "session_id": str(self.session_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create(
        cls,
        user_id: UUID,
        device_type: DeviceType,
        token_ttl_hours: int = 24,
        refresh_ttl_days: int = 7,
        ip_address: str | None = None,
        user_agent: str | None = None,
        location: str | None = None,
        device_name: str | None = None,
        created_by: str = "system",
    ) -> SessionEntity:
        """Create a new session."""
        now = datetime.now(UTC)
        token = cls._generate_token(user_id, now)
        refresh_token = cls._generate_refresh_token(user_id)

        metadata = SessionMetadata(
            ip_address=ip_address,
            user_agent=user_agent,
            location=location,
            device_name=device_name,
        )

        audit = SessionAudit(
            created_at=now,
            created_by=created_by,
            last_activity_at=now,
            version=1,
        )

        return cls(
            session_id=uuid4(),
            user_id=user_id,
            token=token,
            refresh_token=refresh_token,
            device_type=device_type,
            status=SessionStatus.ACTIVE,
            expires_at=now + timedelta(hours=token_ttl_hours),
            refresh_expires_at=now + timedelta(days=refresh_ttl_days),
            metadata=metadata,
            audit=audit,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionEntity:
        device_type = DeviceType.from_string(data["device_type"]) or DeviceType.UNKNOWN
        status = SessionStatus.from_string(data["status"]) or SessionStatus.ACTIVE
        expires_at = datetime.fromisoformat(data["expires_at"])
        refresh_expires_at = datetime.fromisoformat(data["refresh_expires_at"])
        metadata = SessionMetadata.from_dict(data.get("metadata", {}))
        audit = SessionAudit(**data.get("audit", {}))
        return cls(
            session_id=UUID(data["session_id"]),
            user_id=UUID(data["user_id"]),
            token=data["token"],
            refresh_token=data["refresh_token"],
            device_type=device_type,
            status=status,
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            metadata=metadata,
            audit=audit,
        )

    @classmethod
    def _generate_token(cls, user_id: UUID, timestamp: datetime) -> str:
        """Generate unique session token."""
        random_part = secrets.token_urlsafe(32)
        token_input = f"{user_id}_{timestamp.timestamp()}_{random_part}"
        return hashlib.sha256(token_input.encode()).hexdigest()

    @classmethod
    def _generate_refresh_token(cls, user_id: UUID) -> str:
        """Generate unique refresh token."""
        random_part = secrets.token_urlsafe(40)
        token_input = f"refresh_{user_id}_{random_part}"
        return hashlib.sha256(token_input.encode()).hexdigest()

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> SessionEntity:
        self._record_audit("CREATE", created_by, {"user_id": str(self.user_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> SessionEntity:
        if not self.status.can_refresh():
            raise InvalidSessionStatusTransitionError(
                f"Cannot update session in status {self.status.value}"
            )

        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("session_id", "audit", "token", "refresh_token"):
                data[key] = value

        new_session = self.from_dict(data)
        new_session._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_session

    def delete(self, deleted_by: str, reason: str | None = None) -> SessionEntity:
        if self.status == SessionStatus.REVOKED:
            return self

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=self.audit.last_activity_at,
            revoked_at=datetime.now(UTC),
            revoked_by=deleted_by,
            version=self.audit.version + 1,
        )

        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.REVOKED,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_session

    def restore(self, restored_by: str) -> SessionEntity:
        if self.status != SessionStatus.REVOKED:
            raise InvalidSessionStatusTransitionError(
                f"Cannot restore session in status {self.status.value}"
            )

        now = datetime.now(UTC)
        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=now,
            revoked_at=None,
            revoked_by=None,
            version=self.audit.version + 1,
        )

        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self._generate_token(self.user_id, now),
            refresh_token=self._generate_refresh_token(self.user_id),
            device_type=self.device_type,
            status=SessionStatus.ACTIVE,
            expires_at=now + (self.expires_at - self.audit.created_at),
            refresh_expires_at=now + (self.refresh_expires_at - self.audit.created_at),
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("RESTORE", restored_by, {})
        return new_session

    def activate(self, activated_by: str) -> SessionEntity:
        if self.status == SessionStatus.ACTIVE:
            return self
        if not self.status.can_refresh():
            raise InvalidSessionStatusTransitionError(
                f"Cannot activate session in status {self.status.value}"
            )

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=datetime.now(UTC),
            version=self.audit.version + 1,
        )

        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.ACTIVE,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("ACTIVATE", activated_by, {})
        return new_session

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SessionEntity:
        return self.delete(deactivated_by, reason)

    def lock(self, locked_by: str, reason: str) -> SessionEntity:
        if self.status != SessionStatus.ACTIVE:
            raise InvalidSessionStatusTransitionError(
                f"Cannot lock session in status {self.status.value}"
            )

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=self.audit.last_activity_at,
            version=self.audit.version + 1,
        )

        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.SUSPENDED,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("LOCK", locked_by, {"reason": reason})
        return new_session

    def unlock(self, unlocked_by: str) -> SessionEntity:
        if self.status != SessionStatus.SUSPENDED:
            raise InvalidSessionStatusTransitionError(
                f"Cannot unlock session in status {self.status.value}"
            )

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=datetime.now(UTC),
            version=self.audit.version + 1,
        )

        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.ACTIVE,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("UNLOCK", unlocked_by, {})
        return new_session

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except SessionError as e:
            errors.append(str(e))

        if self.is_expired():
            errors.append("Session has expired")
        elif self.is_refresh_expired():
            errors.append("Refresh token has expired")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "session_id": str(self.session_id),
            "version": self.audit.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "token": self.token,
            "refresh_token": self.refresh_token,
            "device_type": self.device_type.value,
            "status": self.status.value,
            "expires_at": self.expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "metadata": self.metadata.to_dict(),
            "audit": self.audit.to_dict(),
        }

    def clone(self) -> SessionEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        new_audit = SessionAudit(
            created_at=now,
            created_by=self.audit.created_by,
            last_activity_at=now,
            version=1,
        )
        cloned = SessionEntity(
            session_id=new_id,
            user_id=self.user_id,
            token=self._generate_token(self.user_id, now),
            refresh_token=self._generate_refresh_token(self.user_id),
            device_type=self.device_type,
            status=SessionStatus.ACTIVE,
            expires_at=now + (self.expires_at - self.audit.created_at),
            refresh_expires_at=now + (self.refresh_expires_at - self.audit.created_at),
            metadata=self.metadata,
            audit=new_audit,
        )
        cloned._record_audit("CLONE", self.audit.created_by, {"source": str(self.session_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.audit.version,
            "session_id": str(self.session_id),
            "user_id": str(self.user_id),
            "status": self.status.value,
            "expires_at": self.expires_at.isoformat(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.audit.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SessionEntity:
        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=datetime.now(UTC),
            version=self.audit.version + 1,
        )
        new_session = SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=self.status,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )
        new_session._record_audit("TOUCH", touched_by, {})
        return new_session

    # ==================== BUSINESS LOGIC ====================

    def is_active(self) -> bool:
        if self.status != SessionStatus.ACTIVE:
            return False
        if datetime.now(UTC) > self.expires_at:
            return False
        return True

    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    def is_refresh_valid(self) -> bool:
        if self.status != SessionStatus.ACTIVE:
            return False
        return datetime.now(UTC) <= self.refresh_expires_at

    def is_refresh_expired(self) -> bool:
        return datetime.now(UTC) > self.refresh_expires_at

    def can_refresh(self) -> bool:
        return self.status.can_refresh() and not self.is_refresh_expired()

    def refresh(self) -> SessionEntity:
        """Refresh the session (create new tokens)."""
        if not self.can_refresh():
            if self.is_expired():
                raise SessionExpiredError("Session has expired")
            if self.is_refresh_expired():
                raise SessionExpiredError("Refresh token has expired")
            raise InvalidSessionStatusTransitionError(
                f"Cannot refresh session in status {self.status.value}"
            )

        now = datetime.now(UTC)
        token_ttl = (self.expires_at - self.audit.created_at).total_seconds() / 3600
        refresh_ttl = (self.refresh_expires_at - self.audit.created_at).total_seconds() / 86400

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=now,
            version=self.audit.version + 1,
        )

        return SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self._generate_token(self.user_id, now),
            refresh_token=self._generate_refresh_token(self.user_id),
            device_type=self.device_type,
            status=SessionStatus.ACTIVE,
            expires_at=now + timedelta(hours=token_ttl),
            refresh_expires_at=now + timedelta(days=refresh_ttl),
            metadata=self.metadata,
            audit=new_audit,
        )

    def revoke(self, revoked_by: str) -> SessionEntity:
        """Revoke the session (logout)."""
        if self.status == SessionStatus.REVOKED:
            return self

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=self.audit.last_activity_at,
            revoked_at=datetime.now(UTC),
            revoked_by=revoked_by,
            version=self.audit.version + 1,
        )

        return SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.REVOKED,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )

    def mark_compromised(self, reason: str) -> SessionEntity:
        """Mark session as compromised."""
        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=self.audit.last_activity_at,
            compromised_at=datetime.now(UTC),
            compromised_reason=reason,
            version=self.audit.version + 1,
        )

        return SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=SessionStatus.COMPROMISED,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )

    def update_activity(self) -> SessionEntity:
        """Update last activity timestamp."""
        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=datetime.now(UTC),
            version=self.audit.version + 1,
        )

        return SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=self.status,
            expires_at=self.expires_at,
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )

    def extend(self, additional_hours: int) -> SessionEntity:
        """Extend session expiry."""
        if not self.is_active():
            raise InvalidSessionStatusTransitionError(
                f"Cannot extend session in status {self.status.value}"
            )

        new_audit = SessionAudit(
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            last_activity_at=datetime.now(UTC),
            version=self.audit.version + 1,
        )

        return SessionEntity(
            session_id=self.session_id,
            user_id=self.user_id,
            token=self.token,
            refresh_token=self.refresh_token,
            device_type=self.device_type,
            status=self.status,
            expires_at=self.expires_at + timedelta(hours=additional_hours),
            refresh_expires_at=self.refresh_expires_at,
            metadata=self.metadata,
            audit=new_audit,
        )

    def get_remaining_seconds(self) -> int:
        """Get remaining seconds until expiry."""
        delta = self.expires_at - datetime.now(UTC)
        return max(0, int(delta.total_seconds()))

    def get_refresh_remaining_seconds(self) -> int:
        """Get remaining seconds until refresh expiry."""
        delta = self.refresh_expires_at - datetime.now(UTC)
        return max(0, int(delta.total_seconds()))


# ============================================================================
# DTO for repository compatibility
# ============================================================================


@dataclass
class UserSession:
    """Simple DTO for session data used by IAM repository."""

    id: UUID
    user_id: UUID
    session_token: str
    ip_address: str
    user_agent: str
    is_active: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def to_entity(self) -> SessionEntity:
        """Convert to full SessionEntity."""
        metadata = SessionMetadata(
            ip_address=self.ip_address,
            user_agent=self.user_agent,
        )
        audit = SessionAudit(
            created_at=self.created_at,
            last_activity_at=self.created_at,
        )
        return SessionEntity(
            session_id=self.id,
            user_id=self.user_id,
            token=self.session_token,
            refresh_token="",
            device_type=DeviceType.UNKNOWN,
            status=SessionStatus.ACTIVE if self.is_active else SessionStatus.REVOKED,
            expires_at=self.expires_at or (self.created_at + timedelta(days=1)),
            refresh_expires_at=self.expires_at or (self.created_at + timedelta(days=8)),
            metadata=metadata,
            audit=audit,
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class SessionRepository:
    _storage: ClassVar[dict[UUID, SessionEntity]] = {}
    _storage_by_token: ClassVar[dict[str, UUID]] = {}
    _storage_by_refresh_token: ClassVar[dict[str, UUID]] = {}

    @classmethod
    async def get_by_id(cls, session_id: UUID) -> SessionEntity | None:
        return cls._storage.get(session_id)

    @classmethod
    async def get_by_token(cls, token: str) -> SessionEntity | None:
        session_id = cls._storage_by_token.get(token)
        return cls._storage.get(session_id) if session_id else None

    @classmethod
    async def get_by_refresh_token(cls, refresh_token: str) -> SessionEntity | None:
        session_id = cls._storage_by_refresh_token.get(refresh_token)
        return cls._storage.get(session_id) if session_id else None

    @classmethod
    async def get_active_by_user(cls, user_id: UUID) -> list[SessionEntity]:
        return [s for s in cls._storage.values() if s.user_id == user_id and s.is_active()]

    @classmethod
    async def get_all_by_user(cls, user_id: UUID) -> list[SessionEntity]:
        return [s for s in cls._storage.values() if s.user_id == user_id]

    @classmethod
    async def get_by_status(cls, status: SessionStatus) -> list[SessionEntity]:
        return [s for s in cls._storage.values() if s.status == status]

    @classmethod
    async def get_expired(cls) -> list[SessionEntity]:
        return [s for s in cls._storage.values() if s.is_expired()]

    @classmethod
    async def get_all(cls) -> list[SessionEntity]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, session: SessionEntity) -> None:
        cls._storage[session.session_id] = session
        cls._storage_by_token[session.token] = session.session_id
        cls._storage_by_refresh_token[session.refresh_token] = session.session_id

    @classmethod
    async def update(cls, session: SessionEntity) -> None:
        await cls.save(session)

    @classmethod
    async def delete(cls, session_id: UUID) -> None:
        session = cls._storage.get(session_id)
        if session:
            cls._storage_by_token.pop(session.token, None)
            cls._storage_by_refresh_token.pop(session.refresh_token, None)
            cls._storage.pop(session_id, None)

    @classmethod
    async def revoke_all_user_sessions(cls, user_id: UUID, revoked_by: str) -> int:
        count = 0
        for session in list(cls._storage.values()):
            if session.user_id == user_id and session.is_active():
                revoked = session.revoke(revoked_by)
                await cls.save(revoked)
                count += 1
        return count

    @classmethod
    async def exists(cls, session_id: UUID) -> bool:
        return session_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[SessionEntity]:
        sessions = list(cls._storage.values())
        return sessions[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()
        cls._storage_by_token.clear()
        cls._storage_by_refresh_token.clear()


__all__ = [
    "DeviceType",
    "InvalidSessionStatusTransitionError",
    "SessionAudit",
    "SessionEntity",
    "SessionError",
    "SessionExpiredError",
    "SessionMetadata",
    "SessionRepository",
    "SessionStatus",
    "UserSession",
]
