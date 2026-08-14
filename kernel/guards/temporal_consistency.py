#!/usr/bin/env python3
"""
Module: temporal_consistency.py
Layer: 4 - Kernel / Guards
Responsibility: Memastikan urutan waktu logis dan fisik konsisten.
               Guard ini memvalidasi bahwa timestamp transaksi tidak terjadi
               di masa depan yang tidak wajar, tidak melompat terlalu jauh
               ke belakang, dan menjaga urutan kronologis antar transaksi
               dalam sesi yang sama.

Dependencies:
- standard library (datetime, logging, typing, threading, uuid, hashlib)
- kernel.context_holder (get_current_user, get_current_legal_entity)
- kernel.guards.guard_exceptions (GuardViolationError, TemporalConsistencyError, GuardSeverity)

Audit: Setiap inkonsistensi temporal dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.guards.guard_exceptions import (
    GuardSeverity,
    TemporalConsistencyError,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK TRANSACTION REPOSITORY (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackTransactionRepository:
    """
    Fallback transaction repository jika infrastructure belum tersedia.
    Menyimpan tanggal transaksi terakhir per legal entity dalam memory.
    """

    def __init__(self) -> None:
        self._last_transaction_by_entity: dict[UUID, datetime] = {}
        self._transaction_count_by_entity: dict[UUID, int] = {}
        self._all_transactions: list[dict[str, Any]] = []  # untuk history sederhana

    async def get_last_transaction(
        self, legal_entity_id: UUID, before_date: datetime | None = None
    ) -> Any | None:
        """Mendapatkan transaksi terakhir sebelum tanggal tertentu."""
        last_date = self._last_transaction_by_entity.get(legal_entity_id)
        if last_date and (before_date is None or last_date < before_date):
            # Return dummy object with transaction_date attribute
            return type("Transaction", (), {"transaction_date": last_date})()
        return None

    async def record_transaction(
        self, legal_entity_id: UUID, transaction_date: datetime, transaction_id: UUID | None = None
    ) -> None:
        """Merekam tanggal transaksi terakhir."""
        current = self._last_transaction_by_entity.get(legal_entity_id)
        if current is None or transaction_date > current:
            self._last_transaction_by_entity[legal_entity_id] = transaction_date
            self._transaction_count_by_entity[legal_entity_id] = (
                self._transaction_count_by_entity.get(legal_entity_id, 0) + 1
            )
            if transaction_id:
                self._all_transactions.append(
                    {
                        "transaction_id": transaction_id,
                        "legal_entity_id": legal_entity_id,
                        "transaction_date": transaction_date,
                        "recorded_at": datetime.now(UTC),
                    }
                )
                if len(self._all_transactions) > 10000:
                    self._all_transactions = self._all_transactions[-5000:]

    async def get_transaction_count(self, legal_entity_id: UUID) -> int:
        """Mendapatkan jumlah transaksi yang tercatat untuk entitas."""
        return self._transaction_count_by_entity.get(legal_entity_id, 0)

    async def get_last_transaction_date(self, legal_entity_id: UUID) -> datetime | None:
        """Mendapatkan tanggal transaksi terakhir."""
        return self._last_transaction_by_entity.get(legal_entity_id)

    def reset(self) -> None:
        """Reset repository (untuk testing)."""
        self._last_transaction_by_entity.clear()
        self._transaction_count_by_entity.clear()
        self._all_transactions.clear()


# === 2. CONSTANTS & ENUMS ===


class TemporalViolationSeverity(Enum):
    """Severity pelanggaran temporal."""

    CRITICAL = 80  # Backdating ke periode tertutup / future dating ekstrem
    HIGH = 60  # Backdating > 30 hari tanpa otorisasi
    MEDIUM = 40  # Backdating 7-30 hari
    LOW = 20  # Backdating 1-7 hari (toleransi)
    INFO = 0


class TemporalViolationType(Enum):
    """Jenis pelanggaran temporal."""

    BACKDATE = "BACKDATE"
    FUTURE_DATE = "FUTURE_DATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    CLOCK_SKEW = "CLOCK_SKEW"


@dataclass
class TemporalViolation:
    """Rekaman pelanggaran konsistensi temporal."""

    violation_id: UUID
    transaction_id: UUID
    legal_entity_id: UUID
    transaction_date: datetime
    reference_date: datetime | None
    violation_type: str  # BACKDATE, FUTURE_DATE, OUT_OF_ORDER, CLOCK_SKEW
    backdate_days: int
    severity: TemporalViolationSeverity
    message: str
    detected_at: datetime
    is_resolved: bool = False
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_action: str | None = None
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.violation_id}|{self.transaction_id}|{self.legal_entity_id}|"
            f"{self.transaction_date.isoformat()}|{self.violation_type}|{self.backdate_days}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def resolve(self, resolved_by: str, action: str = "reviewed") -> TemporalViolation:
        """Menandai pelanggaran sebagai resolved."""
        return TemporalViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            transaction_date=self.transaction_date,
            reference_date=self.reference_date,
            violation_type=self.violation_type,
            backdate_days=self.backdate_days,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            is_resolved=True,
            resolved_at=datetime.now(UTC),
            resolved_by=resolved_by,
            resolution_action=action,
            cryptographic_hash=self.cryptographic_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "transaction_id": str(self.transaction_id),
            "legal_entity_id": str(self.legal_entity_id),
            "transaction_date": self.transaction_date.isoformat(),
            "reference_date": self.reference_date.isoformat() if self.reference_date else None,
            "violation_type": self.violation_type,
            "backdate_days": self.backdate_days,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "is_resolved": self.is_resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
        }


# === 3. TEMPORAL CONSISTENCY VALIDATOR (stateless) ===


class TemporalConsistencyValidator:
    """Validator untuk konsistensi temporal (stateless)."""

    # Default configuration
    MAX_FUTURE_DAYS = 7
    MAX_BACKDATE_DAYS = 30
    MAX_CLOCK_SKEW_SECONDS = 300  # 5 menit

    @classmethod
    def validate_timestamp(
        cls,
        transaction_date: datetime,
        allow_future: bool = False,
        max_future_days: int = MAX_FUTURE_DAYS,
        allow_backdate: bool = False,
        max_backdate_days: int = MAX_BACKDATE_DAYS,
    ) -> tuple[bool, str | None, int]:
        """
        Validasi dasar timestamp: tidak terlalu jauh ke depan/ke belakang.

        Returns:
            (is_valid, message, days_offset) - days_offset positif untuk backdate, negatif untuk future
        """
        now = datetime.now(UTC)
        if transaction_date.tzinfo is None:
            transaction_date = transaction_date.replace(tzinfo=UTC)

        # Future date check
        if transaction_date > now:
            if not allow_future:
                return False, "Transaction date is in the future. Future dating not allowed.", 0
            days_future = (transaction_date - now).days
            if days_future > max_future_days:
                return (
                    False,
                    f"Transaction date is {days_future} days in the future, exceeds max {max_future_days} days.",
                    -days_future,
                )
            return True, None, -days_future

        # Backdate check
        if transaction_date < now:
            if not allow_backdate:
                days_back = (now - transaction_date).days
                if days_back > max_backdate_days:
                    return (
                        False,
                        f"Transaction date is {days_back} days in the past, exceeds max {max_backdate_days} days without approval.",
                        days_back,
                    )
            return True, None, (now - transaction_date).days

        return True, None, 0

    @classmethod
    def validate_chronological_order(
        cls,
        transaction_date: datetime,
        last_transaction_date: datetime | None,
        max_backdate_days: int = MAX_BACKDATE_DAYS,
    ) -> tuple[bool, str | None, int]:
        """
        Validasi urutan kronologis dengan transaksi sebelumnya.

        Returns:
            (is_valid, message, backdate_days)
        """
        if last_transaction_date is None:
            return True, None, 0

        if transaction_date < last_transaction_date:
            days_back = (last_transaction_date - transaction_date).days
            if days_back > max_backdate_days:
                return (
                    False,
                    f"Transaction date {transaction_date.date()} is before last transaction {last_transaction_date.date()} (backdating by {days_back} days)",
                    days_back,
                )
            # Still valid but with warning
            return True, f"Transaction date is {days_back} days before last transaction", days_back

        return True, None, 0

    @classmethod
    def validate_clock_skew(
        cls,
        system_timestamp: datetime,
        source_timestamp: datetime,
        source_name: str,
        max_skew_seconds: int = MAX_CLOCK_SKEW_SECONDS,
    ) -> tuple[bool, str | None]:
        """Validasi perbedaan waktu antara sistem dan sumber eksternal."""
        diff = abs((system_timestamp - source_timestamp).total_seconds())
        if diff > max_skew_seconds:
            return (
                False,
                f"Clock skew detected between system and {source_name}: {diff:.0f} seconds difference",
            )
        return True, None

    @classmethod
    def get_severity(
        cls, days: int, violation_type: str, max_backdate_days: int = MAX_BACKDATE_DAYS
    ) -> TemporalViolationSeverity:
        """Menentukan severity berdasarkan jumlah hari dan tipe pelanggaran."""
        if violation_type == "FUTURE_DATE":
            if days > cls.MAX_FUTURE_DAYS:
                return TemporalViolationSeverity.HIGH
            return TemporalViolationSeverity.LOW
        elif violation_type == "BACKDATE":
            if days > max_backdate_days:
                return TemporalViolationSeverity.CRITICAL
            elif days > 14:
                return TemporalViolationSeverity.HIGH
            elif days > 7:
                return TemporalViolationSeverity.MEDIUM
            else:
                return TemporalViolationSeverity.LOW
        elif violation_type == "OUT_OF_ORDER":
            if days > 30:
                return TemporalViolationSeverity.HIGH
            return TemporalViolationSeverity.MEDIUM
        return TemporalViolationSeverity.MEDIUM


# ============================================================================
# BASE TEMPORAL CONSISTENCY GUARD (ABSTRACT)
# ============================================================================

class BaseTemporalConsistencyGuard(ABC):
    """Base contract untuk Temporal Consistency Guard."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan guard."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        pass

    @abstractmethod
    def configure(
        self,
        max_future_days: int | None = None,
        max_backdate_days: int | None = None,
        max_clock_skew_seconds: int | None = None,
    ) -> None:
        """Konfigurasi batasan temporal."""
        pass

    @abstractmethod
    async def enforce_transaction_timing(
        self,
        transaction_date: datetime,
        legal_entity_id: UUID,
        transaction_id: UUID,
        is_adjustment: bool = False,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, TemporalViolation | None]:
        """Menegakkan konsistensi temporal untuk transaksi."""
        pass

    @abstractmethod
    async def enforce_batch_timing(
        self,
        transaction_dates: list[datetime],
        legal_entity_id: UUID,
        batch_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[TemporalViolation]]:
        """Menegakkan konsistensi temporal untuk batch transaksi."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        legal_entity_id: UUID | None = None,
        violation_type: str | None = None,
        min_severity: TemporalViolationSeverity | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[TemporalViolation]:
        """Mendapatkan history pelanggaran."""
        pass

    @abstractmethod
    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, action: str = "reviewed"
    ) -> TemporalViolation | None:
        """Menandai pelanggaran sebagai resolved."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset guard state."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseTemporalConsistencyGuard:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseTemporalConsistencyGuard:
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
    def touch(self, touched_by: str) -> BaseTemporalConsistencyGuard:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# TEMPORAL CONSISTENCY GUARD (CONCRETE)
