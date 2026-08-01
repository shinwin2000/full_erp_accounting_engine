#!/usr/bin/env python3
"""
Module: version_lock.py
Layer: 1 - Foundation / Constitution
Responsibility: Mengunci versi konstitusi agar tidak diubah sembarangan.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalViolationError,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class VersionLockState(Enum):
    UNLOCKED = auto()
    LOCKED = auto()
    FROZEN = auto()
    CORRUPTED = auto()


class VersionLockSeverity(Enum):
    CRITICAL = 100
    HIGH = 70
    MEDIUM = 40
    LOW = 10


class VersionChangeType(Enum):
    MAJOR = auto()
    MINOR = auto()
    PATCH = auto()
    EMERGENCY = auto()
    CORRUPTION_RECOVERY = auto()


class IntegrityCheckResult(Enum):
    INTACT = auto()
    MODIFIED = auto()
    CORRUPTED = auto()
    TAMPERED = auto()
    INCOMPLETE = auto()


class VersionLockEventType(Enum):
    STATE_CHANGE = auto()
    VERSION_CHANGE = auto()
    INTEGRITY_CHECK = auto()
    INTEGRITY_VIOLATION = auto()


# === 2. EXCEPTIONS ===


class VersionLockError(Exception):
    pass


class VersionLockViolationError(VersionLockError):
    def __init__(
        self, message: str, severity: VersionLockSeverity, attempted_version: str | None = None
    ):
        self.severity = severity
        self.attempted_version = attempted_version
        super().__init__(f"[{severity.name}] {message}")


class VersionIntegrityError(VersionLockError):
    pass


class VersionFreezeError(VersionLockError):
    pass


class InsufficientApprovalError(VersionLockError):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class VersionMetadata:
    # Required fields (no defaults)
    version: str
    release_date: datetime
    created_by: str
    approved_by: list[str]
    change_type: VersionChangeType
    changelog_entry: str
    # Optional fields (with defaults)
    cryptographic_hash: str = ""
    previous_version_hash: str | None = None
    constitution_snapshot_id: UUID | None = None
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        parts = self.version.split(".")
        if len(parts) != 3:
            raise ValueError(f"Invalid semantic version: {self.version}")
        try:
            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
            if major < 0 or minor < 0 or patch < 0:
                raise ValueError("Version components must be non-negative")
        except ValueError:
            raise ValueError(f"Invalid semantic version: {self.version}")
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")
        if self.release_date.tzinfo is None:
            object.__setattr__(self, "release_date", self.release_date.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        content = f"{self.version}|{self.release_date.isoformat()}|{self.created_by}|{','.join(self.approved_by)}|{self.change_type.value}|{self.changelog_entry}|{self.previous_version_hash or ''}|{str(self.constitution_snapshot_id) if self.constitution_snapshot_id else ''}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "release_version": self.version,
                "change_type": self.change_type.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "release_version": self.version,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> VersionMetadata:
        return self

    def update(self, updated_by: str, **kwargs) -> VersionMetadata:
        raise AttributeError("VersionMetadata is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> VersionMetadata:
        raise AttributeError("Cannot delete version metadata")

    def restore(self, restored_by: str) -> VersionMetadata:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> VersionMetadata:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> VersionMetadata:
        return self

    def lock(self, locked_by: str, reason: str) -> VersionMetadata:
        return self

    def unlock(self, unlocked_by: str) -> VersionMetadata:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "version": self.version,
            "version_number": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "release_date": self.release_date.isoformat(),
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "change_type": self.change_type.name,
            "changelog_entry": self.changelog_entry[:200],
            "hash": self.cryptographic_hash[:16] + "...",
            "previous_hash": self.previous_version_hash[:16] + "..."
            if self.previous_version_hash
            else None,
            "constitution_snapshot_id": str(self.constitution_snapshot_id)
            if self.constitution_snapshot_id
            else None,
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionMetadata:
        return cls(
            version=data["version"],
            release_date=datetime.fromisoformat(data["release_date"]),
            created_by=data["created_by"],
            approved_by=data["approved_by"],
            change_type=VersionChangeType[data["change_type"]],
            changelog_entry=data["changelog_entry"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            previous_version_hash=data.get("previous_hash"),
            constitution_snapshot_id=UUID(data["constitution_snapshot_id"])
            if data.get("constitution_snapshot_id")
            else None,
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> VersionMetadata:
        return VersionMetadata(
            version=self.version,
            release_date=self.release_date,
            created_by=self.created_by,
            approved_by=self.approved_by.copy(),
            change_type=self.change_type,
            changelog_entry=self.changelog_entry,
            cryptographic_hash="",
            previous_version_hash=self.cryptographic_hash,
            constitution_snapshot_id=self.constitution_snapshot_id,
            version_number=self.version_number + 1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "release_version": self.version,
            "change_type": self.change_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VersionMetadata:
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass(kw_only=True)
class VersionLockRecord:
    # Required fields (no defaults)
    record_id: UUID
    previous_state: VersionLockState
    new_state: VersionLockState
    reason: str
    initiated_by: str
    initiated_at: datetime
    approved_by: list[str]
    event_type: VersionLockEventType
    # Optional fields (with defaults)
    expires_at: datetime | None = None
    cryptographic_signature: str = ""
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.initiated_by, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")
        if self.initiated_at.tzinfo is None:
            object.__setattr__(self, "initiated_at", self.initiated_at.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "record_id": str(self.record_id),
                "event_type": self.event_type.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "record_id": str(self.record_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> VersionLockRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> VersionLockRecord:
        raise AttributeError("VersionLockRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> VersionLockRecord:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> VersionLockRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> VersionLockRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> VersionLockRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> VersionLockRecord:
        return self

    def unlock(self, unlocked_by: str) -> VersionLockRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "record_id": str(self.record_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": str(self.record_id),
            "previous_state": self.previous_state.name,
            "new_state": self.new_state.name,
            "reason": self.reason,
            "initiated_by": self.initiated_by,
            "initiated_at": self.initiated_at.isoformat(),
            "approved_by": self.approved_by,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "cryptographic_signature": self.cryptographic_signature[:16] + "...",
            "event_type": self.event_type.name,
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionLockRecord:
        return cls(
            record_id=UUID(data["record_id"]),
            previous_state=VersionLockState[data["previous_state"]],
            new_state=VersionLockState[data["new_state"]],
            reason=data["reason"],
            initiated_by=data["initiated_by"],
            initiated_at=datetime.fromisoformat(data["initiated_at"]),
            approved_by=data["approved_by"],
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            cryptographic_signature=data.get("cryptographic_signature", ""),
            event_type=VersionLockEventType[data["event_type"]],
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> VersionLockRecord:
        new_id = uuid4()
        return VersionLockRecord(
            record_id=new_id,
            previous_state=self.previous_state,
            new_state=self.new_state,
            reason=self.reason,
            initiated_by=self.initiated_by,
            initiated_at=datetime.now(UTC),
            approved_by=self.approved_by.copy(),
            expires_at=self.expires_at,
            cryptographic_signature=self.cryptographic_signature,
            event_type=self.event_type,
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "record_id": str(self.record_id),
            "event_type": self.event_type.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VersionLockRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_active(self) -> bool:
        if self.expires_at is None:
            return True
        return datetime.now(UTC) < self.expires_at

    def compute_signature_content(self) -> str:
        return f"{self.record_id}|{self.previous_state.value}|{self.new_state.value}|{self.reason}|{self.initiated_by}|{self.initiated_at.isoformat()}|{','.join(self.approved_by)}|{self.expires_at.isoformat() if self.expires_at else ''}"


@dataclass(kw_only=True)
class VersionChangeAttempt:
    # Required fields (no defaults)
    attempt_id: UUID
    target_version: str
    change_type: VersionChangeType
    attempted_by: str
    attempted_at: datetime
    success: bool
    requires_approval: bool
    approvals_received: list[str]
    # Optional fields (with defaults)
    failure_reason: str | None = None
    cryptographic_hash: str = ""
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.attempted_by, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")
        if self.attempted_at.tzinfo is None:
            object.__setattr__(self, "attempted_at", self.attempted_at.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        content = f"{self.attempt_id}|{self.target_version}|{self.change_type.value}|{self.attempted_by}|{self.attempted_at.isoformat()}|{self.success}|{self.failure_reason or ''}|{self.requires_approval}|{','.join(self.approvals_received)}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "attempt_id": str(self.attempt_id),
                "success": self.success,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "attempt_id": str(self.attempt_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> VersionChangeAttempt:
        return self

    def update(self, updated_by: str, **kwargs) -> VersionChangeAttempt:
        raise AttributeError("VersionChangeAttempt is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> VersionChangeAttempt:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> VersionChangeAttempt:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> VersionChangeAttempt:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> VersionChangeAttempt:
        return self

    def lock(self, locked_by: str, reason: str) -> VersionChangeAttempt:
        return self

    def unlock(self, unlocked_by: str) -> VersionChangeAttempt:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "attempt_id": str(self.attempt_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": str(self.attempt_id),
            "target_version": self.target_version,
            "change_type": self.change_type.name,
            "attempted_by": self.attempted_by,
            "attempted_at": self.attempted_at.isoformat(),
            "success": self.success,
            "failure_reason": self.failure_reason,
            "requires_approval": self.requires_approval,
            "approvals_received": self.approvals_received,
            "hash": self.cryptographic_hash[:16] + "...",
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionChangeAttempt:
        return cls(
            attempt_id=UUID(data["attempt_id"]),
            target_version=data["target_version"],
            change_type=VersionChangeType[data["change_type"]],
            attempted_by=data["attempted_by"],
            attempted_at=datetime.fromisoformat(data["attempted_at"]),
            success=data["success"],
            failure_reason=data.get("failure_reason"),
            requires_approval=data["requires_approval"],
            approvals_received=data["approvals_received"],
            cryptographic_hash=data.get("hash", ""),
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> VersionChangeAttempt:
        new_id = uuid4()
        return VersionChangeAttempt(
            attempt_id=new_id,
            target_version=self.target_version,
            change_type=self.change_type,
            attempted_by=self.attempted_by,
            attempted_at=datetime.now(UTC),
            success=False,
            failure_reason=self.failure_reason,
            requires_approval=self.requires_approval,
            approvals_received=[],
            cryptographic_hash="",
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "attempt_id": str(self.attempt_id),
            "success": self.success,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VersionChangeAttempt:
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass(kw_only=True)
class IntegrityReport:
    # Required fields (no defaults)
    report_id: UUID
    checked_at: datetime
    checked_by: str
    expected_version: str
    actual_version: str | None
    expected_hash: str
    actual_hash: str
    result: IntegrityCheckResult
    discrepancies: list[str]
    recommended_action: str
    # Optional fields (with defaults)
    cryptographic_signature: str = ""
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_signature:
            object.__setattr__(self, "cryptographic_signature", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.checked_by, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")
        if self.checked_at.tzinfo is None:
            object.__setattr__(self, "checked_at", self.checked_at.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        content = f"{self.report_id}|{self.checked_at.isoformat()}|{self.checked_by}|{self.expected_version}|{self.actual_version or ''}|{self.expected_hash}|{self.actual_hash}|{self.result.value}|{','.join(self.discrepancies)}|{self.recommended_action}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "report_id": str(self.report_id),
                "result": self.result.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "report_id": str(self.report_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> IntegrityReport:
        return self

    def update(self, updated_by: str, **kwargs) -> IntegrityReport:
        raise AttributeError("IntegrityReport is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> IntegrityReport:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> IntegrityReport:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> IntegrityReport:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntegrityReport:
        return self

    def lock(self, locked_by: str, reason: str) -> IntegrityReport:
        return self

    def unlock(self, unlocked_by: str) -> IntegrityReport:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_signature != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "report_id": str(self.report_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": str(self.report_id),
            "checked_at": self.checked_at.isoformat(),
            "checked_by": self.checked_by,
            "expected_version": self.expected_version,
            "actual_version": self.actual_version,
            "expected_hash": self.expected_hash[:16] + "...",
            "actual_hash": self.actual_hash[:16] + "...",
            "result": self.result.name,
            "discrepancies": self.discrepancies,
            "recommended_action": self.recommended_action,
            "signature": self.cryptographic_signature[:16] + "...",
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntegrityReport:
        return cls(
            report_id=UUID(data["report_id"]),
            checked_at=datetime.fromisoformat(data["checked_at"]),
            checked_by=data["checked_by"],
            expected_version=data["expected_version"],
            actual_version=data.get("actual_version"),
            expected_hash=data["expected_hash"],
            actual_hash=data["actual_hash"],
            result=IntegrityCheckResult[data["result"]],
            discrepancies=data["discrepancies"],
            recommended_action=data["recommended_action"],
            cryptographic_signature=data.get("signature", ""),
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> IntegrityReport:
        new_id = uuid4()
        return IntegrityReport(
            report_id=new_id,
            checked_at=datetime.now(UTC),
            checked_by=self.checked_by,
            expected_version=self.expected_version,
            actual_version=self.actual_version,
            expected_hash=self.expected_hash,
            actual_hash=self.actual_hash,
            result=self.result,
            discrepancies=self.discrepancies.copy(),
            recommended_action=self.recommended_action,
            cryptographic_signature="",
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "report_id": str(self.report_id),
            "result": self.result.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntegrityReport:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. VERSION LOCK AGGREGATE ===


@dataclass(kw_only=True)
class VersionLock:
    current_version: str
    current_state: VersionLockState
    version_history: list[VersionMetadata] = field(default_factory=list)
    lock_records: list[VersionLockRecord] = field(default_factory=list)
    change_attempts: list[VersionChangeAttempt] = field(default_factory=list)
    integrity_reports: list[IntegrityReport] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.version_history:
            self._create_initial_version()

    def _create_initial_version(self) -> None:
        now = datetime.now(UTC)
        initial_metadata = VersionMetadata(
            version="1.0.0",
            release_date=now,
            created_by="system_bootstrap",
            approved_by=["system_bootstrap", "audit_committee_founder"],
            change_type=VersionChangeType.MAJOR,
            changelog_entry="Initial constitution version",
            cryptographic_hash="",
            previous_version_hash=None,
            constitution_snapshot_id=None,
            version_number=1,
        )
        self.version_history.append(initial_metadata)
        initial_lock = VersionLockRecord(
            record_id=uuid4(),
            previous_state=VersionLockState.UNLOCKED,
            new_state=VersionLockState.UNLOCKED,
            reason="System initialization",
            initiated_by="system_bootstrap",
            initiated_at=now,
            approved_by=["system_bootstrap"],
            expires_at=None,
            cryptographic_signature="",
            event_type=VersionLockEventType.STATE_CHANGE,
            version_number=1,
        )
        self.lock_records.append(initial_lock)
        self.current_version = initial_metadata.version

    # ==================== REPOSITORY METHODS ====================
    def save_version_metadata(self, metadata: VersionMetadata) -> None:
        with self._lock:
            self.version_history.append(metadata)
            self.current_version = metadata.version

    def get_current_metadata(self) -> VersionMetadata | None:
        return self.version_history[-1] if self.version_history else None

    def get_version_history(self, limit: int = 100) -> list[VersionMetadata]:
        return self.version_history[-limit:]

    def delete_version_metadata(self, version: str) -> bool:
        with self._lock:
            for i, v in enumerate(self.version_history):
                if v.version == version:
                    self.version_history.pop(i)
                    return True
            return False

    def save_lock_record(self, record: VersionLockRecord) -> None:
        with self._lock:
            self.lock_records.append(record)
            if record.event_type == VersionLockEventType.STATE_CHANGE:
                self.current_state = record.new_state

    def get_lock_records(
        self, limit: int = 100, event_type: VersionLockEventType | None = None
    ) -> list[VersionLockRecord]:
        result = self.lock_records[-limit:]
        if event_type:
            result = [r for r in result if r.event_type == event_type]
        return result

    def delete_lock_record(self, record_id: UUID) -> bool:
        with self._lock:
            for i, r in enumerate(self.lock_records):
                if r.record_id == record_id:
                    self.lock_records.pop(i)
                    return True
            return False

    def save_change_attempt(self, attempt: VersionChangeAttempt) -> None:
        with self._lock:
            self.change_attempts.append(attempt)

    def get_change_attempts(self, limit: int = 100) -> list[VersionChangeAttempt]:
        return self.change_attempts[-limit:]

    def save_integrity_report(self, report: IntegrityReport) -> None:
        with self._lock:
            self.integrity_reports.append(report)

    def get_integrity_reports(self, limit: int = 50) -> list[IntegrityReport]:
        return self.integrity_reports[-limit:]

    # ==================== BUSINESS METHODS ====================
    def change_lock_state(
        self,
        new_state: VersionLockState,
        reason: str,
        initiated_by: str,
        approved_by: list[str],
        expires_at: datetime | None = None,
        cryptographic_signer: Callable[[str], str] | None = None,
    ) -> VersionLockRecord:
        with self._lock:
            if (
                new_state in [VersionLockState.LOCKED, VersionLockState.FROZEN]
                and len(approved_by) < 2
            ):
                raise VersionLockViolationError(
                    f"Changing to {new_state.name} requires at least 2 approvers",
                    VersionLockSeverity.HIGH,
                )
            if (
                self.current_state == VersionLockState.FROZEN
                and new_state != VersionLockState.CORRUPTED
            ):
                raise VersionLockViolationError(
                    f"Cannot change from FROZEN to {new_state.name}", VersionLockSeverity.CRITICAL
                )
            previous = self.current_state
            record = VersionLockRecord(
                record_id=uuid4(),
                previous_state=previous,
                new_state=new_state,
                reason=reason,
                initiated_by=initiated_by,
                initiated_at=datetime.now(UTC),
                approved_by=approved_by,
                expires_at=expires_at,
                cryptographic_signature="",
                event_type=VersionLockEventType.STATE_CHANGE,
                version_number=1,
            )
            if cryptographic_signer:
                sig_content = record.compute_signature_content()
                record = VersionLockRecord(
                    record_id=record.record_id,
                    previous_state=record.previous_state,
                    new_state=record.new_state,
                    reason=record.reason,
                    initiated_by=record.initiated_by,
                    initiated_at=record.initiated_at,
                    approved_by=record.approved_by,
                    expires_at=record.expires_at,
                    cryptographic_signature=cryptographic_signer(sig_content),
                    event_type=record.event_type,
                    version_number=1,
                )
            self.lock_records.append(record)
            self.current_state = new_state
            self._notify_supreme_law(new_state, reason)
            return record

    def _notify_supreme_law(self, new_state: VersionLockState, reason: str) -> None:
        try:
            supreme_law = get_supreme_law()
            if new_state == VersionLockState.FROZEN:
                supreme_law.check_violation(
                    ConstitutionalPrinciple.IMMUTABILITY, "version_lock", f"System frozen: {reason}"
                )
        except Exception as e:
            logger.error(f"Failed to notify supreme law: {e}")

    def attempt_version_change(
        self,
        target_version: str,
        change_type: VersionChangeType,
        attempted_by: str,
        requires_approval: bool = True,
        approvals: list[str] | None = None,
    ) -> VersionChangeAttempt:
        approvals = approvals or []
        success = True
        failure_reason = None
        if self.current_state == VersionLockState.FROZEN:
            success = False
            failure_reason = "System is frozen, no version changes allowed"
        elif self.current_state == VersionLockState.LOCKED and not requires_approval:
            success = False
            failure_reason = "System is locked, version changes require approval"
        elif requires_approval and len(approvals) < 2:
            success = False
            failure_reason = f"Version change requires at least 2 approvals, got {len(approvals)}"
        attempt = VersionChangeAttempt(
            attempt_id=uuid4(),
            target_version=target_version,
            change_type=change_type,
            attempted_by=attempted_by,
            attempted_at=datetime.now(UTC),
            success=success,
            failure_reason=failure_reason,
            requires_approval=requires_approval,
            approvals_received=approvals,
            cryptographic_hash="",
            version_number=1,
        )
        self.save_change_attempt(attempt)
        return attempt

    def commit_version_change(
        self,
        new_version: str,
        change_type: VersionChangeType,
        changelog_entry: str,
        committed_by: str,
        approved_by: list[str],
        previous_version_hash: str | None = None,
        constitution_snapshot_id: UUID | None = None,
    ) -> VersionMetadata:
        with self._lock:
            if self.current_state == VersionLockState.FROZEN:
                raise VersionLockViolationError(
                    "Cannot commit version change: system is frozen", VersionLockSeverity.CRITICAL
                )
            parts = new_version.split(".")
            current_parts = self.current_version.split(".")
            try:
                major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                curr_major, curr_minor, curr_patch = (
                    int(current_parts[0]),
                    int(current_parts[1]),
                    int(current_parts[2]),
                )
            except (ValueError, IndexError):
                raise VersionLockError(
                    f"Invalid version format: {new_version} or {self.current_version}"
                )
            if change_type == VersionChangeType.MAJOR:
                if major <= curr_major:
                    raise VersionLockError(
                        f"MAJOR version must increment: {new_version} > {self.current_version}"
                    )
            elif change_type == VersionChangeType.MINOR:
                if major != curr_major or minor <= curr_minor:
                    raise VersionLockError(
                        f"MINOR version must increment minor: {new_version} > {self.current_version}"
                    )
            elif change_type == VersionChangeType.PATCH:
                if major != curr_major or minor != curr_minor or patch <= curr_patch:
                    raise VersionLockError(
                        f"PATCH version must increment patch: {new_version} > {self.current_version}"
                    )
            elif change_type not in [
                VersionChangeType.EMERGENCY,
                VersionChangeType.CORRUPTION_RECOVERY,
            ]:
                pass
            previous = self.get_current_metadata()
            prev_hash = previous.cryptographic_hash if previous else None
            if previous_version_hash and prev_hash != previous_version_hash:
                raise VersionIntegrityError(
                    f"Previous version hash mismatch: expected {prev_hash}, got {previous_version_hash}"
                )
            new_metadata = VersionMetadata(
                version=new_version,
                release_date=datetime.now(UTC),
                created_by=committed_by,
                approved_by=approved_by,
                change_type=change_type,
                changelog_entry=changelog_entry,
                cryptographic_hash="",
                previous_version_hash=prev_hash,
                constitution_snapshot_id=constitution_snapshot_id,
                version_number=len(self.version_history) + 1,
            )
            self.version_history.append(new_metadata)
            self.current_version = new_version
            version_change_record = VersionLockRecord(
                record_id=uuid4(),
                previous_state=self.current_state,
                new_state=self.current_state,
                reason=f"Version changed to {new_version}: {changelog_entry[:100]}",
                initiated_by=committed_by,
                initiated_at=datetime.now(UTC),
                approved_by=approved_by,
                expires_at=None,
                cryptographic_signature="",
                event_type=VersionLockEventType.VERSION_CHANGE,
                version_number=len(self.lock_records) + 1,
            )
            self.lock_records.append(version_change_record)
            return new_metadata

    def check_integrity(
        self,
        expected_version: str | None = None,
        expected_hash: str | None = None,
        checker_id: str = "system",
    ) -> IntegrityReport:
        expected_version = expected_version or self.current_version
        current_metadata = self.get_current_metadata()
        actual_version = current_metadata.version if current_metadata else None
        actual_hash = current_metadata.cryptographic_hash if current_metadata else None
        discrepancies = []
        result = IntegrityCheckResult.INTACT
        if actual_version != expected_version:
            discrepancies.append(
                f"Version mismatch: expected {expected_version}, actual {actual_version}"
            )
            result = IntegrityCheckResult.MODIFIED
        if expected_hash and actual_hash != expected_hash:
            discrepancies.append(
                f"Hash mismatch: expected {expected_hash[:16]}..., actual {actual_hash[:16]}..."
            )
            result = (
                IntegrityCheckResult.TAMPERED if expected_hash else IntegrityCheckResult.CORRUPTED
            )
        if actual_version is None or actual_hash is None:
            result = IntegrityCheckResult.INCOMPLETE
            discrepancies.append("Missing version metadata")
        if len(self.version_history) > 1:
            for i in range(1, len(self.version_history)):
                prev = self.version_history[i - 1]
                curr = self.version_history[i]
                if curr.previous_version_hash != prev.cryptographic_hash:
                    discrepancies.append(
                        f"Hash chain broken between {prev.version} and {curr.version}"
                    )
                    result = IntegrityCheckResult.TAMPERED
                    break
        if result == IntegrityCheckResult.TAMPERED:
            recommended_action = "IMMEDIATE_FREEZE_AND_AUDIT"
            try:
                self.change_lock_state(
                    VersionLockState.FROZEN,
                    f"Auto-freeze due to integrity failure: {', '.join(discrepancies)}",
                    checker_id,
                    [checker_id],
                )
            except Exception as e:
                logger.critical(f"Failed to auto-freeze: {e}")
        elif result == IntegrityCheckResult.MODIFIED:
            recommended_action = "REVIEW_AND_RECONCILE"
        elif result == IntegrityCheckResult.CORRUPTED:
            recommended_action = "RESTORE_FROM_BACKUP"
        else:
            recommended_action = "NONE"
        report = IntegrityReport(
            report_id=uuid4(),
            checked_at=datetime.now(UTC),
            checked_by=checker_id,
            expected_version=expected_version,
            actual_version=actual_version,
            expected_hash=expected_hash or "",
            actual_hash=actual_hash or "",
            result=result,
            discrepancies=discrepancies,
            recommended_action=recommended_action,
            cryptographic_signature="",
            version_number=len(self.integrity_reports) + 1,
        )
        self.save_integrity_report(report)
        integrity_event = VersionLockRecord(
            record_id=uuid4(),
            previous_state=self.current_state,
            new_state=self.current_state,
            reason=f"Integrity check: {result.name}",
            initiated_by=checker_id,
            initiated_at=datetime.now(UTC),
            approved_by=[checker_id],
            expires_at=None,
            cryptographic_signature="",
            event_type=VersionLockEventType.INTEGRITY_CHECK,
            version_number=len(self.lock_records) + 1,
        )
        self.lock_records.append(integrity_event)
        return report

    def is_modification_allowed(self, is_amendment: bool = False) -> bool:
        if self.current_state == VersionLockState.FROZEN:
            return False
        if self.current_state == VersionLockState.LOCKED and not is_amendment:
            return False
        # Perbaikan SIM103: kembalikan kondisi secara langsung
        return self.current_state != VersionLockState.CORRUPTED

    def get_version_timeline(self) -> list[dict[str, Any]]:
        return [v.to_dict() for v in self.version_history]

    def get_lock_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.lock_records[-limit:]]

    def get_integrity_report_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.integrity_reports[-limit:]]

    def get_statistics(self) -> dict[str, Any]:
        total_version_changes = len(
            [r for r in self.lock_records if r.event_type == VersionLockEventType.VERSION_CHANGE]
        )
        total_state_changes = len(
            [r for r in self.lock_records if r.event_type == VersionLockEventType.STATE_CHANGE]
        )
        total_integrity_checks = len(self.integrity_reports)
        failed_attempts = len([a for a in self.change_attempts if not a.success])
        successful_attempts = len([a for a in self.change_attempts if a.success])
        return {
            "current_version": self.current_version,
            "current_state": self.current_state.name,
            "is_modification_allowed": self.is_modification_allowed(),
            "total_version_changes": total_version_changes,
            "total_state_changes": total_state_changes,
            "total_integrity_checks": total_integrity_checks,
            "total_change_attempts": len(self.change_attempts),
            "successful_change_attempts": successful_attempts,
            "failed_change_attempts": failed_attempts,
            "last_integrity_result": self.integrity_reports[-1].result.name
            if self.integrity_reports
            else None,
            "last_integrity_at": self.integrity_reports[-1].checked_at.isoformat()
            if self.integrity_reports
            else None,
        }

    def reset(self) -> None:
        with self._lock:
            self.version_history = []
            self.lock_records = []
            self.change_attempts = []
            self.integrity_reports = []
            self._create_initial_version()
            self.current_state = VersionLockState.UNLOCKED


# === 5. VERSION LOCK SERVICE ===


class VersionLockService:
    _instance: VersionLockService | None = None
    _version_lock: VersionLock | None = None
    _scheduler_thread: threading.Thread | None = None
    _stop_scheduler: bool = False

    def __new__(cls) -> VersionLockService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._version_lock = VersionLock(
            current_version="1.0.0", current_state=VersionLockState.UNLOCKED
        )
        self._start_periodic_integrity_check()

    def _start_periodic_integrity_check(self) -> None:
        def periodic_check():
            import time

            while not self._stop_scheduler:
                time.sleep(21600)  # 6 hours
                if not self._stop_scheduler:
                    try:
                        self.run_integrity_check(checker_id="scheduler")
                    except Exception as e:
                        logger.error(f"Periodic integrity check failed: {e}")

        self._scheduler_thread = threading.Thread(target=periodic_check, daemon=True)
        self._scheduler_thread.start()

    def stop_periodic_check(self) -> None:
        self._stop_scheduler = True

    # ==================== REPOSITORY METHODS ====================
    def get_version_lock(self) -> VersionLock:
        return self._version_lock

    # ==================== BUSINESS METHODS ====================
    def lock(
        self,
        reason: str,
        initiated_by: str,
        approved_by: list[str],
        expires_at: datetime | None = None,
    ) -> VersionLockRecord:
        supreme_law = get_supreme_law()
        try:
            supreme_law.enforce(
                ConstitutionalPrinciple.NO_RETROACTIVE_POLICY,
                {"action": "version_lock", "initiated_by": initiated_by},
                "version_lock_service",
            )
        except ConstitutionalViolationError as e:
            raise VersionLockViolationError(f"Cannot lock version: {e}", VersionLockSeverity.HIGH)
        return self._version_lock.change_lock_state(
            VersionLockState.LOCKED, reason, initiated_by, approved_by, expires_at
        )

    def unlock(self, reason: str, initiated_by: str, approved_by: list[str]) -> VersionLockRecord:
        if self._version_lock.current_state == VersionLockState.FROZEN:
            raise VersionFreezeError("Cannot unlock: system is frozen. Unfreeze first.")
        return self._version_lock.change_lock_state(
            VersionLockState.UNLOCKED, reason, initiated_by, approved_by
        )

    def freeze(self, reason: str, initiated_by: str, approved_by: list[str]) -> VersionLockRecord:
        if "audit_committee_chair" not in approved_by:
            raise InsufficientApprovalError("Freeze requires Audit Committee Chair approval")
        return self._version_lock.change_lock_state(
            VersionLockState.FROZEN, reason, initiated_by, approved_by
        )

    def unfreeze(self, reason: str, initiated_by: str, approved_by: list[str]) -> VersionLockRecord:
        if self._version_lock.current_state != VersionLockState.FROZEN:
            raise VersionFreezeError(
                f"Cannot unfreeze: current state is {self._version_lock.current_state.name}"
            )
        if "audit_committee_chair" not in approved_by:
            raise InsufficientApprovalError("Unfreeze requires Audit Committee Chair approval")
        return self._version_lock.change_lock_state(
            VersionLockState.UNLOCKED, reason, initiated_by, approved_by
        )

    def propose_version_upgrade(
        self,
        target_version: str,
        change_type: VersionChangeType,
        changelog_entry: str,
        proposed_by: str,
        requires_approval: bool = True,
    ) -> VersionChangeAttempt:
        attempt = self._version_lock.attempt_version_change(
            target_version, change_type, proposed_by, requires_approval, []
        )
        if not attempt.success:
            raise VersionLockViolationError(
                f"Version upgrade proposal rejected: {attempt.failure_reason}",
                VersionLockSeverity.MEDIUM,
            )
        return attempt

    def commit_version_upgrade(
        self,
        target_version: str,
        change_type: VersionChangeType,
        changelog_entry: str,
        committed_by: str,
        approved_by: list[str],
        constitution_snapshot_id: UUID | None = None,
    ) -> VersionMetadata:
        if not self._version_lock.is_modification_allowed(is_amendment=True):
            raise VersionLockViolationError(
                f"Version upgrade not allowed in state {self._version_lock.current_state.name}",
                VersionLockSeverity.CRITICAL,
            )
        return self._version_lock.commit_version_change(
            target_version,
            change_type,
            changelog_entry,
            committed_by,
            approved_by,
            None,
            constitution_snapshot_id,
        )

    def run_integrity_check(
        self,
        checker_id: str = "scheduled_job",
        expected_version: str | None = None,
        expected_hash: str | None = None,
    ) -> IntegrityReport:
        return self._version_lock.check_integrity(expected_version, expected_hash, checker_id)

    def get_status(self) -> dict[str, Any]:
        stats = self._version_lock.get_statistics()
        current_metadata = self._version_lock.get_current_metadata()
        return {
            "current_version": self._version_lock.current_version,
            "current_state": self._version_lock.current_state.name,
            "is_modification_allowed": self._version_lock.is_modification_allowed(),
            "current_metadata": current_metadata.to_dict() if current_metadata else None,
            "statistics": stats,
            "last_integrity_report": self._version_lock.integrity_reports[-1].to_dict()
            if self._version_lock.integrity_reports
            else None,
        }

    def get_version_timeline(self) -> list[dict[str, Any]]:
        return self._version_lock.get_version_timeline()

    def get_lock_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._version_lock.get_lock_history(limit)

    def get_integrity_report_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._version_lock.get_integrity_report_history(limit)

    def verify_full_integrity_chain(self) -> dict[str, Any]:
        version_chain_valid = True
        broken_at = None
        for i in range(1, len(self._version_lock.version_history)):
            prev = self._version_lock.version_history[i - 1]
            curr = self._version_lock.version_history[i]
            if curr.previous_version_hash != prev.cryptographic_hash:
                version_chain_valid = False
                broken_at = i
                break
        return {
            "version_chain_valid": version_chain_valid,
            "broken_at_version_index": broken_at,
            "total_versions": len(self._version_lock.version_history),
            "total_integrity_reports": len(self._version_lock.integrity_reports),
            "current_integrity_status": self._version_lock.integrity_reports[-1].result.name
            if self._version_lock.integrity_reports
            else "UNKNOWN",
        }

    def emergency_version_restore(
        self, target_version: str, reason: str, initiated_by: str, approved_by: list[str]
    ) -> VersionMetadata:
        from constitution.sovereignty_declaration import SovereigntyStatus, get_sovereignty_guardian

        guardian = get_sovereignty_guardian()
        current_status = guardian.get_current_status()
        if current_status not in [
            SovereigntyStatus.EMERGENCY_LOCKDOWN,
            getattr(SovereigntyStatus, "FROZEN", None),
        ]:
            raise VersionLockViolationError(
                f"Emergency restore only allowed in EMERGENCY_LOCKDOWN or FROZEN, current: {current_status.name}",
                VersionLockSeverity.CRITICAL,
            )
        if len(approved_by) < 3:
            raise InsufficientApprovalError(
                "Emergency version restore requires at least 3 approvers"
            )
        target_metadata = None
        for v in self._version_lock.version_history:
            if v.version == target_version:
                target_metadata = v
                break
        if not target_metadata:
            raise VersionLockError(f"Target version {target_version} not found in history")
        return self._version_lock.commit_version_change(
            target_version + "-restored",
            VersionChangeType.CORRUPTION_RECOVERY,
            f"Emergency restore to {target_version}: {reason}",
            initiated_by,
            approved_by,
            target_metadata.cryptographic_hash,
        )


def get_version_lock_service() -> VersionLockService:
    global _version_lock_service_instance
    if _version_lock_service_instance is None:
        _version_lock_service_instance = VersionLockService()
    return _version_lock_service_instance


_version_lock_service_instance: VersionLockService | None = None

__all__ = [
    "InsufficientApprovalError",
    "IntegrityCheckResult",
    "IntegrityReport",
    "VersionChangeAttempt",
    "VersionChangeType",
    "VersionFreezeError",
    "VersionIntegrityError",
    "VersionLock",
    "VersionLockError",
    "VersionLockEventType",
    "VersionLockRecord",
    "VersionLockService",
    "VersionLockSeverity",
    "VersionLockState",
    "VersionLockViolationError",
    "VersionMetadata",
    "get_version_lock_service",
]
