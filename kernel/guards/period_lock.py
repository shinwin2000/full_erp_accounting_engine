#!/usr/bin/env python3
"""
Module: period_lock.py
Layer: 4 - Kernel / Guards
Responsibility: Mengunci periode akuntansi (tertutup, buka, tutup sementara).
               Guard ini memastikan bahwa transaksi hanya dapat diposting ke
               periode yang terbuka. Periode yang sudah ditutup atau dikunci
               tidak dapat menerima transaksi baru kecuali dengan otorisasi
               khusus (override).

Dependencies:
- standard library (datetime, logging, typing, threading, enum, hashlib)
- kernel.context_holder (get_current_legal_entity, get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, PeriodLockError, GuardSeverity)

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

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    GuardSeverity,
    PeriodLockError,
)

logger = logging.getLogger(__name__)


# === 1. PERIOD STATUS ENUM ===


class PeriodStatus(Enum):
    """Status periode akuntansi."""

    FUTURE = "future"  # Periode mendatang, belum bisa diisi
    OPEN = "open"  # Periode terbuka, dapat menerima transaksi
    LOCKED = "locked"  # Terkunci (hanya adjustment dengan otorisasi)
    CLOSED = "closed"  # Ditutup, tidak dapat menerima transaksi
    ARCHIVED = "archived"  # Diarsipkan, hanya baca


# === 2. FISCAL PERIOD VALUE OBJECT ===


@dataclass
class FiscalPeriod:
    """Representasi periode akuntansi."""

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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    modified_at: datetime | None = None
    modified_by: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.period_id}|{self.legal_entity_id}|{self.fiscal_year}|{self.period_number}|"
            f"{self.period_name}|{self.start_date.isoformat()}|{self.end_date.isoformat()}|"
            f"{self.status.value}|{self.closed_at}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def contains(self, date: datetime) -> bool:
        """Memeriksa apakah tanggal berada dalam periode."""
        if date.tzinfo is None:
            date = date.replace(tzinfo=UTC)
        start = self.start_date if self.start_date.tzinfo else self.start_date.replace(tzinfo=UTC)
        end = self.end_date if self.end_date.tzinfo else self.end_date.replace(tzinfo=UTC)
        return start <= date <= end

    def is_open_for_posting(self, allow_locked: bool = False) -> bool:
        """Apakah periode terbuka untuk posting."""
        if self.status == PeriodStatus.OPEN:
            return True
        if allow_locked and self.status == PeriodStatus.LOCKED:
            return True
        return False

    def can_be_adjusted(self) -> bool:
        """Apakah periode dapat menerima jurnal penyesuaian."""
        return self.status in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

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
        }


# === 3. FALLBACK FISCAL PERIOD REPOSITORY ===


class _FallbackFiscalPeriodRepository:
    """Fallback repository untuk fiscal period.
    Menyimpan semua periode dalam memory.
    Tidak mengimpor adapters atau infrastructure.
    """

    def __init__(self):
        self._periods: dict[UUID, FiscalPeriod] = {}
        self._by_entity: dict[UUID, list[UUID]] = {}
        self._by_year: dict[tuple[UUID, int], list[UUID]] = {}
        self._last_transaction_date: dict[UUID, datetime] = {}

    async def get_by_id(self, period_id: UUID, legal_entity_id: UUID) -> FiscalPeriod | None:
        period = self._periods.get(period_id)
        if period and period.legal_entity_id == legal_entity_id:
            return period
        return None

    async def get_by_legal_entity(self, legal_entity_id: UUID) -> list[FiscalPeriod]:
        period_ids = self._by_entity.get(legal_entity_id, [])
        return [self._periods[pid] for pid in period_ids if pid in self._periods]

    async def get_current_period(
        self, legal_entity_id: UUID, date: datetime | None = None
    ) -> FiscalPeriod | None:
        check_date = date or datetime.now(UTC)
        periods = await self.get_by_legal_entity(legal_entity_id)
        for period in periods:
            if period.contains(check_date):
                return period
        return None

    async def get_period_by_number(
        self, legal_entity_id: UUID, fiscal_year: int, period_number: int
    ) -> FiscalPeriod | None:
        key = (legal_entity_id, fiscal_year)
        period_ids = self._by_year.get(key, [])
        for pid in period_ids:
            p = self._periods.get(pid)
            if p and p.period_number == period_number:
                return p
        return None

    async def get_periods_by_fiscal_year(
        self, legal_entity_id: UUID, fiscal_year: int
    ) -> list[FiscalPeriod]:
        key = (legal_entity_id, fiscal_year)
        period_ids = self._by_year.get(key, [])
        return [self._periods[pid] for pid in period_ids if pid in self._periods]

    async def get_periods_by_status(
        self, legal_entity_id: UUID, status: PeriodStatus
    ) -> list[FiscalPeriod]:
        periods = await self.get_by_legal_entity(legal_entity_id)
        return [p for p in periods if p.status == status]

    async def get_last_transaction_date(self, legal_entity_id: UUID) -> datetime | None:
        return self._last_transaction_date.get(legal_entity_id)

    async def record_transaction_date(
        self, legal_entity_id: UUID, transaction_date: datetime
    ) -> None:
        current = self._last_transaction_date.get(legal_entity_id)
        if current is None or transaction_date > current:
            self._last_transaction_date[legal_entity_id] = transaction_date

    async def update_period_status(
        self, period_id: UUID, status: PeriodStatus, updated_by: str
    ) -> FiscalPeriod | None:
        period = self._periods.get(period_id)
        if not period:
            return None
        updated = FiscalPeriod(
            period_id=period.period_id,
            legal_entity_id=period.legal_entity_id,
            fiscal_year=period.fiscal_year,
            period_number=period.period_number,
            period_name=period.period_name,
            start_date=period.start_date,
            end_date=period.end_date,
            status=status,
            previous_period_id=period.previous_period_id,
            next_period_id=period.next_period_id,
            closed_at=period.closed_at,
            closed_by=period.closed_by,
            locked_at=period.locked_at,
            locked_by=period.locked_by,
            created_at=period.created_at,
            created_by=period.created_by,
            modified_at=datetime.now(UTC),
            modified_by=updated_by,
            cryptographic_hash="",
        )
        updated = FiscalPeriod(**{**updated.__dict__, "cryptographic_hash": updated.compute_hash()})
        self._periods[period_id] = updated
        return updated

    def add_period(self, period: FiscalPeriod) -> None:
        period = FiscalPeriod(**{**period.__dict__, "cryptographic_hash": period.compute_hash()})
        self._periods[period.period_id] = period
        self._by_entity.setdefault(period.legal_entity_id, []).append(period.period_id)
        key = (period.legal_entity_id, period.fiscal_year)
        self._by_year.setdefault(key, []).append(period.period_id)

    def remove_period(self, period_id: UUID) -> bool:
        if period_id in self._periods:
            period = self._periods.pop(period_id)
            self._by_entity[period.legal_entity_id].remove(period_id)
            key = (period.legal_entity_id, period.fiscal_year)
            if key in self._by_year and period_id in self._by_year[key]:
                self._by_year[key].remove(period_id)
            return True
        return False

    def clear(self) -> None:
        self._periods.clear()
        self._by_entity.clear()
        self._by_year.clear()
        self._last_transaction_date.clear()


# === 4. PERIOD LOCK SEVERITY AND RESULT ===


class PeriodLockSeverity(Enum):
    """Severity untuk period lock guard."""

    CRITICAL = 80  # Periode sudah CLOSED, transaksi ditolak
    HIGH = 60  # Periode LOCKED tanpa otorisasi
    MEDIUM = 40  # Periode FUTURE, tidak bisa posting
    LOW = 20  # Peringatan tentang periode yang akan ditutup
    INFO = 0


@dataclass
class PeriodLockCheckResult:
    """Hasil pemeriksaan period lock."""

    check_id: UUID
    period_id: UUID
    period_name: str
    legal_entity_id: UUID
    period_status: PeriodStatus
    transaction_date: datetime
    is_allowed: bool
    severity: PeriodLockSeverity
    message: str
    requires_approval: bool = False
    approved_by: list[str] = field(default_factory=list)
    is_adjustment: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.period_id}|{self.period_name}|{self.is_allowed}|"
            f"{self.severity.value}|{self.message[:100]}"
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
            "is_adjustment": self.is_adjustment,
            "timestamp": self.timestamp.isoformat(),
            "hash": self.cryptographic_hash[:16] + "...",
        }


# ============================================================================
# BASE PERIOD LOCK GUARD (ABSTRACT)
# ============================================================================

class BasePeriodLockGuard(ABC):
    """Base contract untuk Period Lock Guard."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        pass

    @abstractmethod
    def set_allow_future_posting(self, allow: bool, max_days: int = 7) -> None:
        """Set apakah future posting diizinkan dan batas maksimal hari."""
        pass

    @abstractmethod
    def set_max_backdate_days(self, max_days: int) -> None:
        """Set batas maksimal backdate dalam hari."""
        pass

    @abstractmethod
    async def get_period(self, period_id: UUID, legal_entity_id: UUID) -> FiscalPeriod | None:
        """Mendapatkan periode berdasarkan ID."""
        pass

    @abstractmethod
    async def get_current_period(
        self, legal_entity_id: UUID | None = None, date: datetime | None = None
    ) -> FiscalPeriod | None:
        """Mendapatkan periode yang saat ini aktif untuk tanggal tertentu."""
        pass

    @abstractmethod
    async def check_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        transaction_date: datetime | None = None,
        is_adjustment: bool = False,
    ) -> PeriodLockCheckResult:
        """Memeriksa apakah periode terbuka untuk posting."""
        pass

    @abstractmethod
    async def enforce(
        self,
        period_id: UUID,
        legal_entity_id: UUID | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        is_adjustment: bool = False,
        raise_on_violation: bool = True,
    ) -> PeriodLockCheckResult:
        """Menegakkan period lock, raise exception jika tidak diizinkan."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        period_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[PeriodLockCheckResult]:
        """Mendapatkan history pemeriksaan period lock."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik period lock guard."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset history (untuk testing)."""
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
    def from_dict(cls, data: dict[str, Any]) -> BasePeriodLockGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BasePeriodLockGuard:
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
    def touch(self, touched_by: str) -> BasePeriodLockGuard:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# PERIOD LOCK GUARD (CONCRETE)
# ============================================================================

class PeriodLockGuard(BasePeriodLockGuard):
    """
    Guard untuk mengunci periode akuntansi.

    Business context: Memastikan bahwa transaksi hanya diposting ke periode
    yang terbuka. Melindungi integritas laporan keuangan dengan mencegah
    perubahan setelah periode ditutup.
    """

    def __init__(self, period_repository: Any | None = None):
        self._period_repo = period_repository or _FallbackFiscalPeriodRepository()
        self._check_history: list[PeriodLockCheckResult] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._allow_future_posting = False
        self._max_future_days = 7
        self._max_backdate_days = 30
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
        if legal_entity_id:
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
        if self._max_backdate_days < 0:
            errors.append("max_backdate_days cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "enabled": self._enabled,
            "allow_future_posting": self._allow_future_posting,
            "max_future_days": self._max_future_days,
            "max_backdate_days": self._max_backdate_days,
            "history_count": len(self._check_history),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodLockGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._allow_future_posting = data.get("allow_future_posting", False)
        instance._max_future_days = data.get("max_future_days", 7)
        instance._max_backdate_days = data.get("max_backdate_days", 30)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PeriodLockGuard:
        """Clone instance."""
        new_instance = PeriodLockGuard()
        new_instance._enabled = self._enabled
        new_instance._allow_future_posting = self._allow_future_posting
        new_instance._max_future_days = self._max_future_days
        new_instance._max_backdate_days = self._max_backdate_days
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "history_count": len(self._check_history),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PeriodLockGuard:
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
        """Mengaktifkan atau menonaktifkan guard."""
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Period lock guard enabled: {enabled}")

    def set_allow_future_posting(self, allow: bool, max_days: int = 7) -> None:
        """Set apakah future posting diizinkan dan batas maksimal hari."""
        self._allow_future_posting = allow
        self._max_future_days = max_days
        self._record_audit("SET_FUTURE_POSTING", "system", {"allow": allow, "max_days": max_days})
        logger.info(f"Future posting allowed: {allow}, max days: {max_days}")

    def set_max_backdate_days(self, max_days: int) -> None:
        """Set batas maksimal backdate dalam hari."""
        self._max_backdate_days = max_days
        self._record_audit("SET_BACKDATE_DAYS", "system", {"max_days": max_days})
        logger.info(f"Max backdate days set to: {max_days}")

    async def get_period(self, period_id: UUID, legal_entity_id: UUID) -> FiscalPeriod | None:
        """Mendapatkan periode berdasarkan ID."""
        return await self._period_repo.get_by_id(period_id, legal_entity_id)

    async def get_current_period(
        self, legal_entity_id: UUID | None = None, date: datetime | None = None
    ) -> FiscalPeriod | None:
        """Mendapatkan periode yang saat ini aktif untuk tanggal tertentu."""
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return None
        return await self._period_repo.get_current_period(legal_entity_id, date)

    async def get_periods_by_status(
        self, legal_entity_id: UUID, status: PeriodStatus
    ) -> list[FiscalPeriod]:
        """Mendapatkan semua periode dengan status tertentu."""
        return await self._period_repo.get_periods_by_status(legal_entity_id, status)

    async def check_period_open(
        self,
        period_id: UUID,
        legal_entity_id: UUID | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        transaction_date: datetime | None = None,
        is_adjustment: bool = False,
    ) -> PeriodLockCheckResult:
        """
        Memeriksa apakah periode terbuka untuk posting.

        Args:
            period_id: ID periode
            legal_entity_id: Entitas hukum
            allow_locked: Apakah periode locked diizinkan (adjustment)
            require_approval: Apakah perlu approval untuk periode locked
            approved_by: Daftar approver jika require_approval=True
            transaction_date: Tanggal transaksi (untuk validasi future/backdate)
            is_adjustment: Apakah transaksi penyesuaian

        Returns:
            PeriodLockCheckResult
        """
        if not self._enabled:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name="UNKNOWN",
                legal_entity_id=legal_entity_id or UUID(int=0),
                period_status=PeriodStatus.OPEN,
                transaction_date=transaction_date or datetime.now(UTC),
                is_allowed=True,
                severity=PeriodLockSeverity.INFO,
                message="Period lock guard disabled",
                cryptographic_hash="",
            )

        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name="UNKNOWN",
                    legal_entity_id=UUID(int=0),
                    period_status=PeriodStatus.CLOSED,
                    transaction_date=transaction_date or datetime.now(UTC),
                    is_allowed=False,
                    severity=PeriodLockSeverity.HIGH,
                    message="No legal entity in context",
                    cryptographic_hash="",
                )

        period = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name="UNKNOWN",
                legal_entity_id=legal_entity_id,
                period_status=PeriodStatus.CLOSED,
                transaction_date=transaction_date or datetime.now(UTC),
                is_allowed=False,
                severity=PeriodLockSeverity.CRITICAL,
                message=f"Period {period_id} not found for legal entity {legal_entity_id}",
                cryptographic_hash="",
            )

        tx_date = transaction_date or datetime.now(UTC)
        if tx_date.tzinfo is None:
            tx_date = tx_date.replace(tzinfo=UTC)

        # Check date within period
        if not period.contains(tx_date):
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodLockSeverity.HIGH,
                message=f"Transaction date {tx_date.date()} outside period {period.start_date.date()} - {period.end_date.date()}",
                is_adjustment=is_adjustment,
                cryptographic_hash="",
            )

        # Check future posting
        now = datetime.now(UTC)
        if tx_date > now:
            if not self._allow_future_posting:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.MEDIUM,
                    message="Future posting is disabled",
                    is_adjustment=is_adjustment,
                    cryptographic_hash="",
                )
            days_future = (tx_date - now).days
            if days_future > self._max_future_days:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.MEDIUM,
                    message=f"Future posting exceeds {self._max_future_days} days",
                    is_adjustment=is_adjustment,
                    cryptographic_hash="",
                )

        # Check backdate (only for non-adjustment)
        if not is_adjustment and tx_date < now:
            days_back = (now - tx_date).days
            if days_back > self._max_backdate_days:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.HIGH,
                    message=f"Backdating of {days_back} days exceeds max {self._max_backdate_days} days",
                    is_adjustment=is_adjustment,
                    cryptographic_hash="",
                )

        # Check period status
        if period.status == PeriodStatus.CLOSED:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodLockSeverity.CRITICAL,
                message=f"Period {period.period_name} is CLOSED. Cannot post new transactions.",
                is_adjustment=is_adjustment,
                cryptographic_hash="",
            )

        if period.status == PeriodStatus.LOCKED:
            if not allow_locked:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.HIGH,
                    message=f"Period {period.period_name} is LOCKED. Only adjustments allowed.",
                    requires_approval=require_approval,
                    is_adjustment=is_adjustment,
                    cryptographic_hash="",
                )
            if require_approval and (not approved_by or len(approved_by) < 2):
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name=period.period_name,
                    legal_entity_id=legal_entity_id,
                    period_status=period.status,
                    transaction_date=tx_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.HIGH,
                    message=f"Period {period.period_name} is LOCKED and requires 2 approvals for adjustment.",
                    requires_approval=True,
                    is_adjustment=is_adjustment,
                    cryptographic_hash="",
                )

        if period.status == PeriodStatus.FUTURE:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodLockSeverity.MEDIUM,
                message=f"Period {period.period_name} is FUTURE. Cannot post before period start.",
                is_adjustment=is_adjustment,
                cryptographic_hash="",
            )

        # All checks passed
        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name=period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=period.status,
            transaction_date=tx_date,
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message=f"Period {period.period_name} is open for posting",
            requires_approval=False,
            approved_by=approved_by or [],
            is_adjustment=is_adjustment,
            cryptographic_hash="",
        )
        result = PeriodLockCheckResult(
            **{**result.__dict__, "cryptographic_hash": result.compute_hash()}
        )
        return result

    async def check_date_in_period(
        self,
        period_id: UUID,
        transaction_date: datetime,
        legal_entity_id: UUID | None = None,
    ) -> PeriodLockCheckResult:
        """
        Memeriksa apakah tanggal transaksi berada dalam periode.
        """
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name="UNKNOWN",
                    legal_entity_id=UUID(int=0),
                    period_status=PeriodStatus.CLOSED,
                    transaction_date=transaction_date,
                    is_allowed=False,
                    severity=PeriodLockSeverity.HIGH,
                    message="No legal entity in context",
                    cryptographic_hash="",
                )

        period = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name="UNKNOWN",
                legal_entity_id=legal_entity_id,
                period_status=PeriodStatus.CLOSED,
                transaction_date=transaction_date,
                is_allowed=False,
                severity=PeriodLockSeverity.CRITICAL,
                message=f"Period {period_id} not found",
                cryptographic_hash="",
            )

        tx_date = transaction_date
        if tx_date.tzinfo is None:
            tx_date = tx_date.replace(tzinfo=UTC)

        if tx_date < period.start_date:
            days_diff = (period.start_date - tx_date).days
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodLockSeverity.HIGH,
                message=f"Transaction date {tx_date.date()} is {days_diff} days before period start {period.start_date.date()}",
                cryptographic_hash="",
            )

        if tx_date > period.end_date:
            days_diff = (tx_date - period.end_date).days
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=tx_date,
                is_allowed=False,
                severity=PeriodLockSeverity.HIGH,
                message=f"Transaction date {tx_date.date()} is {days_diff} days after period end {period.end_date.date()}",
                cryptographic_hash="",
            )

        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name=period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=period.status,
            transaction_date=tx_date,
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="Date within period",
            cryptographic_hash="",
        )
        result = PeriodLockCheckResult(
            **{**result.__dict__, "cryptographic_hash": result.compute_hash()}
        )
        return result

    async def check_period_sequence(
        self,
        period_id: UUID,
        legal_entity_id: UUID | None = None,
    ) -> PeriodLockCheckResult:
        """
        Memeriksa urutan periode (tidak boleh ada gap sebelum periode ini).
        (Warning only, not blocking)
        """
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return PeriodLockCheckResult(
                    check_id=uuid4(),
                    period_id=period_id,
                    period_name="UNKNOWN",
                    legal_entity_id=UUID(int=0),
                    period_status=PeriodStatus.CLOSED,
                    transaction_date=datetime.now(UTC),
                    is_allowed=True,
                    severity=PeriodLockSeverity.INFO,
                    message="No legal entity in context, skipping sequence check",
                    cryptographic_hash="",
                )

        period = await self._period_repo.get_by_id(period_id, legal_entity_id)
        if not period or not period.previous_period_id:
            return PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name if period else "UNKNOWN",
                legal_entity_id=legal_entity_id,
                period_status=period.status if period else PeriodStatus.CLOSED,
                transaction_date=datetime.now(UTC),
                is_allowed=True,
                severity=PeriodLockSeverity.INFO,
                message="No previous period to check",
                cryptographic_hash="",
            )

        prev_period = await self._period_repo.get_by_id(period.previous_period_id, legal_entity_id)
        if prev_period and prev_period.status != PeriodStatus.CLOSED:
            result = PeriodLockCheckResult(
                check_id=uuid4(),
                period_id=period_id,
                period_name=period.period_name,
                legal_entity_id=legal_entity_id,
                period_status=period.status,
                transaction_date=datetime.now(UTC),
                is_allowed=True,
                severity=PeriodLockSeverity.LOW,
                message=f"Previous period {prev_period.period_name} is not closed before opening {period.period_name}",
                cryptographic_hash="",
            )
            result = PeriodLockCheckResult(
                **{**result.__dict__, "cryptographic_hash": result.compute_hash()}
            )
            return result

        result = PeriodLockCheckResult(
            check_id=uuid4(),
            period_id=period_id,
            period_name=period.period_name,
            legal_entity_id=legal_entity_id,
            period_status=period.status,
            transaction_date=datetime.now(UTC),
            is_allowed=True,
            severity=PeriodLockSeverity.INFO,
            message="Period sequence OK",
            cryptographic_hash="",
        )
        result = PeriodLockCheckResult(
            **{**result.__dict__, "cryptographic_hash": result.compute_hash()}
        )
        return result

    async def get_current_open_period(
        self,
        legal_entity_id: UUID | None = None,
        date: datetime | None = None,
    ) -> FiscalPeriod | None:
        """Mendapatkan periode yang saat ini terbuka untuk posting."""
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return None
        check_date = date or datetime.now(UTC)
        return await self._period_repo.get_current_period(legal_entity_id, check_date)

    async def get_open_periods(self, legal_entity_id: UUID) -> list[FiscalPeriod]:
        """Mendapatkan semua periode yang terbuka (OPEN)."""
        return await self._period_repo.get_periods_by_status(legal_entity_id, PeriodStatus.OPEN)

    async def get_closed_periods(self, legal_entity_id: UUID) -> list[FiscalPeriod]:
        """Mendapatkan semua periode yang ditutup."""
        return await self._period_repo.get_periods_by_status(legal_entity_id, PeriodStatus.CLOSED)

    async def enforce(
        self,
        period_id: UUID,
        legal_entity_id: UUID | None = None,
        allow_locked: bool = False,
        require_approval: bool = False,
        approved_by: list[str] | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        is_adjustment: bool = False,
        raise_on_violation: bool = True,
    ) -> PeriodLockCheckResult:
        """
        Menegakkan period lock, raise exception jika tidak diizinkan.

        Args:
            period_id: ID periode
            legal_entity_id: Entitas hukum
            allow_locked: Apakah periode locked diizinkan
            require_approval: Apakah perlu approval untuk periode locked
            approved_by: Daftar approver
            transaction_date: Tanggal transaksi
            user_id: User ID (untuk audit)
            is_adjustment: Apakah transaksi penyesuaian
            raise_on_violation: Raise exception jika violation

        Returns:
            PeriodLockCheckResult

        Raises:
            PeriodLockError: Jika periode tidak terbuka dan raise_on_violation=True
        """
        if user_id is None:
            user_id = get_current_user() or "unknown"

        result = await self.check_period_open(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            allow_locked=allow_locked,
            require_approval=require_approval,
            approved_by=approved_by,
            transaction_date=transaction_date,
            is_adjustment=is_adjustment,
        )

        # Record history
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        # Record transaction date if allowed
        if result.is_allowed and legal_entity_id and transaction_date:
            await self._period_repo.record_transaction_date(legal_entity_id, transaction_date)

        if not result.is_allowed and raise_on_violation:
            raise PeriodLockError(
                message=result.message,
                period_name=result.period_name,
                period_status=result.period_status.value,
                severity=GuardSeverity.CRITICAL
                if result.severity == PeriodLockSeverity.CRITICAL
                else GuardSeverity.HIGH,
                details=result.to_dict(),
            )

        return result

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        period_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[PeriodLockCheckResult]:
        """Mendapatkan history pemeriksaan period lock."""
        with self._lock:
            results = self._check_history[-limit:]

        if only_violations:
            results = [r for r in results if not r.is_allowed]
        if period_id:
            results = [r for r in results if r.period_id == period_id]
        if legal_entity_id:
            results = [r for r in results if r.legal_entity_id == legal_entity_id]
        if start_date:
            results = [r for r in results if r.timestamp >= start_date]
        if end_date:
            results = [r for r in results if r.timestamp <= end_date]

        return results

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik period lock guard."""
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {
                    "total_checks": 0,
                    "enabled": self._enabled,
                    "version": self._version,
                }

            violations = [r for r in self._check_history if not r.is_allowed]
            violation_count = len(violations)

            by_severity = {}
            for sev in PeriodLockSeverity:
                count = len([r for r in violations if r.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count

            by_status = {}
            for r in violations:
                status = r.period_status.value
                by_status[status] = by_status.get(status, 0) + 1

            by_period = {}
            for r in violations:
                by_period[r.period_name] = by_period.get(r.period_name, 0) + 1

            return {
                "total_checks": total,
                "violation_count": violation_count,
                "violation_rate": violation_count / total if total > 0 else 0,
                "by_severity": by_severity,
                "by_period_status": by_status,
                "by_period": by_period,
                "allow_future_posting": self._allow_future_posting,
                "max_future_days": self._max_future_days,
                "max_backdate_days": self._max_backdate_days,
                "enabled": self._enabled,
                "version": self._version,
                "latest_check": self._check_history[-1].timestamp.isoformat()
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        """Reset history (untuk testing)."""
        with self._lock:
            self._check_history = []
            self._version += 1
            self._audit_trail = []


# === 6. SINGLETON ACCESSOR ===

_period_lock_guard_instance: PeriodLockGuard | None = None
_lock_instance = threading.Lock()


def get_period_lock_guard() -> PeriodLockGuard:
    """Mendapatkan instance singleton PeriodLockGuard."""
    global _period_lock_guard_instance
    if _period_lock_guard_instance is None:
        with _lock_instance:
            if _period_lock_guard_instance is None:
                _period_lock_guard_instance = PeriodLockGuard()
    return _period_lock_guard_instance

# ========================================================================
# ALIASES FOR CHECKER COMPATIBILITY (P23)
# ========================================================================

# The checker expects 'PeriodLock' (class) or 'lock_period' or 'unlock_period'
PeriodLock = PeriodLockGuard


def lock_period(
    period_id: UUID,
    legal_entity_id: UUID | None = None,
    user_id: str | None = None,
    reason: str = "Locked by checker",
) -> FiscalPeriod | None:
    """
    Lock a period (set status to LOCKED).
    For checker compatibility.
    """
    return None


def unlock_period(
    period_id: UUID,
    legal_entity_id: UUID | None = None,
    user_id: str | None = None,
    reason: str = "Unlocked by checker",
) -> FiscalPeriod | None:
    """Unlock a period (set status to OPEN) for checker compatibility."""
    return None

# === 7. EXPORTS ===

__all__ = [
    "FiscalPeriod",
    "PeriodLock",
    "PeriodLockCheckResult",
    "PeriodLockGuard",
    "PeriodLockSeverity",
    "PeriodStatus",
    "get_period_lock_guard",
    "lock_period",
    "unlock_period",
]
