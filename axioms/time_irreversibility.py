#!/usr/bin/env python3
"""
Module: time_irreversibility.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: waktu akuntansi tidak bisa mundur.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class TimeIrreversibilityViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class TransactionTimeContext(Enum):
    POSTING = auto()
    EFFECTIVE = auto()
    APPROVAL = auto()
    SETTLEMENT = auto()
    CREATION = auto()


class TimeFlowDirection(Enum):
    FORWARD = auto()
    BACKWARD = auto()
    SAME = auto()


# === 2. EXCEPTIONS ===


class TimeIrreversibilityError(Exception):
    pass


class TimeIrreversibilityViolationError(Exception):
    def __init__(self, message: str, violation: TimeIrreversibilityViolation):
        self.violation = violation
        super().__init__(message)


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class TimeBoundary:
    period_id: UUID
    period_name: str
    fiscal_year: int
    period_number: int
    start_date: datetime
    end_date: datetime
    is_closed: bool
    is_locked: bool
    closed_at: datetime | None = None
    closed_by: str | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.start_date >= self.end_date:
            raise ValueError("Start date must be before end date")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.period_id}|{self.fiscal_year}|{self.period_number}|{self.start_date.isoformat()}|{self.end_date.isoformat()}|{self.is_closed}|{self.is_locked}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "period_id": str(self.period_id),
                "is_closed": self.is_closed,
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
                "version": self.version,
                "period_id": str(self.period_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> TimeBoundary:
        return self

    def update(self, updated_by: str, **kwargs) -> TimeBoundary:
        new_boundary = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_boundary, key) and key not in ("period_id", "version"):
                setattr(new_boundary, key, value)
        new_boundary.version = self.version + 1
        new_boundary._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_boundary

    def delete(self, deleted_by: str, reason: str | None = None) -> TimeBoundary:
        new_boundary = self._copy()
        new_boundary.deleted_at = datetime.now(UTC)
        new_boundary.deleted_by = deleted_by
        new_boundary.version = self.version + 1
        new_boundary._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_boundary

    def restore(self, restored_by: str) -> TimeBoundary:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_boundary = self._copy()
        new_boundary.deleted_at = None
        new_boundary.deleted_by = None
        new_boundary.version = self.version + 1
        new_boundary._record_audit("RESTORE", restored_by, {})
        return new_boundary

    def activate(self, activated_by: str) -> TimeBoundary:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> TimeBoundary:
        return self

    def lock(self, locked_by: str, reason: str) -> TimeBoundary:
        if self.is_locked:
            return self
        return self.update(
            locked_by, is_locked=True, locked_at=datetime.now(UTC), locked_by=locked_by
        )

    def unlock(self, unlocked_by: str) -> TimeBoundary:
        if not self.is_locked:
            return self
        return self.update(unlocked_by, is_locked=False, locked_at=None, locked_by=None)

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
            "period_id": str(self.period_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "period_name": self.period_name,
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "is_closed": self.is_closed,
            "is_locked": self.is_locked,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": self.locked_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeBoundary:
        return cls(
            period_id=UUID(data["period_id"]),
            period_name=data["period_name"],
            fiscal_year=data["fiscal_year"],
            period_number=data["period_number"],
            start_date=datetime.fromisoformat(data["start_date"]),
            end_date=datetime.fromisoformat(data["end_date"]),
            is_closed=data["is_closed"],
            is_locked=data["is_locked"],
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            closed_by=data.get("closed_by"),
            locked_at=datetime.fromisoformat(data["locked_at"]) if data.get("locked_at") else None,
            locked_by=data.get("locked_by"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> TimeBoundary:
        new_id = uuid4()
        return TimeBoundary(
            period_id=new_id,
            period_name=f"{self.period_name}_COPY",
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            start_date=self.start_date,
            end_date=self.end_date,
            is_closed=False,
            is_locked=False,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "period_id": str(self.period_id),
            "is_closed": self.is_closed,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TimeBoundary:
        new_boundary = self._copy()
        new_boundary.version = self.version + 1
        new_boundary._record_audit("TOUCH", touched_by, {})
        return new_boundary

    def contains(self, dt: datetime) -> bool:
        dt_utc = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        start = self.start_date if self.start_date.tzinfo else self.start_date.replace(tzinfo=UTC)
        end = self.end_date if self.end_date.tzinfo else self.end_date.replace(tzinfo=UTC)
        return start <= dt_utc <= end

    def is_modifiable(self) -> bool:
        return not self.is_closed and not self.is_locked

    def _copy(self) -> TimeBoundary:
        return TimeBoundary(
            period_id=self.period_id,
            period_name=self.period_name,
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            start_date=self.start_date,
            end_date=self.end_date,
            is_closed=self.is_closed,
            is_locked=self.is_locked,
            closed_at=self.closed_at,
            closed_by=self.closed_by,
            locked_at=self.locked_at,
            locked_by=self.locked_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class TransactionTimestamp:
    transaction_id: UUID
    effective_date: datetime
    posting_date: datetime
    approval_date: datetime | None
    settlement_date: datetime | None
    created_at: datetime
    created_by: str
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.effective_date.tzinfo is None:
            object.__setattr__(self, "effective_date", self.effective_date.replace(tzinfo=UTC))
        if self.posting_date.tzinfo is None:
            object.__setattr__(self, "posting_date", self.posting_date.replace(tzinfo=UTC))
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.transaction_id}|{self.effective_date.isoformat()}|{self.posting_date.isoformat()}|{self.approval_date.isoformat() if self.approval_date else ''}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "transaction_id": str(self.transaction_id),
                "effective_date": self.effective_date.isoformat(),
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
                "version": self.version,
                "transaction_id": str(self.transaction_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> TransactionTimestamp:
        return self

    def update(self, updated_by: str, **kwargs) -> TransactionTimestamp:
        raise AttributeError("TransactionTimestamp is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> TransactionTimestamp:
        new_ts = self._copy()
        new_ts.deleted_at = datetime.now(UTC)
        new_ts.deleted_by = deleted_by
        new_ts.version = self.version + 1
        new_ts._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_ts

    def restore(self, restored_by: str) -> TransactionTimestamp:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_ts = self._copy()
        new_ts.deleted_at = None
        new_ts.deleted_by = None
        new_ts.version = self.version + 1
        new_ts._record_audit("RESTORE", restored_by, {})
        return new_ts

    def activate(self, activated_by: str) -> TransactionTimestamp:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> TransactionTimestamp:
        return self

    def lock(self, locked_by: str, reason: str) -> TransactionTimestamp:
        return self

    def unlock(self, unlocked_by: str) -> TransactionTimestamp:
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
            "transaction_id": str(self.transaction_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "effective_date": self.effective_date.isoformat(),
            "posting_date": self.posting_date.isoformat(),
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransactionTimestamp:
        return cls(
            transaction_id=UUID(data["transaction_id"]),
            effective_date=datetime.fromisoformat(data["effective_date"]),
            posting_date=datetime.fromisoformat(data["posting_date"]),
            approval_date=datetime.fromisoformat(data["approval_date"])
            if data.get("approval_date")
            else None,
            settlement_date=datetime.fromisoformat(data["settlement_date"])
            if data.get("settlement_date")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data["created_by"],
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> TransactionTimestamp:
        new_id = uuid4()
        return TransactionTimestamp(
            transaction_id=new_id,
            effective_date=self.effective_date,
            posting_date=self.posting_date,
            approval_date=self.approval_date,
            settlement_date=self.settlement_date,
            created_at=datetime.now(UTC),
            created_by=self.created_by,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transaction_id": str(self.transaction_id),
            "effective_date": self.effective_date.isoformat(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TransactionTimestamp:
        new_ts = self._copy()
        new_ts.version = self.version + 1
        new_ts._record_audit("TOUCH", touched_by, {})
        return new_ts

    def get_time_difference(
        self, context1: TransactionTimeContext, context2: TransactionTimeContext
    ) -> timedelta:
        dt1 = self._get_datetime_for_context(context1)
        dt2 = self._get_datetime_for_context(context2)
        if dt1 is None or dt2 is None:
            raise ValueError(f"Missing datetime for context {context1} or {context2}")
        return dt1 - dt2

    def _get_datetime_for_context(self, context: TransactionTimeContext) -> datetime | None:
        if context == TransactionTimeContext.EFFECTIVE:
            return self.effective_date
        elif context == TransactionTimeContext.POSTING:
            return self.posting_date
        elif context == TransactionTimeContext.APPROVAL:
            return self.approval_date
        elif context == TransactionTimeContext.SETTLEMENT:
            return self.settlement_date
        elif context == TransactionTimeContext.CREATION:
            return self.created_at
        return None

    def is_chronological(self) -> tuple[bool, list[str]]:
        violations = []
        if self.approval_date and self.effective_date > self.approval_date:
            violations.append(
                f"Effective {self.effective_date} after approval {self.approval_date}"
            )
        if self.approval_date and self.approval_date > self.posting_date:
            violations.append(f"Approval {self.approval_date} after posting {self.posting_date}")
        if self.effective_date > self.posting_date:
            violations.append(f"Effective {self.effective_date} after posting {self.posting_date}")
        if self.settlement_date and self.posting_date > self.settlement_date:
            violations.append(
                f"Posting {self.posting_date} after settlement {self.settlement_date}"
            )
        if self.created_at > self.effective_date:
            violations.append(f"Creation {self.created_at} after effective {self.effective_date}")
        return len(violations) == 0, violations

    def get_backdate_days(self, reference_date: datetime | None = None) -> int:
        ref = reference_date or datetime.now(UTC)
        if self.effective_date < ref:
            return (ref - self.effective_date).days
        return 0

    def _copy(self) -> TransactionTimestamp:
        return TransactionTimestamp(
            transaction_id=self.transaction_id,
            effective_date=self.effective_date,
            posting_date=self.posting_date,
            approval_date=self.approval_date,
            settlement_date=self.settlement_date,
            created_at=self.created_at,
            created_by=self.created_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class TimeIrreversibilityViolation:
    violation_id: UUID
    transaction_id: UUID
    attempted_effective_date: datetime
    current_period_start: datetime
    current_period_end: datetime
    last_transaction_date: datetime | None
    period_status: str
    backdate_days: int
    severity: TimeIrreversibilityViolationSeverity
    message: str
    user_id: str | None
    module: str
    detected_at: datetime
    is_blocked: bool
    override_granted: bool
    override_by: str | None
    override_reason: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.module, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.transaction_id}|{self.attempted_effective_date.isoformat()}|{self.backdate_days}|{self.severity.value}|{self.is_blocked}|{self.override_granted}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "violation_id": str(self.violation_id),
                "severity": self.severity.name,
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
                "version": self.version,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> TimeIrreversibilityViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> TimeIrreversibilityViolation:
        raise AttributeError("TimeIrreversibilityViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> TimeIrreversibilityViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> TimeIrreversibilityViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> TimeIrreversibilityViolation:
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> TimeIrreversibilityViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> TimeIrreversibilityViolation:
        return self

    def unlock(self, unlocked_by: str) -> TimeIrreversibilityViolation:
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
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "transaction_id": str(self.transaction_id),
            "attempted_effective_date": self.attempted_effective_date.isoformat(),
            "current_period_start": self.current_period_start.isoformat(),
            "current_period_end": self.current_period_end.isoformat(),
            "last_transaction_date": self.last_transaction_date.isoformat()
            if self.last_transaction_date
            else None,
            "period_status": self.period_status,
            "backdate_days": self.backdate_days,
            "severity": self.severity.name,
            "message": self.message,
            "user_id": self.user_id,
            "module": self.module,
            "detected_at": self.detected_at.isoformat(),
            "is_blocked": self.is_blocked,
            "override_granted": self.override_granted,
            "override_by": self.override_by,
            "override_reason": self.override_reason,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TimeIrreversibilityViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            attempted_effective_date=datetime.fromisoformat(data["attempted_effective_date"]),
            current_period_start=datetime.fromisoformat(data["current_period_start"]),
            current_period_end=datetime.fromisoformat(data["current_period_end"]),
            last_transaction_date=datetime.fromisoformat(data["last_transaction_date"])
            if data.get("last_transaction_date")
            else None,
            period_status=data["period_status"],
            backdate_days=data["backdate_days"],
            severity=TimeIrreversibilityViolationSeverity[data["severity"]],
            message=data["message"],
            user_id=data.get("user_id"),
            module=data["module"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            is_blocked=data["is_blocked"],
            override_granted=data["override_granted"],
            override_by=data.get("override_by"),
            override_reason=data.get("override_reason"),
            version=data.get("version", 1),
        )

    def clone(self) -> TimeIrreversibilityViolation:
        new_id = uuid4()
        return TimeIrreversibilityViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            attempted_effective_date=self.attempted_effective_date,
            current_period_start=self.current_period_start,
            current_period_end=self.current_period_end,
            last_transaction_date=self.last_transaction_date,
            period_status=self.period_status,
            backdate_days=self.backdate_days,
            severity=self.severity,
            message=self.message,
            user_id=self.user_id,
            module=self.module,
            detected_at=self.detected_at,
            is_blocked=self.is_blocked,
            override_granted=False,
            override_by=None,
            override_reason=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TimeIrreversibilityViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, reason: str) -> TimeIrreversibilityViolation:
        if self.override_granted:
            raise ValueError("Already overridden")
        new_violation = self._copy()
        new_violation.override_granted = True
        new_violation.override_by = by
        new_violation.override_reason = reason
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {"reason": reason})
        return new_violation

    def _copy(self) -> TimeIrreversibilityViolation:
        return TimeIrreversibilityViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            attempted_effective_date=self.attempted_effective_date,
            current_period_start=self.current_period_start,
            current_period_end=self.current_period_end,
            last_transaction_date=self.last_transaction_date,
            period_status=self.period_status,
            backdate_days=self.backdate_days,
            severity=self.severity,
            message=self.message,
            user_id=self.user_id,
            module=self.module,
            detected_at=self.detected_at,
            is_blocked=self.is_blocked,
            override_granted=self.override_granted,
            override_by=self.override_by,
            override_reason=self.override_reason,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class TimeIrreversibilityValidator:
    DEFAULT_MAX_BACKDATE_DAYS = 30
    TIMEZONE_TOLERANCE_DAYS = 1
    MAX_FUTURE_DAYS = 7

    @classmethod
    def validate_effective_date(
        cls,
        effective_date: datetime,
        current_period: TimeBoundary,
        last_transaction_date: datetime | None = None,
        max_backdate_days: int = DEFAULT_MAX_BACKDATE_DAYS,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
        module: str = "unknown",
        allow_future_posting: bool = True,
    ) -> tuple[bool, TimeIrreversibilityViolation | None]:
        eff = effective_date if effective_date.tzinfo else effective_date.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if current_period.is_closed:
            if eff < current_period.end_date:
                violation = cls._create_violation(
                    transaction_id or uuid4(),
                    eff,
                    current_period.start_date,
                    current_period.end_date,
                    last_transaction_date,
                    "CLOSED",
                    cls._calc_backdate(eff, current_period.start_date),
                    TimeIrreversibilityViolationSeverity.CATASTROPHIC,
                    f"Period closed. Cannot post with date {eff}",
                    user_id,
                    module,
                    True,
                    False,
                    None,
                    None,
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        if current_period.is_locked and not current_period.is_closed:
            violation = cls._create_violation(
                transaction_id or uuid4(),
                eff,
                current_period.start_date,
                current_period.end_date,
                last_transaction_date,
                "LOCKED",
                cls._calc_backdate(eff, current_period.start_date),
                TimeIrreversibilityViolationSeverity.CRITICAL,
                "Period locked. Adjustments require approval",
                user_id,
                module,
                True,
                False,
                None,
                None,
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation
        if eff > now and not allow_future_posting:
            future_days = (eff - now).days
            if future_days > cls.MAX_FUTURE_DAYS:
                violation = cls._create_violation(
                    transaction_id or uuid4(),
                    eff,
                    current_period.start_date,
                    current_period.end_date,
                    last_transaction_date,
                    "OPEN",
                    -future_days,
                    TimeIrreversibilityViolationSeverity.MEDIUM,
                    f"Future date {future_days} days ahead",
                    user_id,
                    module,
                    False,
                    False,
                    None,
                    None,
                )
                cls._log_violation(violation)
                return True, violation
        if eff < current_period.start_date:
            backdate = cls._calc_backdate(eff, current_period.start_date)
            if backdate > max_backdate_days:
                severity = TimeIrreversibilityViolationSeverity.CRITICAL
                is_blocked = True
            elif backdate > cls.TIMEZONE_TOLERANCE_DAYS:
                severity = TimeIrreversibilityViolationSeverity.HIGH
                is_blocked = True
            else:
                severity = TimeIrreversibilityViolationSeverity.LOW
                is_blocked = False
            if is_blocked:
                violation = cls._create_violation(
                    transaction_id or uuid4(),
                    eff,
                    current_period.start_date,
                    current_period.end_date,
                    last_transaction_date,
                    "OPEN",
                    backdate,
                    severity,
                    f"Backdate {backdate} days before period start",
                    user_id,
                    module,
                    True,
                    False,
                    None,
                    None,
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        if last_transaction_date and eff < last_transaction_date:
            days_back = (last_transaction_date - eff).days
            if days_back > max_backdate_days:
                severity = TimeIrreversibilityViolationSeverity.CRITICAL
                is_blocked = True
            elif days_back > cls.TIMEZONE_TOLERANCE_DAYS:
                severity = TimeIrreversibilityViolationSeverity.HIGH
                is_blocked = True
            else:
                severity = TimeIrreversibilityViolationSeverity.LOW
                is_blocked = False
            if is_blocked:
                violation = cls._create_violation(
                    transaction_id or uuid4(),
                    eff,
                    current_period.start_date,
                    current_period.end_date,
                    last_transaction_date,
                    "OPEN",
                    days_back,
                    severity,
                    f"Backdate {days_back} days before last tx",
                    user_id,
                    module,
                    True,
                    False,
                    None,
                    None,
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        return True, None

    @classmethod
    def validate_chronological_order(
        cls,
        timestamp: TransactionTimestamp,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
        module: str = "unknown",
        max_delay_days: int = 30,
    ) -> tuple[bool, list[TimeIrreversibilityViolation]]:
        is_valid, violations_list = timestamp.is_chronological()
        violations = []
        for msg in violations_list:
            severity = (
                TimeIrreversibilityViolationSeverity.HIGH
                if "effective" in msg and "posting" in msg
                else TimeIrreversibilityViolationSeverity.MEDIUM
            )
            is_blocked = severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value
            violation = cls._create_violation(
                transaction_id or timestamp.transaction_id,
                timestamp.effective_date,
                datetime.now(UTC),
                datetime.now(UTC),
                timestamp.posting_date,
                "N/A",
                0,
                severity,
                msg,
                user_id,
                module,
                is_blocked,
                False,
                None,
                None,
            )
            violations.append(violation)
            cls._log_violation(violation)
            cls._notify_constitution(violation)
        return is_valid, violations

    @classmethod
    def _calc_backdate(cls, effective: datetime, reference: datetime) -> int:
        eff = effective if effective.tzinfo else effective.replace(tzinfo=UTC)
        ref = reference if reference.tzinfo else reference.replace(tzinfo=UTC)
        if eff < ref:
            return (ref - eff).days
        return 0

    @classmethod
    def _create_violation(
        cls,
        transaction_id: UUID,
        attempted_date: datetime,
        period_start: datetime,
        period_end: datetime,
        last_date: datetime | None,
        period_status: str,
        backdate_days: int,
        severity: TimeIrreversibilityViolationSeverity,
        message: str,
        user_id: str | None,
        module: str,
        is_blocked: bool,
        override_granted: bool,
        override_by: str | None,
        override_reason: str | None,
    ) -> TimeIrreversibilityViolation:
        return TimeIrreversibilityViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            attempted_effective_date=attempted_date,
            current_period_start=period_start,
            current_period_end=period_end,
            last_transaction_date=last_date,
            period_status=period_status,
            backdate_days=backdate_days,
            severity=severity,
            message=message,
            user_id=user_id,
            module=module,
            detected_at=datetime.now(UTC),
            is_blocked=is_blocked,
            override_granted=override_granted,
            override_by=override_by,
            override_reason=override_reason,
        )

    @classmethod
    def _log_violation(cls, violation: TimeIrreversibilityViolation) -> None:
        log_msg = f"[{violation.severity.name}] Time irreversibility: {violation.message}"
        if violation.severity.value >= TimeIrreversibilityViolationSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: TimeIrreversibilityViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                TimeIrreversibilityViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                TimeIrreversibilityViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                TimeIrreversibilityViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                TimeIrreversibilityViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                TimeIrreversibilityViolationSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.TIME_IRREVERSIBILITY,
                offending_module=violation.module,
                message=violation.message,
                offending_user=violation.user_id,
                offending_command_id=violation.transaction_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class TimeIrreversibilityAxiom:
    _instance: TimeIrreversibilityAxiom | None = None
    _time_boundaries: dict[UUID, TimeBoundary] = {}
    _transaction_timestamps: dict[UUID, TransactionTimestamp] = {}
    _violation_history: list[TimeIrreversibilityViolation] = []
    _last_transaction_date_by_entity: dict[UUID, datetime] = {}
    _lock = threading.Lock()

    def __new__(cls) -> TimeIrreversibilityAxiom:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._time_boundaries = {}
        self._transaction_timestamps = {}
        self._violation_history = []
        self._last_transaction_date_by_entity = {}

    # ==================== REPOSITORY METHODS ====================
    def save_time_boundary(self, boundary: TimeBoundary) -> None:
        with self._lock:
            self._time_boundaries[boundary.period_id] = boundary

    def get_time_boundary(self, period_id: UUID) -> TimeBoundary | None:
        return self._time_boundaries.get(period_id)

    def get_all_time_boundaries(self) -> list[TimeBoundary]:
        return list(self._time_boundaries.values())

    def delete_time_boundary(self, period_id: UUID) -> bool:
        with self._lock:
            if period_id in self._time_boundaries:
                del self._time_boundaries[period_id]
                return True
            return False

    def save_transaction_timestamp(self, timestamp: TransactionTimestamp) -> None:
        with self._lock:
            self._transaction_timestamps[timestamp.transaction_id] = timestamp

    def get_transaction_timestamp(self, transaction_id: UUID) -> TransactionTimestamp | None:
        return self._transaction_timestamps.get(transaction_id)

    def delete_transaction_timestamp(self, transaction_id: UUID) -> bool:
        with self._lock:
            if transaction_id in self._transaction_timestamps:
                del self._transaction_timestamps[transaction_id]
                return True
            return False

    def save_violation(self, violation: TimeIrreversibilityViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: TimeIrreversibilityViolationSeverity | None = None,
        only_blocked: bool | None = None,
        transaction_id: UUID | None = None,
    ) -> list[TimeIrreversibilityViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if only_blocked is not None:
            result = [v for v in result if v.is_blocked == only_blocked]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        return result

    # ==================== BUSINESS METHODS ====================
    def register_time_boundary(self, boundary: TimeBoundary) -> None:
        self.save_time_boundary(boundary)

    def get_current_period(self, as_of: datetime | None = None) -> TimeBoundary | None:
        check = as_of or datetime.now(UTC)
        for b in self._time_boundaries.values():
            if b.contains(check):
                return b
        return None

    def record_transaction_timestamp(self, timestamp: TransactionTimestamp) -> None:
        self.save_transaction_timestamp(timestamp)
        key = timestamp.created_by
        if timestamp.effective_date > self._last_transaction_date_by_entity.get(
            key, datetime.min.replace(tzinfo=UTC)
        ):
            self._last_transaction_date_by_entity[key] = timestamp.effective_date

    def get_last_transaction_date(self, legal_entity_id: UUID | None = None) -> datetime | None:
        key = str(legal_entity_id) if legal_entity_id else "default"
        return self._last_transaction_date_by_entity.get(key)

    def enforce_effective_date(
        self,
        effective_date: datetime,
        period_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
        module: str = "unknown",
        max_backdate_days: int | None = None,
        allow_future_posting: bool = True,
        raise_on_violation: bool = True,
        allow_override: bool = False,
        override_by: str | None = None,
        override_reason: str | None = None,
    ) -> tuple[bool, TimeIrreversibilityViolation | None]:
        eff = effective_date if effective_date.tzinfo else effective_date.replace(tzinfo=UTC)
        period = self.get_time_boundary(period_id) if period_id else self.get_current_period(eff)
        if not period:
            violation = TimeIrreversibilityValidator._create_violation(
                transaction_id or uuid4(),
                eff,
                datetime.now(UTC),
                datetime.now(UTC),
                None,
                "NO_PERIOD",
                0,
                TimeIrreversibilityViolationSeverity.CRITICAL,
                f"No period for date {eff}",
                user_id,
                module,
                True,
                False,
                None,
                None,
            )
            self.save_violation(violation)
            if raise_on_violation:
                raise TimeIrreversibilityViolationError(violation.message, violation)
            return False, violation
        last_date = self.get_last_transaction_date(legal_entity_id)
        max_days = max_backdate_days or TimeIrreversibilityValidator.DEFAULT_MAX_BACKDATE_DAYS
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            eff, period, last_date, max_days, transaction_id, user_id, module, allow_future_posting
        )
        if violation:
            if allow_override and violation.is_blocked and override_by:
                violation = self._grant_override(violation, override_by, override_reason)
                is_valid = True
            else:
                self.save_violation(violation)
                if (
                    raise_on_violation
                    and violation.severity.value
                    >= TimeIrreversibilityViolationSeverity.CRITICAL.value
                ):
                    raise TimeIrreversibilityViolationError(violation.message, violation)
        if is_valid and transaction_id:
            key = str(legal_entity_id) if legal_entity_id else "default"
            if eff > self._last_transaction_date_by_entity.get(
                key, datetime.min.replace(tzinfo=UTC)
            ):
                self._last_transaction_date_by_entity[key] = eff
        return is_valid, violation

    def enforce_chronological_order(
        self,
        timestamp: TransactionTimestamp,
        transaction_id: UUID | None = None,
        user_id: str | None = None,
        module: str = "unknown",
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[TimeIrreversibilityViolation]]:
        is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
            timestamp, transaction_id, user_id, module
        )
        for v in violations:
            self.save_violation(v)
            if (
                raise_on_violation
                and v.severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value
            ):
                raise TimeIrreversibilityViolationError(v.message, v)
        if is_valid:
            self.record_transaction_timestamp(timestamp)
        return is_valid, violations

    def _grant_override(
        self, violation: TimeIrreversibilityViolation, override_by: str, override_reason: str | None
    ) -> TimeIrreversibilityViolation:
        new_violation = violation.resolve(override_by, override_reason)
        for i, v in enumerate(self._violation_history):
            if v.violation_id == violation.violation_id:
                self._violation_history[i] = new_violation
                break
        logger.warning(f"Override granted for violation {violation.violation_id} by {override_by}")
        return new_violation

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_boundaries = len(self._time_boundaries)
            total_timestamps = len(self._transaction_timestamps)
            total_violations = len(self._violation_history)
            blocked = len([v for v in self._violation_history if v.is_blocked])
            overridden = len([v for v in self._violation_history if v.override_granted])
            by_severity = {
                sev.name: len([v for v in self._violation_history if v.severity == sev])
                for sev in TimeIrreversibilityViolationSeverity
            }
            backdate_vals = [
                v.backdate_days for v in self._violation_history if v.backdate_days > 0
            ]
            avg_backdate = sum(backdate_vals) / len(backdate_vals) if backdate_vals else 0
            return {
                "total_time_boundaries": total_boundaries,
                "total_transaction_timestamps": total_timestamps,
                "total_violations": total_violations,
                "blocked_count": blocked,
                "overridden_count": overridden,
                "by_severity": by_severity,
                "avg_backdate_days": avg_backdate,
            }

    def reset(self) -> None:
        with self._lock:
            self._time_boundaries = {}
            self._transaction_timestamps = {}
            self._violation_history = []
            self._last_transaction_date_by_entity = {}


# === 6. SINGLETON ACCESSOR ===

_time_irreversibility_axiom_instance: TimeIrreversibilityAxiom | None = None


def get_time_irreversibility_axiom() -> TimeIrreversibilityAxiom:
    global _time_irreversibility_axiom_instance
    if _time_irreversibility_axiom_instance is None:
        _time_irreversibility_axiom_instance = TimeIrreversibilityAxiom()
    return _time_irreversibility_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_time_boundary(
    period_id: UUID,
    period_name: str,
    fiscal_year: int,
    period_number: int,
    start_date: datetime,
    end_date: datetime,
    is_closed: bool = False,
    is_locked: bool = False,
    closed_at: datetime | None = None,
    closed_by: str | None = None,
    locked_at: datetime | None = None,
    locked_by: str | None = None,
) -> TimeBoundary:
    return TimeBoundary(
        period_id=period_id,
        period_name=period_name,
        fiscal_year=fiscal_year,
        period_number=period_number,
        start_date=start_date,
        end_date=end_date,
        is_closed=is_closed,
        is_locked=is_locked,
        closed_at=closed_at,
        closed_by=closed_by,
        locked_at=locked_at,
        locked_by=locked_by,
    )


def create_transaction_timestamp(
    transaction_id: UUID,
    effective_date: datetime,
    posting_date: datetime | None = None,
    approval_date: datetime | None = None,
    settlement_date: datetime | None = None,
    created_by: str = "system",
) -> TransactionTimestamp:
    posting_date = posting_date or datetime.now(UTC)
    return TransactionTimestamp(
        transaction_id=transaction_id,
        effective_date=effective_date,
        posting_date=posting_date,
        approval_date=approval_date,
        settlement_date=settlement_date,
        created_at=datetime.now(UTC),
        created_by=created_by,
    )


__all__ = [
    "TimeBoundary",
    "TimeFlowDirection",
    "TimeIrreversibilityAxiom",
    "TimeIrreversibilityError",
    "TimeIrreversibilityValidator",
    "TimeIrreversibilityViolation",
    "TimeIrreversibilityViolationError",
    "TimeIrreversibilityViolationSeverity",
    "TransactionTimeContext",
    "TransactionTimestamp",
    "create_time_boundary",
    "create_transaction_timestamp",
    "get_time_irreversibility_axiom",
]