# ============================================================================

class TemporalConsistencyGuard(BaseTemporalConsistencyGuard):
    """
    Guard untuk konsistensi temporal.

    Business context: Memastikan bahwa timestamp transaksi konsisten dan
    tidak melanggar urutan waktu yang logis. Mencegah backdating yang tidak
    sah dan future dating yang ekstrem.
    """

    def __init__(self, transaction_repository: Any | None = None):
        self._tx_repo = transaction_repository or _FallbackTransactionRepository()
        self._violations: list[TemporalViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._max_future_days = TemporalConsistencyValidator.MAX_FUTURE_DAYS
        self._max_backdate_days = TemporalConsistencyValidator.MAX_BACKDATE_DAYS
        self._max_clock_skew_seconds = TemporalConsistencyValidator.MAX_CLOCK_SKEW_SECONDS
        self._enabled = True
        self._strict_mode = True  # Jika True, backdate > max_backdate_days akan ditolak
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        transaction_date = context.get("transaction_date")
        legal_entity_id = context.get("legal_entity_id")
        transaction_id = context.get("transaction_id")
        is_adjustment = context.get("is_adjustment", False)

        if not transaction_date:
            errors.append("transaction_date is required")
        else:
            try:
                if isinstance(transaction_date, str):
                    datetime.fromisoformat(transaction_date)
                elif not isinstance(transaction_date, datetime):
                    errors.append("transaction_date must be a datetime or ISO string")
            except ValueError:
                errors.append("transaction_date must be a valid ISO format date")
        if not legal_entity_id:
            errors.append("legal_entity_id is required")
        if not transaction_id:
            errors.append("transaction_id is required")
        if not isinstance(is_adjustment, bool):
            errors.append("is_adjustment must be a boolean")

        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_future_days <= 0:
            errors.append("max_future_days must be positive")
        if self._max_backdate_days <= 0:
            errors.append("max_backdate_days must be positive")
        if self._max_clock_skew_seconds <= 0:
            errors.append("max_clock_skew_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "enabled": self._enabled,
            "strict_mode": self._strict_mode,
            "max_future_days": self._max_future_days,
            "max_backdate_days": self._max_backdate_days,
            "max_clock_skew_seconds": self._max_clock_skew_seconds,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemporalConsistencyGuard:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_future_days = data.get("max_future_days", TemporalConsistencyValidator.MAX_FUTURE_DAYS)
        instance._max_backdate_days = data.get("max_backdate_days", TemporalConsistencyValidator.MAX_BACKDATE_DAYS)
        instance._max_clock_skew_seconds = data.get("max_clock_skew_seconds", TemporalConsistencyValidator.MAX_CLOCK_SKEW_SECONDS)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TemporalConsistencyGuard:
        """Clone instance."""
        new_instance = TemporalConsistencyGuard()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
        new_instance._max_future_days = self._max_future_days
        new_instance._max_backdate_days = self._max_backdate_days
        new_instance._max_clock_skew_seconds = self._max_clock_skew_seconds
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "violations_count": len(self._violations),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TemporalConsistencyGuard:
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
        logger.info(f"Temporal consistency guard enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode."""
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"Temporal consistency guard strict mode: {strict}")

    def configure(
        self,
        max_future_days: int | None = None,
        max_backdate_days: int | None = None,
        max_clock_skew_seconds: int | None = None,
    ) -> None:
        """Konfigurasi batasan temporal."""
        if max_future_days is not None:
            self._max_future_days = max_future_days
        if max_backdate_days is not None:
            self._max_backdate_days = max_backdate_days
        if max_clock_skew_seconds is not None:
            self._max_clock_skew_seconds = max_clock_skew_seconds
        self._record_audit("CONFIGURE", "system", {
            "max_future_days": max_future_days,
            "max_backdate_days": max_backdate_days,
            "max_clock_skew_seconds": max_clock_skew_seconds,
        })
        logger.info(
            f"Temporal consistency config updated: future_days={self._max_future_days}, backdate_days={self._max_backdate_days}, clock_skew_sec={self._max_clock_skew_seconds}"
        )

    async def check_timestamp_validity(
        self,
        transaction_date: datetime,
        allow_future: bool = False,
        allow_backdate: bool = False,
        user_id: str | None = None,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, TemporalViolation | None]:
        """
        Memeriksa validitas timestamp transaksi.

        Returns:
            (is_valid, violation_if_any)
        """
        if not self._enabled:
            return True, None

        is_valid, msg, days_offset = TemporalConsistencyValidator.validate_timestamp(
            transaction_date,
            allow_future=allow_future,
            max_future_days=self._max_future_days,
            allow_backdate=allow_backdate,
            max_backdate_days=self._max_backdate_days,
        )

        if not is_valid:
            violation_type = "FUTURE_DATE" if days_offset < 0 else "BACKDATE"
            abs_days = abs(days_offset) if days_offset != 0 else 0
            severity = TemporalConsistencyValidator.get_severity(
                abs_days, violation_type, self._max_backdate_days
            )
            # Ensure message is a string; fallback to a default if msg is None
            violation = self._create_violation(
                transaction_id=transaction_id or uuid4(),
                legal_entity_id=legal_entity_id or UUID(int=0),
                transaction_date=transaction_date,
                reference_date=datetime.now(UTC),
                violation_type=violation_type,
                backdate_days=abs_days,
                severity=severity,
                message=msg if msg else f"Timestamp validation failed: {violation_type}",
            )
            return False, violation

        return True, None

    async def check_chronological_order(
        self,
        transaction_date: datetime,
        legal_entity_id: UUID,
        transaction_id: UUID,
        user_id: str | None = None,
        ignore_last_tx: bool = False,
    ) -> tuple[bool, TemporalViolation | None]:
        """
        Memeriksa urutan kronologis dengan transaksi sebelumnya di entitas yang sama.

        Returns:
            (is_valid, violation_if_any)
        """
        if not self._enabled or ignore_last_tx:
            return True, None

        last_tx = await self._tx_repo.get_last_transaction(
            legal_entity_id, before_date=transaction_date
        )
        last_date = (
            last_tx.transaction_date if last_tx and hasattr(last_tx, "transaction_date") else None
        )

        is_valid, msg, days_back = TemporalConsistencyValidator.validate_chronological_order(
            transaction_date,
            last_date,
            max_backdate_days=self._max_backdate_days,
        )

        if not is_valid:
            severity = TemporalConsistencyValidator.get_severity(
                days_back, "OUT_OF_ORDER", self._max_backdate_days
            )
            violation = self._create_violation(
                transaction_id=transaction_id,
                legal_entity_id=legal_entity_id,
                transaction_date=transaction_date,
                reference_date=last_date,
                violation_type="OUT_OF_ORDER",
                backdate_days=days_back,
                severity=severity,
                message=msg or f"Transaction out of order: date {transaction_date} before last transaction {last_date}",
            )
            return False, violation

        # If warning (not blocking), still return True but record violation as warning? Optional
        if msg and self._strict_mode:
            logger.warning(f"Chronological order warning: {msg}")

        return True, None

    async def check_clock_skew(
        self,
        system_timestamp: datetime,
        source_timestamp: datetime,
        source_name: str,
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, TemporalViolation | None]:
        """
        Memeriksa perbedaan waktu dengan sumber eksternal.
        """
        if not self._enabled:
            return True, None

        is_valid, msg = TemporalConsistencyValidator.validate_clock_skew(
            system_timestamp, source_timestamp, source_name, self._max_clock_skew_seconds
        )
        if not is_valid:
            violation = self._create_violation(
                transaction_id=transaction_id or uuid4(),
                legal_entity_id=legal_entity_id or UUID(int=0),
                transaction_date=source_timestamp,
                reference_date=system_timestamp,
                violation_type="CLOCK_SKEW",
                backdate_days=0,
                severity=TemporalViolationSeverity.MEDIUM,
                message=msg if msg else "Clock skew detected",
            )
            return False, violation
        return True, None

    async def enforce_transaction_timing(
        self,
        transaction_date: datetime,
        legal_entity_id: UUID,
        transaction_id: UUID,
        is_adjustment: bool = False,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, TemporalViolation | None]:
        """
        Menegakkan konsistensi temporal untuk transaksi.

        Args:
            transaction_date: Tanggal transaksi
            legal_entity_id: Entitas hukum
            transaction_id: ID transaksi
            is_adjustment: Apakah transaksi penyesuaian (allow backdate)
            user_id: User ID
            raise_on_violation: Raise exception untuk violation CRITICAL

        Returns:
            (is_valid, violation_if_any)
        """
        if not self._enabled:
            return True, None

        # 1. Basic timestamp validity
        allow_backdate = is_adjustment
        _, violation = await self.check_timestamp_validity(
            transaction_date,
            allow_future=False,
            allow_backdate=allow_backdate,
            user_id=user_id,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
        )
        if violation:
            self._record_violation(violation)
            if raise_on_violation and violation.severity in (
                TemporalViolationSeverity.CRITICAL,
                TemporalViolationSeverity.HIGH,
            ):
                raise TemporalConsistencyError(
                    message=violation.message,
                    transaction_date=violation.transaction_date.isoformat(),
                    severity=GuardSeverity.CRITICAL,
                    details=violation.to_dict(),
                )
            return False, violation

        # 2. Chronological order with last transaction (skip if adjustment)
        if not is_adjustment:
            _, violation = await self.check_chronological_order(
                transaction_date, legal_entity_id, transaction_id, user_id
            )
            if violation:
                self._record_violation(violation)
                if raise_on_violation and violation.severity in (
                    TemporalViolationSeverity.CRITICAL,
                    TemporalViolationSeverity.HIGH,
                ):
                    raise TemporalConsistencyError(
                        message=violation.message,
                        transaction_date=violation.transaction_date.isoformat(),
                        severity=GuardSeverity.CRITICAL,
                        details=violation.to_dict(),
                    )
                return False, violation

        # 3. Record this transaction's date for future checks
        await self._tx_repo.record_transaction(legal_entity_id, transaction_date, transaction_id)

        return True, None

    async def enforce_batch_timing(
        self,
        transaction_dates: list[datetime],
        legal_entity_id: UUID,
        batch_id: UUID,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, list[TemporalViolation]]:
        """
        Menegakkan konsistensi temporal untuk batch transaksi.
        """
        if not self._enabled:
            return True, []

        if not transaction_dates:
            return True, []

        violations = []
        sorted_dates = sorted(transaction_dates)

        # Check dates are in non-decreasing order
        for i in range(1, len(sorted_dates)):
            if sorted_dates[i] < sorted_dates[i - 1]:
                violation = self._create_violation(
                    transaction_id=batch_id,
                    legal_entity_id=legal_entity_id,
                    transaction_date=sorted_dates[i],
                    reference_date=sorted_dates[i - 1],
                    violation_type="OUT_OF_ORDER",
                    backdate_days=(sorted_dates[i - 1] - sorted_dates[i]).days,
                    severity=TemporalViolationSeverity.MEDIUM,
                    message=f"Batch {batch_id} contains out-of-order transaction dates",
                )
                self._record_violation(violation)
                violations.append(violation)

        # Check first and last date against existing transactions
        first_date = sorted_dates[0]
        last_tx = await self._tx_repo.get_last_transaction(legal_entity_id, before_date=first_date)
        if (
            last_tx
            and hasattr(last_tx, "transaction_date")
            and last_tx.transaction_date > first_date
        ):
            days_back = (last_tx.transaction_date - first_date).days
            severity = (
                TemporalViolationSeverity.HIGH
                if days_back > self._max_backdate_days
                else TemporalViolationSeverity.MEDIUM
            )
            violation = self._create_violation(
                transaction_id=batch_id,
                legal_entity_id=legal_entity_id,
                transaction_date=first_date,
                reference_date=last_tx.transaction_date,
                violation_type="OUT_OF_ORDER",
                backdate_days=days_back,
                severity=severity,
                message=f"Batch {batch_id} first date {first_date} is before last existing transaction {last_tx.transaction_date}",
            )
            self._record_violation(violation)
            violations.append(violation)

        if raise_on_violation and any(
            v.severity in (TemporalViolationSeverity.CRITICAL, TemporalViolationSeverity.HIGH)
            for v in violations
        ):
            raise TemporalConsistencyError(
                message="Batch timing violation",
                transaction_date=first_date.isoformat(),
                severity=GuardSeverity.CRITICAL,
                details={"violations": [v.to_dict() for v in violations]},
            )

        return len(violations) == 0, violations

    def _create_violation(
        self,
        transaction_id: UUID,
        legal_entity_id: UUID,
        transaction_date: datetime,
        reference_date: datetime | None,
        violation_type: str,
        backdate_days: int,
        severity: TemporalViolationSeverity,
        message: str,
    ) -> TemporalViolation:
        violation = TemporalViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            transaction_date=transaction_date,
            reference_date=reference_date,
            violation_type=violation_type,
            backdate_days=backdate_days,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            is_resolved=False,
            cryptographic_hash="",
        )
        violation.cryptographic_hash = violation.compute_hash()
        return violation

    def _record_violation(self, violation: TemporalViolation) -> None:
        with self._lock:
            self._violations.append(violation)
            if len(self._violations) > self._max_history:
                self._violations = self._violations[-self._max_history :]

    def get_violations(
        self,
        limit: int = 100,
        legal_entity_id: UUID | None = None,
        violation_type: str | None = None,
        min_severity: TemporalViolationSeverity | None = None,
        unresolved_only: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[TemporalViolation]:
        with self._lock:
            result = self._violations[-limit:]
        if legal_entity_id:
            result = [v for v in result if v.legal_entity_id == legal_entity_id]
        if violation_type:
            result = [v for v in result if v.violation_type == violation_type]
        if min_severity:
            result = [v for v in result if v.severity.value >= min_severity.value]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved]
        if start_date:
            result = [v for v in result if v.detected_at >= start_date]
        if end_date:
            result = [v for v in result if v.detected_at <= end_date]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, action: str = "reviewed"
    ) -> TemporalViolation | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.is_resolved:
                    resolved = v.resolve(resolved_by, action)
                    self._violations[i] = resolved
                    self._record_audit("RESOLVE_VIOLATION", resolved_by, {"violation_id": str(violation_id)})
                    logger.info(f"Temporal violation {violation_id} resolved by {resolved_by}")
                    return resolved
        return None

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._violations)
            if total == 0:
                return {
                    "total_violations": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "max_future_days": self._max_future_days,
                    "max_backdate_days": self._max_backdate_days,
                    "max_clock_skew_seconds": self._max_clock_skew_seconds,
                    "version": self._version,
                }

            by_type: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            unresolved = 0
            for v in self._violations:
                by_type[v.violation_type] = by_type.get(v.violation_type, 0) + 1
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1
                if not v.is_resolved:
                    unresolved += 1

            return {
                "total_violations": total,
                "unresolved_violations": unresolved,
                "by_type": by_type,
                "by_severity": by_severity,
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "max_future_days": self._max_future_days,
                "max_backdate_days": self._max_backdate_days,
                "max_clock_skew_seconds": self._max_clock_skew_seconds,
                "version": self._version,
                "latest_violation": self._violations[-1].detected_at.isoformat()
                if self._violations
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._violations = []
            if hasattr(self._tx_repo, "reset"):
                self._tx_repo.reset()
            self._enabled = True
            self._strict_mode = True
            self._version += 1
            self._audit_trail = []


# === 5. SINGLETON ACCESSOR ===

_temporal_consistency_guard_instance: TemporalConsistencyGuard | None = None
_lock_instance = threading.Lock()


def get_temporal_consistency_guard() -> TemporalConsistencyGuard:
    global _temporal_consistency_guard_instance
    if _temporal_consistency_guard_instance is None:
        with _lock_instance:
            if _temporal_consistency_guard_instance is None:
                _temporal_consistency_guard_instance = TemporalConsistencyGuard()
    return _temporal_consistency_guard_instance


# === 6. EXPORTS ===

__all__ = [
    "TemporalConsistencyGuard",
    "TemporalConsistencyValidator",
    "TemporalViolation",
    "TemporalViolationSeverity",
    "TemporalViolationType",
    "get_temporal_consistency_guard",
]
