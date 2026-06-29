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
        if self in (AccountType.ASSET, AccountType.EXPENSE, AccountType.CONTRA_LIABILITY):
            return False
        return True

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
# Balance Checker (Stateless Guard)
# ============================================================================
class BalanceChecker:
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

        logger.debug("BalanceChecker initialized with port: %s", type(account_balance_port).__name__)

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
        """
        Check if the proposed change would cause an invalid negative balance.

        Args:
            account_id: The account to check.
            proposed_change: The change to apply (positive for credit, negative for debit).
            legal_entity_id: Legal entity context (default from context holder).
            allow_negative: Override to allow negative balance for this check.
            currency: Transaction currency (for mismatch check).
            user_id: User performing the action (for audit).

        Returns:
            BalanceCheckResult with details and decision.
        """
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
        """Check balances for a transaction with multiple debits and credits."""
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
        """Check balances for a batch of transactions efficiently using batch API."""
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
        """
        Enforce the balance check. Raises exception on violation unless disabled.
        """
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
        """Enforce balance checks for multiple account changes."""
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
# This is intentionally placed at the end of the file and clearly marked
# as TESTING ONLY. It should be moved to tests/fakes/ in a real project.
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
    "InMemoryAccountBalancePort",  # testing only
]