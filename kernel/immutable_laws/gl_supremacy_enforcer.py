#!/usr/bin/env python3
"""
Module: gl_supremacy_enforcer.py
Layer: 4 - Kernel / Immutable Laws
Responsibility: Hukum: General Ledger adalah sumber kebenaran tertinggi.
               Memastikan bahwa semua transaksi dari subledger (AR, AP, Inventory)
               harus ter-rekonsiliasi dengan General Ledger. GL adalah master
               record yang menjadi acuan utama untuk pelaporan keuangan.

Dependencies:
- standard library (hashlib, json, logging, dataclass, datetime, decimal, enum, typing, uuid, threading)
- kernel.context_holder (get_current_user)
- kernel.immutable_laws.law_violation_exceptions (ImmutableLawViolationError, GLSupremacyViolation)

Audit: Setiap ketidaksesuaian antara GL dan subledger dictat.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from kernel.context_holder import get_current_user
from kernel.immutable_laws.law_violation_exceptions import (
    GLSupremacyViolation,
    LawViolationSeverity,
)

logger = logging.getLogger(__name__)


# === 1. FALLBACK REPOSITORIES (internal, tidak mengimpor adapters/infrastructure) ===


class _FallbackLedgerRepository:
    """Fallback ledger repository dengan in-memory storage."""

    def __init__(self):
        self._balances: dict[tuple[UUID, UUID, str], Decimal] = {}
        self._reconciliations: list[dict[str, Any]] = []
        self._accounts: dict[str, dict[str, Any]] = {}
        self._period_balances: dict[tuple[UUID, UUID, str], dict[str, Decimal]] = {}

    async def get_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        account_code: str,
    ) -> Decimal:
        key = (legal_entity_id, period_id, account_code)
        return self._balances.get(key, Decimal(0))

    async def get_balance_history(
        self,
        legal_entity_id: UUID,
        account_code: str,
        from_period_id: UUID,
        to_period_id: UUID,
    ) -> dict[UUID, Decimal]:
        result = {}
        for (le, pid, acc), bal in self._balances.items():
            if le == legal_entity_id and acc == account_code:
                result[pid] = bal
        return result

    async def record_reconciliation(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        reconciliation_type: str,
        result: dict[str, Any],
        reconciled_by: str,
    ) -> None:
        self._reconciliations.append(
            {
                "legal_entity_id": legal_entity_id,
                "period_id": period_id,
                "reconciliation_type": reconciliation_type,
                "result": result,
                "reconciled_by": reconciled_by,
                "reconciled_at": datetime.now(UTC),
            }
        )

    async def get_reconciliations(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> list[dict[str, Any]]:
        return [
            r
            for r in self._reconciliations
            if r["legal_entity_id"] == legal_entity_id and r["period_id"] == period_id
        ]

    async def get_account_balance_summary(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        account_prefix: str | None = None,
    ) -> dict[str, Decimal]:
        result = {}
        for (le, pid, acc), bal in self._balances.items():
            if le == legal_entity_id and pid == period_id and (account_prefix is None or acc.startswith(account_prefix)):
                result[acc] = bal
        return result

    def set_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        account_code: str,
        balance: Decimal,
    ) -> None:
        key = (legal_entity_id, period_id, account_code)
        self._balances[key] = balance

    def register_account(
        self,
        account_code: str,
        account_name: str,
        account_type: str,
        is_control_account: bool = False,
        subledger_type: str | None = None,
    ) -> None:
        self._accounts[account_code] = {
            "account_code": account_code,
            "account_name": account_name,
            "account_type": account_type,
            "is_control_account": is_control_account,
            "subledger_type": subledger_type,
        }

    def clear(self) -> None:
        self._balances.clear()
        self._reconciliations.clear()
        self._accounts.clear()
        self._period_balances.clear()


class _FallbackSubledgerRepository:
    """Fallback subledger repository dengan in-memory storage."""

    def __init__(self):
        self._ar_balances: dict[tuple[UUID, UUID], Decimal] = {}
        self._ap_balances: dict[tuple[UUID, UUID], Decimal] = {}
        self._inventory_balances: dict[tuple[UUID, UUID], Decimal] = {}
        self._fa_balances: dict[tuple[UUID, UUID], Decimal] = {}
        self._ar_details: dict[UUID, list[dict[str, Any]]] = {}
        self._ap_details: dict[UUID, list[dict[str, Any]]] = {}
        self._inventory_details: dict[UUID, list[dict[str, Any]]] = {}

    async def get_ar_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> Decimal:
        return self._ar_balances.get((legal_entity_id, period_id), Decimal(0))

    async def get_ap_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> Decimal:
        return self._ap_balances.get((legal_entity_id, period_id), Decimal(0))

    async def get_inventory_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> Decimal:
        return self._inventory_balances.get((legal_entity_id, period_id), Decimal(0))

    async def get_fixed_asset_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> Decimal:
        return self._fa_balances.get((legal_entity_id, period_id), Decimal(0))

    async def get_ar_aging(
        self,
        legal_entity_id: UUID,
        as_of: datetime,
    ) -> dict[str, Any]:
        return {"total_outstanding": Decimal(0), "buckets": {}}

    async def get_ap_aging(
        self,
        legal_entity_id: UUID,
        as_of: datetime,
    ) -> dict[str, Any]:
        return {"total_outstanding": Decimal(0), "buckets": {}}

    async def get_ar_details(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._ar_details.get(period_id, [])[:limit]

    async def get_ap_details(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._ap_details.get(period_id, [])[:limit]

    async def get_inventory_details(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._inventory_details.get(period_id, [])[:limit]

    def set_balance(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        subledger_type: str,
        balance: Decimal,
    ) -> None:
        if subledger_type == "AR":
            self._ar_balances[(legal_entity_id, period_id)] = balance
        elif subledger_type == "AP":
            self._ap_balances[(legal_entity_id, period_id)] = balance
        elif subledger_type == "INVENTORY":
            self._inventory_balances[(legal_entity_id, period_id)] = balance
        elif subledger_type == "FIXED_ASSET":
            self._fa_balances[(legal_entity_id, period_id)] = balance

    def add_ar_detail(self, period_id: UUID, detail: dict[str, Any]) -> None:
        self._ar_details.setdefault(period_id, []).append(detail)

    def add_ap_detail(self, period_id: UUID, detail: dict[str, Any]) -> None:
        self._ap_details.setdefault(period_id, []).append(detail)

    def add_inventory_detail(self, period_id: UUID, detail: dict[str, Any]) -> None:
        self._inventory_details.setdefault(period_id, []).append(detail)

    def clear(self) -> None:
        self._ar_balances.clear()
        self._ap_balances.clear()
        self._inventory_balances.clear()
        self._fa_balances.clear()
        self._ar_details.clear()
        self._ap_details.clear()
        self._inventory_details.clear()


# === 2. CONSTANTS & ENUMS ===


class SubledgerType(Enum):
    ACCOUNTS_RECEIVABLE = "AR"
    ACCOUNTS_PAYABLE = "AP"
    INVENTORY = "INVENTORY"
    FIXED_ASSET = "FIXED_ASSET"


class ReconciliationStatus(Enum):
    MATCHED = "matched"
    MISMATCHED = "mismatched"
    PENDING = "pending"
    ADJUSTMENT_NEEDED = "adjustment_needed"


@dataclass
class ReconciliationResult:
    reconciliation_id: UUID
    legal_entity_id: UUID
    period_id: UUID
    subledger_type: SubledgerType
    gl_balance: Decimal
    subledger_balance: Decimal
    difference: Decimal
    tolerance: Decimal
    status: ReconciliationStatus
    reconciled_by: str
    reconciled_at: datetime
    adjustment_journal_id: UUID | None = None
    notes: str = ""
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.reconciliation_id}|{self.legal_entity_id}|{self.period_id}|"
            f"{self.subledger_type.value}|{self.gl_balance}|{self.subledger_balance}|"
            f"{self.difference}|{self.status.value}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def is_matched(self) -> bool:
        return self.status == ReconciliationStatus.MATCHED

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciliation_id": str(self.reconciliation_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period_id": str(self.period_id),
            "subledger_type": self.subledger_type.value,
            "gl_balance": str(self.gl_balance),
            "subledger_balance": str(self.subledger_balance),
            "difference": str(self.difference),
            "tolerance": str(self.tolerance),
            "status": self.status.value,
            "reconciled_by": self.reconciled_by,
            "reconciled_at": self.reconciled_at.isoformat(),
            "adjustment_journal_id": str(self.adjustment_journal_id)
            if self.adjustment_journal_id
            else None,
            "notes": self.notes[:100],
        }


@dataclass
class ReconciliationHistory:
    period_id: UUID
    legal_entity_id: UUID
    reconciliations: list[ReconciliationResult]
    total_gl_balance: Decimal
    total_subledger_balance: Decimal
    total_difference: Decimal
    all_matched: bool
    last_reconciled_at: datetime | None
    last_reconciled_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_id": str(self.period_id),
            "legal_entity_id": str(self.legal_entity_id),
            "reconciliations_count": len(self.reconciliations),
            "total_gl_balance": str(self.total_gl_balance),
            "total_subledger_balance": str(self.total_subledger_balance),
            "total_difference": str(self.total_difference),
            "all_matched": self.all_matched,
            "last_reconciled_at": self.last_reconciled_at.isoformat()
            if self.last_reconciled_at
            else None,
            "last_reconciled_by": self.last_reconciled_by,
        }


# ============================================================================
# BASE GL SUPREMACY ENFORCER (ABSTRACT)
# ============================================================================

class BaseGLSupremacyEnforcer(ABC):
    """Base contract untuk GL Supremacy Enforcer."""

    @abstractmethod
    def enable(self, enabled: bool = True) -> None:
        """Mengaktifkan atau menonaktifkan enforcer."""
        pass

    @abstractmethod
    def set_tolerance(self, tolerance: Decimal) -> None:
        """Set tolerance for reconciliation."""
        pass

    @abstractmethod
    def set_auto_correct_threshold(self, threshold: Decimal) -> None:
        """Set auto-correct threshold."""
        pass

    @abstractmethod
    async def enforce_gl_supremacy(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        account_code: str,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        """Enforce GL supremacy for a specific account."""
        pass

    @abstractmethod
    async def reconcile_ar_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        """Reconcile AR subledger to GL."""
        pass

    @abstractmethod
    async def reconcile_ap_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        """Reconcile AP subledger to GL."""
        pass

    @abstractmethod
    async def reconcile_inventory_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        """Reconcile Inventory subledger to GL."""
        pass

    @abstractmethod
    async def reconcile_fixed_asset_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        """Reconcile Fixed Asset subledger to GL."""
        pass

    @abstractmethod
    async def reconcile_all_subledgers(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
    ) -> list[ReconciliationResult]:
        """Reconcile all subledgers to GL."""
        pass

    @abstractmethod
    async def get_reconciliation_status(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> ReconciliationHistory:
        """Get reconciliation status for a period."""
        pass

    @abstractmethod
    async def get_reconciliation_details(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        subledger_type: SubledgerType,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get reconciliation details for a subledger."""
        pass

    @abstractmethod
    async def create_adjustment_journal(
        self,
        reconciliation_result: ReconciliationResult,
        adjustment_amount: Decimal,
        adjustment_reason: str,
        user_id: str | None = None,
    ) -> UUID:
        """Create adjustment journal for mismatch."""
        pass

    @abstractmethod
    def get_reconciliation_history(
        self,
        limit: int = 100,
        legal_entity_id: UUID | None = None,
        period_id: UUID | None = None,
        only_mismatched: bool = False,
    ) -> list[ReconciliationResult]:
        """Get reconciliation history."""
        pass

    @abstractmethod
    def get_violations(
        self,
        limit: int = 100,
        account_code: str | None = None,
    ) -> list[GLSupremacyViolation]:
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
    def from_dict(cls, data: dict[str, Any]) -> BaseGLSupremacyEnforcer:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseGLSupremacyEnforcer:
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
    def touch(self, touched_by: str) -> BaseGLSupremacyEnforcer:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# GL SUPREMACY ENFORCER (CONCRETE)
