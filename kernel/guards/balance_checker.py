#!/usr/bin/env python3
"""
Module: balance_checker.py
Layer: 4 - Kernel / Guards
Responsibility: Memeriksa saldo akun agar tidak negatif untuk akun tertentu.
               Guard ini memastikan bahwa saldo akun aset (seperti kas, piutang)
               tidak menjadi negatif. Untuk akun liabilitas/ekuitas, saldo negatif
               mungkin diizinkan tergantung kebijakan.

               Catatan: Balance checker ini menggunakan fallback in-memory
               untuk account repository karena tidak ada ketergantungan infrastruktur
               di lapisan kernel. Ini adalah desain yang disengaja untuk menjaga
               kernel tetap independen dan mudah di-test.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    BalanceCheckerError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)

# ============================================================================
# ALIAS SEMENTARA (untuk mencegah ImportError saat modul di-load)
# ============================================================================
# Ini akan diisi dengan instance singleton yang sebenarnya di bagian akhir file.
balance_checker = None


# ============================================================================
# FALLBACK ACCOUNT REPOSITORY (in-memory, no infrastructure)
# ============================================================================
# Ini adalah fallback yang sengaja digunakan karena kernel tidak boleh
# bergantung pada infrastruktur database. Semua logika balance checker
# diuji dengan repository ini.
# ============================================================================

class _FallbackAccountRepository:
    def __init__(self):
        self._accounts: dict[UUID, dict[str, Any]] = {}
        self._balances: dict[
            tuple[UUID, UUID], Decimal
        ] = {}  # (account_id, legal_entity_id) -> balance

    async def get_by_id(self, account_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        return self._accounts.get(account_id)

    async def get_balance(self, account_id: UUID, legal_entity_id: UUID) -> Decimal:
        key = (account_id, legal_entity_id)
        return self._balances.get(key, Decimal(0))

    async def update_balance(
        self, account_id: UUID, legal_entity_id: UUID, new_balance: Decimal
    ) -> None:
        key = (account_id, legal_entity_id)
        self._balances[key] = new_balance

    def register_account(
        self, account_id: UUID, account_code: str, account_type: str, currency: str = "IDR"
    ):
        self._accounts[account_id] = {
            "account_id": account_id,
            "account_code": account_code,
            "account_type": account_type,
            "currency": currency,
        }


def _get_account_repository():
    # Selalu gunakan fallback in-memory (disengaja)
    logger.info("Using in-memory fallback for account repository (kernel independence)")
    return _FallbackAccountRepository()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class AccountType(Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"
    CONTRA_ASSET = "contra_asset"
    CONTRA_LIABILITY = "contra_liability"

    def allows_negative_balance(self) -> bool:
        if self in (AccountType.ASSET, AccountType.EXPENSE, AccountType.CONTRA_LIABILITY):
            return False
        return True


class BalanceCheckSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


@dataclass
class BalanceCheckResult:
    check_id: UUID
    account_id: UUID
    account_code: str
    account_type: AccountType
    legal_entity_id: UUID
    current_balance: Decimal
    proposed_change: Decimal
    new_balance: Decimal
    is_allowed: bool
    severity: BalanceCheckSeverity
    message: str
    requires_approval: bool = False
    approved_by: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": str(self.check_id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "account_type": self.account_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "current_balance": str(self.current_balance),
            "proposed_change": str(self.proposed_change),
            "new_balance": str(self.new_balance),
            "is_allowed": self.is_allowed,
            "severity": self.severity.name,
            "message": self.message,
            "requires_approval": self.requires_approval,
            "timestamp": self.timestamp.isoformat(),
        }


# ============================================================================
# BALANCE CHECKER
# ============================================================================


class BalanceChecker:
    def __init__(self, account_repository: Any | None = None):
        self._account_repo = account_repository or _get_account_repository()
        self._check_history: list[BalanceCheckResult] = []
        self._max_history = 10000
        self._lock = threading.RLock()
        self._tolerance = Decimal("0.01")
        self._warning_threshold_percentage = Decimal("85")

    def set_tolerance(self, tolerance: Decimal) -> None:
        self._tolerance = tolerance

    def _get_account_type(self, account_code: str) -> AccountType:
        if not account_code:
            return AccountType.ASSET
        first_digit = account_code[0] if account_code else "1"
        mapping = {
            "1": AccountType.ASSET,
            "2": AccountType.LIABILITY,
            "3": AccountType.EQUITY,
            "4": AccountType.REVENUE,
            "5": AccountType.EXPENSE,
            "6": AccountType.CONTRA_ASSET,
            "7": AccountType.CONTRA_LIABILITY,
        }
        return mapping.get(first_digit, AccountType.ASSET)

    async def check_balance(
        self,
        account_id: UUID,
        proposed_change: Decimal,
        legal_entity_id: UUID | None = None,
        allow_negative: bool = False,
        currency: str = "IDR",
        user_id: str | None = None,
    ) -> BalanceCheckResult:
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return BalanceCheckResult(
                    check_id=uuid4(),
                    account_id=account_id,
                    account_code="UNKNOWN",
                    account_type=AccountType.ASSET,
                    legal_entity_id=UUID(int=0),
                    current_balance=Decimal(0),
                    proposed_change=proposed_change,
                    new_balance=proposed_change,
                    is_allowed=False,
                    severity=BalanceCheckSeverity.HIGH,
                    message="No legal entity in context",
                )

        if user_id is None:
            user_id = get_current_user() or "unknown"

        account_data = await self._account_repo.get_by_id(account_id, legal_entity_id)
        if not account_data:
            account_code = str(account_id)[:8]
            account_type = self._get_account_type(account_code)
            current_balance = Decimal(0)
        else:
            account_code = account_data.get("account_code", str(account_id))
            account_type = self._get_account_type(account_code)
            current_balance = await self._account_repo.get_balance(account_id, legal_entity_id)

        new_balance = current_balance + proposed_change
        inherently_allows = account_type.allows_negative_balance()
        final_allow_negative = allow_negative or inherently_allows

        is_negative = new_balance < -self._tolerance
        is_allowed = not is_negative or final_allow_negative

        severity = BalanceCheckSeverity.INFO
        message = ""
        requires_approval = False

        if is_negative and not final_allow_negative:
            severity = BalanceCheckSeverity.CRITICAL
            message = (
                f"Account {account_code} would have negative balance {new_balance:.2f} "
                f"(current: {current_balance:.2f}, change: {proposed_change:+.2f})"
            )
            if not inherently_allows:
                message += ". This account type does not allow negative balances."
        elif is_negative and final_allow_negative and not inherently_allows:
            severity = BalanceCheckSeverity.HIGH
            message = f"Account {account_code} would have negative balance {new_balance:.2f} (override allowed)"
            requires_approval = True
        elif is_negative and final_allow_negative and inherently_allows:
            severity = BalanceCheckSeverity.LOW
            message = f"Account {account_code} would have negative balance {new_balance:.2f} (allowed for this account type)"
        else:
            if account_type == AccountType.ASSET and current_balance > 0:
                usage_percentage = (
                    (current_balance - new_balance) / current_balance * 100
                    if current_balance > 0
                    else 0
                )
                if usage_percentage >= self._warning_threshold_percentage:
                    severity = BalanceCheckSeverity.MEDIUM
                    message = f"Account {account_code} balance would decrease by {usage_percentage:.1f}% to {new_balance:.2f}"

        if account_data and account_data.get("currency") != currency:
            is_allowed = False
            severity = BalanceCheckSeverity.CRITICAL
            message = f"Currency mismatch: account uses {account_data.get('currency')}, transaction uses {currency}"

        result = BalanceCheckResult(
            check_id=uuid4(),
            account_id=account_id,
            account_code=account_code,
            account_type=account_type,
            legal_entity_id=legal_entity_id,
            current_balance=current_balance,
            proposed_change=proposed_change,
            new_balance=new_balance,
            is_allowed=is_allowed,
            severity=severity,
            message=message,
            requires_approval=requires_approval,
        )

        with self._lock:
            self._check_history.append(result)
            if len(self._check_history) > self._max_history:
                self._check_history = self._check_history[-self._max_history :]

        if not is_allowed or severity.value >= BalanceCheckSeverity.HIGH.value:
            log_level = logging.ERROR if not is_allowed else logging.WARNING
            logger.log(log_level, f"Balance check: {result.message} (allowed={is_allowed})")

        return result

    async def check_balance_before_transaction(
        self,
        account_debits: dict[UUID, Decimal],
        account_credits: dict[UUID, Decimal],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        results = []
        for account_id, debit in account_debits.items():
            result = await self.check_balance(
                account_id=account_id,
                proposed_change=-debit,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
            )
            if not result.is_allowed or result.severity.value >= BalanceCheckSeverity.HIGH.value:
                results.append(result)
        for account_id, credit in account_credits.items():
            result = await self.check_balance(
                account_id=account_id,
                proposed_change=credit,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
            )
            if not result.is_allowed or result.severity.value >= BalanceCheckSeverity.HIGH.value:
                results.append(result)
        return results

    async def check_batch_balances(
        self,
        transactions: list[dict[str, Any]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        results = []
        temp_balances: dict[UUID, Decimal] = {}
        for tx in transactions:
            account_id = tx["account_id"]
            amount = tx["amount"]
            is_debit = tx.get("is_debit", True)
            current = await self._account_repo.get_balance(account_id, legal_entity_id)
            current_with_temp = temp_balances.get(account_id, current)
            proposed_change = -amount if is_debit else amount
            new_balance = current_with_temp + proposed_change
            account_data = await self._account_repo.get_by_id(account_id, legal_entity_id)
            account_code = (
                account_data.get("account_code", str(account_id))
                if account_data
                else str(account_id)
            )
            account_type = self._get_account_type(account_code)
            inherently_allows = account_type.allows_negative_balance()
            is_allowed = new_balance >= -self._tolerance or inherently_allows
            if not is_allowed:
                result = BalanceCheckResult(
                    check_id=uuid4(),
                    account_id=account_id,
                    account_code=account_code,
                    account_type=account_type,
                    legal_entity_id=legal_entity_id or UUID(int=0),
                    current_balance=current,
                    proposed_change=proposed_change,
                    new_balance=new_balance,
                    is_allowed=False,
                    severity=BalanceCheckSeverity.CRITICAL,
                    message=f"Batch transaction would cause negative balance on {account_code}: {new_balance:.2f}",
                )
                results.append(result)
            temp_balances[account_id] = new_balance
        return results

    async def enforce(
        self,
        account_id: UUID,
        proposed_change: Decimal,
        legal_entity_id: UUID | None = None,
        allow_negative: bool = False,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> BalanceCheckResult:
        result = await self.check_balance(
            account_id=account_id,
            proposed_change=proposed_change,
            legal_entity_id=legal_entity_id,
            allow_negative=allow_negative,
            user_id=user_id,
        )
        if not result.is_allowed and raise_on_violation:
            raise BalanceCheckerError(
                message=result.message,
                account_code=result.account_code,
                current_balance=result.current_balance,
                severity=GuardSeverity.CRITICAL,
                details=result.to_dict(),
            )
        return result

    async def enforce_multi_balance(
        self,
        account_balances: list[tuple[UUID, Decimal]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        violations = []
        for account_id, change in account_balances:
            result = await self.enforce(
                account_id=account_id,
                proposed_change=change,
                legal_entity_id=legal_entity_id,
                user_id=user_id,
                raise_on_violation=False,
            )
            if not result.is_allowed:
                violations.append(result)
        return violations

    def get_check_history(
        self,
        limit: int = 100,
        only_violations: bool = False,
        account_id: UUID | None = None,
    ) -> list[BalanceCheckResult]:
        with self._lock:
            results = self._check_history[-limit:]
        if only_violations:
            results = [r for r in results if not r.is_allowed]
        if account_id:
            results = [r for r in results if r.account_id == account_id]
        return results

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._check_history)
            if total == 0:
                return {"total_checks": 0}
            violations = [r for r in self._check_history if not r.is_allowed]
            violation_count = len(violations)
            by_severity = {}
            for sev in BalanceCheckSeverity:
                count = len([r for r in violations if r.severity == sev])
                if count > 0:
                    by_severity[sev.name] = count
            by_account = {}
            for r in violations:
                code = r.account_code
                by_account[code] = by_account.get(code, 0) + 1
            return {
                "total_checks": total,
                "violation_count": violation_count,
                "violation_rate": violation_count / total if total > 0 else 0,
                "by_severity": by_severity,
                "by_account": by_account,
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

_balance_checker_instance: BalanceChecker | None = None
_lock_instance = threading.Lock()


def get_balance_checker() -> BalanceChecker:
    global _balance_checker_instance
    if _balance_checker_instance is None:
        with _lock_instance:
            if _balance_checker_instance is None:
                # Inisialisasi dengan fallback repository
                # Ini aman untuk kernel dan tidak memerlukan set_balance_checker
                _balance_checker_instance = BalanceChecker()
    return _balance_checker_instance


# ============================================================================
# FUNGSI UNTUK TESTING
# ============================================================================
def create_test_balance_checker(repository: Any = None) -> BalanceChecker:
    """
    Buat instance BalanceChecker untuk keperluan testing.
    Jika repository tidak diberikan, akan menggunakan fallback in-memory.
    """
    return BalanceChecker(account_repository=repository or _get_account_repository())


# ============================================================================
# ALIAS FINAL (mengganti None dengan instance singleton yang sebenarnya)
# ============================================================================

# Sekarang setelah class dan fungsi singleton sudah didefinisikan,
# kita isi alias dengan instance yang sebenarnya.
balance_checker = get_balance_checker()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AccountType",
    "BalanceCheckResult",
    "BalanceCheckSeverity",
    "BalanceChecker",
    "balance_checker",
    "get_balance_checker",
    "create_test_balance_checker",
]