#!/usr/bin/env python3
"""
Module: user_entity.py
Layer: Domain / IAM
Responsibility: Entitas pengguna dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.iam.password_hashed_vo import PasswordHashedVO

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class UserStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOCKED = "locked"
    PENDING_ACTIVATION = "pending"
    SUSPENDED = "suspended"
    DELETED = "deleted"

    def can_login(self) -> bool:
        return self == UserStatus.ACTIVE

    def can_be_modified(self) -> bool:
        return self not in (UserStatus.DELETED,)

    def display_name(self) -> str:
        names = {
            UserStatus.ACTIVE: "Aktif",
            UserStatus.INACTIVE: "Tidak Aktif",
            UserStatus.LOCKED: "Terkunci",
            UserStatus.PENDING_ACTIVATION: "Menunggu Aktivasi",
            UserStatus.SUSPENDED: "Ditangguhkan",
            UserStatus.DELETED: "Dihapus",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> UserStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class UserError(ValueError):
    pass


class InvalidUserStatusTransitionError(UserError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class UserProfile:
    full_name: str
    email: str
    phone: str | None = None
    mobile: str | None = None
    department: str | None = None
    position: str | None = None
    avatar_url: str | None = None
    timezone: str = "Asia/Jakarta"
    language: str = "id"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.full_name or len(self.full_name.strip()) < 2:
            raise UserError("Full name must be at least 2 characters")
        if not self.email or "@" not in self.email:
            raise UserError("Valid email is required")
        if self.phone and len(self.phone) < 8:
            raise UserError("Phone number must be at least 8 characters")

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "mobile": self.mobile,
            "department": self.department,
            "position": self.position,
            "avatar_url": self.avatar_url,
            "timezone": self.timezone,
            "language": self.language,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserProfile:
        return cls(
            full_name=data["full_name"],
            email=data["email"],
            phone=data.get("phone"),
            mobile=data.get("mobile"),
            department=data.get("department"),
            position=data.get("position"),
            avatar_url=data.get("avatar_url"),
            timezone=data.get("timezone", "Asia/Jakarta"),
            language=data.get("language", "id"),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class UserAudit:
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    last_password_change_at: datetime | None = None
    last_password_change_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: str = "system"
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
            "last_login_ip": self.last_login_ip,
            "last_password_change_at": self.last_password_change_at.isoformat()
            if self.last_password_change_at
            else None,
            "last_password_change_by": self.last_password_change_by,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "updated_at": self.updated_at.isoformat(),
            "updated_by": self.updated_by,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
            "version": self.version,
        }


# ============================================================================
# User Entity
# ============================================================================


@dataclass
class UserEntity:
    user_id: UUID
    username: str
    email: str
    password_hash: PasswordHashedVO
    status: UserStatus
    profile: UserProfile
    legal_entity_id: UUID
    role_ids: list[UUID]
    failed_login_attempts: int = 0
    locked_until: datetime | None = None
    mfa_enabled: bool = False
    mfa_secret: str | None = None
    audit: UserAudit = field(default_factory=UserAudit)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _instances: ClassVar[dict[str, UserEntity]] = {}

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        UserEntity._instances[str(self.user_id)] = self
        if self.username:
            UserEntity._instances[self.username] = self

    def _validate(self) -> None:
        if not self.username or len(self.username.strip()) < 3:
            raise UserError("Username must be at least 3 characters")
        if len(self.username) > 50:
            raise UserError("Username must not exceed 50 characters")
        if not self.email or "@" not in self.email:
            raise UserError("Valid email is required")
        if self.failed_login_attempts < 0:
            raise UserError("Failed login attempts cannot be negative")
        if self.audit.version < 1:
            raise UserError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.audit.version,
            "user_id": str(self.user_id),
            "username": self.username,
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
            "user_id": str(self.user_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> UserEntity:
        new_audit = UserAudit(
            created_at=self.audit.created_at,
            created_by=created_by,
            updated_at=self.audit.updated_at,
            updated_by=created_by,
            version=1,
        )
        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.PENDING_ACTIVATION,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            audit=new_audit,
        )
        new_user._record_audit("CREATE", created_by, {"username": self.username})
        return new_user

    def update(self, updated_by: str, **kwargs) -> UserEntity:
        if not self.status.can_be_modified():
            raise InvalidUserStatusTransitionError(
                f"Cannot update user in status {self.status.value}"
            )

        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("user_id", "audit", "password_hash"):
                data[key] = value

        new_profile = UserProfile.from_dict(data.get("profile", {}))
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=data.get("username", self.username),
            email=data.get("email", self.email),
            password_hash=self.password_hash,
            status=UserStatus.from_string(data.get("status", self.status.value)) or self.status,
            profile=new_profile,
            legal_entity_id=UUID(data.get("legal_entity_id", str(self.legal_entity_id))),
            role_ids=data.get("role_ids", self.role_ids),
            failed_login_attempts=data.get("failed_login_attempts", self.failed_login_attempts),
            locked_until=self.locked_until,
            mfa_enabled=data.get("mfa_enabled", self.mfa_enabled),
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_user

    def delete(self, deleted_by: str, reason: str | None = None) -> UserEntity:
        if self.status == UserStatus.DELETED:
            return self

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=deleted_by,
            deleted_at=datetime.now(UTC),
            deleted_by=deleted_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.DELETED,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=[],
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=False,
            mfa_secret=None,
            audit=new_audit,
        )
        new_user._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_user

    def restore(self, restored_by: str) -> UserEntity:
        if self.status != UserStatus.DELETED:
            raise InvalidUserStatusTransitionError(
                f"Cannot restore user in status {self.status.value}"
            )

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=restored_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.INACTIVE,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            audit=new_audit,
        )
        new_user._record_audit("RESTORE", restored_by, {})
        return new_user

    def activate(self, activated_by: str) -> UserEntity:
        if self.status == UserStatus.ACTIVE:
            return self
        if self.status not in (UserStatus.PENDING_ACTIVATION, UserStatus.INACTIVE):
            raise InvalidUserStatusTransitionError(
                f"Cannot activate user in status {self.status.value}"
            )

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=activated_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.ACTIVE,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("ACTIVATE", activated_by, {})
        return new_user

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> UserEntity:
        if self.status == UserStatus.INACTIVE:
            return self
        if self.status != UserStatus.ACTIVE:
            raise InvalidUserStatusTransitionError(
                f"Cannot deactivate user in status {self.status.value}"
            )

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=deactivated_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.INACTIVE,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_user

    def lock(self, locked_by: str, reason: str) -> UserEntity:
        if self.status == UserStatus.LOCKED:
            return self

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=locked_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.LOCKED,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=datetime.now(UTC),
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("LOCK", locked_by, {"reason": reason})
        return new_user

    def unlock(self, unlocked_by: str) -> UserEntity:
        if self.status != UserStatus.LOCKED:
            raise InvalidUserStatusTransitionError(
                f"Cannot unlock user in status {self.status.value}"
            )

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=unlocked_by,
            version=self.audit.version + 1,
        )

        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.ACTIVE,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("UNLOCK", unlocked_by, {})
        return new_user

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except UserError as e:
            errors.append(str(e))

        if self.status == UserStatus.ACTIVE and self.failed_login_attempts >= 5:
            errors.append(f"User has {self.failed_login_attempts} failed login attempts")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "user_id": str(self.user_id),
            "version": self.audit.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "username": self.username,
            "email": self.email,
            "status": self.status.value,
            "profile": self.profile.to_dict(),
            "legal_entity_id": str(self.legal_entity_id),
            "role_ids": [str(rid) for rid in self.role_ids],
            "failed_login_attempts": self.failed_login_attempts,
            "locked_until": self.locked_until.isoformat() if self.locked_until else None,
            "mfa_enabled": self.mfa_enabled,
            "audit": self.audit.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserEntity:
        status = UserStatus.from_string(data["status"]) or UserStatus.PENDING_ACTIVATION
        profile = UserProfile.from_dict(data["profile"])
        audit = UserAudit(**data.get("audit", {}))
        return cls(
            user_id=UUID(data["user_id"]),
            username=data["username"],
            email=data["email"],
            password_hash=PasswordHashedVO(data["password_hash"], "bcrypt")
            if isinstance(data.get("password_hash"), str)
            else data.get("password_hash"),
            status=status,
            profile=profile,
            legal_entity_id=UUID(data["legal_entity_id"]),
            role_ids=[UUID(rid) for rid in data.get("role_ids", [])],
            failed_login_attempts=data.get("failed_login_attempts", 0),
            locked_until=datetime.fromisoformat(data["locked_until"])
            if data.get("locked_until")
            else None,
            mfa_enabled=data.get("mfa_enabled", False),
            mfa_secret=data.get("mfa_secret"),
            audit=audit,
        )

    def clone(self) -> UserEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        new_audit = UserAudit(
            created_at=now,
            created_by=self.audit.created_by,
            updated_at=now,
            updated_by=self.audit.created_by,
            version=1,
        )
        cloned = UserEntity(
            user_id=new_id,
            username=f"{self.username}_COPY",
            email=f"copy_{self.email}",
            password_hash=self.password_hash,
            status=UserStatus.PENDING_ACTIVATION,
            profile=UserProfile(
                full_name=f"{self.profile.full_name} (COPY)",
                email=f"copy_{self.profile.email}",
                phone=self.profile.phone,
                mobile=self.profile.mobile,
                department=self.profile.department,
                position=self.profile.position,
                timezone=self.profile.timezone,
                language=self.profile.language,
            ),
            legal_entity_id=self.legal_entity_id,
            role_ids=[],
            audit=new_audit,
        )
        cloned._record_audit("CLONE", self.audit.created_by, {"source": str(self.user_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.audit.version,
            "user_id": str(self.user_id),
            "username": self.username,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @property
    def version(self) -> int:
        return self.audit.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> UserEntity:
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=touched_by,
            version=self.audit.version + 1,
        )
        new_user = UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=self.status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )
        new_user._record_audit("TOUCH", touched_by, {})
        return new_user

    # ==================== BUSINESS LOGIC ====================

    def is_active(self) -> bool:
        """Return True if user is active and not locked."""
        return (
            self.status == UserStatus.ACTIVE
            and (self.locked_until is None or datetime.now(UTC) >= self.locked_until)
        )

    def is_locked(self) -> bool:
        if self.locked_until:
            return datetime.now(UTC) < self.locked_until
        return self.status == UserStatus.LOCKED

    def can_login(self) -> bool:
        return self.status.can_login() and not self.is_locked()

    def record_login_success(self, ip_address: str) -> UserEntity:
        new_audit = UserAudit(
            last_login_at=datetime.now(UTC),
            last_login_ip=ip_address,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=self.audit.created_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=self.status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )

    def record_login_failure(
        self, max_attempts: int = 5, lock_duration_minutes: int = 30
    ) -> UserEntity:
        new_attempts = self.failed_login_attempts + 1
        locked_until = None
        new_status = self.status

        if new_attempts >= max_attempts:
            locked_until = datetime.now(UTC) + timedelta(minutes=lock_duration_minutes)
            new_status = UserStatus.LOCKED

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=self.audit.created_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=new_status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=new_attempts,
            locked_until=locked_until,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )

    def change_password(self, new_password_hash: PasswordHashedVO, changed_by: str) -> UserEntity:
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=datetime.now(UTC),
            last_password_change_by=changed_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=changed_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=new_password_hash,
            status=self.status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=0,
            locked_until=None,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )

    def update_profile(self, full_name: str, email: str, updated_by: str, **kwargs) -> UserEntity:
        new_profile = UserProfile(
            full_name=full_name,
            email=email,
            phone=kwargs.get("phone", self.profile.phone),
            mobile=kwargs.get("mobile", self.profile.mobile),
            department=kwargs.get("department", self.profile.department),
            position=kwargs.get("position", self.profile.position),
            avatar_url=kwargs.get("avatar_url", self.profile.avatar_url),
            timezone=kwargs.get("timezone", self.profile.timezone),
            language=kwargs.get("language", self.profile.language),
            metadata=kwargs.get("metadata", self.profile.metadata),
        )
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=updated_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=email,
            password_hash=self.password_hash,
            status=self.status,
            profile=new_profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )

    def suspend(self, suspended_by: str, reason: str) -> UserEntity:
        if self.status == UserStatus.SUSPENDED:
            return self

        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=suspended_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=UserStatus.SUSPENDED,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=self.mfa_enabled,
            mfa_secret=self.mfa_secret,
            audit=new_audit,
        )

    def enable_mfa(self, secret: str, enabled_by: str) -> UserEntity:
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=enabled_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=self.status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=True,
            mfa_secret=secret,
            audit=new_audit,
        )

    def disable_mfa(self, disabled_by: str) -> UserEntity:
        new_audit = UserAudit(
            last_login_at=self.audit.last_login_at,
            last_login_ip=self.audit.last_login_ip,
            last_password_change_at=self.audit.last_password_change_at,
            last_password_change_by=self.audit.last_password_change_by,
            created_at=self.audit.created_at,
            created_by=self.audit.created_by,
            updated_at=datetime.now(UTC),
            updated_by=disabled_by,
            version=self.audit.version + 1,
        )
        return UserEntity(
            user_id=self.user_id,
            username=self.username,
            email=self.email,
            password_hash=self.password_hash,
            status=self.status,
            profile=self.profile,
            legal_entity_id=self.legal_entity_id,
            role_ids=self.role_ids,
            failed_login_attempts=self.failed_login_attempts,
            locked_until=self.locked_until,
            mfa_enabled=False,
            mfa_secret=None,
            audit=new_audit,
        )

    # ==================== CLASS METHODS ====================

    @classmethod
    def get_instance(cls, identifier: str) -> UserEntity | None:
        return cls._instances.get(identifier)

    @classmethod
    def register(
        cls,
        username: str,
        email: str,
        password_hash: PasswordHashedVO,
        legal_entity_id: UUID,
        full_name: str,
        created_by: str = "system",
    ) -> UserEntity:
        profile = UserProfile(
            full_name=full_name,
            email=email,
        )
        return cls(
            user_id=uuid4(),
            username=username,
            email=email,
            password_hash=password_hash,
            status=UserStatus.PENDING_ACTIVATION,
            profile=profile,
            legal_entity_id=legal_entity_id,
            role_ids=[],
            audit=UserAudit(created_by=created_by),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class UserRepository:
    _storage: ClassVar[dict[UUID, UserEntity]] = {}
    _storage_by_username: ClassVar[dict[str, UUID]] = {}
    _storage_by_email: ClassVar[dict[str, UUID]] = {}

    @classmethod
    async def get_by_id(cls, user_id: UUID, legal_entity_id: UUID) -> UserEntity | None:
        user = cls._storage.get(user_id)
        if user and user.legal_entity_id == legal_entity_id:
            return user
        return None

    @classmethod
    async def get_by_username(cls, username: str, legal_entity_id: UUID) -> UserEntity | None:
        user_id = cls._storage_by_username.get(username)
        if user_id:
            user = cls._storage.get(user_id)
            if user and user.legal_entity_id == legal_entity_id:
                return user
        return None

    @classmethod
    async def get_by_email(cls, email: str, legal_entity_id: UUID) -> UserEntity | None:
        user_id = cls._storage_by_email.get(email)
        if user_id:
            user = cls._storage.get(user_id)
            if user and user.legal_entity_id == legal_entity_id:
                return user
        return None

    @classmethod
    async def list_by_legal_entity(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[UserEntity]:
        users = [u for u in cls._storage.values() if u.legal_entity_id == legal_entity_id]
        return users[offset : offset + limit]

    @classmethod
    async def list_by_status(
        cls, legal_entity_id: UUID, status: UserStatus, limit: int = 100
    ) -> list[UserEntity]:
        users = [
            u
            for u in cls._storage.values()
            if u.legal_entity_id == legal_entity_id and u.status == status
        ]
        return users[:limit]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[UserEntity]:
        return [u for u in cls._storage.values() if u.legal_entity_id == legal_entity_id]

    @classmethod
    async def save(cls, user: UserEntity, legal_entity_id: UUID) -> None:
        if user.legal_entity_id != legal_entity_id:
            raise UserError("User legal entity mismatch")
        cls._storage[user.user_id] = user
        cls._storage_by_username[user.username] = user.user_id
        cls._storage_by_email[user.email] = user.user_id

    @classmethod
    async def update(cls, user: UserEntity, legal_entity_id: UUID) -> None:
        await cls.save(user, legal_entity_id)

    @classmethod
    async def delete(cls, user_id: UUID, legal_entity_id: UUID) -> None:
        user = cls._storage.get(user_id)
        if user and user.legal_entity_id == legal_entity_id:
            cls._storage_by_username.pop(user.username, None)
            cls._storage_by_email.pop(user.email, None)
            cls._storage.pop(user_id, None)

    @classmethod
    async def exists(cls, user_id: UUID, legal_entity_id: UUID) -> bool:
        user = cls._storage.get(user_id)
        return user is not None and user.legal_entity_id == legal_entity_id

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        return len([u for u in cls._storage.values() if u.legal_entity_id == legal_entity_id])

    @classmethod
    async def list(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[UserEntity]:
        users = await cls.get_all(legal_entity_id)
        return users[offset : offset + limit]

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        to_delete = [u for u in cls._storage.values() if u.legal_entity_id == legal_entity_id]
        for u in to_delete:
            cls._storage_by_username.pop(u.username, None)
            cls._storage_by_email.pop(u.email, None)
            cls._storage.pop(u.user_id, None)


__all__ = [
    "UserAudit",
    "UserEntity",
    "UserError",
    "UserProfile",
    "UserRepository",
    "UserStatus",
]
