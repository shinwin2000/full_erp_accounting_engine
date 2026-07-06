#!/usr/bin/env python3
"""
Module: credit_limit_enforcer.py
Layer: 4 - Kernel / Guards
Responsibility: Menegakkan batas kredit pelanggan.
               Guard ini memastikan bahwa transaksi penjualan kredit tidak
               melebihi batas kredit yang telah ditetapkan untuk pelanggan.
               Juga memonitor outstanding piutang dan mencegah pengiriman
               barang jika pelanggan melebihi limit.

Dependencies:
- standard library (decimal, logging, datetime, typing, threading, uuid, hashlib)
- kernel.context_holder (get_current_legal_entity, get_current_user)
- kernel.guards.guard_exceptions (GuardViolationError, CreditLimitEnforcerError, GuardSeverity)

Audit: Setiap pelanggaran credit limit dictat untuk review credit control.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity
from kernel.guards.guard_exceptions import (
    CreditLimitEnforcerError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackCustomerRepository:
    """Fallback customer repository jika infrastructure belum tersedia.
    Menyimpan data customer dalam memory dengan struktur lengkap.
    """

    def __init__(self):
        self._customers: dict[UUID, dict[str, Any]] = {}
        self._index_by_code: dict[str, UUID] = {}

    async def get_by_id(self, customer_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        """Mendapatkan customer berdasarkan ID dan legal entity."""
        cust = self._customers.get(customer_id)
        if cust and cust.get("legal_entity_id") == legal_entity_id:
            return cust
        return None

    async def get_by_code(self, customer_code: str, legal_entity_id: UUID) -> dict[str, Any] | None:
        """Mendapatkan customer berdasarkan kode customer."""
        cust_id = self._index_by_code.get(customer_code)
        if cust_id:
            return await self.get_by_id(cust_id, legal_entity_id)
        return None

    async def get_credit_limit(self, customer_id: UUID, legal_entity_id: UUID) -> Decimal:
        """Mendapatkan batas kredit customer."""
        cust = await self.get_by_id(customer_id, legal_entity_id)
        if cust:
            return Decimal(str(cust.get("credit_limit", 0)))
        return Decimal(0)

    async def get_risk_rating(self, customer_id: UUID, legal_entity_id: UUID) -> str:
        """Mendapatkan rating risiko customer (low, medium, high)."""
        cust = await self.get_by_id(customer_id, legal_entity_id)
        if cust:
            return cust.get("risk_rating", "medium")
        return "medium"

    async def update_credit_limit(
        self, customer_id: UUID, legal_entity_id: UUID, new_limit: Decimal
    ) -> bool:
        """Memperbarui batas kredit customer."""
        cust = await self.get_by_id(customer_id, legal_entity_id)
        if cust:
            cust["credit_limit"] = new_limit
            cust["updated_at"] = datetime.now(UTC)
            return True
        return False

    def add_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        name: str,
        credit_limit: Decimal = Decimal(0),
        customer_code: str = "",
        risk_rating: str = "medium",
    ) -> None:
        """Menambahkan customer baru ke fallback storage."""
        self._customers[customer_id] = {
            "customer_id": customer_id,
            "legal_entity_id": legal_entity_id,
            "name": name,
            "credit_limit": credit_limit,
            "customer_code": customer_code,
            "risk_rating": risk_rating,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        if customer_code:
            self._index_by_code[customer_code] = customer_id

    def remove_customer(self, customer_id: UUID) -> bool:
        """Menghapus customer dari fallback storage."""
        if customer_id in self._customers:
            cust = self._customers.pop(customer_id)
            if cust.get("customer_code"):
                self._index_by_code.pop(cust["customer_code"], None)
            return True
        return False


class _FallbackARRepository:
    """Fallback AR repository jika infrastructure belum tersedia.
    Menyimpan outstanding balance per customer dan legal entity.
    """

    def __init__(self):
        self._outstanding: dict[
            tuple[UUID, UUID], Decimal
        ] = {}  # (customer_id, legal_entity_id) -> outstanding
        self._aging_buckets: dict[tuple[UUID, UUID], dict[str, Decimal]] = {}  # aging buckets
        self._payment_history: dict[UUID, list[dict[str, Any]]] = {}

    async def get_outstanding_balance(
        self, customer_id: UUID, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> Decimal:
        """Mendapatkan total outstanding piutang customer."""
        return self._outstanding.get((customer_id, legal_entity_id), Decimal(0))

    async def get_aging_buckets(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> dict[str, Decimal]:
        """Mendapatkan aging buckets (0-30, 31-60, 61-90, 90+)."""
        return self._aging_buckets.get(
            (customer_id, legal_entity_id),
            {"0_30": Decimal(0), "31_60": Decimal(0), "61_90": Decimal(0), "90_plus": Decimal(0)},
        )

    async def get_overdue_amount(self, customer_id: UUID, legal_entity_id: UUID) -> Decimal:
        """Mendapatkan jumlah yang overdue (lebih dari 30 hari)."""
        buckets = await self.get_aging_buckets(customer_id, legal_entity_id)
        return (
            buckets.get("31_60", Decimal(0))
            + buckets.get("61_90", Decimal(0))
            + buckets.get("90_plus", Decimal(0))
        )

    async def get_available_credit(self, customer_id: UUID, legal_entity_id: UUID) -> Decimal:
        """Mendapatkan sisa kredit yang tersedia."""
        credit_limit = await self._get_credit_limit_fallback(customer_id, legal_entity_id)
        outstanding = await self.get_outstanding_balance(customer_id, legal_entity_id)
        return max(Decimal(0), credit_limit - outstanding)

    async def _get_credit_limit_fallback(self, customer_id: UUID, legal_entity_id: UUID) -> Decimal:
        """Helper untuk mendapatkan credit limit dari fallback customer repo."""
        # Simulasi, di real implementation akan panggil customer repo
        return Decimal(1000000000)

    def set_outstanding(self, customer_id: UUID, legal_entity_id: UUID, amount: Decimal) -> None:
        """Set outstanding balance (untuk testing)."""
        self._outstanding[(customer_id, legal_entity_id)] = amount

    def set_aging_buckets(
        self, customer_id: UUID, legal_entity_id: UUID, buckets: dict[str, Decimal]
    ) -> None:
        """Set aging buckets."""
        self._aging_buckets[(customer_id, legal_entity_id)] = buckets

    def add_payment(
        self, customer_id: UUID, payment_id: UUID, amount: Decimal, payment_date: datetime
    ) -> None:
        """Mencatat pembayaran untuk history."""
        if customer_id not in self._payment_history:
            self._payment_history[customer_id] = []
        self._payment_history[customer_id].append(
            {
                "payment_id": payment_id,
                "amount": amount,
                "payment_date": payment_date,
            }
        )


# === 2. CONSTANTS & ENUMS ===


class CreditCheckAction(Enum):
    """Tindakan yang dapat diambil berdasarkan credit check."""

    ALLOW = auto()  # Transaksi diizinkan
    WARN = auto()  # Peringatan, tapi diizinkan
    BLOCK = auto()  # Diblokir, tidak diizinkan
    REQUIRE_APPROVAL = auto()  # Perlu persetujuan manajer


class CreditCheckSeverity(Enum):
    """Severity untuk pelanggaran credit limit."""

    CRITICAL = 80  # Melebihi limit, transaksi diblokir
    HIGH = 60  # Melebihi limit dengan approval
    MEDIUM = 40  # Mendekati limit
    LOW = 20  # Informasi


@dataclass
class CreditLimitInfo:
    """Informasi batas kredit pelanggan."""

    check_id: UUID
    customer_id: UUID
    customer_name: str
    credit_limit: Decimal
    currency: str
    current_outstanding: Decimal
    available_credit: Decimal
    requested_amount: Decimal
    new_outstanding: Decimal
    would_exceed: bool
    exceed_amount: Decimal
    action: CreditCheckAction
    severity: CreditCheckSeverity
    message: str
    risk_rating: str = "medium"
    overdue_amount: Decimal = Decimal(0)
    aging_buckets: dict[str, Decimal] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        """Menghitung hash kriptografis untuk integritas record."""
        content = (
            f"{self.check_id}|{self.customer_id}|{self.would_exceed}|{self.action.value}|"
            f"{self.credit_limit}|{self.current_outstanding}|{self.requested_amount}|"
            f"{self.risk_rating}|{self.overdue_amount}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary untuk serialisasi."""
        return {
            "check_id": str(self.check_id),
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "credit_limit": str(self.credit_limit),
            "currency": self.currency,
            "current_outstanding": str(self.current_outstanding),
            "available_credit": str(self.available_credit),
            "requested_amount": str(self.requested_amount),
            "new_outstanding": str(self.new_outstanding),
            "would_exceed": self.would_exceed,
            "exceed_amount": str(self.exceed_amount),
            "action": self.action.name,
            "severity": self.severity.name,
            "message": self.message,
            "risk_rating": self.risk_rating,
            "overdue_amount": str(self.overdue_amount),
            "aging_buckets": {k: str(v) for k, v in self.aging_buckets.items()},
            "timestamp": self.timestamp.isoformat(),
            "hash": self.cryptographic_hash[:16] + "...",
        }


