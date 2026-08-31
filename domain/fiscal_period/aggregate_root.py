#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Fiscal Period
Responsibility: Aggregate root untuk fiscal/accounting periods dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class PeriodStatus(Enum):
    """Status of an accounting period with full lifecycle: DRAFT → OPEN → LOCKED → CLOSED."""

    DRAFT = "draft"
    OPEN = "open"
    LOCKED = "locked"
    CLOSED = "closed"

    def can_post(self) -> bool:
        return self == PeriodStatus.OPEN

    def can_adjust(self) -> bool:
        return self in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

    def can_close(self) -> bool:
        return self != PeriodStatus.CLOSED

    def can_open(self) -> bool:
        return self in (PeriodStatus.DRAFT, PeriodStatus.CLOSED)

    def display_name(self) -> str:
        names = {
            PeriodStatus.DRAFT: "Draft",
            PeriodStatus.OPEN: "Terbuka",
            PeriodStatus.LOCKED: "Terkunci",
            PeriodStatus.CLOSED: "Ditutup",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> PeriodStatus | None:
        value_lower = value.lower()
        for s in cls:
            if s.value == value_lower:
                return s
        return None


class PeriodType(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"

    def display_name(self) -> str:
        names = {
            PeriodType.MONTHLY: "Bulanan",
            PeriodType.QUARTERLY: "Triwulan",
            PeriodType.ANNUAL: "Tahunan",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> PeriodType | None:
        value_lower = value.lower()
        for t in cls:
            if t.value == value_lower:
                return t
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class FiscalPeriodError(ValueError):
    pass


class InvalidPeriodNumberError(FiscalPeriodError):
    pass


class InvalidDateRangeError(FiscalPeriodError):
    pass


class InvalidStatusTransitionError(FiscalPeriodError):
    pass


class PeriodNotFoundError(FiscalPeriodError):
    pass


class PeriodAlreadyExistsError(FiscalPeriodError):
    pass


# ============================================================================
# Value Object: AccountingPeriod
# ============================================================================


@dataclass(frozen=True)
class AccountingPeriod:
    year: int
    month: int
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.month < 1 or self.month > 12:
            raise ValueError(f"Month must be 1-12, got {self.month}")
        if self.start_date >= self.end_date:
            raise ValueError(
                f"Start date {self.start_date} must be before end date {self.end_date}"
            )

    @classmethod
    def from_month(cls, year: int, month: int) -> AccountingPeriod:
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        return cls(year, month, start, end)

    @property
    def period_name(self) -> str:
        month_names = [
            "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des",
        ]
        return f"{month_names[self.month - 1]} {self.year}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "period_name": self.period_name,
        }


# ============================================================================
# Helper Functions
# ============================================================================


def _normalize_datetime(dt: datetime | None) -> datetime:
    """Ensure datetime is UTC and not None."""
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _parse_period_string(period_str: str) -> tuple[int, int]:
    parts = period_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid period format: {period_str}, expected YYYY-MM")
    year = int(parts[0])
    month = int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f"Month must be 1-12, got {month}")
    return year, month


# ============================================================================
# Aggregate Root: FiscalPeriod
# ============================================================================


class FiscalPeriod:
    """Aggregate root untuk fiscal period dengan semua method entity dasar."""

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _events: ClassVar[list[Any]] = []

    def __init__(
        self,
        period_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        period_type: PeriodType | None = None,
        period_number: int | None = None,
        year: int | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        status: PeriodStatus | None = None,
        opened_at: datetime | None = None,
        opened_by: str | None = None,
        closed_at: datetime | None = None,
        closed_by: str | None = None,
        locked_at: datetime | None = None,
        locked_by: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        created_by: str = "system",
        updated_by: str = "system",
        version: int = 1,
        period: str | None = None,
    ):
        # Handle test case where period is provided as string
        if period is not None:
            year, month = _parse_period_string(period)
            period_type = PeriodType.MONTHLY
            period_number = month
            start = datetime(year, month, 1, tzinfo=UTC)
            if month == 12:
                end = datetime(year + 1, 1, 1, tzinfo=UTC)
            else:
                end = datetime(year, month + 1, 1, tzinfo=UTC)
            start_date = start
            end_date = end
            if legal_entity_id is None:
                legal_entity_id = uuid4()
            if status is None:
                status = PeriodStatus.OPEN
        else:
            if year is None:
                year = 2000
            if period_number is None:
                period_number = 1
            if period_type is None:
                period_type = PeriodType.MONTHLY
            if start_date is None:
                start_date = datetime.now(UTC)
            if end_date is None:
                end_date = datetime.now(UTC)
            if legal_entity_id is None:
                legal_entity_id = uuid4()
            if status is None:
                status = PeriodStatus.OPEN

        self._period_id = period_id or uuid4()
        self._legal_entity_id = legal_entity_id
        self._period_type = period_type
        self._period_number = period_number
        self._year = year
        self._start_date = _normalize_datetime(start_date)
        self._end_date = _normalize_datetime(end_date)
        self._status = status
        self._opened_at = _normalize_datetime(opened_at) if opened_at else None
        self._opened_by = opened_by
        self._closed_at = _normalize_datetime(closed_at) if closed_at else None
        self._closed_by = closed_by
        self._locked_at = _normalize_datetime(locked_at) if locked_at else None
        self._locked_by = locked_by
        self._created_at = _normalize_datetime(created_at)
        self._updated_at = _normalize_datetime(updated_at)
        self._created_by = created_by
        self._updated_by = updated_by
        self._version = version
        self._metadata: dict[str, Any] = {}

        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", created_by, {})

    def _validate(self) -> None:
        if self._start_date >= self._end_date:
            raise InvalidDateRangeError(
                f"Start date {self._start_date} must be before end date {self._end_date}"
            )
        if self._version < 1:
            raise FiscalPeriodError("Version must be >= 1")
        if self._period_type == PeriodType.MONTHLY and not (1 <= self._period_number <= 12):
            raise InvalidPeriodNumberError(
                f"Monthly period number must be 1-12, got {self._period_number}"
            )
        if self._period_type == PeriodType.QUARTERLY and not (1 <= self._period_number <= 4):
            raise InvalidPeriodNumberError(
                f"Quarterly period number must be 1-4, got {self._period_number}"
            )
        if self._period_type == PeriodType.ANNUAL and self._period_number != 1:
            raise InvalidPeriodNumberError(
                f"Annual period number must be 1, got {self._period_number}"
            )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "period_id": str(self._period_id),
            "period": self.period,
            "status": self._status.value,
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
            "version": self._version,
            "period_id": str(self._period_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _register_event(self, event: Any) -> None:
        self._events.append(event)

    # ==================== PROPERTIES ====================

    @property
    def period_id(self) -> UUID:
        return self._period_id

    @property
    def legal_entity_id(self) -> UUID:
        return self._legal_entity_id

    @property
    def period_type(self) -> PeriodType:
        return self._period_type

    @property
    def period_number(self) -> int:
        return self._period_number

    @property
    def year(self) -> int:
        return self._year

    @property
    def start_date(self) -> datetime:
        return self._start_date

    @property
    def end_date(self) -> datetime:
        return self._end_date

    @property
    def status(self) -> PeriodStatus:
        return self._status

    @property
    def opened_at(self) -> datetime | None:
        return self._opened_at

    @property
    def opened_by(self) -> str | None:
        return self._opened_by

    @property
    def closed_at(self) -> datetime | None:
        return self._closed_at

    @property
    def closed_by(self) -> str | None:
        return self._closed_by

    @property
    def locked_at(self) -> datetime | None:
        return self._locked_at

    @property
    def locked_by(self) -> str | None:
        return self._locked_by

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def created_by(self) -> str:
        return self._created_by

    @property
    def updated_by(self) -> str:
        return self._updated_by

    @property
    def version(self) -> int:
        return self._version

    @property
    def period(self) -> str:
        if self._period_type == PeriodType.MONTHLY:
            return f"{self._year}-{self._period_number:02d}"
        elif self._period_type == PeriodType.QUARTERLY:
            return f"{self._year}-Q{self._period_number}"
        else:
            return str(self._year)

    @property
    def is_closed(self) -> bool:
        return self._status == PeriodStatus.CLOSED

    @property
    def is_reopened(self) -> bool:
        return self._status == PeriodStatus.OPEN and self._opened_at is not None

    @property
    def is_open(self) -> bool:
        return self._status == PeriodStatus.OPEN

    @property
    def is_locked(self) -> bool:
        return self._status == PeriodStatus.LOCKED

    @property
    def is_draft(self) -> bool:
        return self._status == PeriodStatus.DRAFT

    @property
    def duration_days(self) -> int:
        return (self._end_date - self._start_date).days

    @property
    def can_adjust(self) -> bool:
        return self._status.can_adjust()

    # ==================== FACTORY METHODS ====================

    @classmethod
    def create_monthly(
        cls,
        legal_entity_id: UUID,
        year: int,
        month: int,
        created_by: str = "system",
        period_id: UUID | None = None,
        status: PeriodStatus = PeriodStatus.OPEN,
    ) -> FiscalPeriod:
        return cls(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            period_type=PeriodType.MONTHLY,
            period_number=month,
            year=year,
            start_date=datetime(year, month, 1, tzinfo=UTC),
            end_date=datetime(year + 1, 1, 1, tzinfo=UTC)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=UTC),
            status=status,
            opened_at=datetime.now(UTC) if status == PeriodStatus.OPEN else None,
            opened_by=created_by if status == PeriodStatus.OPEN else None,
            created_by=created_by,
            updated_by=created_by,
        )

    @classmethod
    def create_quarterly(
        cls,
        legal_entity_id: UUID,
        year: int,
        quarter: int,
        created_by: str = "system",
        period_id: UUID | None = None,
        status: PeriodStatus = PeriodStatus.OPEN,
    ) -> FiscalPeriod:
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 3
        return cls(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            period_type=PeriodType.QUARTERLY,
            period_number=quarter,
            year=year,
            start_date=datetime(year, start_month, 1, tzinfo=UTC),
            end_date=datetime(year, end_month, 1, tzinfo=UTC)
            if quarter < 4
            else datetime(year + 1, 1, 1, tzinfo=UTC),
            status=status,
            opened_at=datetime.now(UTC) if status == PeriodStatus.OPEN else None,
            opened_by=created_by if status == PeriodStatus.OPEN else None,
            created_by=created_by,
            updated_by=created_by,
        )

    @classmethod
    def create_annual(
        cls,
        legal_entity_id: UUID,
        year: int,
        created_by: str = "system",
        period_id: UUID | None = None,
        status: PeriodStatus = PeriodStatus.OPEN,
    ) -> FiscalPeriod:
        return cls(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            period_type=PeriodType.ANNUAL,
            period_number=1,
            year=year,
            start_date=datetime(year, 1, 1, tzinfo=UTC),
            end_date=datetime(year + 1, 1, 1, tzinfo=UTC),
            status=status,
            opened_at=datetime.now(UTC) if status == PeriodStatus.OPEN else None,
            opened_by=created_by if status == PeriodStatus.OPEN else None,
            created_by=created_by,
            updated_by=created_by,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FiscalPeriod:
        period_type = PeriodType.from_string(data["period_type"])
        if period_type is None:
            raise FiscalPeriodError(f"Invalid period_type: {data['period_type']}")
        status = PeriodStatus.from_string(data["status"])
        if status is None:
            raise FiscalPeriodError(f"Invalid status: {data['status']}")

        def parse_dt(key: str) -> datetime | None:
            val = data.get(key)
            if val is None:
                return None
            if isinstance(val, str):
                return datetime.fromisoformat(val)
            return val

        start_dt = parse_dt("start_date")
        end_dt = parse_dt("end_date")
        if start_dt is None or end_dt is None:
            raise FiscalPeriodError("start_date and end_date are required")

        return cls(
            period_id=UUID(data["period_id"])
            if isinstance(data["period_id"], str)
            else data["period_id"],
            legal_entity_id=UUID(data["legal_entity_id"])
            if isinstance(data["legal_entity_id"], str)
            else data["legal_entity_id"],
            period_type=period_type,
            period_number=data["period_number"],
            year=data["year"],
            start_date=start_dt,
            end_date=end_dt,
            status=status,
            opened_at=parse_dt("opened_at"),
            opened_by=data.get("opened_by"),
            closed_at=parse_dt("closed_at"),
            closed_by=data.get("closed_by"),
            locked_at=parse_dt("locked_at"),
            locked_by=data.get("locked_by"),
            created_at=parse_dt("created_at") or datetime.now(UTC),
            updated_at=parse_dt("updated_at") or datetime.now(UTC),
            created_by=data.get("created_by", "system"),
            updated_by=data.get("updated_by", "system"),
            version=data.get("version", 1),
        )

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> FiscalPeriod:
        self._record_audit("CREATE", created_by, {"period": self.period})
        return self

    def update(self, updated_by: str, **kwargs) -> FiscalPeriod:
        if self._status == PeriodStatus.CLOSED:
            raise InvalidStatusTransitionError("Cannot update a closed period")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("period_id", "created_at", "created_by", "version"):
                data[key] = value
        new_period = self.from_dict(data)
        new_period._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_period

    def delete(self, deleted_by: str, reason: str | None = None) -> FiscalPeriod:
        if self._status != PeriodStatus.OPEN:
            raise InvalidStatusTransitionError(
                f"Cannot delete period with status {self._status.value}"
            )
        new_period = self._copy()
        new_period._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_period

    def restore(self, restored_by: str) -> FiscalPeriod:
        if self._status != PeriodStatus.CLOSED:
            raise InvalidStatusTransitionError(
                f"Period must be CLOSED to restore, current: {self._status.value}"
            )
        new_period = self.reopen(restored_by, reason="Restored from closed state")
        new_period._record_audit("RESTORE", restored_by, {})
        new_period._register_event(
            {
                "event_type": "period_restored",
                "period_id": str(self._period_id),
                "restored_by": restored_by,
            }
        )
        return new_period

    def activate(self, activated_by: str) -> FiscalPeriod:
        if self._status == PeriodStatus.OPEN:
            return self
        return self.open(activated_by)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> FiscalPeriod:
        if self._status == PeriodStatus.CLOSED:
            return self
        return self.close(deactivated_by)

    def lock(self, locked_by: str, reason: str) -> FiscalPeriod:
        if self._status != PeriodStatus.OPEN:
            raise InvalidStatusTransitionError(
                f"Period must be OPEN to lock, current: {self._status.value}"
            )
        now = datetime.now(UTC)
        new_period = FiscalPeriod(
            period_id=self._period_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=PeriodStatus.LOCKED,
            opened_at=self._opened_at,
            opened_by=self._opened_by,
            closed_at=None,
            closed_by=None,
            locked_at=now,
            locked_by=locked_by,
            created_at=self._created_at,
            updated_at=now,
            created_by=self._created_by,
            updated_by=locked_by,
            version=self._version + 1,
        )
        new_period._record_audit("LOCK", locked_by, {"reason": reason})
        new_period._register_event({
            "event_type": "period_locked",
            "period_id": str(self._period_id),
            "locked_by": locked_by,
        })
        return new_period

    def unlock_period(self, unlocked_by: str) -> FiscalPeriod:
        if self._status != PeriodStatus.LOCKED:
            raise InvalidStatusTransitionError(
                f"Period must be LOCKED to unlock, current: {self._status.value}"
            )
        now = datetime.now(UTC)
        new_period = FiscalPeriod(
            period_id=self._period_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=PeriodStatus.OPEN,
            opened_at=now,
            opened_by=unlocked_by,
            closed_at=None,
            closed_by=None,
            locked_at=None,
            locked_by=None,
            created_at=self._created_at,
            updated_at=now,
            created_by=self._created_by,
            updated_by=unlocked_by,
            version=self._version + 1,
        )
        new_period._record_audit("UNLOCK", unlocked_by, {})
        return new_period

    def unlock(self, unlocked_by: str) -> FiscalPeriod:
        if self._status == PeriodStatus.CLOSED:
            raise InvalidStatusTransitionError(
                "Cannot unlock a CLOSED period, use reopen() instead."
            )
        if self._status != PeriodStatus.LOCKED:
            raise InvalidStatusTransitionError(
                f"Period must be LOCKED to unlock, current: {self._status.value}"
            )
        return self.unlock_period(unlocked_by)

    def can_close(self) -> bool:
        return self._status == PeriodStatus.LOCKED

    def close(self, closed_by: str) -> FiscalPeriod:
        if self._status != PeriodStatus.LOCKED:
            raise InvalidStatusTransitionError(
                f"Period must be LOCKED to close, current: {self._status.value}"
            )
        now = datetime.now(UTC)
        new_period = FiscalPeriod(
            period_id=self._period_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=PeriodStatus.CLOSED,
            opened_at=self._opened_at,
            opened_by=self._opened_by,
            closed_at=now,
            closed_by=closed_by,
            locked_at=self._locked_at,
            locked_by=self._locked_by,
            created_at=self._created_at,
            updated_at=now,
            created_by=self._created_by,
            updated_by=closed_by,
            version=self._version + 1,
        )
        new_period._record_audit("CLOSE", closed_by, {})
        new_period._register_event(
            {
                "event_type": "period_closed",
                "period_id": str(self._period_id),
                "closed_by": closed_by,
            }
        )
        return new_period

    def can_reopen(self) -> bool:
        return self._status == PeriodStatus.CLOSED

    def reopen(self, reopened_by: str, reason: str = "") -> FiscalPeriod:
        if self._status != PeriodStatus.CLOSED:
            raise InvalidStatusTransitionError(
                f"Period must be CLOSED to reopen, current: {self._status.value}"
            )
        return self.open(reopened_by, force=True)

    def can_archive(self) -> bool:
        return self._status == PeriodStatus.CLOSED

    def archive(self, archived_by: str, reason: str | None = None) -> FiscalPeriod:
        new_period = self._copy()
        new_period._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return new_period

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> FiscalPeriod:
        new_period = self._copy()
        new_period._record_audit("UNARCHIVE", unarchived_by, {})
        return new_period

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, child: Any, created_by: str) -> FiscalPeriod:
        raise NotImplementedError("FiscalPeriod has no child entities")

    def remove_child(self, child_id: UUID, removed_by: str) -> FiscalPeriod:
        raise NotImplementedError("FiscalPeriod has no child entities")

    def can_post(self, transaction_date: datetime | None = None) -> bool:
        if self._status != PeriodStatus.OPEN:
            return False
        check_date = transaction_date or datetime.now(UTC)
        return self._start_date <= check_date < self._end_date

    def post(self, transaction_date: datetime, posted_by: str) -> FiscalPeriod:
        if not self.can_post(transaction_date):
            raise InvalidStatusTransitionError(
                f"Cannot post to period with status {self._status.value} or date out of range"
            )
        return self

    def can_approve(self, user_role: str = "user") -> bool:
        return self._status == PeriodStatus.OPEN and user_role in ("finance_manager", "admin")

    def approve(self, approved_by: str) -> FiscalPeriod:
        return self.lock(approved_by, "Approved by finance manager")

    def can_reject(self, user_role: str = "user") -> bool:
        return self._status == PeriodStatus.OPEN

    def reject(self, rejected_by: str, reason: str) -> FiscalPeriod:
        self._record_audit("REJECT", rejected_by, {"reason": reason})
        return self

    def can_cancel(self) -> bool:
        return self._status == PeriodStatus.OPEN

    def cancel(self, cancelled_by: str, reason: str) -> FiscalPeriod:
        return self.close(cancelled_by)

    def can_reverse(self) -> bool:
        return False

    def reverse(self, reversed_by: str, reason: str) -> FiscalPeriod:
        raise NotImplementedError("Reverse not applicable for fiscal period")

    # ==================== EVENT METHODS ====================

    def register_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== STATUS TRANSITION METHODS ====================

    def open(self, opened_by: str, force: bool = False) -> FiscalPeriod:
        if self._status == PeriodStatus.OPEN:
            return self
        if self._status == PeriodStatus.CLOSED and not force:
            raise InvalidStatusTransitionError(
                "Cannot reopen a CLOSED period without force flag"
            )
        if self._status not in (PeriodStatus.DRAFT, PeriodStatus.CLOSED):
            raise InvalidStatusTransitionError(
                f"Cannot open period with status {self._status.value}"
            )
        now = datetime.now(UTC)
        new_period = FiscalPeriod(
            period_id=self._period_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=PeriodStatus.OPEN,
            opened_at=now,
            opened_by=opened_by,
            closed_at=None,
            closed_by=None,
            locked_at=None,
            locked_by=None,
            created_at=self._created_at,
            updated_at=now,
            created_by=self._created_by,
            updated_by=opened_by,
            version=self._version + 1,
        )
        new_period._record_audit("OPEN", opened_by, {"force": force})
        new_period._register_event(
            {
                "event_type": "period_opened",
                "period_id": str(self._period_id),
                "opened_by": opened_by,
            }
        )
        return new_period

    # ==================== QUERY METHODS ====================

    def contains_date(self, check_date: datetime) -> bool:
        return self._start_date <= check_date < self._end_date

    def overlaps_with(self, other: FiscalPeriod) -> bool:
        """
        Return True if this period overlaps with another period.
        """
        return self._start_date < other._end_date and other._start_date < self._end_date

    # ==================== VALIDATE & CONVERT METHODS ====================

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except FiscalPeriodError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "period_id": str(self._period_id),
            "version": self._version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self._period_id),
            "legal_entity_id": str(self._legal_entity_id),
            "period_type": self._period_type.value,
            "period_type_display": self._period_type.display_name(),
            "period_number": self._period_number,
            "year": self._year,
            "period": self.period,
            "start_date": self._start_date.isoformat(),
            "end_date": self._end_date.isoformat(),
            "duration_days": self.duration_days,
            "status": self._status.value,
            "status_display": self._status.display_name(),
            "is_open": self.is_open,
            "is_locked": self.is_locked,
            "is_closed": self.is_closed,
            "is_draft": self.is_draft,
            "can_post": self.can_post(),
            "can_adjust": self.can_adjust,
            "opened_at": self._opened_at.isoformat() if self._opened_at else None,
            "opened_by": self._opened_by,
            "closed_at": self._closed_at.isoformat() if self._closed_at else None,
            "closed_by": self._closed_by,
            "locked_at": self._locked_at.isoformat() if self._locked_at else None,
            "locked_by": self._locked_by,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "created_by": self._created_by,
            "updated_by": self._updated_by,
            "version": self._version,
            "metadata": self._metadata,
        }

    def clone(self) -> FiscalPeriod:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = FiscalPeriod(
            period_id=new_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=PeriodStatus.DRAFT,
            created_at=now,
            updated_at=now,
            created_by=self._created_by,
            updated_by=self._created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self._created_by, {"source": str(self._period_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "period_id": str(self._period_id),
            "period": self.period,
            "status": self._status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FiscalPeriod:
        new_period = self._copy()
        new_period._updated_at = datetime.now(UTC)
        new_period._updated_by = touched_by
        new_period._version = self._version + 1
        new_period._record_audit("TOUCH", touched_by, {})
        return new_period

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> FiscalPeriod:
        return FiscalPeriod(
            period_id=self._period_id,
            legal_entity_id=self._legal_entity_id,
            period_type=self._period_type,
            period_number=self._period_number,
            year=self._year,
            start_date=self._start_date,
            end_date=self._end_date,
            status=self._status,
            opened_at=self._opened_at,
            opened_by=self._opened_by,
            closed_at=self._closed_at,
            closed_by=self._closed_by,
            locked_at=self._locked_at,
            locked_by=self._locked_by,
            created_at=self._created_at,
            updated_at=self._updated_at,
            created_by=self._created_by,
            updated_by=self._updated_by,
            version=self._version,
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class FiscalPeriodRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, FiscalPeriod]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, FiscalPeriod]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(cls, period_id: UUID, legal_entity_id: UUID) -> FiscalPeriod | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(period_id)

    @classmethod
    async def get_by_year_month(
        cls, legal_entity_id: UUID, year: int, month: int
    ) -> FiscalPeriod | None:
        storage = cls._get_storage(legal_entity_id)
        for period in storage.values():
            if (
                period.year == year
                and period.period_type == PeriodType.MONTHLY
                and period.period_number == month
            ):
                return period
        return None

    @classmethod
    async def get_by_year(
        cls, legal_entity_id: UUID, year: int, period_type: PeriodType | None = None
    ) -> list[FiscalPeriod]:
        storage = cls._get_storage(legal_entity_id)
        result = [p for p in storage.values() if p.year == year]
        if period_type:
            result = [p for p in result if p.period_type == period_type]
        return result

    @classmethod
    async def get_active_period(
        cls, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> FiscalPeriod | None:
        storage = cls._get_storage(legal_entity_id)
        check_date = as_of or datetime.now(UTC)
        for period in storage.values():
            if period.status == PeriodStatus.OPEN and period.contains_date(check_date):
                return period
        return None

    @classmethod
    async def get_periods_by_date_range(
        cls, legal_entity_id: UUID, start_date: datetime, end_date: datetime
    ) -> list[FiscalPeriod]:
        storage = cls._get_storage(legal_entity_id)
        return [
            p
            for p in storage.values()
            if not (p.end_date <= start_date or p.start_date >= end_date)
        ]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[FiscalPeriod]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def get_by_status(cls, legal_entity_id: UUID, status: PeriodStatus) -> list[FiscalPeriod]:
        storage = cls._get_storage(legal_entity_id)
        return [p for p in storage.values() if p.status == status]

    @classmethod
    async def get_open_periods(cls, legal_entity_id: UUID) -> list[FiscalPeriod]:
        return await cls.get_by_status(legal_entity_id, PeriodStatus.OPEN)

    @classmethod
    async def exists(cls, period_id: UUID, legal_entity_id: UUID) -> bool:
        storage = cls._get_storage(legal_entity_id)
        return period_id in storage

    @classmethod
    async def count(cls, legal_entity_id: UUID) -> int:
        storage = cls._get_storage(legal_entity_id)
        return len(storage)

    @classmethod
    async def list_periods(
        cls, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[FiscalPeriod]:
        periods = await cls.get_all(legal_entity_id)
        return periods[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[FiscalPeriod], int]:
        periods = await cls.get_all(legal_entity_id)
        total = len(periods)
        start = (page - 1) * per_page
        end = start + per_page
        return periods[start:end], total

    @classmethod
    async def search(
        cls, legal_entity_id: UUID, query: str, fields: list[str] | None = None
    ) -> list[FiscalPeriod]:
        if fields is None:
            fields = ["period", "year"]
        periods = await cls.get_all(legal_entity_id)
        query_lower = query.lower()
        results: list[FiscalPeriod] = []
        for p in periods:
            for field in fields:
                if field == "period":
                    value = p.period
                elif field == "year":
                    value = str(p.year)
                else:
                    value = getattr(p, field, "")
                if value and query_lower in str(value).lower():
                    results.append(p)
                    break
        return results

    @classmethod
    async def lock(
        cls, period_id: UUID, legal_entity_id: UUID, locked_by: str, reason: str
    ) -> FiscalPeriod:
        period = await cls.get_by_id(period_id, legal_entity_id)
        if not period:
            raise ValueError(f"Period {period_id} not found")
        if period.status != PeriodStatus.OPEN:
            raise InvalidStatusTransitionError(
                f"Period must be OPEN to lock, current: {period.status.value}"
            )
        locked = period.lock(locked_by, reason)
        await cls.save(locked, legal_entity_id)
        return locked

    @classmethod
    async def unlock(cls, period_id: UUID, legal_entity_id: UUID, unlocked_by: str) -> FiscalPeriod:
        period = await cls.get_by_id(period_id, legal_entity_id)
        if not period:
            raise ValueError(f"Period {period_id} not found")
        if period.status != PeriodStatus.LOCKED:
            raise InvalidStatusTransitionError(
                f"Period must be LOCKED to unlock, current: {period.status.value}"
            )
        unlocked = period.unlock(unlocked_by)
        await cls.save(unlocked, legal_entity_id)
        return unlocked

    @classmethod
    async def save(cls, period: FiscalPeriod, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[period.period_id] = period

    @classmethod
    async def update(cls, period: FiscalPeriod, legal_entity_id: UUID) -> None:
        await cls.save(period, legal_entity_id)

    @classmethod
    async def delete(cls, period_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(period_id, None)

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        if legal_entity_id in cls._storage:
            cls._storage[legal_entity_id] = {}


__all__ = [
    "AccountingPeriod",
    "FiscalPeriod",
    "FiscalPeriodError",
    "FiscalPeriodRepository",
    "InvalidDateRangeError",
    "InvalidPeriodNumberError",
    "InvalidStatusTransitionError",
    "PeriodAlreadyExistsError",
    "PeriodNotFoundError",
    "PeriodStatus",
    "PeriodType",
]
