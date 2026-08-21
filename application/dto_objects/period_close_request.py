# period_close_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: period_close_request.py
Layer: 8 - Application / DTO Objects
Responsibility: DTO permintaan tutup periode akuntansi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID

# === 1. CONSTANTS & ENUMS ===


class PeriodStatus(Enum):
    """Status periode akuntansi."""

    OPEN = "open"
    LOCKED = "locked"
    CLOSED = "closed"
    ARCHIVED = "archived"
    FUTURE = "future"


class PeriodType(Enum):
    """Jenis periode akuntansi."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


class CloseAction(Enum):
    """Aksi penutupan periode."""

    CLOSE = "close"
    LOCK = "lock"
    REOPEN = "reopen"
    ARCHIVE = "archive"


class ReopenReason(Enum):
    """Alasan pembukaan kembali periode."""

    CORRECTION = "correction"
    ADJUSTMENT = "adjustment"
    AUDIT_REQUIREMENT = "audit_requirement"
    REGULATORY = "regulatory"
    SYSTEM_ERROR = "system_error"
    OTHER = "other"


# === 2. PERIOD INFO DTO ===


@dataclass(kw_only=True)
class PeriodInfo:
    """Informasi periode akuntansi."""

    period_id: UUID
    fiscal_year: int
    period_number: int
    period_type: PeriodType
    period_name: str
    start_date: datetime
    end_date: datetime
    status: PeriodStatus = PeriodStatus.OPEN
    closed_at: datetime | None = None
    closed_by: str | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    reopened_at: datetime | None = None
    reopened_by: str | None = None
    reopen_reason: str | None = None
    reopen_approvals: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.start_date >= self.end_date:
            raise ValueError(
                f"Start date {self.start_date} must be before end date {self.end_date}"
            )
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))
        if self.closed_at and self.closed_at.tzinfo is None:
            object.__setattr__(self, "closed_at", self.closed_at.replace(tzinfo=UTC))
        if self.locked_at and self.locked_at.tzinfo is None:
            object.__setattr__(self, "locked_at", self.locked_at.replace(tzinfo=UTC))
        if self.reopened_at and self.reopened_at.tzinfo is None:
            object.__setattr__(self, "reopened_at", self.reopened_at.replace(tzinfo=UTC))

    def is_open(self) -> bool:
        return self.status == PeriodStatus.OPEN

    def is_locked(self) -> bool:
        return self.status == PeriodStatus.LOCKED

    def is_closed(self) -> bool:
        return self.status == PeriodStatus.CLOSED

    def is_archived(self) -> bool:
        return self.status == PeriodStatus.ARCHIVED

    def can_post(self) -> bool:
        return self.status in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

    def can_adjust(self) -> bool:
        return self.status in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

    def days_in_period(self) -> int:
        return (self.end_date - self.start_date).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
            "period_type": self.period_type.value,
            "period_name": self.period_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status.value,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "closed_by": self.closed_by,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by": self.locked_by,
            "reopened_at": self.reopened_at.isoformat() if self.reopened_at else None,
            "reopened_by": self.reopened_by,
            "reopen_reason": self.reopen_reason,
            "reopen_approvals": self.reopen_approvals,
            "days_in_period": self.days_in_period(),
        }

    @classmethod
    def create_open(
        cls,
        period_id: UUID,
        fiscal_year: int,
        period_number: int,
        period_type: PeriodType,
        period_name: str,
        start_date: datetime,
        end_date: datetime,
    ) -> PeriodInfo:
        """Create an open period."""
        return cls(
            period_id=period_id,
            fiscal_year=fiscal_year,
            period_number=period_number,
            period_type=period_type,
            period_name=period_name,
            start_date=start_date,
            end_date=end_date,
            status=PeriodStatus.OPEN,
        )


# === 3. CLOSE PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class ClosePeriodRequest:
    """DTO untuk request penutupan periode."""

    period_id: UUID
    legal_entity_id: UUID
    closed_by: str
    adjustment_journal_id: UUID | None = None
    force_close: bool = False
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.closed_by:
            raise ValueError("closed_by is required")
        if self.force_close and not self.notes:
            raise ValueError("Notes are required for force close")

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "closed_by": self.closed_by,
            "adjustment_journal_id": str(self.adjustment_journal_id)
            if self.adjustment_journal_id
            else None,
            "force_close": self.force_close,
            "notes": self.notes,
            "idempotency_key": self.idempotency_key,
        }


# === 4. LOCK PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class LockPeriodRequest:
    """DTO untuk request penguncian periode."""

    period_id: UUID
    legal_entity_id: UUID
    locked_by: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.locked_by:
            raise ValueError("locked_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "locked_by": self.locked_by,
            "notes": self.notes,
        }


# === 5. REOPEN PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class ReopenPeriodRequest:
    """DTO untuk request pembukaan kembali periode."""

    period_id: UUID
    legal_entity_id: UUID
    reopened_by: str
    reason: ReopenReason
    reason_description: str
    approved_by: list[str]
    notes: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.reopened_by:
            raise ValueError("reopened_by is required")
        if not self.reason_description or len(self.reason_description.strip()) < 10:
            raise ValueError("Reason description must be at least 10 characters")
        if not self.approved_by or len(self.approved_by) < 2:
            raise ValueError("At least 2 approvers required for reopening a closed period")
        if self.reopened_by in self.approved_by:
            raise ValueError("Reopener cannot be one of the approvers (dual control)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "reopened_by": self.reopened_by,
            "reason": self.reason.value,
            "reason_description": self.reason_description,
            "approved_by": self.approved_by,
            "notes": self.notes,
            "idempotency_key": self.idempotency_key,
        }


# === 6. ARCHIVE PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class ArchivePeriodRequest:
    """DTO untuk request pengarsipan periode."""

    period_id: UUID
    legal_entity_id: UUID
    archived_by: str
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.archived_by:
            raise ValueError("archived_by is required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "archived_by": self.archived_by,
            "notes": self.notes,
        }


# === 7. GET PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class GetPeriodRequest:
    """DTO untuk request get periode."""

    period_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 8. GET PERIOD BY DATE REQUEST DTO ===


@dataclass(kw_only=True)
class GetPeriodByDateRequest:
    """DTO untuk request get periode berdasarkan tanggal."""

    legal_entity_id: UUID
    date: datetime

    def __post_init__(self) -> None:
        if self.date.tzinfo is None:
            object.__setattr__(self, "date", self.date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "date": self.date.isoformat(),
        }


# === 9. LIST PERIODS REQUEST DTO ===


@dataclass(kw_only=True)
class ListPeriodsRequest:
    """DTO untuk request list periode dengan filter."""

    legal_entity_id: UUID
    fiscal_year: int | None = None
    period_type: PeriodType | None = None
    status: PeriodStatus | None = None
    from_date: datetime | None = None
    to_date: datetime | None = None
    limit: int = 100
    offset: int = 0

    def __post_init__(self) -> None:
        if self.limit < 1 or self.limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if self.offset < 0:
            raise ValueError("offset must be >= 0")
        if self.fiscal_year is not None and self.fiscal_year < 2000:
            raise ValueError(f"fiscal_year must be >= 2000: {self.fiscal_year}")
        if self.from_date and self.from_date.tzinfo is None:
            object.__setattr__(self, "from_date", self.from_date.replace(tzinfo=UTC))
        if self.to_date and self.to_date.tzinfo is None:
            object.__setattr__(self, "to_date", self.to_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "fiscal_year": self.fiscal_year,
            "period_type": self.period_type.value if self.period_type else None,
            "status": self.status.value if self.status else None,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "limit": self.limit,
            "offset": self.offset,
        }


# === 10. GET CURRENT PERIOD REQUEST DTO ===


@dataclass(kw_only=True)
class GetCurrentPeriodRequest:
    """DTO untuk request get periode saat ini."""

    legal_entity_id: UUID
    as_of_date: datetime | None = None

    def __post_init__(self) -> None:
        if self.as_of_date is None:
            object.__setattr__(self, "as_of_date", datetime.now(UTC))
        elif self.as_of_date.tzinfo is None:
            object.__setattr__(self, "as_of_date", self.as_of_date.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        # as_of_date is guaranteed non-None after __post_init__
        assert self.as_of_date is not None
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
        }


# === 11. VERIFY PERIOD READINESS REQUEST DTO ===


@dataclass(kw_only=True)
class VerifyPeriodReadinessRequest:
    """DTO untuk request verifikasi kesiapan periode ditutup."""

    period_id: UUID
    legal_entity_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
        }


# === 12. PERIOD READINESS REPORT DTO ===


@dataclass(kw_only=True)
class PeriodReadinessReport:
    """Laporan kesiapan periode ditutup."""

    period_id: UUID
    period_name: str
    is_ready: bool
    unposted_journals_count: int
    unposted_journals: list[dict[str, Any]]
    unreconciled_transactions_count: int
    unbalanced_accounts: list[dict[str, Any]]
    pending_approvals_count: int
    warnings: list[str]
    errors: list[str]
    verified_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.verified_at.tzinfo is None:
            object.__setattr__(self, "verified_at", self.verified_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "period_name": self.period_name,
            "is_ready": self.is_ready,
            "unposted_journals_count": self.unposted_journals_count,
            "unposted_journals": self.unposted_journals[:10],
            "unreconciled_transactions_count": self.unreconciled_transactions_count,
            "unbalanced_accounts": self.unbalanced_accounts[:10],
            "pending_approvals_count": self.pending_approvals_count,
            "warnings": self.warnings,
            "errors": self.errors,
            "verified_at": self.verified_at.isoformat(),
        }

    @classmethod
    def create_ready(cls, period_id: UUID, period_name: str) -> PeriodReadinessReport:
        """Membuat laporan ready."""
        return cls(
            period_id=period_id,
            period_name=period_name,
            is_ready=True,
            unposted_journals_count=0,
            unposted_journals=[],
            unreconciled_transactions_count=0,
            unbalanced_accounts=[],
            pending_approvals_count=0,
            warnings=[],
            errors=[],
        )

    @classmethod
    def create_not_ready(
        cls,
        period_id: UUID,
        period_name: str,
        errors: list[str],
        warnings: list[str] | None = None,
    ) -> PeriodReadinessReport:
        """Membuat laporan not ready."""
        return cls(
            period_id=period_id,
            period_name=period_name,
            is_ready=False,
            unposted_journals_count=0,
            unposted_journals=[],
            unreconciled_transactions_count=0,
            unbalanced_accounts=[],
            pending_approvals_count=0,
            warnings=warnings or [],
            errors=errors,
        )


# === 13. PERIOD CLOSE SUMMARY DTO ===


@dataclass(kw_only=True)
class PeriodCloseSummary:
    """Ringkasan penutupan periode."""

    period_id: UUID
    period_name: str
    closed_at: datetime
    closed_by: str
    closing_journal_id: UUID | None = None
    closing_journal_number: str | None = None
    adjustment_entries_count: int = 0
    previous_period_status: str | None = None
    next_period_status: str | None = None

    def __post_init__(self) -> None:
        if self.closed_at.tzinfo is None:
            object.__setattr__(self, "closed_at", self.closed_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "period_name": self.period_name,
            "closed_at": self.closed_at.isoformat(),
            "closed_by": self.closed_by,
            "closing_journal_id": str(self.closing_journal_id) if self.closing_journal_id else None,
            "closing_journal_number": self.closing_journal_number,
            "adjustment_entries_count": self.adjustment_entries_count,
            "previous_period_status": self.previous_period_status,
            "next_period_status": self.next_period_status,
        }


# === 14. RESPONSE DTOS ===


class PeriodCloseStatusDTO(str, Enum):
    """Status penutupan periode untuk DTO response."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class PeriodCloseResponseDTO:
    """DTO response untuk penutupan periode."""

    id: UUID
    period_year: int
    period_month: int
    started_by: UUID
    started_at: datetime
    status: PeriodCloseStatusDTO = PeriodCloseStatusDTO.PENDING
    completed_at: datetime | None = None
    steps_completed: list[str] = field(default_factory=list)
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.started_at.tzinfo is None:
            object.__setattr__(self, "started_at", self.started_at.replace(tzinfo=UTC))
        if self.completed_at and self.completed_at.tzinfo is None:
            object.__setattr__(self, "completed_at", self.completed_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "period_year": self.period_year,
            "period_month": self.period_month,
            "started_by": str(self.started_by),
            "started_at": self.started_at.isoformat(),
            "status": self.status.value,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "steps_completed": self.steps_completed,
            "error_message": self.error_message,
        }

    def is_completed(self) -> bool:
        return self.status == PeriodCloseStatusDTO.COMPLETED

    def is_failed(self) -> bool:
        return self.status == PeriodCloseStatusDTO.FAILED