# ============================================================================
# BASE CREDIT LIMIT ENFORCER (ABSTRACT)
# ============================================================================

class BaseCreditLimitEnforcer(ABC):
    """Base contract untuk Credit Limit Enforcer."""

    @abstractmethod
    def set_thresholds(
        self,
        warning_percentage: Decimal,
        block_percentage: Decimal,
        overdue_penalty_percentage: Decimal | None = None,
    ) -> None:
        """Set threshold persentase untuk warning dan block."""
        pass

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    async def check_credit_limit(
        self,
        customer_id: UUID,
        invoice_amount: Decimal,
        legal_entity_id: UUID | None = None,
        currency: str = "IDR",
        include_overdue_penalty: bool = True,
    ) -> CreditLimitInfo:
        """Memeriksa batas kredit pelanggan."""
        pass

    @abstractmethod
    async def check_multiple_invoices(
        self,
        customer_id: UUID,
        invoice_amounts: list[Decimal],
        legal_entity_id: UUID | None = None,
        currency: str = "IDR",
    ) -> tuple[bool, list[CreditLimitInfo]]:
        """Memeriksa batas kredit untuk multiple faktur secara sequential."""
        pass

    @abstractmethod
    async def enforce(
        self,
        customer_id: UUID,
        invoice_amount: Decimal,
        legal_entity_id: UUID | None = None,
        bypass_warning: bool = False,
        raise_on_violation: bool = True,
        user_id: str | None = None,
    ) -> CreditLimitInfo:
        """Menegakkan batas kredit, raise exception jika diblokir."""
        pass

    @abstractmethod
    def get_check_history(
        self,
        limit: int = 100,
        customer_id: UUID | None = None,
        only_violations: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CreditLimitInfo]:
        """Mendapatkan history pemeriksaan credit limit."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik credit limit enforcer."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset history (untuk testing)."""
        pass

    # === Entity methods (wajib untuk semua guard) ===
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
    def from_dict(cls, data: dict[str, Any]) -> CreditLimitEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> CreditLimitEnforcer:
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
    def touch(self, touched_by: str) -> CreditLimitEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# CREDIT LIMIT ENFORCER (CONCRETE)
