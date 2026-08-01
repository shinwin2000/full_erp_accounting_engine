#!/usr/bin/env python3
"""
Module: balance_checker.py
Layer: 4 - Kernel / Guards

Responsibility:
    Pure domain guard to ensure account balances do not go negative for
    certain account types (e.g., assets, expenses). This is a stateless
    guard that relies on an injected AccountBalancePort to fetch account
    metadata and balances.

Design decisions:
    - No global state or singleton; lifecycle managed by DI container.
    - No fallback to in-memory repository by default; port must be provided.
    - Stateless: history, statistics, and reset are delegated to audit/telemetry.
    - Kernel independence: depends only on the AccountBalancePort protocol.
    - Testing: use InMemoryAccountBalancePort from `tests/fakes/` or create
      a test double directly.

Usage (production):
    from kernel.guards.balance_checker import BalanceChecker
    from infrastructure.adapters.sqlalchemy_account_balance_port import SqlAlchemyAccountBalancePort

    port = SqlAlchemyAccountBalancePort(session_factory)
    checker = BalanceChecker(port)

    result = await checker.check_balance(
        account_id=account_id,
        proposed_change=Decimal("-100000"),
        legal_entity_id=legal_entity_id,
    )

Usage (testing):
    from kernel.guards.balance_checker import BalanceChecker
    from tests.fakes.in_memory_account_balance_port import InMemoryAccountBalancePort

    port = InMemoryAccountBalancePort()
    checker = BalanceChecker(port)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from kernel.context_holder import get_current_legal_entity, get_current_user
from kernel.guards.guard_exceptions import (
    BalanceCheckerError,
    GuardSeverity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Protocol: AccountBalancePort (kernel contract)
# ============================================================================
@runtime_checkable
class AccountBalancePort(Protocol):
    """Port for fetching account metadata and balances."""

    async def get_account(self, account_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        """
        Fetch account metadata.

        Expected return dict:
            {
                "account_code": str,
                "account_type": str,  # e.g., "ASSET", "LIABILITY", etc.
                "currency": str,
                "name": str,
            }
        Returns None if account not found.
        """
        ...

    async def get_balance(self, account_id: UUID, legal_entity_id: UUID) -> Decimal:
        """
        Fetch current balance for the account in the given legal entity.
        """
        ...

    async def get_balances(self, account_ids: list[UUID], legal_entity_id: UUID) -> dict[UUID, Decimal]:
        """
        Fetch balances for multiple accounts in one batch call.
        """
        ...


# ============================================================================
# Enums
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
        # Assets and expenses typically should not be negative.
        # Contra-liability also should not be negative (it's a debit balance).
        # Return the negated condition directly (SIM103)
        return self not in (AccountType.ASSET, AccountType.EXPENSE, AccountType.CONTRA_LIABILITY)

    @classmethod
    def from_string(cls, value: str) -> AccountType:
        """Parse from string (case-insensitive)."""
        try:
            return cls(value.lower())
        except ValueError:
            raise ValueError(f"Invalid account type: {value}")

    @classmethod
    def from_code(cls, code: str) -> AccountType:
        """
        Infer account type from account code first digit (legacy fallback).
        Only use if the port does not return explicit account_type.
        """
        if not code:
            return cls.ASSET
        first = code[0]
        mapping = {
            "1": cls.ASSET,
            "2": cls.LIABILITY,
            "3": cls.EQUITY,
            "4": cls.REVENUE,
            "5": cls.EXPENSE,
            "6": cls.CONTRA_ASSET,
            "7": cls.CONTRA_LIABILITY,
        }
        return mapping.get(first, cls.ASSET)


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
# BASE BALANCE CHECKER (ABSTRACT)
# ============================================================================

class BaseBalanceChecker(ABC):
    """Base contract untuk Balance Checker."""

    @abstractmethod
    async def check_balance(
        self,
        account_id: UUID,
        proposed_change: Decimal,
        legal_entity_id: UUID | None = None,
        allow_negative: bool = False,
        currency: str = "IDR",
        user_id: str | None = None,
    ) -> BalanceCheckResult:
        """Check if proposed change would cause invalid negative balance."""
        pass

    @abstractmethod
    async def check_balance_before_transaction(
        self,
        account_debits: dict[UUID, Decimal],
        account_credits: dict[UUID, Decimal],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        """Check balances for a transaction with multiple debits and credits."""
        pass

    @abstractmethod
    async def check_batch_balances(
        self,
        transactions: list[dict[str, Any]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        """Check balances for a batch of transactions efficiently."""
        pass

    @abstractmethod
    async def enforce(
        self,
        account_id: UUID,
        proposed_change: Decimal,
        legal_entity_id: UUID | None = None,
        allow_negative: bool = False,
        user_id: str | None = None,
        raise_on_violation: bool = True,
    ) -> BalanceCheckResult:
        """Enforce balance check, raise exception on violation."""
        pass

    @abstractmethod
    async def enforce_multi_balance(
        self,
        account_balances: list[tuple[UUID, Decimal]],
        legal_entity_id: UUID | None = None,
        user_id: str | None = None,
    ) -> list[BalanceCheckResult]:
        """Enforce balance checks for multiple account changes."""
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
    def from_dict(cls, data: dict[str, Any]) -> BaseBalanceChecker:
        """Reconstruct dari dictionary."""
        pass

    @abstractmethod
    def clone(self) -> BaseBalanceChecker:
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
    def touch(self, touched_by: str) -> BaseBalanceChecker:
        """Touch instance (increment version)."""
        pass


# ============================================================================
# Balance Checker (Stateless Guard)
# ============================================================================


class BalanceChecker(BaseBalanceChecker):
    """
    Stateless guard for checking account balance constraints.

    This guard does not maintain any internal state (no history, no statistics).
    All checks are performed based on the injected port and the input parameters.

    The guard is designed to be instantiated via dependency injection and
    reused across the application.
    """

    def __init__(
        self,
        account_balance_port: AccountBalancePort,
        tolerance: Decimal = Decimal("0.01"),
        warning_threshold_percentage: Decimal = Decimal("85"),
    ):
        if account_balance_port is None:
            raise ValueError("account_balance_port is required")
        self._port = account_balance_port
        self._tolerance = tolerance
        self._warning_threshold = warning_threshold_percentage
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

        logger.debug("BalanceChecker initialized with port: %s", type(account_balance_port).__name__)

    # ==================== SYNC CHECK METHOD (untuk checker compliance) ====================

    def check(self, context: dict) -> list[str]:
        """
        Sync check method untuk compliance checker.
        Memvalidasi context dan mengembalikan daftar error jika ada.
        """
        errors = []
        account_id = context.get("account_id")
        proposed_change = context.get("proposed_change")
        legal_entity_id = context.get("legal_entity_id")
        currency = context.get("currency", "IDR")

        if not account_id:
            errors.append("account_id is required")
        if proposed_change is None:
            errors.append("proposed_change is required")
        else:
            try:
                Decimal(str(proposed_change))
            except Exception:
                errors.append("proposed_change must be a valid number")
        if legal_entity_id:
            try:
                UUID(str(legal_entity_id))
            except Exception:
                errors.append("legal_entity_id must be a valid UUID")
        if currency and not isinstance(currency, str):
            errors.append("currency must be a string")
        return errors

    # ==================== ENTITY METHODS (wajib) ====================

    def validate(self) -> dict[str, Any]:
        """Validasi internal state."""
        errors = []
        if self._tolerance < 0:
            errors.append("tolerance must be non-negative")
        if self._warning_threshold < 0 or self._warning_threshold > 100:
            errors.append("warning_threshold_percentage must be between 0 and 100")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Konversi ke dictionary."""
        return {
            "tolerance": str(self._tolerance),
            "warning_threshold_percentage": str(self._warning_threshold),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BalanceChecker:
        """Reconstruct dari dictionary."""
        # Note: port cannot be restored from dict, caller must provide it.
        # This is a placeholder; in practice, we would need the port.
        raise NotImplementedError("BalanceChecker.from_dict requires account_balance_port; use constructor instead.")

    def clone(self) -> BalanceChecker:
        """Clone instance."""
        # Cannot clone the port; create new instance with same parameters.
        # In practice, cloning a stateless guard is trivial.
        new_checker = BalanceChecker(self._port, self._tolerance, self._warning_threshold)
        new_checker._version = self._version + 1
        return new_checker

    def snapshot(self) -> dict[str, Any]:
        """Ambil snapshot state."""
        return {
            "version": self._version,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        """Dapatkan versi."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Dapatkan audit trail."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BalanceChecker:
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

    def _get_account_type_from_data(self, account_data: dict[str, Any] | None, account_code: str) -> AccountType:
        if account_data and "account_type" in account_data:
            try:
                return AccountType.from_string(account_data["account_type"])
            except ValueError:
                logger.warning(
                    "Invalid account_type '%s' for account %s, falling back to code inference",
                    account_data["account_type"],
                    account_code,
                )
        return AccountType.from_code(account_code)

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

        # Fetch account data
        account_data = await self._port.get_account(account_id, legal_entity_id)
        if account_data is None:
            raise BalanceCheckerError(
                message=f"Account {account_id} not found for legal entity {legal_entity_id}",
                account_code=str(account_id),
                current_balance=Decimal(0),
                severity=GuardSeverity.CRITICAL,
                details={"account_id": str(account_id), "legal_entity_id": str(legal_entity_id)},
            )

        account_code = account_data.get("account_code", str(account_id))
        account_type = self._get_account_type_from_data(account_data, account_code)
        current_balance = await self._port.get_balance(account_id, legal_entity_id)

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
            # Warn if asset balance is being heavily consumed
            if account_type == AccountType.ASSET and current_balance > 0:
                usage_percentage = (
                    (current_balance - new_balance) / current_balance * 100
                    if current_balance > 0
                    else 0
                )
                if usage_percentage >= self._warning_threshold:
                    severity = BalanceCheckSeverity.MEDIUM
                    message = f"Account {account_code} balance would decrease by {usage_percentage:.1f}% to {new_balance:.2f}"

        # Currency mismatch check
        account_currency = account_data.get("currency")
        if account_currency and account_currency != currency:
            is_allowed = False
            severity = BalanceCheckSeverity.CRITICAL
            message = f"Currency mismatch: account uses {account_currency}, transaction uses {currency}"

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

        # Log the check result
        if not is_allowed or severity.value >= BalanceCheckSeverity.HIGH.value:
            log_level = logging.ERROR if not is_allowed else logging.WARNING
            logger.log(
                log_level,
                "Balance check: %s (allowed=%s)",
                result.message,
                result.is_allowed,
                extra={
                    "account_id": str(account_id),
                    "legal_entity_id": str(legal_entity_id),
                    "user_id": user_id,
                    "current_balance": str(current_balance),
                    "proposed_change": str(proposed_change),
                    "new_balance": str(new_balance),
                },
            )
        else:
            logger.debug(
                "Balance check passed for %s (new balance: %s)",
                account_code,
                new_balance,
            )

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
        if legal_entity_id is None:
            legal_entity_id = get_current_legal_entity()
            if legal_entity_id is None:
                return [
                    BalanceCheckResult(
                        check_id=uuid4(),
                        account_id=UUID(int=0),
                        account_code="UNKNOWN",
                        account_type=AccountType.ASSET,
                        legal_entity_id=UUID(int=0),
                        current_balance=Decimal(0),
                        proposed_change=Decimal(0),
                        new_balance=Decimal(0),
                        is_allowed=False,
                        severity=BalanceCheckSeverity.HIGH,
                        message="No legal entity in context",
                    )
                ]

        if user_id is None:
            user_id = get_current_user() or "unknown"

        # Extract all account IDs and compute net changes per account
        account_changes: dict[UUID, Decimal] = {}
        for tx in transactions:
            account_id = tx["account_id"]
            amount = tx["amount"]
            is_debit = tx.get("is_debit", True)
            change = -amount if is_debit else amount
            account_changes[account_id] = account_changes.get(account_id, Decimal(0)) + change

        # Fetch all accounts and balances in batch
        account_ids = list(account_changes.keys())
        account_data_map = {}
        for account_id in account_ids:
            data = await self._port.get_account(account_id, legal_entity_id)
            if data is None:
                raise BalanceCheckerError(
                    message=f"Account {account_id} not found for legal entity {legal_entity_id}",
                    account_code=str(account_id),
                    current_balance=Decimal(0),
                    severity=GuardSeverity.CRITICAL,
                    details={"account_id": str(account_id), "legal_entity_id": str(legal_entity_id)},
                )
            account_data_map[account_id] = data

        balances = await self._port.get_balances(account_ids, legal_entity_id)

        results = []
        for account_id, change in account_changes.items():
            current_balance = balances.get(account_id, Decimal(0))
            new_balance = current_balance + change
            account_data = account_data_map.get(account_id)
            account_code = account_data.get("account_code", str(account_id)) if account_data else str(account_id)
            account_type = self._get_account_type_from_data(account_data, account_code)

            inherently_allows = account_type.allows_negative_balance()
            is_allowed = new_balance >= -self._tolerance or inherently_allows

            if not is_allowed:
                result = BalanceCheckResult(
                    check_id=uuid4(),
                    account_id=account_id,
                    account_code=account_code,
                    account_type=account_type,
                    legal_entity_id=legal_entity_id,
                    current_balance=current_balance,
                    proposed_change=change,
                    new_balance=new_balance,
                    is_allowed=False,
                    severity=BalanceCheckSeverity.CRITICAL,
                    message=f"Batch transaction would cause negative balance on {account_code}: {new_balance:.2f}",
                )
                results.append(result)

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


# ============================================================================
# In-Memory Test Double (separate from production kernel)
# ============================================================================
class InMemoryAccountBalancePort:
    """
    In-memory implementation of AccountBalancePort for testing purposes.

    This is not used in production and is provided only for convenience
    during testing. In a real project, this should be placed in tests/fakes/.
    """

    def __init__(self):
        self._accounts: dict[UUID, dict[str, Any]] = {}
        self._balances: dict[tuple[UUID, UUID], Decimal] = {}

    def register_account(
        self,
        account_id: UUID,
        account_code: str,
        account_type: str,
        currency: str = "IDR",
        initial_balance: Decimal = Decimal(0),
        legal_entity_id: UUID | None = None,
    ) -> None:
        self._accounts[account_id] = {
            "account_code": account_code,
            "account_type": account_type,
            "currency": currency,
        }
        if legal_entity_id:
            self._balances[(account_id, legal_entity_id)] = initial_balance

    async def get_account(self, account_id: UUID, legal_entity_id: UUID) -> dict[str, Any] | None:
        return self._accounts.get(account_id)

    async def get_balance(self, account_id: UUID, legal_entity_id: UUID) -> Decimal:
        key = (account_id, legal_entity_id)
        return self._balances.get(key, Decimal(0))

    async def get_balances(self, account_ids: list[UUID], legal_entity_id: UUID) -> dict[UUID, Decimal]:
        result = {}
        for account_id in account_ids:
            result[account_id] = await self.get_balance(account_id, legal_entity_id)
        return result

    def set_balance(self, account_id: UUID, legal_entity_id: UUID, balance: Decimal) -> None:
        self._balances[(account_id, legal_entity_id)] = balance


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "AccountBalancePort",
    "AccountType",
    "BalanceCheckResult",
    "BalanceCheckSeverity",
    "BalanceChecker",
    "InMemoryAccountBalancePort",
]