# ============================================================================

class GLSupremacyEnforcer(BaseGLSupremacyEnforcer):
    """
    Enforcer untuk hukum GL supremacy.

    Business context: General Ledger adalah sumber kebenaran tertinggi.
    Semakin besar ketidaksesuaian dengan subledger, semakin besar risiko
    laporan keuangan yang tidak akurat.
    """

    DEFAULT_TOLERANCE: ClassVar[Decimal] = Decimal("0.01")
    AUTO_CORRECT_THRESHOLD: ClassVar[Decimal] = Decimal("1000")

    ACCOUNT_CODE_MAPPING: ClassVar[dict[str, SubledgerType]] = {
        "1.1": SubledgerType.ACCOUNTS_RECEIVABLE,
        "1.1.01": SubledgerType.ACCOUNTS_RECEIVABLE,
        "1.1.02": SubledgerType.ACCOUNTS_RECEIVABLE,
        "2.1": SubledgerType.ACCOUNTS_PAYABLE,
        "2.1.01": SubledgerType.ACCOUNTS_PAYABLE,
        "2.1.02": SubledgerType.ACCOUNTS_PAYABLE,
        "1.3": SubledgerType.INVENTORY,
        "1.3.01": SubledgerType.INVENTORY,
        "1.3.02": SubledgerType.INVENTORY,
        "1.6": SubledgerType.FIXED_ASSET,
        "1.6.01": SubledgerType.FIXED_ASSET,
    }

    def __init__(
        self,
        ledger_repository: Any | None = None,
        subledger_repository: Any | None = None,
    ):
        self._ledger_repo = ledger_repository or _FallbackLedgerRepository()
        self._subledger_repo = subledger_repository or _FallbackSubledgerRepository()
        self._reconciliation_history: list[ReconciliationResult] = []
        self._violation_history: list[GLSupremacyViolation] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._tolerance = self.DEFAULT_TOLERANCE
        self._auto_correct_threshold = self.AUTO_CORRECT_THRESHOLD
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
        legal_entity_id = context.get("legal_entity_id")
        period_id = context.get("period_id")
        account_code = context.get("account_code")

        if not legal_entity_id:
            errors.append("legal_entity_id is required")
        else:
            try:
                UUID(str(legal_entity_id))
            except Exception:
                errors.append("legal_entity_id must be a valid UUID")
        if not period_id:
            errors.append("period_id is required")
        else:
            try:
                UUID(str(period_id))
            except Exception:
                errors.append("period_id must be a valid UUID")
        if not account_code:
            errors.append("account_code is required")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if self._tolerance < 0:
            errors.append("tolerance cannot be negative")
        if self._auto_correct_threshold < 0:
            errors.append("auto_correct_threshold cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "tolerance": str(self._tolerance),
                "auto_correct_threshold": str(self._auto_correct_threshold),
                "reconciliations_count": len(self._reconciliation_history),
                "violations_count": len(self._violation_history),
                "version": self._version,
            }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GLSupremacyEnforcer:
        """Reconstruct dari dictionary."""
        instance = cls()
        instance._enabled = data.get("enabled", True)
        instance._tolerance = Decimal(str(data.get("tolerance", 0.01)))
        instance._auto_correct_threshold = Decimal(str(data.get("auto_correct_threshold", 1000)))
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> GLSupremacyEnforcer:
        """Clone instance."""
        new_instance = GLSupremacyEnforcer()
        new_instance._enabled = self._enabled
        new_instance._tolerance = self._tolerance
        new_instance._auto_correct_threshold = self._auto_correct_threshold
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        with self._lock:
            return {
                "version": self._version,
                "reconciliations_count": len(self._reconciliation_history),
                "violations_count": len(self._violation_history),
                "enabled": self._enabled,
                "timestamp": datetime.now(UTC).isoformat(),
            }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> GLSupremacyEnforcer:
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
        logger.info(f"GL supremacy enforcer enabled: {enabled}")

    def set_tolerance(self, tolerance: Decimal) -> None:
        if tolerance < 0:
            raise ValueError("Tolerance cannot be negative")
        self._tolerance = tolerance
        self._record_audit("SET_TOLERANCE", "system", {"tolerance": str(tolerance)})
        logger.info(f"GL-Subledger reconciliation tolerance set to {tolerance}")

    def set_auto_correct_threshold(self, threshold: Decimal) -> None:
        self._auto_correct_threshold = threshold
        self._record_audit("SET_AUTO_CORRECT_THRESHOLD", "system", {"threshold": str(threshold)})
        logger.info(f"Auto-correct threshold set to {threshold}")

    def _get_subledger_type_from_account(self, account_code: str) -> SubledgerType | None:
        for prefix, subledger_type in self.ACCOUNT_CODE_MAPPING.items():
            if account_code.startswith(prefix):
                return subledger_type
        return None

    async def enforce_gl_supremacy(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        account_code: str,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        if not self._enabled:
            return ReconciliationResult(
                reconciliation_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_id,
                subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
                gl_balance=Decimal(0),
                subledger_balance=Decimal(0),
                difference=Decimal(0),
                tolerance=self._tolerance,
                status=ReconciliationStatus.MATCHED,
                reconciled_by=user_id or "system",
                reconciled_at=datetime.now(UTC),
                notes="Enforcer disabled",
            )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        subledger_type = self._get_subledger_type_from_account(account_code)
        if subledger_type is None:
            return ReconciliationResult(
                reconciliation_id=uuid4(),
                legal_entity_id=legal_entity_id,
                period_id=period_id,
                subledger_type=SubledgerType.ACCOUNTS_RECEIVABLE,
                gl_balance=Decimal(0),
                subledger_balance=Decimal(0),
                difference=Decimal(0),
                tolerance=self._tolerance,
                status=ReconciliationStatus.MATCHED,
                reconciled_by=user_id,
                reconciled_at=datetime.now(UTC),
                notes="Non-subledger account, no reconciliation required",
            )

        gl_balance = await self._ledger_repo.get_balance(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            account_code=account_code,
        )

        if subledger_type == SubledgerType.ACCOUNTS_RECEIVABLE:
            subledger_balance = await self._subledger_repo.get_ar_balance(
                legal_entity_id=legal_entity_id,
                period_id=period_id,
            )
        elif subledger_type == SubledgerType.ACCOUNTS_PAYABLE:
            subledger_balance = await self._subledger_repo.get_ap_balance(
                legal_entity_id=legal_entity_id,
                period_id=period_id,
            )
        elif subledger_type == SubledgerType.INVENTORY:
            subledger_balance = await self._subledger_repo.get_inventory_balance(
                legal_entity_id=legal_entity_id,
                period_id=period_id,
            )
        elif subledger_type == SubledgerType.FIXED_ASSET:
            subledger_balance = await self._subledger_repo.get_fixed_asset_balance(
                legal_entity_id=legal_entity_id,
                period_id=period_id,
            )
        else:
            subledger_balance = Decimal(0)

        difference = gl_balance - subledger_balance
        abs_diff = abs(difference)
        is_matched = abs_diff <= self._tolerance

        status = ReconciliationStatus.MATCHED if is_matched else ReconciliationStatus.MISMATCHED
        adjustment_journal_id = None

        if not is_matched and auto_correct and abs_diff <= self._auto_correct_threshold:
            adjustment_journal_id = uuid4()
            status = ReconciliationStatus.ADJUSTMENT_NEEDED
            logger.info(f"Auto-correction triggered for {account_code}: difference {difference}")

        result = ReconciliationResult(
            reconciliation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            subledger_type=subledger_type,
            gl_balance=gl_balance,
            subledger_balance=subledger_balance,
            difference=difference,
            tolerance=self._tolerance,
            status=status,
            reconciled_by=user_id,
            reconciled_at=datetime.now(UTC),
            adjustment_journal_id=adjustment_journal_id,
            notes=f"GL balance: {gl_balance}, Subledger: {subledger_balance}, Diff: {difference}",
            cryptographic_hash="",
        )
        result.cryptographic_hash = result.compute_hash()

        await self._ledger_repo.record_reconciliation(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            reconciliation_type=f"{subledger_type.value}_TO_GL",
            result=result.to_dict(),
            reconciled_by=user_id,
        )

        with self._lock:
            self._reconciliation_history.append(result)
            if len(self._reconciliation_history) > self._max_history:
                self._reconciliation_history = self._reconciliation_history[-self._max_history :]

        if not is_matched and not auto_correct:
            violation = GLSupremacyViolation(
                message=(
                    f"GL/Subledger mismatch for {subledger_type.value} (account {account_code}): "
                    f"GL={gl_balance}, Subledger={subledger_balance}, diff={difference}"
                ),
                account_code=account_code,
                gl_balance=str(gl_balance),
                subledger_balance=str(subledger_balance),
                severity=LawViolationSeverity.CRITICAL,
                details={
                    "legal_entity_id": str(legal_entity_id),
                    "period_id": str(period_id),
                    "difference": str(difference),
                    "tolerance": str(self._tolerance),
                },
            )
            self._record_violation(violation)
            raise violation

        return result

    async def reconcile_ar_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        ar_control_account = "1.1.01"
        return await self.enforce_gl_supremacy(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            account_code=ar_control_account,
            user_id=user_id,
            auto_correct=auto_correct,
        )

    async def reconcile_ap_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        ap_control_account = "2.1.01"
        return await self.enforce_gl_supremacy(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            account_code=ap_control_account,
            user_id=user_id,
            auto_correct=auto_correct,
        )

    async def reconcile_inventory_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        inventory_account = "1.3.01"
        return await self.enforce_gl_supremacy(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            account_code=inventory_account,
            user_id=user_id,
            auto_correct=auto_correct,
        )

    async def reconcile_fixed_asset_to_gl(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
        auto_correct: bool = False,
    ) -> ReconciliationResult:
        fa_account = "1.6.01"
        return await self.enforce_gl_supremacy(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
            account_code=fa_account,
            user_id=user_id,
            auto_correct=auto_correct,
        )

    async def reconcile_all_subledgers(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        user_id: str | None = None,
    ) -> list[ReconciliationResult]:
        results = []
        results.append(
            await self.reconcile_ar_to_gl(legal_entity_id, period_id, user_id, auto_correct=False)
        )
        results.append(
            await self.reconcile_ap_to_gl(legal_entity_id, period_id, user_id, auto_correct=False)
        )
        results.append(
            await self.reconcile_inventory_to_gl(
                legal_entity_id, period_id, user_id, auto_correct=False
            )
        )
        results.append(
            await self.reconcile_fixed_asset_to_gl(
                legal_entity_id, period_id, user_id, auto_correct=False
            )
        )
        return results

    async def get_reconciliation_status(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
    ) -> ReconciliationHistory:
        reconciliations = await self._ledger_repo.get_reconciliations(
            legal_entity_id=legal_entity_id,
            period_id=period_id,
        )

        results = []
        total_gl = Decimal(0)
        total_sub = Decimal(0)
        all_matched = True
        last_at = None
        last_by = None

        for rec in reconciliations:
            gl = Decimal(str(rec["result"].get("gl_balance", 0)))
            sub = Decimal(str(rec["result"].get("subledger_balance", 0)))
            total_gl += gl
            total_sub += sub
            if not rec["result"].get("is_matched", False):
                all_matched = False
            if rec.get("reconciled_at"):
                last_at = rec["reconciled_at"]
                last_by = rec.get("reconciled_by")

            results.append(
                ReconciliationResult(
                    reconciliation_id=UUID(rec["result"].get("reconciliation_id", str(uuid4()))),
                    legal_entity_id=legal_entity_id,
                    period_id=period_id,
                    subledger_type=SubledgerType(rec["result"].get("subledger_type", "AR")),
                    gl_balance=gl,
                    subledger_balance=sub,
                    difference=gl - sub,
                    tolerance=self._tolerance,
                    status=ReconciliationStatus.MATCHED
                    if rec["result"].get("is_matched", False)
                    else ReconciliationStatus.MISMATCHED,
                    reconciled_by=rec.get("reconciled_by", ""),
                    reconciled_at=rec.get("reconciled_at", datetime.now(UTC)),
                    notes=rec["result"].get("notes", ""),
                )
            )

        total_diff = total_gl - total_sub

        return ReconciliationHistory(
            period_id=period_id,
            legal_entity_id=legal_entity_id,
            reconciliations=results,
            total_gl_balance=total_gl,
            total_subledger_balance=total_sub,
            total_difference=total_diff,
            all_matched=all_matched,
            last_reconciled_at=last_at,
            last_reconciled_by=last_by,
        )

    async def get_reconciliation_details(
        self,
        legal_entity_id: UUID,
        period_id: UUID,
        subledger_type: SubledgerType,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if subledger_type == SubledgerType.ACCOUNTS_RECEIVABLE:
            return await self._subledger_repo.get_ar_details(legal_entity_id, period_id, limit)
        elif subledger_type == SubledgerType.ACCOUNTS_PAYABLE:
            return await self._subledger_repo.get_ap_details(legal_entity_id, period_id, limit)
        elif subledger_type == SubledgerType.INVENTORY:
            return await self._subledger_repo.get_inventory_details(
                legal_entity_id, period_id, limit
            )
        return []

    async def create_adjustment_journal(
        self,
        reconciliation_result: ReconciliationResult,
        adjustment_amount: Decimal,
        adjustment_reason: str,
        user_id: str | None = None,
    ) -> UUID:
        if user_id is None:
            user_id = get_current_user() or "unknown"

        adjustment_journal_id = uuid4()
        self._record_audit("CREATE_ADJUSTMENT_JOURNAL", user_id, {
            "reconciliation_id": str(reconciliation_result.reconciliation_id),
            "subledger_type": reconciliation_result.subledger_type.value,
            "amount": str(adjustment_amount),
            "reason": adjustment_reason,
        })
        logger.warning(
            f"Adjustment journal created for {reconciliation_result.subledger_type.value}: "
            f"amount {adjustment_amount}, reason: {adjustment_reason} by {user_id}"
        )
        return adjustment_journal_id

    def _record_violation(self, violation: GLSupremacyViolation) -> None:
        with self._lock:
            self._violation_history.append(violation)
            if len(self._violation_history) > self._max_history:
                self._violation_history = self._violation_history[-self._max_history :]
            # Use getattr to safely access attributes that may not exist
            user_id = getattr(violation, "user_id", None) or "system"
            severity = getattr(violation, "severity", LawViolationSeverity.CRITICAL)
            self._record_audit(
                "VIOLATION",
                user_id,
                {
                    "account_code": violation.account_code,
                    "severity": severity.name if hasattr(severity, "name") else str(severity),
                }
            )

    def get_reconciliation_history(
        self,
        limit: int = 100,
        legal_entity_id: UUID | None = None,
        period_id: UUID | None = None,
        only_mismatched: bool = False,
    ) -> list[ReconciliationResult]:
        with self._lock:
            results = self._reconciliation_history[-limit:]
        if legal_entity_id:
            results = [r for r in results if r.legal_entity_id == legal_entity_id]
        if period_id:
            results = [r for r in results if r.period_id == period_id]
        if only_mismatched:
            results = [r for r in results if r.status != ReconciliationStatus.MATCHED]
        return results

    def get_violations(
        self,
        limit: int = 100,
        account_code: str | None = None,
    ) -> list[GLSupremacyViolation]:
        with self._lock:
            result = self._violation_history[-limit:]
        if account_code:
            result = [v for v in result if v.account_code == account_code]
        return result

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._reconciliation_history)
            if total == 0:
                return {
                    "total_reconciliations": 0,
                    "total_violations": len(self._violation_history),
                    "enabled": self._enabled,
                    "version": self._version,
                }

            matched = len(
                [
                    r
                    for r in self._reconciliation_history
                    if r.status == ReconciliationStatus.MATCHED
                ]
            )
            mismatched = len(
                [
                    r
                    for r in self._reconciliation_history
                    if r.status == ReconciliationStatus.MISMATCHED
                ]
            )
            adjusted = len(
                [
                    r
                    for r in self._reconciliation_history
                    if r.status == ReconciliationStatus.ADJUSTMENT_NEEDED
                ]
            )

            by_subledger: dict[str, int] = {}
            for r in self._reconciliation_history:
                st = r.subledger_type.value
                by_subledger[st] = by_subledger.get(st, 0) + 1

            mismatched_results = [
                r
                for r in self._reconciliation_history
                if r.status == ReconciliationStatus.MISMATCHED
            ]
            avg_diff = (
                sum(abs(r.difference) for r in mismatched_results) / len(mismatched_results)
                if mismatched_results
                else Decimal(0)
            )

            return {
                "total_reconciliations": total,
                "matched_count": matched,
                "mismatched_count": mismatched,
                "adjusted_count": adjusted,
                "match_rate": matched / total if total > 0 else 0,
                "by_subledger": by_subledger,
                "avg_mismatch_amount": str(avg_diff),
                "tolerance": str(self._tolerance),
                "auto_correct_threshold": str(self._auto_correct_threshold),
                "enabled": self._enabled,
                "total_violations": len(self._violation_history),
                "version": self._version,
                "latest_reconciliation": self._reconciliation_history[-1].reconciled_at.isoformat()
                if self._reconciliation_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._reconciliation_history = []
            self._violation_history = []
            self._tolerance = self.DEFAULT_TOLERANCE
            self._auto_correct_threshold = self.AUTO_CORRECT_THRESHOLD
            self._enabled = True
            self._version += 1
            self._audit_trail = []
            if hasattr(self._ledger_repo, "clear"):
                self._ledger_repo.clear()
            if hasattr(self._subledger_repo, "clear"):
                self._subledger_repo.clear()


# === 4. SINGLETON ACCESSOR ===

_gl_supremacy_enforcer_instance: GLSupremacyEnforcer | None = None
_lock_instance = threading.Lock()


def get_gl_supremacy_enforcer() -> GLSupremacyEnforcer:
    global _gl_supremacy_enforcer_instance
    if _gl_supremacy_enforcer_instance is None:
        with _lock_instance:
            if _gl_supremacy_enforcer_instance is None:
                _gl_supremacy_enforcer_instance = GLSupremacyEnforcer()
    return _gl_supremacy_enforcer_instance


# === 5. EXPORTS ===

__all__ = [
    "GLSupremacyEnforcer",
    "ReconciliationHistory",
    "ReconciliationResult",
    "ReconciliationStatus",
    "SubledgerType",
    "get_gl_supremacy_enforcer",
]