# ============================================================================

class CreditLimitEnforcer(BaseCreditLimitEnforcer):
    """
    Guard untuk menegakkan batas kredit pelanggan.

    Business context: Mencegah risiko piutang tak tertagih dengan memastikan
    pelanggan tidak melebihi batas kredit yang telah disetujui.
    Juga mempertimbangkan aging buckets dan overdue amount.
    """

    def __init__(
        self,
        customer_repository: Any | None = None,
        ar_repository: Any | None = None,
    ):
        self._customer_repo = customer_repository or _FallbackCustomerRepository()
        self._ar_repo = ar_repository or _FallbackARRepository()
        self._warning_threshold_percentage = Decimal("85")  # Warning at 85% usage
        self._block_threshold_percentage = Decimal("100")  # Block at 100% usage
        self._overdue_penalty_percentage = Decimal("10")  # Reduce available credit by overdue * 10%
        self._check_history: list[CreditLimitInfo] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._enabled = True
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================
    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        customer_id = context.get("customer_id")
        invoice_amount = context.get("invoice_amount")
        if not customer_id:
            errors.append("customer_id is required")
        if invoice_amount is None:
            errors.append("invoice_amount is required")
        else:
            try:
                amount = Decimal(str(invoice_amount))
                if amount <= 0:
                    errors.append("invoice_amount must be positive")
            except Exception:
                errors.append("invoice_amount must be a valid number")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================
    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._warning_threshold_percentage < 0 or self._warning_threshold_percentage > 100:
            errors.append("warning_threshold_percentage must be between 0 and 100")
        if self._block_threshold_percentage < 0 or self._block_threshold_percentage > 100:
            errors.append("block_threshold_percentage must be between 0 and 100")
        if self._overdue_penalty_percentage < 0 or self._overdue_penalty_percentage > 100:
            errors.append("overdue_penalty_percentage must be between 0 and 100")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "warning_threshold_percentage": str(self._warning_threshold_percentage),
            "block_threshold_percentage": str(self._block_threshold_percentage),
            "overdue_penalty_percentage": str(self._overdue_penalty_percentage),
            "max_history": self._max_history,
            "enabled": self._enabled,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CreditLimitEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._warning_threshold_percentage = Decimal(str(data.get("warning_threshold_percentage", 85)))
        instance._block_threshold_percentage = Decimal(str(data.get("block_threshold_percentage", 100)))
        instance._overdue_penalty_percentage = Decimal(str(data.get("overdue_penalty_percentage", 10)))
        instance._max_history = data.get("max_history", 10000)
        instance._enabled = data.get("enabled", True)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> CreditLimitEnforcer:
        """Clone instance."""
        new_instance = CreditLimitEnforcer()
        new_instance._warning_threshold_percentage = self._warning_threshold_percentage
        new_instance._block_threshold_percentage = self._block_threshold_percentage
        new_instance._overdue_penalty_percentage = self._overdue_penalty_percentage
        new_instance._max_history = self._max_history
        new_instance._enabled = self._enabled
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

    def touch(self, touched_by: str) -> CreditLimitEnforcer:
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
    def set_thresholds(
        self,
        warning_percentage: Decimal,
        block_percentage: Decimal,
        overdue_penalty_percentage: Decimal | None = None,
    ) -> None:
        """Set threshold persentase untuk warning dan block."""
        if 0 <= warning_percentage <= 100:
            self._warning_threshold_percentage = warning_percentage
        if 0 <= block_percentage <= 100:
            self._block_threshold_percentage = block_percentage
        if overdue_penalty_percentage is not None:
            self._overdue_penalty_percentage = overdue_penalty_percentage
        logger.info(
            f"Credit limit thresholds set: warning={warning_percentage}%, block={block_percentage}%, "
            f"overdue_penalty={self._overdue_penalty_percentage}%"
        )

    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        self._enabled = enabled
        logger.info(f"Credit limit enforcer enabled: {enabled}")

    async def check_credit_limit(
        self,
        customer_id: UUID,
        invoice_amount: Decimal,
        legal_entity_id: UUID | None = None,
        currency: str = "IDR",
        include_overdue_penalty: bool = True,
    ) -> CreditLimitInfo:
        """Memeriksa batas kredit pelanggan."""
        if not self._enabled:
            return CreditLimitInfo(
                check_id=uuid4(),
                customer_id=customer_id,
                customer_name="Unknown",
                credit_limit=Decimal(0),
                currency=currency,
                current_outstanding=Decimal(0),
                available_credit=Decimal(0),
                requested_amount=invoice_amount,
                new_outstanding=invoice_amount,
                would_exceed=False,
                exceed_amount=Decimal(0),
                action=CreditCheckAction.ALLOW,
                severity=CreditCheckSeverity.LOW,
                message="Credit limit enforcer is disabled",
                cryptographic_hash="",
            )

        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return CreditLimitInfo(
                    check_id=uuid4(),
                    customer_id=customer_id,
                    customer_name="Unknown",
                    credit_limit=Decimal(0),
                    currency=currency,
                    current_outstanding=Decimal(0),
                    available_credit=Decimal(0),
                    requested_amount=invoice_amount,
                    new_outstanding=invoice_amount,
                    would_exceed=False,
                    exceed_amount=Decimal(0),
                    action=CreditCheckAction.ALLOW,
                    severity=CreditCheckSeverity.LOW,
                    message="No legal entity context, skipping credit check",
                    cryptographic_hash="",
                )

        # Get customer data
        customer_data = await self._customer_repo.get_by_id(customer_id, legal_entity_id)
        if not customer_data:
            return CreditLimitInfo(
                check_id=uuid4(),
                customer_id=customer_id,
                customer_name=f"Customer {customer_id}",
                credit_limit=Decimal(0),
                currency=currency,
                current_outstanding=Decimal(0),
                available_credit=Decimal(0),
                requested_amount=invoice_amount,
                new_outstanding=invoice_amount,
                would_exceed=False,
                exceed_amount=Decimal(0),
                action=CreditCheckAction.WARN,
                severity=CreditCheckSeverity.LOW,
                message=f"Customer {customer_id} not found, skipping credit limit check",
                cryptographic_hash="",
            )

        customer_name = customer_data.get("name", f"Customer {customer_id}")
        credit_limit = Decimal(str(customer_data.get("credit_limit", 0)))
        risk_rating = customer_data.get("risk_rating", "medium")

        # Get current outstanding AR
        current_outstanding = await self._ar_repo.get_outstanding_balance(
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
            as_of=datetime.now(UTC),
        )

        # Get overdue amount and aging buckets
        overdue_amount = Decimal(0)
        aging_buckets = {}
        if include_overdue_penalty:
            overdue_amount = await self._ar_repo.get_overdue_amount(customer_id, legal_entity_id)
            aging_buckets = await self._ar_repo.get_aging_buckets(customer_id, legal_entity_id)

        # Adjust effective available credit with overdue penalty
        effective_credit_limit = credit_limit
        if include_overdue_penalty and overdue_amount > 0:
            penalty = overdue_amount * self._overdue_penalty_percentage / Decimal(100)
            effective_credit_limit = max(Decimal(0), credit_limit - penalty)

        new_outstanding = current_outstanding + invoice_amount
        available = effective_credit_limit - current_outstanding
        would_exceed = (
            new_outstanding > effective_credit_limit if effective_credit_limit > 0 else False
        )
        exceed_amount = new_outstanding - effective_credit_limit if would_exceed else Decimal(0)

        # Determine action based on usage percentage
        usage_percentage = (
            (current_outstanding / effective_credit_limit * 100)
            if effective_credit_limit > 0
            else 0
        )

        if effective_credit_limit == 0:
            action = CreditCheckAction.WARN
            severity = CreditCheckSeverity.MEDIUM
            message = f"Customer {customer_name} has no effective credit limit (limit={credit_limit}, penalty={penalty if include_overdue_penalty else 0})"
        elif would_exceed:
            action = CreditCheckAction.BLOCK
            severity = CreditCheckSeverity.CRITICAL
            message = (
                f"Credit limit exceeded: effective limit {effective_credit_limit}, "
                f"outstanding {current_outstanding}, requested {invoice_amount}, "
                f"would exceed by {exceed_amount}"
            )
        elif usage_percentage >= self._block_threshold_percentage:
            action = CreditCheckAction.BLOCK
            severity = CreditCheckSeverity.HIGH
            message = (
                f"Credit limit usage {usage_percentage:.1f}% at or above threshold "
                f"{self._block_threshold_percentage}%. New request would exceed."
            )
        elif usage_percentage >= self._warning_threshold_percentage:
            action = CreditCheckAction.WARN
            severity = CreditCheckSeverity.MEDIUM
            message = (
                f"Credit limit usage {usage_percentage:.1f}% approaching limit. "
                f"Remaining credit: {available}"
            )
        else:
            action = CreditCheckAction.ALLOW
            severity = CreditCheckSeverity.INFO
            message = f"Credit available: {available}"

        # Create result with hash
        result = CreditLimitInfo(
            check_id=uuid4(),
            customer_id=customer_id,
            customer_name=customer_name,
            credit_limit=credit_limit,
            currency=currency,
            current_outstanding=current_outstanding,
            available_credit=available,
            requested_amount=invoice_amount,
            new_outstanding=new_outstanding,
            would_exceed=would_exceed,
            exceed_amount=exceed_amount,
            action=action,
            severity=severity,
            message=message,
            risk_rating=risk_rating,
            overdue_amount=overdue_amount,
            aging_buckets=aging_buckets,
            timestamp=datetime.now(UTC),
            cryptographic_hash="",
        )
        result = CreditLimitInfo(
            check_id=result.check_id,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            credit_limit=result.credit_limit,
            currency=result.currency,
            current_outstanding=result.current_outstanding,
            available_credit=result.available_credit,
            requested_amount=result.requested_amount,
            new_outstanding=result.new_outstanding,
            would_exceed=result.would_exceed,
            exceed_amount=result.exceed_amount,
            action=result.action,
            severity=result.severity,
            message=result.message,
            risk_rating=result.risk_rating,
            overdue_amount=result.overdue_amount,
            aging_buckets=result.aging_buckets,
            timestamp=result.timestamp,
            cryptographic_hash=result.compute_hash(),
        )

        # Store in history
        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        # Log warning if needed
        if action in (CreditCheckAction.WARN, CreditCheckAction.BLOCK):
            logger.warning(
                f"Credit limit check: {message} (customer={customer_id}, action={action.name})"
            )

        return result

    async def check_multiple_invoices(
        self,
        customer_id: UUID,
        invoice_amounts: list[Decimal],
        legal_entity_id: UUID | None = None,
        currency: str = "IDR",
    ) -> tuple[bool, list[CreditLimitInfo]]:
        """Memeriksa batas kredit untuk multiple faktur secara sequential."""
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()

        # Get current outstanding
        current_outstanding = await self._ar_repo.get_outstanding_balance(
            customer_id=customer_id,
            legal_entity_id=legal_entity_id,
        )

        customer_data = await self._customer_repo.get_by_id(customer_id, legal_entity_id)
        customer_name = (
            customer_data.get("name", f"Customer {customer_id}") if customer_data else "Unknown"
        )
        credit_limit = (
            Decimal(str(customer_data.get("credit_limit", 0))) if customer_data else Decimal(0)
        )
        risk_rating = customer_data.get("risk_rating", "medium") if customer_data else "medium"

        results = []
        running_outstanding = current_outstanding
        all_allowed = True

        for amount in invoice_amounts:
            new_outstanding = running_outstanding + amount
            would_exceed = new_outstanding > credit_limit if credit_limit > 0 else False
            exceed_amount = new_outstanding - credit_limit if would_exceed else Decimal(0)
            usage_percentage = (running_outstanding / credit_limit * 100) if credit_limit > 0 else 0

            if would_exceed:
                action = CreditCheckAction.BLOCK
                severity = CreditCheckSeverity.CRITICAL
                message = f"Would exceed credit limit: requested {amount}, would push outstanding to {new_outstanding}"
            elif usage_percentage >= self._block_threshold_percentage:
                action = CreditCheckAction.BLOCK
                severity = CreditCheckSeverity.HIGH
                message = f"Credit limit usage {usage_percentage:.1f}% at threshold"
            elif usage_percentage >= self._warning_threshold_percentage:
                action = CreditCheckAction.WARN
                severity = CreditCheckSeverity.MEDIUM
                message = f"Credit limit usage {usage_percentage:.1f}% approaching limit"
            else:
                action = CreditCheckAction.ALLOW
                severity = CreditCheckSeverity.INFO
                message = "OK"

            result = CreditLimitInfo(
                check_id=uuid4(),
                customer_id=customer_id,
                customer_name=customer_name,
                credit_limit=credit_limit,
                currency=currency,
                current_outstanding=running_outstanding,
                available_credit=credit_limit - running_outstanding,
                requested_amount=amount,
                new_outstanding=new_outstanding,
                would_exceed=would_exceed,
                exceed_amount=exceed_amount,
                action=action,
                severity=severity,
                message=message,
                risk_rating=risk_rating,
                cryptographic_hash="",
            )
            result = CreditLimitInfo(
                check_id=result.check_id,
                customer_id=result.customer_id,
                customer_name=result.customer_name,
                credit_limit=result.credit_limit,
                currency=result.currency,
                current_outstanding=result.current_outstanding,
                available_credit=result.available_credit,
                requested_amount=result.requested_amount,
                new_outstanding=result.new_outstanding,
                would_exceed=result.would_exceed,
                exceed_amount=result.exceed_amount,
                action=result.action,
                severity=result.severity,
                message=result.message,
                risk_rating=result.risk_rating,
                overdue_amount=result.overdue_amount,
                aging_buckets=result.aging_buckets,
                timestamp=result.timestamp,
                cryptographic_hash=result.compute_hash(),
            )
            results.append(result)

            if action == CreditCheckAction.BLOCK:
                all_allowed = False
                break

            running_outstanding = new_outstanding

        with self._lock:
            self._check_history.extend(results)
            if len(self._check_history) > self._max_history:
                excess = len(self._check_history) - self._max_history
                self._check_history = self._check_history[excess:]

        return all_allowed, results

    async def enforce(
        self,
        customer_id: UUID,
        invoice_amount: Decimal,
        legal_entity_id: UUID | None = None,
        bypass_warning: bool = False,
        raise_on_violation: bool = True,
        user_id: str | None = None,
    ) -> CreditLimitInfo:
        """Menegakkan batas kredit, raise exception jika diblokir."""
        result = await self.check_credit_limit(customer_id, invoice_amount, legal_entity_id)

        if raise_on_violation:
            if result.action == CreditCheckAction.BLOCK:
                raise CreditLimitEnforcerError(
                    message=f"Credit limit exceeded: {result.message}",
                    customer_id=str(customer_id),
                    credit_limit=result.credit_limit,
                    outstanding=result.current_outstanding,
                    severity=GuardSeverity.CRITICAL,
                    details=result.to_dict(),
                )
            elif result.action == CreditCheckAction.WARN and not bypass_warning:
                logger.warning(f"Credit limit warning for customer {customer_id}: {result.message}")
                # Optionally raise warning exception if configured
                if False:  # Configurable
                    raise CreditLimitEnforcerError(
                        message=f"Credit limit warning: {result.message}",
                        customer_id=str(customer_id),
                        credit_limit=result.credit_limit,
                        outstanding=result.current_outstanding,
                        severity=GuardSeverity.MEDIUM,
                        details=result.to_dict(),
                    )

        return result

    def get_check_history(
        self,
        limit: int = 100,
        customer_id: UUID | None = None,
        only_violations: bool = False,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[CreditLimitInfo]:
        """Mendapatkan history pemeriksaan credit limit."""
        with self._lock:
            results = self._check_history[-limit:]

        if customer_id:
            results = [r for r in results if r.customer_id == customer_id]
        if only_violations:
            results = [
                r for r in results if r.action in (CreditCheckAction.BLOCK, CreditCheckAction.WARN)
            ]
        if start_date:
            results = [r for r in results if r.timestamp >= start_date]
        if end_date:
            results = [r for r in results if r.timestamp <= end_date]

        return results

    def get_statistics(self) -> dict[str, Any]:
        """Mendapatkan statistik credit limit enforcer."""
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {"total_checks": 0, "enabled": self._enabled, "version": self._version}

            blocks = len([r for r in self._check_history if r.action == CreditCheckAction.BLOCK])
            warnings = len([r for r in self._check_history if r.action == CreditCheckAction.WARN])
            allows = len([r for r in self._check_history if r.action == CreditCheckAction.ALLOW])

            by_severity = {}
            for r in self._check_history:
                if r.severity != CreditCheckSeverity.INFO:
                    by_severity[r.severity.name] = by_severity.get(r.severity.name, 0) + 1

            by_risk_rating = {}
            for r in self._check_history:
                by_risk_rating[r.risk_rating] = by_risk_rating.get(r.risk_rating, 0) + 1

            return {
                "total_checks": total,
                "blocked_count": blocks,
                "warning_count": warnings,
                "allowed_count": allows,
                "block_rate": blocks / total if total > 0 else 0,
                "by_severity": by_severity,
                "by_risk_rating": by_risk_rating,
                "warning_threshold_percentage": str(self._warning_threshold_percentage),
                "block_threshold_percentage": str(self._block_threshold_percentage),
                "overdue_penalty_percentage": str(self._overdue_penalty_percentage),
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


# === 4. SINGLETON ACCESSOR ===

_credit_limit_enforcer_instance: CreditLimitEnforcer | None = None
_lock_instance = threading.Lock()


def get_credit_limit_enforcer() -> CreditLimitEnforcer:
    """Mendapatkan instance singleton CreditLimitEnforcer."""
    global _credit_limit_enforcer_instance
    if _credit_limit_enforcer_instance is None:
        with _lock_instance:
            if _credit_limit_enforcer_instance is None:
                _credit_limit_enforcer_instance = CreditLimitEnforcer()
    return _credit_limit_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "CreditCheckAction",
    "CreditCheckSeverity",
    "CreditLimitEnforcer",
    "CreditLimitInfo",
    "get_credit_limit_enforcer",
]