#!/usr/bin/env python3
"""
Module: period_closure_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: tidak bisa posting ke periode yang sudah ditutup.
               Memastikan bahwa setelah suatu periode akuntansi ditutup,
               tidak ada transaksi baru yang dapat diposting ke periode tersebut.
               Periode yang sudah ditutup bersifat immutable.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, PeriodClosureViolation)

Audit: Setiap percobaan posting ke periode tertutup dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    LawViolationSeverity,
    PeriodClosureViolation,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackFiscalPeriodRepository:
    """Fallback fiscal period repository dengan in-memory storage."""

    def __init__(self):
        self._periods: dict[UUID, dict[str, Any]] = {}
        self._by_entity: dict[UUID, list[UUID]] = {}
        self._by_year: dict[tuple[UUID, int], list[UUID]] = {}

    async def get_by_id(self, period_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        period = self._periods.get(period_id)
        if period and period.get("legal_entity_id") == legal_entity_id:
            return period
        return None

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        period_ids = self._by_entity.get(legal_entity_id, [])
        return [self._periods[pid] for pid in period_ids if pid in self._periods]

    async def get_by_fiscal_year(
        self, fiscal_year: int, legal_entity_id: UUID
    ) -> list[dict[str, Any]]:
        key = (legal_entity_id, fiscal_year)
        period_ids = self._by_year.get(key, [])
        return [self._periods[pid] for pid in period_ids if pid in self._periods]

    async def get_current_period(
        self, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> dict[str, Any] | None:
        check_date = as_of or datetime.now(UTC)
        periods = await self.get_by_legal_entity(legal_entity_id)
        for period in periods:
            start = period.get("start_date")
            end = period.get("end_date")
            if start and end and start <= check_date <= end:
                return period
        return None

    async def update_status(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        new_status: str,
        closed_by: str | None = None,
        closed_at: datetime | None = None,
        adjustment_journal_id: UUID | None = None,
        reopened_by: str | None = None,
        reopened_at: datetime | None = None,
        reopen_reason: str | None = None,
        locked_by: str | None = None,
        locked_at: datetime | None = None,
    ) -> bool:
        period = self._periods.get(period_id)
        if not period or period.get("legal_entity_id") != legal_entity_id:
            return False
        period["status"] = new_status
        if closed_by:
            period["closed_by"] = closed_by
        if closed_at:
            period["closed_at"] = closed_at
        if adjustment_journal_id:
            period["adjustment_journal_id"] = adjustment_journal_id
        if reopened_by:
            period["reopened_by"] = reopened_by
        if reopened_at:
            period["reopened_at"] = reopened_at
        if reopen_reason:
            period["reopen_reason"] = reopen_reason
        if locked_by:
            period["locked_by"] = locked_by
        if locked_at:
            period["locked_at"] = locked_at
        period["updated_at"] = datetime.now(UTC)
        return True

    async def get_pending_by_period(self, period_id: UUID, legal_entity_id: UUID) -> list[Any]:
        return []

    async def get_periods_by_status(
        self, legal_entity_id: UUID, status: str
    ) -> list[dict[str, Any]]:
        periods = await self.get_by_legal_entity(legal_entity_id)
        return [p for p in periods if p.get("status") == status]

    async def get_last_closed_period(self, legal_entity_id: UUID) -> dict[str, Any] | None:
        periods = await self.get_by_legal_entity(legal_entity_id)
        closed = [p for p in periods if p.get("status") == "closed"]
        if not closed:
            return None
        return max(closed, key=lambda p: p.get("end_date", datetime.min))

    def add_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        period_name: str,
        fiscal_year: int,
        period_number: int,
        start_date: datetime,
        end_date: datetime,
        status: str = "OPEN",
        previous_period_id: UUID | None = None,
        next_period_id: UUID | None = None,
    ) -> None:
        period = {
            "period_id": period_id,
            "legal_entity_id": legal_entity_id,
            "period_name": period_name,
            "fiscal_year": fiscal_year,
            "period_number": period_number,
            "start_date": start_date,
            "end_date": end_date,
            "status": status,
            "previous_period_id": previous_period_id,
            "next_period_id": next_period_id,
            "created_at": datetime.now(UTC),
        }
        self._periods[period_id] = period
        self._by_entity.setdefault(legal_entity_id, []).append(period_id)
        key = (legal_entity_id, fiscal_year)
        self._by_year.setdefault(key, []).append(period_id)

    def clear(self) -> None:
        self._periods.clear()
        self._by_entity.clear()
        self._by_year.clear()


class _FallbackJournalRepository:
    """Fallback journal repository jika infrastructure belum tersedia."""

    def __init__(self):
        self._journals: dict[UUID, dict[str, Any]] = {}

    async def get_by_id(self, journal_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        journal = self._journals.get(journal_id)
        if journal and journal.get("legal_entity_id") == legal_entity_id:
            return journal
        return None

    async def get_pending_by_period(self, period_id: UUID, legal_entity_id: UUID) -> list[Any]:
        result = []
        for journal in self._journals.values():
            if (
                journal.get("legal_entity_id") == legal_entity_id
                and journal.get("period_id") == period_id
                and journal.get("status") in ("DRAFT", "SUBMITTED", "APPROVED")
            ):
                result.append(journal)
        return result

    async def get_posted_by_period(self, period_id: UUID, legal_entity_id: UUID) -> list[Any]:
        result = []
        for journal in self._journals.values():
            if (
                journal.get("legal_entity_id") == legal_entity_id
                and journal.get("period_id") == period_id
                and journal.get("status") == "POSTED"
            ):
                result.append(journal)
        return result

    def add_journal(
        self, journal_id: UUID, legal_entity_id: UUID, period_id: UUID, status: str
    ) -> None:
        self._journals[journal_id] = {
            "journal_id": journal_id,
            "legal_entity_id": legal_entity_id,
            "period_id": period_id,
            "status": status,
            "created_at": datetime.now(UTC),
        }

    def clear(self) -> None:
        self._journals.clear()


# === 2. CONSTANTS & ENUMS ===


class PeriodStatus(Enum):
    FUTURE = "future"
    OPEN = "open"
    LOCKED = "locked"
    CLOSED = "closed"
    ARCHIVED = "archived"


class PeriodClosureSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


@dataclass
class FiscalPeriod:
    period_id: UUID
    legal_entity_id: UUID
    fiscal_year: int
    period_number: int
    period_name: str
    start_date: datetime
    end_date: datetime
    status: PeriodStatus
    previous_period_id: UUID | None = None
    next_period_id: UUID | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    locked_at: datetime | None = None
    locked_by: str | None = None
    reopened_at: datetime | None = None
    reopened_by: str | None = None
    reopen_reason: str | None = None
    adjustment_journal_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.period_id}|{self.legal_entity_id}|{self.fiscal_year}|{self.period_number}|"
            f"{self.start_date.isoformat()}|{self.end_date.isoformat()}|{self.status.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def contains(self, date: datetime) -> bool:
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        start = self.start_date if self.start_date.tzinfo else self.start_date.replace(tzinfo=UTC)
        end = self.end_date if self.end_date.tzinfo else self.end_date.replace(tzinfo=UTC)
        return start <= date <= end

    def is_open_for_posting(self, allow_locked: bool = False) -> bool:
        if self.status == PeriodStatus.OPEN:
            return True
        if allow_locked and self.status == PeriodStatus.LOCKED:
            return True
        return False

    def is_closed(self) -> bool:
        return self.status == PeriodStatus.CLOSED

    def is_locked(self) -> bool:
        return self.status == PeriodStatus.LOCKED

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
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
        }


@dataclass
class PeriodClosureCheckResult:
    check_id: UUID
    period_id: UUID
    period_name: str
    legal_entity_id: UUID
    period_status: PeriodStatus
    transaction_date: datetime
    is_allowed: bool
    severity: PeriodClosureSeverity
    message: str
    requires_approval: bool = False
    approved_by: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.period_id}|{self.period_status.value}|"
            f"{self.is_allowed}|{self.severity.value}|{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "period_id": str(self.period_id),
            "period_name": self.period_name,
            "legal_entity_id": str(self.legal_entity_id),
            "period_status": self.period_status.value,
            "transaction_date": self.transaction_date.isoformat(),
            "is_allowed": self.is_allowed,
            "severity": self.severity.name,
            "message": self.message,
            "requires_approval": self.requires_approval,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================================
# BASE PERIOD CLOSURE ENFORCER (ABSTRACT)
# ============================================================================

class BasePeriodClosureEnforcer(ABC):
    """Base contract untuk Period Closure Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_allow_future_posting(self, allow: bool, max_days: int = 7) -> None:
        """Set future posting policy."""
        pass

    @abstractmethod
    async def check_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        transaction_date: datetime | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
    ) -> PeriodClosureCheckResult:
        """Check if period is open for posting."""
        pass

    @abstractmethod
    async def enforce_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> PeriodClosureCheckResult:
        """Enforce period open, raise violation if closed."""
        pass

    @abstractmethod
    async def enforce_period_sequence(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, PeriodClosureViolation | None]:
        """Enforce period sequence (previous period must be closed)."""
        pass

    @abstractmethod
    async def close_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        closed_by: str,
        adjustment_journal_id: UUID | None = None,
        force: bool = False,
    ) -> bool:
        """Close a period."""
        pass

    @abstractmethod
    async def lock_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        locked_by: str,
    ) -> bool:
        """Lock a period."""
        pass

    @abstractmethod
    async def reopen_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        reopened_by: str,
        reason: str,
        requires_dual_control: bool = True,
        approved_by: list[str] | None = None,
    ) -> bool:
        """Reopen a closed period."""
        pass

    @abstractmethod
    async def get_period_status_summary(
        self,
        fiscal_year: int,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        """Get status summary for fiscal year."""
        pass

    @abstractmethod
    async def get_current_open_period(
        self,
        legal_entity_id: UUID,
        date: datetime | None = None,
    ) -> FiscalPeriod | None:
        """Get current open period."""
        pass

    @abstractmethod
    async def get_last_closed_period(
        self,
        legal_entity_id: UUID,
    ) -> FiscalPeriod | None:
        """Get last closed period."""
        pass

    @abstractmethod
    def get_closure_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        period_id: UUID | None = None,
    ) -> list[PeriodClosureCheckResult]:
        """Get closure check history."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        period_id: UUID | None = None,
    ) -> list[PeriodClosureViolation]:
        """Get violation history."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset state."""
        pass

    # ==================== CHECKER METHODS ====================

    @abstractmethod
    def check(self, context: dict) -> list[str]:
        """Sync check method untuk compliance checker."""
        pass

    @abstractmethod
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        pass

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        pass

    @classmethod
    @abstractmethod
    def from_dict(cls, data: dict[str, Any]) -> BasePeriodClosureEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BasePeriodClosureEnforcer:
        """Clone instance."""
        pass

    @abstractmethod
    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        pass

    @abstractmethod
    def version(self) -> int:
        """Dapatkan versi."""
        pass

    @abstractmethod
    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        pass

    @abstractmethod
    def touch(self, touched_by: str) -> BasePeriodClosureEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# PERIOD CLOSURE ENFORCER (CONCRETE)
