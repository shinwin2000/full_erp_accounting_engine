#!/usr/bin/env python3
"""
Module: currency_validator.py
Layer: 4 - Kernel / Guards
Responsibility: Validasi mata uang yang diizinkan per transaksi.
               Memastikan bahwa transaksi menggunakan mata uang yang didukung
               sistem dan sesuai dengan mata uang fungsional entitas.
               Mendukung multi-currency dengan validasi kurs dan konversi.

Dependencies:
- standard library (decimal, logging, datetime, typing, threading, hashlib)
- kernel.context_holder (get_current_legal_entity, get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, CurrencyValidatorError, GuardSeverity)

Audit: Setiap transaksi multi-currency dan validasi kurs dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, getcontext
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity
from kernel.guards.guard_exceptions import (
    CurrencyValidatorError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)

# Set precision untuk Decimal
getcontext().prec = 28


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackExchangeRateRepository:
    """Fallback exchange rate repository dengan data kurs default untuk testing.
    Tidak mengimpor apapun dari adapters atau infrastructure.
    """

    def __init__(self):
        # Default rates: (from_curr, to_curr) -> rate
        self._default_rates: dict[tuple[str, str], Decimal] = {
            ("USD", "IDR"): Decimal("15250.00"),
            ("EUR", "IDR"): Decimal("16500.00"),
            ("JPY", "IDR"): Decimal("105.50"),
            ("SGD", "IDR"): Decimal("11300.00"),
            ("MYR", "IDR"): Decimal("3400.00"),
            ("CNY", "IDR"): Decimal("2100.00"),
            ("GBP", "IDR"): Decimal("19500.00"),
            ("AUD", "IDR"): Decimal("10000.00"),
            ("THB", "IDR"): Decimal("420.00"),
            ("IDR", "USD"): Decimal("1") / Decimal("15250.00"),
            ("IDR", "EUR"): Decimal("1") / Decimal("16500.00"),
            ("USD", "EUR"): Decimal("0.92"),
            ("EUR", "USD"): Decimal("1.09"),
        }
        # Historical rates: (from_curr, to_curr, date_str) -> rate
        self._historical_rates: dict[tuple[str, str, str], Decimal] = {}
        self._rate_sources: dict[tuple[str, str, str], str] = {}  # source info

    async def get_rate(
        self, from_currency: str, to_currency: str, as_of: datetime
    ) -> Decimal | None:
        """Mendapatkan kurs valas pada tanggal tertentu."""
        from_curr = from_currency.upper()
        to_curr = to_currency.upper()

        if from_curr == to_curr:
            return Decimal(1)

        # Cek historical rate berdasarkan tanggal
        date_str = as_of.strftime("%Y-%m-%d")
        key = (from_curr, to_curr, date_str)
        if key in self._historical_rates:
            return self._historical_rates[key]

        # Cek reverse historical
        rev_key = (to_curr, from_curr, date_str)
        if rev_key in self._historical_rates:
            return Decimal(1) / self._historical_rates[rev_key]

        # Gunakan default rate jika tidak ada historical
        default_key = (from_curr, to_curr)
        if default_key in self._default_rates:
            return self._default_rates[default_key]

        # Cek reverse default
        rev_default_key = (to_curr, from_curr)
        if rev_default_key in self._default_rates:
            return Decimal(1) / self._default_rates[rev_default_key]

        return None

    async def add_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        effective_date: datetime,
        source: str = "manual",
    ) -> None:
        """Menambahkan atau memperbarui kurs secara manual."""
        from_curr = from_currency.upper()
        to_curr = to_currency.upper()
        date_str = effective_date.strftime("%Y-%m-%d")
        key = (from_curr, to_curr, date_str)
        self._historical_rates[key] = rate
        self._rate_sources[key] = source
        logger.info(f"Added exchange rate {from_curr}/{to_curr}={rate} on {date_str} from {source}")

    async def get_historical_rates(
        self, from_currency: str, to_currency: str, start_date: datetime, end_date: datetime
    ) -> dict[date, Decimal]:
        """Mendapatkan kurs historis dalam rentang tanggal."""
        result = {}
        current = start_date
        while current <= end_date:
            rate = await self.get_rate(from_currency, to_currency, current)
            if rate:
                result[current.date()] = rate
            current = current + timedelta(days=1)
        return result

    async def get_rate_source(
        self, from_currency: str, to_currency: str, effective_date: datetime
    ) -> str | None:
        """Mendapatkan sumber kurs (misal: Bank Indonesia, manual)."""
        date_str = effective_date.strftime("%Y-%m-%d")
        key = (from_currency.upper(), to_currency.upper(), date_str)
        return self._rate_sources.get(key)


class _FallbackLegalEntityRepository:
    """Fallback legal entity repository dengan data dummy untuk testing.
    Tidak mengimpor adapters atau infrastructure.
    """

    def __init__(self):
        self._entities: dict[UUID, dict[str, Any]] = {}
        self._entity_by_code: dict[str, UUID] = {}

    async def get_by_id(self, entity_id: UUID) -> dict[str, Any] | None:
        """Mendapatkan entitas berdasarkan ID."""
        return self._entities.get(entity_id)

    async def get_by_code(self, entity_code: str) -> dict[str, Any] | None:
        """Mendapatkan entitas berdasarkan kode entitas."""
        ent_id = self._entity_by_code.get(entity_code)
        if ent_id:
            return self._entities.get(ent_id)
        return None

    async def get_functional_currency(self, entity_id: UUID) -> str:
        """Mendapatkan mata uang fungsional entitas."""
        entity = self._entities.get(entity_id)
        if entity:
            return entity.get("functional_currency", "IDR")
        return "IDR"

    async def get_reporting_currency(self, entity_id: UUID) -> str:
        """Mendapatkan mata uang pelaporan entitas (biasanya sama dengan fungsional)."""
        entity = self._entities.get(entity_id)
        if entity:
            return entity.get("reporting_currency", entity.get("functional_currency", "IDR"))
        return "IDR"

    async def get_legal_entity_name(self, entity_id: UUID) -> str:
        """Mendapatkan nama entitas."""
        entity = self._entities.get(entity_id)
        if entity:
            return entity.get("name", f"Entity {entity_id}")
        return f"Entity {entity_id}"

    async def has_multi_currency_enabled(self, entity_id: UUID) -> bool:
        """Apakah entitas mengizinkan multi-currency."""
        entity = self._entities.get(entity_id)
        if entity:
            return entity.get("multi_currency_enabled", True)
        return True

    def register_entity(
        self,
        entity_id: UUID,
        functional_currency: str = "IDR",
        reporting_currency: str = "IDR",
        name: str = "",
        entity_code: str = "",
        multi_currency_enabled: bool = True,
    ):
        """Mendaftarkan entitas ke fallback storage."""
        self._entities[entity_id] = {
            "entity_id": entity_id,
            "functional_currency": functional_currency,
            "reporting_currency": reporting_currency,
            "name": name or f"Entity {entity_id}",
            "entity_code": entity_code,
            "multi_currency_enabled": multi_currency_enabled,
            "created_at": datetime.now(UTC),
        }
        if entity_code:
            self._entity_by_code[entity_code] = entity_id

    def remove_entity(self, entity_id: UUID) -> bool:
        """Menghapus entitas."""
        if entity_id in self._entities:
            ent = self._entities.pop(entity_id)
            if ent.get("entity_code"):
                self._entity_by_code.pop(ent["entity_code"], None)
            return True
        return False


# === 2. CONSTANTS & ENUMS ===

SUPPORTED_CURRENCIES = {
    "IDR",
    "USD",
    "EUR",
    "JPY",
    "SGD",
    "MYR",
    "CNY",
    "GBP",
    "AUD",
    "THB",
    "KRW",
    "INR",
}
DEFAULT_TOLERANCE = Decimal("0.0001")
EXCHANGE_RATE_DEVIATION_TOLERANCE = Decimal("0.02")  # 2%
MAX_CONVERSION_ROUNDING_DECIMALS = 2


class CurrencyValidatorSeverity(Enum):
    """Severity untuk pelanggaran currency validator."""

    CRITICAL = 80  # Mata uang tidak didukung / kurs tidak tersedia
    HIGH = 60  # Kurs menyimpang > 2%
    MEDIUM = 40  # Multi-currency tanpa dokumentasi kurs
    LOW = 20  # Peringatan mata uang berbeda dari fungsional
    INFO = 0


@dataclass
class CurrencyValidationResult:
    """Hasil validasi mata uang."""

    check_id: UUID
    currency: str
    functional_currency: str
    legal_entity_id: UUID
    exchange_rate: Decimal | None
    is_supported: bool
    rate_available: bool
    deviation_percentage: Decimal | None
    severity: CurrencyValidatorSeverity
    message: str
    source_currency: str | None = None
    target_currency: str | None = None
    converted_amount: Decimal | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.currency}|{self.functional_currency}|"
            f"{self.is_supported}|{self.rate_available}|{self.severity.value}|"
            f"{self.message[:100]}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "currency": self.currency,
            "functional_currency": self.functional_currency,
            "legal_entity_id": str(self.legal_entity_id),
            "exchange_rate": str(self.exchange_rate) if self.exchange_rate else None,
            "is_supported": self.is_supported,
            "rate_available": self.rate_available,
            "deviation_percentage": str(self.deviation_percentage)
            if self.deviation_percentage
            else None,
            "severity": self.severity.name,
            "message": self.message,
            "source_currency": self.source_currency,
            "target_currency": self.target_currency,
            "converted_amount": str(self.converted_amount) if self.converted_amount else None,
            "timestamp": self.timestamp.isoformat(),
            "hash": self.cryptographic_hash[:16] + "...",
        }


# ============================================================================
# BASE CURRENCY VALIDATOR (ABSTRACT)
# ============================================================================

class BaseCurrencyValidator(ABC):
    """Base contract untuk Currency Validator."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan validator."""
        pass

    @abstractmethod
    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode. Jika True, transaksi multi-currency tanpa kurs akan ditolak."""
        pass

    @abstractmethod
    async def get_functional_currency(self, legal_entity_id: UUID) -> str:
        """Mendapatkan mata uang fungsional entitas."""
        pass

    @abstractmethod
    async def validate_currency(
        self,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
    ) -> CurrencyValidationResult:
        """Memvalidasi apakah mata uang didukung dan memiliki kurs jika berbeda dari fungsional."""
        pass

    @abstractmethod
    async def validate_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        as_of: datetime,
        legal_entity_id: UUID | None = None,
        tolerance: Decimal = EXCHANGE_RATE_DEVIATION_TOLERANCE,
        user_id: str | None = None,
    ) -> CurrencyValidationResult:
        """Memvalidasi kurs yang digunakan terhadap official rate."""
        pass

    @abstractmethod
    async def validate_multi_currency_transaction(
        self,
        amounts: list[tuple[Decimal, str]],
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        target_currency: str | None = None,
    ) -> tuple[bool, list[CurrencyValidationResult], Decimal | None]:
        """Memvalidasi transaksi multi-currency."""
        pass

    @abstractmethod
    async def convert_amount(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        as_of: datetime | None = None,
        legal_entity_id: UUID | None = None,
        raise_on_error: bool = False,
    ) -> tuple[Decimal | None, str | None]:
        """Mengkonversi amount ke mata uang target."""
        pass

    @abstractmethod
    async def get_historical_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: datetime,
    ) -> Decimal | None:
        """Mendapatkan kurs historis pada tanggal tertentu."""
        pass

    @abstractmethod
    async def enforce(
        self,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> CurrencyValidationResult:
        """Menegakkan validasi mata uang, raise exception jika tidak valid."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        currency: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CurrencyValidationResult]:
        """Mendapatkan history pemeriksaan mata uang."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik currency validator."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseCurrencyValidator:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseCurrencyValidator:
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
    def touch(self, touched_by: str) -> BaseCurrencyValidator:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# CURRENCY VALIDATOR (CONCRETE)
# ============================================================================

class CurrencyValidator(BaseCurrencyValidator):
    """
    Guard untuk validasi mata uang.

    Business context: Memastikan bahwa semua transaksi menggunakan mata uang
    yang valid dan konsisten dengan kebijakan entitas. Mendukung konversi
    multi-currency dengan validasi kurs.
    """

    def __init__(
        self,
        exchange_rate_repo: Any | None = None,
        legal_entity_repo: Any | None = None,
    ):
        self._exchange_rate_repo = exchange_rate_repo or _FallbackExchangeRateRepository()
        self._legal_entity_repo = legal_entity_repo or _FallbackLegalEntityRepository()
        self._check_history: list[CurrencyValidationResult] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._strict_mode = True  # Jika True, transaksi dengan kurs missing akan ditolak
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        currency = context.get("currency")
        legal_entity_id = context.get("legal_entity_id")
        transaction_date = context.get("transaction_date")

        if not currency:
            errors.append("currency is required")
        else:
            if not isinstance(currency, str):
                errors.append("currency must be a string")
            elif currency.upper() not in SUPPORTED_CURRENCIES:
                errors.append(f"currency {currency} is not supported. Supported: {sorted(SUPPORTED_CURRENCIES)}")

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
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
                "history_count": len(self._check_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CurrencyValidator:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._strict_mode = data.get("strict_mode", True)
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CurrencyValidator:
        """Clone instance."""
        new_instance = CurrencyValidator()
        new_instance._enabled = self._enabled
        new_instance._strict_mode = self._strict_mode
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

    def touch(self, touched_by: str) -> CurrencyValidator:
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
        """Mengaktifkan atau menonaktifkan validator."""
        self._enabled = enabled
        self._record_audit("ENABLE", "system", {"enabled": enabled})
        logger.info(f"Currency validator enabled: {enabled}")

    def set_strict_mode(self, strict: bool = True) -> None:
        """Set strict mode. Jika True, transaksi multi-currency tanpa kurs akan ditolak."""
        self._strict_mode = strict
        self._record_audit("SET_STRICT_MODE", "system", {"strict": strict})
        logger.info(f"Currency validator strict mode: {strict}")

    async def get_functional_currency(self, legal_entity_id: UUID) -> str:
        """Mendapatkan mata uang fungsional entitas."""
        try:
            if hasattr(self._legal_entity_repo, "get_functional_currency"):
                return await self._legal_entity_repo.get_functional_currency(legal_entity_id)
            entity = await self._legal_entity_repo.get_by_id(legal_entity_id)
            if entity:
                return entity.get("functional_currency", "IDR")
            return "IDR"
        except Exception as e:
            logger.error(f"Error getting functional currency: {e}")
            return "IDR"

    async def validate_currency(
        self,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
    ) -> CurrencyValidationResult:
        """
        Memvalidasi apakah mata uang didukung dan memiliki kurs jika berbeda dari fungsional.

        Args:
            currency: Kode mata uang (ISO 4217)
            legal_entity_id: Entitas hukum (default dari context)
            transaction_date: Tanggal transaksi (untuk kurs)
            user_id: User ID (untuk audit)

        Returns:
            CurrencyValidationResult
        """
        if not self._enabled:
            return CurrencyValidationResult(
                check_id=uuid4(),
                currency=currency,
                functional_currency="IDR",
                legal_entity_id=legal_entity_id or UUID(int=0),
                exchange_rate=None,
                is_supported=True,
                rate_available=True,
                deviation_percentage=None,
                severity=CurrencyValidatorSeverity.INFO,
                message="Currency validator disabled",
                cryptographic_hash="",
            )

        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return CurrencyValidationResult(
                    check_id=uuid4(),
                    currency=currency,
                    functional_currency="IDR",
                    legal_entity_id=UUID(int=0),
                    exchange_rate=None,
                    is_supported=False,
                    rate_available=False,
                    deviation_percentage=None,
                    severity=CurrencyValidatorSeverity.CRITICAL,
                    message="No legal entity in context",
                    cryptographic_hash="",
                )

        functional_currency = await self.get_functional_currency(legal_entity_id)
        currency_upper = currency.upper()
        is_supported = currency_upper in SUPPORTED_CURRENCIES

        exchange_rate = None
        rate_available = True
        deviation_percentage = None
        severity = CurrencyValidatorSeverity.INFO
        message = f"Currency {currency_upper} is supported"

        # Check if multi-currency is allowed for this entity
        multi_currency_enabled = True
        if hasattr(self._legal_entity_repo, "has_multi_currency_enabled"):
            multi_currency_enabled = await self._legal_entity_repo.has_multi_currency_enabled(
                legal_entity_id
            )
        else:
            entity = await self._legal_entity_repo.get_by_id(legal_entity_id)
            multi_currency_enabled = entity.get("multi_currency_enabled", True) if entity else True

        if not is_supported:
            severity = CurrencyValidatorSeverity.CRITICAL
            message = (
                f"Currency {currency_upper} is not supported. Supported: {SUPPORTED_CURRENCIES}"
            )
        elif currency_upper != functional_currency:
            # Need exchange rate
            if not multi_currency_enabled:
                severity = CurrencyValidatorSeverity.HIGH
                message = f"Multi-currency not enabled for entity {legal_entity_id}. Transaction currency {currency_upper} differs from functional {functional_currency}"
                rate_available = False
            else:
                tx_date = transaction_date or datetime.now(UTC)
                exchange_rate = await self._exchange_rate_repo.get_rate(
                    currency_upper, functional_currency, tx_date
                )
                if exchange_rate is None:
                    rate_available = False
                    if self._strict_mode:
                        severity = CurrencyValidatorSeverity.HIGH
                        message = f"No exchange rate from {currency_upper} to {functional_currency} on {tx_date.date()}"
                    else:
                        severity = CurrencyValidatorSeverity.MEDIUM
                        message = f"No exchange rate from {currency_upper} to {functional_currency} on {tx_date.date()} (non-strict mode)"
                else:
                    message = f"Exchange rate from {currency_upper} to {functional_currency}: {exchange_rate}"

        result = CurrencyValidationResult(
            check_id=uuid4(),
            currency=currency_upper,
            functional_currency=functional_currency,
            legal_entity_id=legal_entity_id,
            exchange_rate=exchange_rate,
            is_supported=is_supported,
            rate_available=rate_available,
            deviation_percentage=deviation_percentage,
            severity=severity,
            message=message,
            source_currency=currency_upper,
            target_currency=functional_currency,
            cryptographic_hash="",
        )
        result = CurrencyValidationResult(
            check_id=result.check_id,
            currency=result.currency,
            functional_currency=result.functional_currency,
            legal_entity_id=result.legal_entity_id,
            exchange_rate=result.exchange_rate,
            is_supported=result.is_supported,
            rate_available=result.rate_available,
            deviation_percentage=result.deviation_percentage,
            severity=result.severity,
            message=result.message,
            source_currency=result.source_currency,
            target_currency=result.target_currency,
            converted_amount=result.converted_amount,
            timestamp=result.timestamp,
            cryptographic_hash=result.compute_hash(),
        )

        # Record history
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        if severity.value >= CurrencyValidatorSeverity.HIGH.value:
            self._record_audit("VALIDATE_CURRENCY", user_id or "system", {
                "currency": currency_upper,
                "functional": functional_currency,
                "severity": severity.name,
            })
            logger.warning(f"Currency validation: {message}")

        return result

    async def validate_exchange_rate(
        self,
        from_currency: str,
        to_currency: str,
        rate: Decimal,
        as_of: datetime,
        legal_entity_id: UUID | None = None,
        tolerance: Decimal = EXCHANGE_RATE_DEVIATION_TOLERANCE,
        user_id: str | None = None,
    ) -> CurrencyValidationResult:
        """
        Memvalidasi kurs yang digunakan terhadap official rate.

        Args:
            from_currency: Mata uang sumber
            to_currency: Mata uang target
            rate: Kurs yang digunakan
            as_of: Tanggal berlaku
            legal_entity_id: Entitas hukum (untuk logging)
            tolerance: Toleransi deviasi (default 2%)
            user_id: User ID

        Returns:
            CurrencyValidationResult
        """
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity() or UUID(int=0)

        official_rate = await self._exchange_rate_repo.get_rate(from_currency, to_currency, as_of)

        if official_rate is None:
            severity = CurrencyValidatorSeverity.HIGH
            message = f"No official rate for {from_currency}/{to_currency} on {as_of.date()}"
            deviation = None
            is_valid = not self._strict_mode
        else:
            deviation = abs(rate - official_rate) / official_rate
            is_within_tolerance = deviation <= tolerance
            if is_within_tolerance:
                severity = CurrencyValidatorSeverity.INFO
                message = f"Exchange rate {rate} is within {tolerance * 100:.0f}% tolerance of official rate {official_rate}"
                is_valid = True
            else:
                severity = CurrencyValidatorSeverity.HIGH
                message = f"Exchange rate {rate} deviates {deviation:.2%} from official rate {official_rate}"
                is_valid = False

        result = CurrencyValidationResult(
            check_id=uuid4(),
            currency=from_currency,
            functional_currency=to_currency,
            legal_entity_id=legal_entity_id,
            exchange_rate=rate,
            is_supported=True,
            rate_available=official_rate is not None,
            deviation_percentage=deviation,
            severity=severity,
            message=message,
            source_currency=from_currency,
            target_currency=to_currency,
            cryptographic_hash="",
        )
        result = CurrencyValidationResult(
            check_id=result.check_id,
            currency=result.currency,
            functional_currency=result.functional_currency,
            legal_entity_id=result.legal_entity_id,
            exchange_rate=result.exchange_rate,
            is_supported=result.is_supported,
            rate_available=result.rate_available,
            deviation_percentage=result.deviation_percentage,
            severity=result.severity,
            message=result.message,
            source_currency=result.source_currency,
            target_currency=result.target_currency,
            converted_amount=result.converted_amount,
            timestamp=result.timestamp,
            cryptographic_hash=result.compute_hash(),
        )

        with self._lock:
            self._check_history.append(result)

        if not is_valid:
            self._record_audit("VALIDATE_EXCHANGE_RATE", user_id or "system", {
                "from": from_currency,
                "to": to_currency,
                "rate": str(rate),
                "official": str(official_rate) if official_rate else None,
            })
            logger.warning(f"Exchange rate validation failed: {message}")

        return result

    async def validate_multi_currency_transaction(
        self,
        amounts: list[tuple[Decimal, str]],  # (amount, currency)
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        target_currency: str | None = None,
    ) -> tuple[bool, list[CurrencyValidationResult], Decimal | None]:
        """
        Memvalidasi transaksi multi-currency.
        Mengkonversi semua amount ke target currency (default: functional currency).

        Returns:
            (is_valid, list_of_violations, total_converted_amount)
        """
        violations = []
        total_converted = Decimal(0)

        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return (
                    False,
                    [
                        CurrencyValidationResult(
                            check_id=uuid4(),
                            currency="unknown",
                            functional_currency="IDR",
                            legal_entity_id=UUID(int=0),
                            exchange_rate=None,
                            is_supported=False,
                            rate_available=False,
                            deviation_percentage=None,
                            severity=CurrencyValidatorSeverity.CRITICAL,
                            message="No legal entity in context",
                        )
                    ],
                    None,
                )

        functional_currency = await self.get_functional_currency(legal_entity_id)
        target = target_currency or functional_currency
        tx_date = transaction_date or datetime.now(UTC)

        for amount, currency in amounts:
            # Validate each currency
            result = await self.validate_currency(currency, legal_entity_id, tx_date, user_id)
            if not result.is_supported or (not result.rate_available and self._strict_mode):
                violations.append(result)

            # Convert to target currency
            if currency.upper() == target:
                converted = amount
            else:
                rate = await self._exchange_rate_repo.get_rate(currency.upper(), target, tx_date)
                if rate is None:
                    if self._strict_mode:
                        violations.append(
                            CurrencyValidationResult(
                                check_id=uuid4(),
                                currency=currency,
                                functional_currency=target,
                                legal_entity_id=legal_entity_id,
                                exchange_rate=None,
                                is_supported=True,
                                rate_available=False,
                                deviation_percentage=None,
                                severity=CurrencyValidatorSeverity.HIGH,
                                message=f"Missing exchange rate for {currency} to {target}",
                            )
                        )
                        converted = Decimal(0)
                    else:
                        converted = amount  # assume 1:1 in non-strict
                else:
                    converted = amount * rate
                    converted = converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

            total_converted += converted

        is_valid = len(violations) == 0
        return is_valid, violations, total_converted

    async def convert_amount(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        as_of: datetime | None = None,
        legal_entity_id: UUID | None = None,
        raise_on_error: bool = False,
    ) -> tuple[Decimal | None, str | None]:
        """
        Mengkonversi amount ke mata uang target menggunakan kurs yang valid.

        Args:
            amount: Jumlah sumber
            from_currency: Mata uang sumber
            to_currency: Mata uang target
            as_of: Tanggal kurs
            legal_entity_id: Entitas hukum (untuk logging)
            raise_on_error: Jika True, raise exception saat gagal

        Returns:
            (converted_amount, error_message) - converted_amount None jika gagal
        """
        if from_currency.upper() == to_currency.upper():
            return amount, None

        as_of = as_of or datetime.now(UTC)
        rate = await self._exchange_rate_repo.get_rate(from_currency, to_currency, as_of)

        if rate is None:
            error_msg = f"No exchange rate from {from_currency} to {to_currency} on {as_of.date()}"
            if raise_on_error:
                raise CurrencyValidatorError(
                    message=error_msg, currency=from_currency, severity=GuardSeverity.HIGH
                )
            return None, error_msg

        converted = amount * rate
        # Round sesuai standar mata uang (biasanya 2 desimal)
        converted = converted.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        return converted, None

    async def get_historical_rate(
        self,
        from_currency: str,
        to_currency: str,
        as_of: datetime,
    ) -> Decimal | None:
        """Mendapatkan kurs historis pada tanggal tertentu."""
        return await self._exchange_rate_repo.get_rate(from_currency, to_currency, as_of)

    async def enforce(
        self,
        currency: str,
        legal_entity_id: UUID | None = None,
        transaction_date: datetime | None = None,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> CurrencyValidationResult:
        """
        Menegakkan validasi mata uang, raise exception jika tidak valid.

        Args:
            currency: Kode mata uang
            legal_entity_id: Entitas hukum
            transaction_date: Tanggal transaksi
            user_id: User ID
            raise_on_violation: Raise exception jika violation

        Returns:
            CurrencyValidationResult

        Raises:
            CurrencyValidatorError: Jika currency tidak valid dan raise_on_violation=True
        """
        result = await self.validate_currency(currency, legal_entity_id, transaction_date, user_id)

        if raise_on_violation:
            if not result.is_supported:
                raise CurrencyValidatorError(
                    message=result.message,
                    currency=currency,
                    severity=GuardSeverity.CRITICAL,
                    details=result.to_dict(),
                )
            if result.severity.value >= CurrencyValidatorSeverity.HIGH.value:
                raise CurrencyValidatorError(
                    message=result.message,
                    currency=currency,
                    severity=GuardSeverity.HIGH,
                    details=result.to_dict(),
                )

        return result

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        currency: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CurrencyValidationResult]:
        """Mendapatkan history pemeriksaan mata uang."""
        with self._lock:
            results = self._check_history[-limit:]

        if only_violations:
            results = [
                r for r in results if r.severity.value >= CurrencyValidatorSeverity.MEDIUM.value
            ]
        if currency:
            results = [r for r in results if r.currency == currency.upper()]
        if start_date:
            results = [r for r in results if r.timestamp >= start_date]
        if end_date:
            results = [r for r in results if r.timestamp <= end_date]

        return results

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik currency validator."""
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {
                    "total_checks": 0,
                    "enabled": self._enabled,
                    "strict_mode": self._strict_mode,
                    "version": self._version,
                }

            violations = [
                r
                for r in self._check_history
                if r.severity.value >= CurrencyValidatorSeverity.MEDIUM.value
            ]
            violation_count = len(violations)

            by_severity = {}
            for sev in CurrencyValidatorSeverity:
                count = len([r for r in violations if r.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count

            by_currency = {}
            for r in violations:
                curr = r.currency
                by_currency[curr] = by_currency.get(curr, 0) + 1

            supported_count = len([r for r in self._check_history if r.is_supported])
            rate_missing_count = len([r for r in self._check_history if not r.rate_available])

            return {
                "total_checks": total,
                "violation_count": violation_count,
                "violation_rate": violation_count / total if total > 0 else 0,
                "supported_rate": supported_count / total if total > 0 else 0,
                "rate_missing_count": rate_missing_count,
                "by_severity": by_severity,
                "by_currency": by_currency,
                "enabled": self._enabled,
                "strict_mode": self._strict_mode,
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


# === 4. SINGLETON ACCESSOR ===

_currency_validator_instance: CurrencyValidator | None = None
_lock_instance = threading.Lock()


def get_currency_validator() -> CurrencyValidator:
    """Mendapatkan instance singleton CurrencyValidator."""
    global _currency_validator_instance
    if _currency_validator_instance is None:
        with _lock_instance:
            if _currency_validator_instance is None:
                _currency_validator_instance = CurrencyValidator()
    return _currency_validator_instance


# === 5. EXPORTS ===

__all__ = [
    "SUPPORTED_CURRENCIES",
    "CurrencyValidationResult",
    "CurrencyValidator",
    "CurrencyValidatorSeverity",
    "get_currency_validator",
]