# === 15. FACTORY ===


class PeriodCloseRequestFactory:
    """Factory untuk membuat Period Close Request DTOs."""

    @staticmethod
    def create_close_request(
        period_id: UUID,
        legal_entity_id: UUID,
        closed_by: str,
        adjustment_journal_id: UUID | None = None,
        notes: str = "",
    ) -> ClosePeriodRequest:
        """Membuat ClosePeriodRequest."""
        return ClosePeriodRequest(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            closed_by=closed_by,
            adjustment_journal_id=adjustment_journal_id,
            notes=notes,
        )

    @staticmethod
    def create_reopen_request(
        period_id: UUID,
        legal_entity_id: UUID,
        reopened_by: str,
        reason: ReopenReason,
        reason_description: str,
        approved_by: list[str],
        notes: str = "",
    ) -> ReopenPeriodRequest:
        """Membuat ReopenPeriodRequest."""
        return ReopenPeriodRequest(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            reopened_by=reopened_by,
            reason=reason,
            reason_description=reason_description,
            approved_by=approved_by,
            notes=notes,
        )

    @staticmethod
    def create_lock_request(
        period_id: UUID,
        legal_entity_id: UUID,
        locked_by: str,
        notes: str = "",
    ) -> LockPeriodRequest:
        """Membuat LockPeriodRequest."""
        return LockPeriodRequest(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            locked_by=locked_by,
            notes=notes,
        )

    @staticmethod
    def create_archive_request(
        period_id: UUID,
        legal_entity_id: UUID,
        archived_by: str,
        notes: str = "",
    ) -> ArchivePeriodRequest:
        """Membuat ArchivePeriodRequest."""
        return ArchivePeriodRequest(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            archived_by=archived_by,
            notes=notes,
        )


# === 16. ALIASES ===

PeriodCloseRequestDTO = ClosePeriodRequest
PeriodLockRequestDTO = LockPeriodRequest
PeriodReopenRequestDTO = ReopenPeriodRequest
PeriodArchiveRequestDTO = ArchivePeriodRequest


# === 17. EXPORTS ===

__all__ = [
    # DTOs
    "ArchivePeriodRequest",
    # Enums
    "CloseAction",
    "ClosePeriodRequest",
    "GetCurrentPeriodRequest",
    "GetPeriodByDateRequest",
    "GetPeriodRequest",
    "ListPeriodsRequest",
    "LockPeriodRequest",
    # Aliases
    "PeriodArchiveRequestDTO",
    "PeriodCloseRequestDTO",
    # Factory
    "PeriodCloseRequestFactory",
    "PeriodCloseResponseDTO",
    "PeriodCloseStatusDTO",
    "PeriodCloseSummary",
    "PeriodInfo",
    "PeriodLockRequestDTO",
    "PeriodReadinessReport",
    "PeriodReopenRequestDTO",
    "PeriodStatus",
    "PeriodType",
    "ReopenPeriodRequest",
    "ReopenReason",
    "VerifyPeriodReadinessRequest",
]