# ============================================================================

class PeriodClosureEnforcer(BasePeriodClosureEnforcer):
    """
    Enforcer untuk hukum period closure.

    Business context: Setelah periode ditutup, tidak ada transaksi yang
    boleh diposting ke periode tersebut. Ini menjaga integritas laporan
    keuangan antar periode.
    """

    def __init__(
        self,
        period_repository: Any | None = None,
        journal_repository: Any | None = None,
    ):
        self._period_repo = period_repository or _FallbackFiscalPeriodRepository()
        self._journal_repo = journal_repository or _FallbackJournalRepository()
        self._closure_history: list[PeriodClosureCheckResult] = []
        self._violation_history: list[PeriodClosureViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._allow_future_posting = False
        self._max_future_days = 7
        self._enabled = True
        # Entity fields
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        period_id = context.get("period_id")
        legal_entity_id = context.get("legal_entity_id")
        transaction_date = context.get("transaction_date")

        if not period_id:
            errors.append("period_id is required")
        else:
            try:
                UUID(str(period_id))
            except Exception:
                errors.append("period_id must be a valid UUID")
        if not legal_entity_id:
            errors.append("legal_entity_id is required")
        else:
            try:
                UUID(str(legal_entity_id))
            except Exception:
                errors.append("legal_entity_id must be a valid UUID")
        if transaction_date:
            try:
                if isinstance(transaction_date, str):
                    datetime.fromisoformat(transaction_date)
                elif not isinstance(transaction_date, datetime):
                    errors.append("transaction_date must be a datetime or ISO string")
            except ValueError:
                errors.append("transaction_date must be a valid ISO format date")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if self._max_future_days < 0:
            errors.append("max_future_days cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "allow_future_posting": self._allow_future_posting,
                "max_future_days": self._max_future_days,
                "max_history": self._max_history,
                "closure_history_count": len(self._closure_history),
                "violation_history_count": len(self._violation_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodClosureEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._allow_future_posting = data.get("allow_future_posting", False)
        instance._max_future_days = data.get("max_future_days", 7)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PeriodClosureEnforcer:
        """Clone instance."""
        new_instance = PeriodClosureEnforcer()
        new_instance._enabled = self._enabled
        new_instance._allow_future_posting = self._allow_future_posting
        new_instance._max_future_days = self._max_future_days
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "closure_history_count": len(self._closure_history),
                "violation_history_count": len(self._violation_history),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PeriodClosureEnforcer:
        """Touch instance (increment version)."""
        self._version += 1
        self._audit_trail.append({
            "action": "TOUCH",
            "performed_by": touched_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
        })
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append({
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self._version,
            "details": details,
        })

    # ==================== ORIGINAL BUSINESS METHODS ====================

    def enable(self, enabled: bool = True) -> None:
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Period closure enforcer enabled: {enabled}")

    def set_allow_future_posting(self, allow: bool, max_days: int = 7) -> None:
        self._allow_future_posting = allow
        self._max_future_days = max_days
        self._record_audit("SET_FUTURE_POSTING", "system", {"allow": allow, "max_days": max_days})
        logger.info(f"Future posting allowed: {allow}, max days: {max_days}")

    async def check_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        transaction_date: datetime | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
    ) -> PeriodClosureCheckResult:
        period_data = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period_data:
            return PeriodClosureCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name="UNKNOWN",
                legal_entity_id=legal_entity_id,
                period_status=PeriodStatus.CLOSED,
                transaction_date=transaction_date or datetime.now(UTC),
                is_allowed=False,
                severity=PeriodClosureSeverity.CRITICAL,
                message=f"Period {period_id} not found",
                cryptographic_hash="",
            )

        period = FiscalPeriod(
            period_id=period_data["period_id"],
            legal_entity_id=period_data["legal_entity_id"],
            fiscal_year=period_data.get("fiscal_year", 0),
            period_number=period_data.get("period_number", 0),
            period_name=period_data.get("period_name", "UNKNOWN"),
            start_date=period_data.get("start_date", datetime.now(UTC)),
            end_date=period_data.get("end_date", datetime.now(UTC)),
            status=PeriodStatus(period_data.get("status", "CLOSED")),
            previous_period_id=period_data.get("previous_period_id"),
            next_period_id=period_data.get("next_period_id"),
            closed_at=period_data.get("closed_at"),
            closed_by=period_data.get("closed_by"),
            locked_at=period_data.get("locked_at"),
            locked_by=period_data.get("locked_by"),
        )

        tx_date = transaction_date or datetime.now(UTC)
        if tx_date.tzinfo is None:
            tx_date = tx_date.replace(tzinfo=UTC)

        now = datetime.now(UTC)
        if tx_date > now:
            if not self._allow_future_posting:
                return PeriodClosureCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodClosureSeverity.MEDIUM,
                    message="Future posting is disabled",
                )
            days_future = (tx_date - now).days
            if days_future > self._max_future_days:
                return PeriodClosureCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodClosureSeverity.MEDIUM,
                    message=f"Future posting exceeds {self._max_future_days} days",
                )

        if not period.contains(tx_date):
            return PeriodClosureCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodClosureSeverity.HIGH,
                message=(
                    f"Transaction date {tx_date.date()} outside period "
                    f"{period.start_date.date()} - {period.end_date.date()}"
                ),
            )

        if period.status == PeriodStatus.CLOSED:
            return PeriodClosureCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodClosureSeverity.CRITICAL,
                message=f"Period {period.period_name} is CLOSED. Cannot post new transactions.",
            )

        if period.status == PeriodStatus.LOCKED:
            if not allow_locked:
                return PeriodClosureCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodClosureSeverity.HIGH,
                    message=f"Period {period.period_name} is LOCKED. Only adjustments allowed.",
                )
            if require_approval and (not approved_by or len(approved_by) < 2):
                return PeriodClosureCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodClosureSeverity.HIGH,
                    message=(
                        f"Period {period.period_name} is LOCKED and requires 2 approvals for adjustment."
                    ),
                    requires_approval=True,
                )

        if period.status == PeriodStatus.FUTURE:
            return PeriodClosureCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodClosureSeverity.MEDIUM,
                message=f"Period {period.period_name} is FUTURE. Cannot post before period start.",
            )

        return PeriodClosureCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name=period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=period.status,
            transaction_date=tx_date,
            is_allowed=True,
            severity=PeriodClosureSeverity.INFO,
            message=f"Period {period.period_name} is open for posting",
        )

    async def enforce_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        raise_on_violation: bool = True,
    ) -> PeriodClosureCheckResult:
        if not self._enabled:
            return PeriodClosureCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name="UNKNOWN",
                legal_entity_id=legal_entity_id,
                period_status=PeriodStatus.OPEN,
                transaction_date=transaction_date or datetime.now(UTC),
                is_allowed=True,
                severity=PeriodClosureSeverity.INFO,
                message="Period closure enforcer disabled",
            )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        result = await self.check_period_open(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            transaction_date=transaction_date,
            allow_locked=allow_locked,
            require_approval=require_approval,
            approved_by=approved_by,
        )

        with self._lock:
            self._closure_history.append(result)
            if len(self._closure_history) > self._max_history:
                self._closure_history = self._closure_history[-self._max_history :]

        if not result.is_allowed and raise_on_violation:
            violation = PeriodClosureViolation(
                message=result.message,
                period_id=str(period_id),
                period_name=result.period_name,
                severity=LawViolationSeverity.CRITICAL,
                details=result.to_dict(),
            )
            with self._lock:
                self._violation_history.append(violation)
                self._record_audit("VIOLATION", user_id, {"period_id": str(period_id)})
            raise violation

        return result

    async def enforce_period_sequence(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, PeriodClosureViolation | None]:
        if not self._enabled:
            return True, None

        period_data = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period_data:
            return True, None

        period = FiscalPeriod(
            period_id=period_data["period_id"],
            legal_entity_id=period_data["legal_entity_id"],
            fiscal_year=period_data.get("fiscal_year", 0),
            period_number=period_data.get("period_number", 0),
            period_name=period_data.get("period_name", "UNKNOWN"),
            start_date=period_data.get("start_date", datetime.now(UTC)),
            end_date=period_data.get("end_date", datetime.now(UTC)),
            status=PeriodStatus(period_data.get("status", "OPEN")),
            previous_period_id=period_data.get("previous_period_id"),
        )

        if period.previous_period_id:
            prev_data = await self._period_repo.get_by_id(
                period.previous_period_id, legal_entity_id
            )
            if prev_data:
                prev_status = PeriodStatus(prev_data.get("status", "OPEN"))
                if prev_status != PeriodStatus.CLOSED:
                    violation = PeriodClosureViolation(
                        message=(
                            f"Cannot close period {period.period_name}. "
                            f"Previous period {prev_data.get('period_name', 'UNKNOWN')} is not closed."
                        ),
                        period_id=str(period_id),
                        period_name=period.period_name,
                        severity=LawViolationSeverity.HIGH,
                        details={
                            "current_period": period.period_name,
                            "previous_period": prev_data.get("period_name"),
                            "previous_period_status": prev_status.value,
                        },
                    )
                    if raise_on_violation:
                        self._record_audit("SEQUENCE_VIOLATION", user_id or "system", {
                            "period_id": str(period_id),
                        })
                        raise violation
                    return False, violation

        return True, None

    async def close_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        closed_by: str,
        adjustment_journal_id: UUID | None = None,
        force: bool = False,
    ) -> bool:
        if not self._enabled:
            logger.warning("Period closure enforcer disabled, cannot close period")
            return False

        is_valid, violation = await self.enforce_period_sequence(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            user_id=closed_by,
            raise_on_violation=False,
        )
        if not is_valid and violation:
            logger.error(f"Period closure blocked: {violation.message}")
            return False

        pending = await self._journal_repo.get_pending_by_period(period_id, legal_entity_id)
        if pending and not force:
            logger.warning(
                f"Period {period_id} has {len(pending)} pending journals before closing. "
                f"Use force=True to override."
            )
            return False

        success = await self._period_repo.update_status(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            new_status=PeriodStatus.CLOSED.value,
            closed_by=closed_by,
            closed_at=datetime.now(UTC),
            adjustment_journal_id=adjustment_journal_id,
        )

        if success:
            self._record_audit("CLOSE_PERIOD", closed_by, {"period_id": str(period_id)})
            logger.info(f"Period {period_id} closed by {closed_by}")

        return success

    async def lock_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        locked_by: str,
    ) -> bool:
        if not self._enabled:
            return False

        period_data = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period_data:
            return False

        if period_data.get("status") == PeriodStatus.CLOSED.value:
            logger.warning(f"Cannot lock a closed period {period_id}")
            return False

        success = await self._period_repo.update_status(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            new_status=PeriodStatus.LOCKED.value,
            locked_by=locked_by,
            locked_at=datetime.now(UTC),
        )

        if success:
            self._record_audit("LOCK_PERIOD", locked_by, {"period_id": str(period_id)})
            logger.info(f"Period {period_id} locked by {locked_by}")

        return success

    async def reopen_period(
        self,
        period_id: UUID,
        legal_entity_id: UUID,
        reopened_by: str,
        reason: str,
        requires_dual_control: bool = True,
        approved_by: list[str] | None = None,
    ) -> bool:
        if not self._enabled:
            return False

        period_data = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period_data:
            return False

        if period_data.get("status") != PeriodStatus.CLOSED.value:
            logger.warning(
                f"Period {period_id} is not closed (status: {period_data.get('status')})"
            )
            return False

        if requires_dual_control:
            if not approved_by or len(approved_by) < 2:
                logger.error(f"Reopen of period {period_id} requires at least 2 approvals")
                return False
            logger.info(
                f"Dual control reopen of period {period_id} by {reopened_by}, approved by {approved_by}"
            )

        success = await self._period_repo.update_status(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            new_status=PeriodStatus.OPEN.value,
            reopened_by=reopened_by,
            reopened_at=datetime.now(UTC),
            reopen_reason=reason,
        )

        if success:
            self._record_audit("REOPEN_PERIOD", reopened_by, {
                "period_id": str(period_id),
                "reason": reason,
            })
            logger.warning(f"Period {period_id} REOPENED by {reopened_by}. Reason: {reason}")

        return success

    async def get_period_status_summary(
        self,
        fiscal_year: int,
        legal_entity_id: UUID,
    ) -> dict[str, Any]:
        periods_data = await self._period_repo.get_by_fiscal_year(fiscal_year, legal_entity_id)

        periods = []
        for p in periods_data:
            periods.append(
                {
                    "period_number": p.get("period_number"),
                    "period_name": p.get("period_name"),
                    "status": p.get("status"),
                    "start_date": p.get("start_date").isoformat() if p.get("start_date") else None,
                    "end_date": p.get("end_date").isoformat() if p.get("end_date") else None,
                    "closed_at": p.get("closed_at").isoformat() if p.get("closed_at") else None,
                    "closed_by": p.get("closed_by"),
                    "locked_at": p.get("locked_at").isoformat() if p.get("locked_at") else None,
                    "locked_by": p.get("locked_by"),
                }
            )

        return {
            "fiscal_year": fiscal_year,
            "legal_entity_id": str(legal_entity_id),
            "periods": periods,
            "total_periods": len(periods),
            "closed_periods": len([p for p in periods if p["status"] == PeriodStatus.CLOSED.value]),
            "open_periods": len([p for p in periods if p["status"] == PeriodStatus.OPEN.value]),
            "locked_periods": len([p for p in periods if p["status"] == PeriodStatus.LOCKED.value]),
        }

    async def get_current_open_period(
        self,
        legal_entity_id: UUID,
        date: datetime | None = None,
    ) -> FiscalPeriod | None:
        period_data = await self._period_repo.get_current_period(legal_entity_id, date)
        if not period_data:
            return None

        return FiscalPeriod(
            period_id=period_data["period_id"],
            legal_entity_id=period_data["legal_entity_id"],
            fiscal_year=period_data.get("fiscal_year", 0),
            period_number=period_data.get("period_number", 0),
            period_name=period_data.get("period_name", "UNKNOWN"),
            start_date=period_data.get("start_date", datetime.now(UTC)),
            end_date=period_data.get("end_date", datetime.now(UTC)),
            status=PeriodStatus(period_data.get("status", "OPEN")),
        )

    async def get_last_closed_period(
        self,
        legal_entity_id: UUID,
    ) -> FiscalPeriod | None:
        period_data = await self._period_repo.get_last_closed_period(legal_entity_id)
        if not period_data:
            return None
        return FiscalPeriod(
            period_id=period_data["period_id"],
            legal_entity_id=period_data["legal_entity_id"],
            fiscal_year=period_data.get("fiscal_year", 0),
            period_number=period_data.get("period_number", 0),
            period_name=period_data.get("period_name", "UNKNOWN"),
            start_date=period_data.get("start_date", datetime.now(UTC)),
            end_date=period_data.get("end_date", datetime.now(UTC)),
            status=PeriodStatus(period_data.get("status", "CLOSED")),
            closed_at=period_data.get("closed_at"),
            closed_by=period_data.get("closed_by"),
        )

    def get_closure_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        period_id: UUID | None = None,
    ) -> list[PeriodClosureCheckResult]:
        with self._lock:
            results = self._closure_history[-limit:]
        if only_violations:
            results = [r for r in results if not r.is_allowed]
        if period_id:
            results = [r for r in results if r.period_id == period_id]
        return results

    def get_violations(
        self,
        limit: int = 100,
        period_id: UUID | None = None,
    ) -> list[PeriodClosureViolation]:
        with self._lock:
            result = self._violation_history[-limit:]
        if period_id:
            result = [v for v in result if v.period_id == str(period_id)]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_checks = len(self._closure_history)
            total_violations = len(self._violation_history)
            if total_checks == 0:
                return {
                    "total_checks": 0,
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "version": self._version,
                }

            allowed = len([r for r in self._closure_history if r.is_allowed])
            blocked = total_checks - allowed

            by_severity = {}
            for r in self._closure_history:
                if not r.is_allowed:
                    sev = r.severity.name
                    by_severity[sev] = by_severity.get(sev, 0) + 1

            return {
                "total_checks": total_checks,
                "total_violations": total_violations,
                "allowed_count": allowed,
                "blocked_count": blocked,
                "allow_rate": allowed / total_checks if total_checks > 0 else 0,
                "by_severity": by_severity,
                "allow_future_posting": self._allow_future_posting,
                "max_future_days": self._max_future_days,
                "enabled": self._enabled,
                "version": self._version,
                "latest_check": self._closure_history[-1].timestamp.isoformat()
                if self._closure_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._closure_history = []
            self._violation_history = []
            self._enabled = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._period_repo, "clear"):
                self._period_repo.clear()
            if hasattr(self._journal_repo, "clear"):
                self._journal_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_period_closure_enforcer_instance: PeriodClosureEnforcer | None = None
_lock_instance = threading.Lock()


def get_period_closure_enforcer() -> PeriodClosureEnforcer:
    global _period_closure_enforcer_instance
    if _period_closure_enforcer_instance is None:
        with _lock_instance:
            if _period_closure_enforcer_instance is None:
                _period_closure_enforcer_instance = PeriodClosureEnforcer()
    return _period_closure_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "FiscalPeriod",
    "PeriodClosureCheckResult",
    "PeriodClosureEnforcer",
    "PeriodClosureSeverity",
    "PeriodStatus",
    "get_period_closure_enforcer",
]
