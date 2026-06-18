#!/usr/bin/env python3
"""
Module: budget_availability.py
Layer: 4 - Kernel / Guards
Responsibility: Memeriksa ketersediaan anggaran sebelum transaksi.
               Guard ini memvalidasi apakah transaksi yang akan dilakukan
               (terutama belanja, investasi, atau komitmen biaya) masih
               dalam batas anggaran yang telah disetujui untuk periode
               dan cost center tertentu.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity
from kernel.guards.guard_exceptions import (
    BudgetAvailabilityError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# FALLBACK BUDGET REPOSITORY (in-memory)
# ============================================================================


class _FallbackBudgetRepository:
    def __init__(self):
        self._budgets: dict[UUID, dict[str, Any]] = {}
        self._usage: dict[UUID, Decimal] = {}
        self._reservations: dict[UUID, dict[UUID, Decimal]] = {}

    async def get_active_budget(
        self,
        legal_entity_id: UUID,
        cost_center_id: UUID,
        account_code: str,
        as_of: datetime,
    ) -> Any | None:
        for bid, budget in self._budgets.items():
            if (
                budget.get("legal_entity_id") == legal_entity_id
                and budget.get("cost_center_id") == cost_center_id
                and budget.get("account_code") == account_code
                and budget.get("period_start") <= as_of <= budget.get("period_end")
            ):
                return type(
                    "Budget",
                    (),
                    {
                        "budget_id": bid,
                        "amount": budget.get("amount", Decimal(0)),
                        "period_start": budget.get("period_start"),
                        "period_end": budget.get("period_end"),
                    },
                )()
        return None

    async def get_actual_usage(
        self,
        budget_id: UUID,
        cost_center_id: UUID,
        account_code: str,
        period_start: datetime,
        period_end: datetime,
    ) -> Decimal:
        return self._usage.get(budget_id, Decimal(0))

    async def reserve_amount(
        self,
        budget_id: UUID,
        amount: Decimal,
        transaction_id: UUID,
        reservation_type: str,
    ) -> bool:
        if budget_id not in self._reservations:
            self._reservations[budget_id] = {}
        self._reservations[budget_id][transaction_id] = amount
        current = self._usage.get(budget_id, Decimal(0))
        self._usage[budget_id] = current + amount
        return True

    async def release_amount(
        self,
        budget_id: UUID,
        amount: Decimal,
        transaction_id: UUID,
    ) -> bool:
        if budget_id in self._reservations:
            self._reservations[budget_id].pop(transaction_id, None)
            current = self._usage.get(budget_id, Decimal(0))
            self._usage[budget_id] = max(Decimal(0), current - amount)
        return True

    def add_budget(self, budget_id: UUID, data: dict[str, Any]):
        self._budgets[budget_id] = data


def _get_budget_repository():
    logger.info("Using in-memory fallback for budget repository (no infrastructure)")
    return _FallbackBudgetRepository()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class BudgetCheckMode(Enum):
    STRICT = "strict"
    WARNING = "warning"
    FLEXIBLE = "flexible"
    DISABLED = "disabled"


class BudgetPeriodType(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    CUSTOM = "custom"


class BudgetCheckSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


@dataclass
class BudgetCheckResult:
    check_id: UUID
    is_available: bool
    budget_id: UUID | None
    cost_center_id: UUID
    account_code: str
    budget_amount: Decimal
    used_amount: Decimal
    available_amount: Decimal
    requested_amount: Decimal
    overage: Decimal
    severity: BudgetCheckSeverity
    message: str
    requires_approval: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""

    def compute_hash(self) -> str:
        content = (
            f"{self.check_id}|{self.is_available}|{self.budget_id}|{self.cost_center_id}|"
            f"{self.account_code}|{self.overage}|{self.requires_approval}"
        )
        return hashlib.sha3_256(content.encode()).hexdigest()

    def __post_init__(self):
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "is_available": self.is_available,
            "budget_id": str(self.budget_id) if self.budget_id else None,
            "cost_center_id": str(self.cost_center_id),
            "account_code": self.account_code,
            "budget_amount": str(self.budget_amount),
            "used_amount": str(self.used_amount),
            "available_amount": str(self.available_amount),
            "requested_amount": str(self.requested_amount),
            "overage": str(self.overage),
            "severity": self.severity.name,
            "message": self.message,
            "requires_approval": self.requires_approval,
        }


# ============================================================================
# BUDGET AVAILABILITY GUARD
# ============================================================================


class BudgetAvailabilityGuard:
    def __init__(self, budget_repository: Any | None = None):
        self._budget_repo = budget_repository or _get_budget_repository()
        self._mode = BudgetCheckMode.STRICT
        self._tolerance_percentage = Decimal("5")
        self._check_history: list[BudgetCheckResult] = []
        self._max_history = 10000
        self._lock = threading.RLock()

    def set_mode(self, mode: BudgetCheckMode) -> None:
        self._mode = mode
        logger.info(f"Budget check mode set to {mode.value}")

    def set_tolerance(self, percentage: Decimal) -> None:
        if 0 <= percentage <= 100:
            self._tolerance_percentage = percentage
            logger.info(f"Budget tolerance set to {percentage}%")

    async def check_budget(
        self,
        cost_center_id: UUID,
        account_code: str,
        amount: Decimal,
        transaction_date: datetime,
        legal_entity_id: UUID | None = None,
        period_type: BudgetPeriodType = BudgetPeriodType.MONTHLY,
    ) -> BudgetCheckResult:
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return BudgetCheckResult(
                    check_id=uuid4(),
                    is_available=True,
                    budget_id=None,
                    cost_center_id=cost_center_id,
                    account_code=account_code,
                    budget_amount=Decimal(0),
                    used_amount=Decimal(0),
                    available_amount=Decimal(0),
                    requested_amount=amount,
                    overage=Decimal(0),
                    severity=BudgetCheckSeverity.LOW,
                    message="No legal entity in context, skipping budget check",
                    requires_approval=False,
                )

        budget = await self._budget_repo.get_active_budget(
            legal_entity_id=legal_entity_id,
            cost_center_id=cost_center_id,
            account_code=account_code,
            as_of=transaction_date,
        )

        if not budget:
            if self._mode == BudgetCheckMode.STRICT:
                return BudgetCheckResult(
                    check_id=uuid4(),
                    is_available=False,
                    budget_id=None,
                    cost_center_id=cost_center_id,
                    account_code=account_code,
                    budget_amount=Decimal(0),
                    used_amount=Decimal(0),
                    available_amount=Decimal(0),
                    requested_amount=amount,
                    overage=amount,
                    severity=BudgetCheckSeverity.HIGH,
                    message=f"No budget defined for cost center {cost_center_id}, account {account_code}",
                    requires_approval=True,
                )
            else:
                return BudgetCheckResult(
                    check_id=uuid4(),
                    is_available=True,
                    budget_id=None,
                    cost_center_id=cost_center_id,
                    account_code=account_code,
                    budget_amount=Decimal(0),
                    used_amount=Decimal(0),
                    available_amount=Decimal(0),
                    requested_amount=amount,
                    overage=Decimal(0),
                    severity=BudgetCheckSeverity.LOW,
                    message="No budget defined, but mode allows transaction",
                    requires_approval=False,
                )

        used_amount = await self._budget_repo.get_actual_usage(
            budget_id=budget.budget_id,
            cost_center_id=cost_center_id,
            account_code=account_code,
            period_start=budget.period_start,
            period_end=budget.period_end,
        )

        budget_amount = budget.amount
        available = budget_amount - used_amount
        new_usage = used_amount + amount
        overage = new_usage - budget_amount if new_usage > budget_amount else Decimal(0)

        is_available = new_usage <= budget_amount
        requires_approval = False
        severity = BudgetCheckSeverity.INFO
        message = ""

        if not is_available:
            if self._mode == BudgetCheckMode.WARNING:
                tolerance = budget_amount * (self._tolerance_percentage / Decimal(100))
                if overage <= tolerance:
                    is_available = True
                    severity = BudgetCheckSeverity.MEDIUM
                    message = f"Warning: Transaction would exceed budget by {overage} (within {self._tolerance_percentage}% tolerance)"
                else:
                    severity = BudgetCheckSeverity.HIGH
                    message = f"Budget exceeded by {overage} (exceeds tolerance)"
            elif self._mode == BudgetCheckMode.FLEXIBLE:
                requires_approval = True
                severity = BudgetCheckSeverity.HIGH
                message = f"Budget exceeded by {overage}. Requires managerial approval."
            else:
                severity = BudgetCheckSeverity.CRITICAL
                message = f"Insufficient budget: available {available}, requested {amount}"

        result = BudgetCheckResult(
            check_id=uuid4(),
            is_available=is_available,
            budget_id=budget.budget_id,
            cost_center_id=cost_center_id,
            account_code=account_code,
            budget_amount=budget_amount,
            used_amount=used_amount,
            available_amount=available,
            requested_amount=amount,
            overage=overage,
            severity=severity,
            message=message,
            requires_approval=requires_approval,
            cryptographic_hash="",
        )
        result = BudgetCheckResult(
            check_id=result.check_id,
            is_available=result.is_available,
            budget_id=result.budget_id,
            cost_center_id=result.cost_center_id,
            account_code=result.account_code,
            budget_amount=result.budget_amount,
            used_amount=result.used_amount,
            available_amount=result.available_amount,
            requested_amount=result.requested_amount,
            overage=result.overage,
            severity=result.severity,
            message=result.message,
            requires_approval=result.requires_approval,
            timestamp=result.timestamp,
            cryptographic_hash=result.compute_hash(),
        )

        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        return result

    async def check_multiple_budgets(
        self,
        budget_checks: list[dict[str, Any]],
        legal_entity_id: UUID | None = None,
    ) -> tuple[bool, list[BudgetCheckResult]]:
        results = []
        overall_available = True
        for check in budget_checks:
            result = await self.check_budget(
                cost_center_id=check["cost_center_id"],
                account_code=check["account_code"],
                amount=check["amount"],
                transaction_date=check.get("transaction_date", datetime.now(UTC)),
                legal_entity_id=legal_entity_id,
            )
            results.append(result)
            if not result.is_available:
                overall_available = False
        return overall_available, results

    async def reserve_budget(
        self,
        budget_id: UUID,
        amount: Decimal,
        transaction_id: UUID,
        reservation_type: str = "COMMITTED",
    ) -> bool:
        success = await self._budget_repo.reserve_amount(
            budget_id=budget_id,
            amount=amount,
            transaction_id=transaction_id,
            reservation_type=reservation_type,
        )
        if success:
            logger.debug(
                f"Reserved {amount} from budget {budget_id} for transaction {transaction_id}"
            )
        return success

    async def release_budget(
        self,
        budget_id: UUID,
        amount: Decimal,
        transaction_id: UUID,
    ) -> bool:
        success = await self._budget_repo.release_amount(
            budget_id=budget_id,
            amount=amount,
            transaction_id=transaction_id,
        )
        if success:
            logger.debug(
                f"Released {amount} from budget {budget_id} for transaction {transaction_id}"
            )
        return success

    async def enforce(
        self,
        cost_center_id: UUID,
        account_code: str,
        amount: Decimal,
        transaction_date: datetime,
        legal_entity_id: UUID | None = None,
        require_approval_override: bool = False,
        raise_on_violation: bool = True,
    ) -> BudgetCheckResult:
        result = await self.check_budget(
            cost_center_id=cost_center_id,
            account_code=account_code,
            amount=amount,
            transaction_date=transaction_date,
            legal_entity_id=legal_entity_id,
        )

        if not result.is_available and raise_on_violation:
            if result.requires_approval and not require_approval_override:
                raise BudgetAvailabilityError(
                    message=f"Budget approval required: {result.message}",
                    cost_center=str(cost_center_id),
                    account=account_code,
                    severity=GuardSeverity.HIGH,
                    details=result.to_dict(),
                )
            elif not result.requires_approval:
                raise BudgetAvailabilityError(
                    message=f"Budget insufficient: {result.message}",
                    cost_center=str(cost_center_id),
                    account=account_code,
                    severity=GuardSeverity.CRITICAL,
                    details=result.to_dict(),
                )
            else:
                logger.warning(f"Budget override approved: {result.message}")

        return result

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        cost_center_id: UUID | None = None,
    ) -> list[BudgetCheckResult]:
        with self._lock:
            results = self._check_history[-limit:]
        if only_violations:
            results = [r for r in results if not r.is_available]
        if cost_center_id:
            results = [r for r in results if r.cost_center_id == cost_center_id]
        return results

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {"total_checks": 0}
            violations = [r for r in self._check_history if not r.is_available]
            violation_count = len(violations)
            by_severity = {}
            for v in violations:
                by_severity[v.severity.name] = by_severity.get(v.severity.name, 0) + 1
            return {
                "total_checks": total,
                "violation_count": violation_count,
                "violation_rate": violation_count / total if total > 0 else 0,
                "by_severity": by_severity,
                "mode": self._mode.value,
                "tolerance_percentage": str(self._tolerance_percentage),
                "latest_check": self._check_history[-1].timestamp.isoformat()
                if self._check_history
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._check_history = []


# ============================================================================
# SINGLETON ACCESSOR
# ============================================================================

_budget_availability_guard_instance: BudgetAvailabilityGuard | None = None
_lock_instance = threading.Lock()


def get_budget_availability_guard() -> BudgetAvailabilityGuard:
    global _budget_availability_guard_instance
    if _budget_availability_guard_instance is None:
        with _lock_instance:
            if _budget_availability_guard_instance is None:
                _budget_availability_guard_instance = BudgetAvailabilityGuard()
    return _budget_availability_guard_instance


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BudgetAvailabilityGuard",
    "BudgetCheckMode",
    "BudgetCheckResult",
    "BudgetCheckSeverity",
    "BudgetPeriodType",
    "get_budget_availability_guard",
]
