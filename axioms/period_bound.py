#!/usr/bin/env python3
"""
Module: period_bound.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: setiap transaksi terikat pada periode akuntansi tertentu.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
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


class PeriodStatus(Enum):
    FUTURE = auto()
    OPEN = auto()
    LOCKED = auto()
    CLOSED = auto()
    ARCHIVED = auto()


class PeriodType(Enum):
    MONTHLY = auto()
    QUARTERLY = auto()
    YEARLY = auto()
    CUSTOM = auto()


class PeriodBoundViolationSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. EXCEPTIONS ===


class PeriodBoundError(Exception):
    pass


class PeriodNotFoundError(PeriodBoundError):
    pass


class PeriodClosedError(PeriodBoundError):
    pass


class PeriodBoundViolationError(Exception):
    def __init__(
        self,
        message: str,
        transaction_id: UUID,
        period_id: UUID,
        period_status: str,
        severity: PeriodBoundViolationSeverity,
    ):
        self.transaction_id = transaction_id
        self.period_id = period_id
        self.period_status = period_status
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | TX: {transaction_id}, Period: {period_id}, Status: {period_status}"
        )


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class AccountingPeriod:
    period_id: UUID
    fiscal_year: int
    period_number: int
    period_type: PeriodType
    start_date: datetime
    end_date: datetime
    status: PeriodStatus
    closed_at: datetime | None = None
    closed_by: str | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    previous_period_id: UUID | None = None
    next_period_id: UUID | None = None
    is_budget_period: bool = False
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
            raise ValueError(f"Start {self.start_date} >= end {self.end_date}")
        if self.period_number < 1 or self.period_number > 13:
            raise ValueError(f"Invalid period number: {self.period_number}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.period_id}|{self.fiscal_year}|{self.period_number}|{self.period_type.value}|{self.start_date.isoformat()}|{self.end_date.isoformat()}|{self.status.value}|{self.is_budget_period}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "period_id": str(self.period_id),
                "status": self.status.name,
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
    def create(self, created_by: str) -> AccountingPeriod:
        return self

    def update(self, updated_by: str, **kwargs) -> AccountingPeriod:
        new_period = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_period, key) and key not in (
                "period_id",
                "fiscal_year",
                "period_number",
                "version",
            ):
                setattr(new_period, key, value)
        new_period.version = self.version + 1
        new_period._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_period

    def delete(self, deleted_by: str, reason: str | None = None) -> AccountingPeriod:
        new_period = self._copy()
        new_period.deleted_at = datetime.now(UTC)
        new_period.deleted_by = deleted_by
        new_period.version = self.version + 1
        new_period._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_period

    def restore(self, restored_by: str) -> AccountingPeriod:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_period = self._copy()
        new_period.deleted_at = None
        new_period.deleted_by = None
        new_period.version = self.version + 1
        new_period._record_audit("RESTORE", restored_by, {})
        return new_period

    def activate(self, activated_by: str) -> AccountingPeriod:
        if self.status == PeriodStatus.OPEN:
            return self
        if self.status == PeriodStatus.FUTURE:
            new_period = self._copy()
            new_period.status = PeriodStatus.OPEN
            new_period.version = self.version + 1
            new_period._record_audit("ACTIVATE", activated_by, {})
            return new_period
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AccountingPeriod:
        if self.status == PeriodStatus.FUTURE:
            return self
        new_period = self._copy()
        new_period.status = PeriodStatus.FUTURE
        new_period.version = self.version + 1
        new_period._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_period

    def lock(self, locked_by: str, reason: str) -> AccountingPeriod:
        if self.status == PeriodStatus.LOCKED:
            return self
        if self.status in (PeriodStatus.CLOSED, PeriodStatus.ARCHIVED):
            raise ValueError(f"Cannot lock period with status {self.status.name}")
        new_period = self._copy()
        new_period.status = PeriodStatus.LOCKED
        new_period.locked_at = datetime.now(UTC)
        new_period.locked_by = locked_by
        new_period.version = self.version + 1
        new_period._record_audit("LOCK", locked_by, {"reason": reason})
        return new_period

    def unlock(self, unlocked_by: str) -> AccountingPeriod:
        if self.status != PeriodStatus.LOCKED:
            raise ValueError(f"Cannot unlock period with status {self.status.name}")
        new_period = self._copy()
        new_period.status = PeriodStatus.OPEN
        new_period.locked_at = None
        new_period.locked_by = None
        new_period.version = self.version + 1
        new_period._record_audit("UNLOCK", unlocked_by, {})
        return new_period

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
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
            "period_type": self.period_type.name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status.name,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": self.locked_by,
            "previous_period_id": str(self.previous_period_id) if self.previous_period_id else None,
            "next_period_id": str(self.next_period_id) if self.next_period_id else None,
            "is_budget_period": self.is_budget_period,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountingPeriod:
        return cls(
            period_id=UUID(data["period_id"]),
            fiscal_year=data["fiscal_year"],
            period_number=data["period_number"],
            period_type=PeriodType[data["period_type"]],
            start_date=datetime.fromisoformat(data["start_date"]),
            end_date=datetime.fromisoformat(data["end_date"]),
            status=PeriodStatus[data["status"]],
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            closed_by=data.get("closed_by"),
            locked_at=datetime.fromisoformat(data["locked_at"]) if data.get("locked_at") else None,
            locked_by=data.get("locked_by"),
            previous_period_id=UUID(data["previous_period_id"])
            if data.get("previous_period_id")
            else None,
            next_period_id=UUID(data["next_period_id"]) if data.get("next_period_id") else None,
            is_budget_period=data.get("is_budget_period", False),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> AccountingPeriod:
        new_id = uuid4()
        return AccountingPeriod(
            period_id=new_id,
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            period_type=self.period_type,
            start_date=self.start_date,
            end_date=self.end_date,
            status=PeriodStatus.FUTURE,
            is_budget_period=self.is_budget_period,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "period_id": str(self.period_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccountingPeriod:
        new_period = self._copy()
        new_period.version = self.version + 1
        new_period._record_audit("TOUCH", touched_by, {})
        return new_period

    def contains(self, date: datetime) -> bool:
        dt = date if date.tzinfo else date.replace(tzinfo=UTC)
        start = self.start_date if self.start_date.tzinfo else self.start_date.replace(tzinfo=UTC)
        end = self.end_date if self.end_date.tzinfo else self.end_date.replace(tzinfo=UTC)
        return start <= dt <= end

    def is_open_for_posting(self, allow_budget: bool = False) -> bool:
        if self.is_budget_period and allow_budget:
            return self.status in (PeriodStatus.OPEN, PeriodStatus.FUTURE)
        return self.status == PeriodStatus.OPEN

    def can_adjust(self, require_authorization: bool = True) -> bool:
        return self.status in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

    def can_read(self) -> bool:
        return self.status != PeriodStatus.FUTURE

    def close(self, closed_by: str) -> AccountingPeriod:
        if self.status == PeriodStatus.CLOSED:
            raise PeriodClosedError(f"Period {self.period_id} already closed")
        new_period = self._copy()
        new_period.status = PeriodStatus.CLOSED
        new_period.closed_at = datetime.now(UTC)
        new_period.closed_by = closed_by
        new_period.version = self.version + 1
        new_period._record_audit("CLOSE", closed_by, {})
        return new_period

    def reopen(self, reopened_by: str, reason: str) -> AccountingPeriod:
        if self.status == PeriodStatus.OPEN:
            raise ValueError(f"Period {self.period_id} already open")
        new_period = self._copy()
        new_period.status = PeriodStatus.OPEN
        new_period.closed_at = None
        new_period.closed_by = None
        new_period.version = self.version + 1
        new_period._record_audit("REOPEN", reopened_by, {"reason": reason})
        return new_period

    def archive(self, archived_by: str) -> AccountingPeriod:
        if self.status == PeriodStatus.ARCHIVED:
            return self
        new_period = self._copy()
        new_period.status = PeriodStatus.ARCHIVED
        new_period.version = self.version + 1
        new_period._record_audit("ARCHIVE", archived_by, {})
        return new_period

    def _copy(self) -> AccountingPeriod:
        return AccountingPeriod(
            period_id=self.period_id,
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            period_type=self.period_type,
            start_date=self.start_date,
            end_date=self.end_date,
            status=self.status,
            closed_at=self.closed_at,
            closed_by=self.closed_by,
            locked_at=self.locked_at,
            locked_by=self.locked_by,
            previous_period_id=self.previous_period_id,
            next_period_id=self.next_period_id,
            is_budget_period=self.is_budget_period,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class FiscalYearDefinition:
    fiscal_year_id: UUID
    legal_entity_id: UUID
    year_name: str
    start_month: int
    start_day: int = 1
    periods: list[AccountingPeriod] = field(default_factory=list)
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
        if self.start_month < 1 or self.start_month > 12:
            raise ValueError(f"Invalid start month: {self.start_month}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        periods_hash = hashlib.sha3_256(
            "".join(str(p.period_id) for p in self.periods).encode()
        ).hexdigest()
        content = f"{self.fiscal_year_id}|{self.legal_entity_id}|{self.year_name}|{self.start_month}|{self.start_day}|{periods_hash}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "fiscal_year_id": str(self.fiscal_year_id),
                "year_name": self.year_name,
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
                "fiscal_year_id": str(self.fiscal_year_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> FiscalYearDefinition:
        return self

    def update(self, updated_by: str, **kwargs) -> FiscalYearDefinition:
        new_fy = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_fy, key) and key not in ("fiscal_year_id", "legal_entity_id", "version"):
                setattr(new_fy, key, value)
        new_fy.version = self.version + 1
        new_fy._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_fy

    def delete(self, deleted_by: str, reason: str | None = None) -> FiscalYearDefinition:
        new_fy = self._copy()
        new_fy.deleted_at = datetime.now(UTC)
        new_fy.deleted_by = deleted_by
        new_fy.version = self.version + 1
        new_fy._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_fy

    def restore(self, restored_by: str) -> FiscalYearDefinition:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_fy = self._copy()
        new_fy.deleted_at = None
        new_fy.deleted_by = None
        new_fy.version = self.version + 1
        new_fy._record_audit("RESTORE", restored_by, {})
        return new_fy

    def activate(self, activated_by: str) -> FiscalYearDefinition:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> FiscalYearDefinition:
        return self

    def lock(self, locked_by: str, reason: str) -> FiscalYearDefinition:
        return self

    def unlock(self, unlocked_by: str) -> FiscalYearDefinition:
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
            "fiscal_year_id": str(self.fiscal_year_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "fiscal_year_id": str(self.fiscal_year_id),
            "legal_entity_id": str(self.legal_entity_id),
            "year_name": self.year_name,
            "start_month": self.start_month,
            "start_day": self.start_day,
            "periods_count": len(self.periods),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FiscalYearDefinition:
        return cls(
            fiscal_year_id=UUID(data["fiscal_year_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            year_name=data["year_name"],
            start_month=data["start_month"],
            start_day=data.get("start_day", 1),
            periods=[],
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> FiscalYearDefinition:
        new_id = uuid4()
        return FiscalYearDefinition(
            fiscal_year_id=new_id,
            legal_entity_id=self.legal_entity_id,
            year_name=f"{self.year_name}_COPY",
            start_month=self.start_month,
            start_day=self.start_day,
            periods=[],
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "fiscal_year_id": str(self.fiscal_year_id),
            "year_name": self.year_name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FiscalYearDefinition:
        new_fy = self._copy()
        new_fy.version = self.version + 1
        new_fy._record_audit("TOUCH", touched_by, {})
        return new_fy

    def get_period_for_date(self, date: datetime) -> AccountingPeriod | None:
        for period in self.periods:
            if period.contains(date):
                return period
        return None

    def get_open_periods(self) -> list[AccountingPeriod]:
        return [p for p in self.periods if p.is_open_for_posting()]

    def get_period_by_number(self, period_number: int) -> AccountingPeriod | None:
        for period in self.periods:
            if period.period_number == period_number:
                return period
        return None

    def _copy(self) -> FiscalYearDefinition:
        return FiscalYearDefinition(
            fiscal_year_id=self.fiscal_year_id,
            legal_entity_id=self.legal_entity_id,
            year_name=self.year_name,
            start_month=self.start_month,
            start_day=self.start_day,
            periods=self.periods.copy(),
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class PeriodBoundViolation:
    violation_id: UUID
    transaction_id: UUID
    transaction_date: datetime
    target_period_id: UUID
    period_status: str
    attempted_operation: str
    severity: PeriodBoundViolationSeverity
    message: str
    was_blocked: bool
    user_id: UUID | None
    module: str
    detected_at: datetime
    override_granted: bool
    override_by: str | None
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
        content = f"{self.violation_id}|{self.transaction_id}|{self.target_period_id}|{self.period_status}|{self.was_blocked}|{self.severity.value}"
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
    def create(self, created_by: str) -> PeriodBoundViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> PeriodBoundViolation:
        raise AttributeError("PeriodBoundViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> PeriodBoundViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> PeriodBoundViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> PeriodBoundViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> PeriodBoundViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> PeriodBoundViolation:
        return self

    def unlock(self, unlocked_by: str) -> PeriodBoundViolation:
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
            "transaction_date": self.transaction_date.isoformat(),
            "target_period_id": str(self.target_period_id),
            "period_status": self.period_status,
            "attempted_operation": self.attempted_operation,
            "severity": self.severity.name,
            "message": self.message,
            "was_blocked": self.was_blocked,
            "user_id": str(self.user_id) if self.user_id else None,
            "module": self.module,
            "detected_at": self.detected_at.isoformat(),
            "override_granted": self.override_granted,
            "override_by": self.override_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodBoundViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            target_period_id=UUID(data["target_period_id"]),
            period_status=data["period_status"],
            attempted_operation=data["attempted_operation"],
            severity=PeriodBoundViolationSeverity[data["severity"]],
            message=data["message"],
            was_blocked=data["was_blocked"],
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            module=data["module"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            override_granted=data["override_granted"],
            override_by=data.get("override_by"),
            version=data.get("version", 1),
        )

    def clone(self) -> PeriodBoundViolation:
        new_id = uuid4()
        return PeriodBoundViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            transaction_date=self.transaction_date,
            target_period_id=self.target_period_id,
            period_status=self.period_status,
            attempted_operation=self.attempted_operation,
            severity=self.severity,
            message=self.message,
            was_blocked=self.was_blocked,
            user_id=self.user_id,
            module=self.module,
            detected_at=self.detected_at,
            override_granted=False,
            override_by=None,
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

    def touch(self, touched_by: str) -> PeriodBoundViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def grant_override(self, by: str) -> PeriodBoundViolation:
        if self.override_granted:
            return self
        new_violation = self._copy()
        new_violation.override_granted = True
        new_violation.override_by = by
        new_violation.version = self.version + 1
        new_violation._record_audit("OVERRIDE", by, {})
        return new_violation

    def _copy(self) -> PeriodBoundViolation:
        return PeriodBoundViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            transaction_date=self.transaction_date,
            target_period_id=self.target_period_id,
            period_status=self.period_status,
            attempted_operation=self.attempted_operation,
            severity=self.severity,
            message=self.message,
            was_blocked=self.was_blocked,
            user_id=self.user_id,
            module=self.module,
            detected_at=self.detected_at,
            override_granted=self.override_granted,
            override_by=self.override_by,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class PeriodBoundValidator:
    DEFAULT_TOLERANCE_DAYS = 7

    @classmethod
    def validate_transaction_period(
        cls,
        transaction_date: datetime,
        target_period: AccountingPeriod,
        transaction_id: UUID,
        user_id: UUID | None = None,
        module: str = "unknown",
        allow_budget_posting: bool = False,
        allow_future_posting: bool = False,
        max_future_days: int = 7,
        auto_correct: bool = False,
    ) -> tuple[bool, PeriodBoundViolation | None, str | None]:
        tx_date = (
            transaction_date if transaction_date.tzinfo else transaction_date.replace(tzinfo=UTC)
        )
        now = datetime.now(UTC)
        if not target_period.contains(tx_date):
            violation = cls._create_violation(
                transaction_id,
                tx_date,
                target_period.period_id,
                target_period.status.name,
                "POST",
                PeriodBoundViolationSeverity.HIGH,
                f"Date {tx_date} outside period {target_period.start_date} to {target_period.end_date}",
                True,
                user_id,
                module,
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation, "Correct transaction date"
        if not target_period.is_open_for_posting(allow_budget=allow_budget_posting):
            severity = cls._determine_severity_by_status(
                target_period.status, target_period.is_budget_period
            )
            is_blocked = severity.value >= PeriodBoundViolationSeverity.HIGH.value
            violation = cls._create_violation(
                transaction_id,
                tx_date,
                target_period.period_id,
                target_period.status.name,
                "POST",
                severity,
                f"Cannot post to period with status {target_period.status.name}",
                is_blocked,
                user_id,
                module,
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return not is_blocked, violation, "Open period first"
        if tx_date > now:
            days_future = (tx_date - now).days
            if not allow_future_posting and days_future > max_future_days:
                violation = cls._create_violation(
                    transaction_id,
                    tx_date,
                    target_period.period_id,
                    target_period.status.name,
                    "POST",
                    PeriodBoundViolationSeverity.MEDIUM,
                    f"Future date {tx_date} is {days_future} days ahead",
                    True,
                    user_id,
                    module,
                )
                cls._log_violation(violation)
                return False, violation, f"Use future posting (max {max_future_days} days)"
        return True, None, None

    @classmethod
    def _determine_severity_by_status(
        cls, status: PeriodStatus, is_budget: bool = False
    ) -> PeriodBoundViolationSeverity:
        if status == PeriodStatus.CLOSED:
            return PeriodBoundViolationSeverity.CRITICAL
        elif status == PeriodStatus.LOCKED:
            return PeriodBoundViolationSeverity.HIGH
        elif status == PeriodStatus.FUTURE:
            return (
                PeriodBoundViolationSeverity.MEDIUM
                if not is_budget
                else PeriodBoundViolationSeverity.LOW
            )
        return PeriodBoundViolationSeverity.LOW

    @classmethod
    def _create_violation(
        cls,
        transaction_id: UUID,
        transaction_date: datetime,
        target_period_id: UUID,
        period_status: str,
        attempted_op: str,
        severity: PeriodBoundViolationSeverity,
        message: str,
        was_blocked: bool,
        user_id: UUID | None,
        module: str,
    ) -> PeriodBoundViolation:
        return PeriodBoundViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            transaction_date=transaction_date,
            target_period_id=target_period_id,
            period_status=period_status,
            attempted_operation=attempted_op,
            severity=severity,
            message=message,
            was_blocked=was_blocked,
            user_id=user_id,
            module=module,
            detected_at=datetime.now(UTC),
            override_granted=False,
            override_by=None,
        )

    @classmethod
    def _log_violation(cls, violation: PeriodBoundViolation) -> None:
        log_msg = f"[{violation.severity.name}] Period bound violation: {violation.message}"
        if violation.severity.value >= PeriodBoundViolationSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= PeriodBoundViolationSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: PeriodBoundViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                PeriodBoundViolationSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                PeriodBoundViolationSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                PeriodBoundViolationSeverity.HIGH: ConstitutionalSeverity.HIGH,
                PeriodBoundViolationSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                PeriodBoundViolationSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.PERIOD_BOUND,
                offending_module=violation.module,
                message=violation.message,
                offending_user=str(violation.user_id) if violation.user_id else None,
                offending_command_id=violation.transaction_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class PeriodBoundAxiom:
    _instance: PeriodBoundAxiom | None = None
    _fiscal_years: dict[UUID, FiscalYearDefinition] = {}
    _periods: dict[UUID, AccountingPeriod] = {}
    _violation_history: list[PeriodBoundViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> PeriodBoundAxiom:
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
        self._fiscal_years = {}
        self._periods = {}
        self._violation_history = []

    # ==================== REPOSITORY METHODS ====================
    def save_fiscal_year(self, fiscal_year: FiscalYearDefinition) -> None:
        with self._lock:
            self._fiscal_years[fiscal_year.fiscal_year_id] = fiscal_year
            for period in fiscal_year.periods:
                self._periods[period.period_id] = period

    def get_fiscal_year(self, fiscal_year_id: UUID) -> FiscalYearDefinition | None:
        return self._fiscal_years.get(fiscal_year_id)

    def get_all_fiscal_years(
        self, legal_entity_id: UUID | None = None
    ) -> list[FiscalYearDefinition]:
        result = list(self._fiscal_years.values())
        if legal_entity_id:
            result = [fy for fy in result if fy.legal_entity_id == legal_entity_id]
        return result

    def delete_fiscal_year(self, fiscal_year_id: UUID) -> bool:
        with self._lock:
            if fiscal_year_id in self._fiscal_years:
                fy = self._fiscal_years[fiscal_year_id]
                for p in fy.periods:
                    if p.period_id in self._periods:
                        del self._periods[p.period_id]
                del self._fiscal_years[fiscal_year_id]
                return True
            return False

    def save_period(self, period: AccountingPeriod) -> None:
        with self._lock:
            self._periods[period.period_id] = period

    def get_period(self, period_id: UUID) -> AccountingPeriod | None:
        return self._periods.get(period_id)

    def get_all_periods(self, legal_entity_id: UUID | None = None) -> list[AccountingPeriod]:
        result = list(self._periods.values())
        if legal_entity_id:
            result = [
                p
                for p in result
                if any(
                    fy.legal_entity_id == legal_entity_id
                    for fy in self._fiscal_years.values()
                    if p in fy.periods
                )
            ]
        return result

    def delete_period(self, period_id: UUID) -> bool:
        with self._lock:
            if period_id in self._periods:
                del self._periods[period_id]
                return True
            return False

    def save_violation(self, violation: PeriodBoundViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        min_severity: PeriodBoundViolationSeverity | None = None,
        period_id: UUID | None = None,
        transaction_id: UUID | None = None,
    ) -> list[PeriodBoundViolation]:
        result = self._violation_history[-limit:]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if period_id:
            result = [v for v in result if v.target_period_id == period_id]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str
    ) -> PeriodBoundViolation | None:
        return None

    # ==================== BUSINESS METHODS ====================
    def define_fiscal_year(
        self,
        legal_entity_id: UUID,
        year_name: str,
        start_month: int,
        start_day: int = 1,
        periods: list[AccountingPeriod] | None = None,
    ) -> FiscalYearDefinition:
        fiscal_year = FiscalYearDefinition(
            fiscal_year_id=uuid4(),
            legal_entity_id=legal_entity_id,
            year_name=year_name,
            start_month=start_month,
            start_day=start_day,
            periods=periods or [],
        )
        self.save_fiscal_year(fiscal_year)
        return fiscal_year

    def add_period(self, fiscal_year_id: UUID, period: AccountingPeriod) -> None:
        with self._lock:
            fy = self._fiscal_years.get(fiscal_year_id)
            if not fy:
                raise PeriodBoundError(f"Fiscal year {fiscal_year_id} not found")
            new_periods = fy.periods + [period]
            new_fy = fy.update("system", periods=new_periods)
            self._fiscal_years[fiscal_year_id] = new_fy
            self._periods[period.period_id] = period

    def get_period_for_date(self, legal_entity_id: UUID, date: datetime) -> AccountingPeriod | None:
        dt = date if date.tzinfo else date.replace(tzinfo=UTC)
        for fy in self._fiscal_years.values():
            if fy.legal_entity_id == legal_entity_id:
                period = fy.get_period_for_date(dt)
                if period:
                    return period
        return None

    def get_current_period(self, legal_entity_id: UUID) -> AccountingPeriod | None:
        return self.get_period_for_date(legal_entity_id, datetime.now(UTC))

    def close_period(self, period_id: UUID, closed_by: str) -> AccountingPeriod:
        with self._lock:
            period = self._periods.get(period_id)
            if not period:
                raise PeriodBoundError(f"Period {period_id} not found")
            if period.status == PeriodStatus.CLOSED:
                raise PeriodClosedError(f"Period {period_id} already closed")
            closed = period.close(closed_by)
            self._periods[period_id] = closed
            return closed

    def lock_period(self, period_id: UUID, locked_by: str) -> AccountingPeriod:
        with self._lock:
            period = self._periods.get(period_id)
            if not period:
                raise PeriodBoundError(f"Period {period_id} not found")
            locked = period.lock(locked_by, "Manual lock")
            self._periods[period_id] = locked
            return locked

    def reopen_period(self, period_id: UUID, reopened_by: str, reason: str) -> AccountingPeriod:
        with self._lock:
            period = self._periods.get(period_id)
            if not period:
                raise PeriodBoundError(f"Period {period_id} not found")
            reopened = period.reopen(reopened_by, reason)
            self._periods[period_id] = reopened
            return reopened

    def archive_period(self, period_id: UUID, archived_by: str) -> AccountingPeriod:
        with self._lock:
            period = self._periods.get(period_id)
            if not period:
                raise PeriodBoundError(f"Period {period_id} not found")
            archived = period.archive(archived_by)
            self._periods[period_id] = archived
            return archived

    def get_open_periods(self, legal_entity_id: UUID) -> list[AccountingPeriod]:
        periods = self.get_all_periods(legal_entity_id)
        return [p for p in periods if p.is_open_for_posting()]

    def get_period_sequence(self, period_id: UUID) -> list[AccountingPeriod]:
        result = []
        period = self.get_period(period_id)
        if not period:
            return result
        current = period
        while current.previous_period_id:
            prev = self.get_period(current.previous_period_id)
            if not prev:
                break
            current = prev
        while current:
            result.append(current)
            if current.next_period_id:
                current = self.get_period(current.next_period_id)
            else:
                break
        return result

    def enforce_transaction_period(
        self,
        transaction_date: datetime,
        legal_entity_id: UUID,
        transaction_id: UUID,
        user_id: UUID | None = None,
        module: str = "unknown",
        allow_budget_posting: bool = False,
        allow_future_posting: bool = False,
        max_future_days: int = 7,
        auto_correct: bool = True,
        raise_on_violation: bool = True,
    ) -> tuple[bool, PeriodBoundViolation | None, AccountingPeriod | None]:
        target_period = self.get_period_for_date(legal_entity_id, transaction_date)
        if not target_period:
            violation = PeriodBoundValidator._create_violation(
                transaction_id,
                transaction_date,
                UUID(int=0),
                "NO_PERIOD",
                "POST",
                PeriodBoundViolationSeverity.CATASTROPHIC,
                f"No period for date {transaction_date}",
                True,
                user_id,
                module,
            )
            self.save_violation(violation)
            if raise_on_violation:
                raise PeriodBoundViolationError(
                    violation.message,
                    transaction_id,
                    violation.target_period_id,
                    violation.period_status,
                    violation.severity,
                )
            return False, violation, None
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date,
            target_period,
            transaction_id,
            user_id,
            module,
            allow_budget_posting,
            allow_future_posting,
            max_future_days,
            auto_correct,
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= PeriodBoundViolationSeverity.HIGH.value
            ):
                raise PeriodBoundViolationError(
                    violation.message,
                    transaction_id,
                    violation.target_period_id,
                    violation.period_status,
                    violation.severity,
                )
        return is_valid, violation, target_period

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_fy = len(self._fiscal_years)
            total_periods = len(self._periods)
            total_violations = len(self._violation_history)
            open_periods = len([p for p in self._periods.values() if p.is_open_for_posting()])
            closed_periods = len(
                [p for p in self._periods.values() if p.status == PeriodStatus.CLOSED]
            )
            locked_periods = len(
                [p for p in self._periods.values() if p.status == PeriodStatus.LOCKED]
            )
            return {
                "total_fiscal_years": total_fy,
                "total_periods": total_periods,
                "total_violations": total_violations,
                "periods_by_status": {
                    "OPEN": open_periods,
                    "CLOSED": closed_periods,
                    "LOCKED": locked_periods,
                },
                "unresolved_violations": 0,
            }

    def reset(self) -> None:
        with self._lock:
            self._fiscal_years = {}
            self._periods = {}
            self._violation_history = []


# === 6. SINGLETON ACCESSOR ===

_period_bound_axiom_instance: PeriodBoundAxiom | None = None


def get_period_bound_axiom() -> PeriodBoundAxiom:
    global _period_bound_axiom_instance
    if _period_bound_axiom_instance is None:
        _period_bound_axiom_instance = PeriodBoundAxiom()
    return _period_bound_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_accounting_period(
    fiscal_year: int,
    period_number: int,
    period_type: PeriodType,
    start_date: datetime,
    end_date: datetime,
    status: PeriodStatus = PeriodStatus.FUTURE,
    is_budget_period: bool = False,
) -> AccountingPeriod:
    return AccountingPeriod(
        period_id=uuid4(),
        fiscal_year=fiscal_year,
        period_number=period_number,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        status=status,
        is_budget_period=is_budget_period,
    )


def generate_monthly_periods(
    fiscal_year: int, start_month: int = 1, year_start: int | None = None
) -> list[AccountingPeriod]:
    periods = []
    year = year_start if year_start else fiscal_year
    month = start_month
    for i in range(1, 13):
        start_date = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end_date = datetime(year + 1, 1, 1, tzinfo=UTC) - timedelta(seconds=1)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(seconds=1)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        period = create_accounting_period(
            fiscal_year,
            i,
            PeriodType.MONTHLY,
            start_date,
            end_date,
            PeriodStatus.FUTURE if i > 1 else PeriodStatus.OPEN,
        )
        periods.append(period)
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def generate_quarterly_periods(fiscal_year: int, start_month: int = 1) -> list[AccountingPeriod]:
    periods = []
    quarters = [(1, 3), (4, 6), (7, 9), (10, 12)]
    start_year = fiscal_year
    for i, (start_q, end_q) in enumerate(quarters, 1):
        start_date = datetime(start_year, start_q, 1, tzinfo=UTC)
        if end_q == 12:
            end_date = datetime(start_year + 1, 1, 1, tzinfo=UTC) - timedelta(seconds=1)
        else:
            end_date = datetime(start_year, end_q + 1, 1, tzinfo=UTC) - timedelta(seconds=1)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        period = create_accounting_period(
            fiscal_year,
            i,
            PeriodType.QUARTERLY,
            start_date,
            end_date,
            PeriodStatus.FUTURE if i > 1 else PeriodStatus.OPEN,
        )
        periods.append(period)
    return periods


__all__ = [
    "AccountingPeriod",
    "FiscalYearDefinition",
    "PeriodBoundAxiom",
    "PeriodBoundError",
    "PeriodBoundValidator",
    "PeriodBoundViolation",
    "PeriodBoundViolationError",
    "PeriodBoundViolationSeverity",
    "PeriodClosedError",
    "PeriodNotFoundError",
    "PeriodStatus",
    "PeriodType",
    "create_accounting_period",
    "generate_monthly_periods",
    "generate_quarterly_periods",
    "get_period_bound_axiom",
]
