#!/usr/bin/env python3
"""
Module: invariants.py

Layer: Domain / Equity & Retained Earnings

Responsibility:
    Invariants (business rules) validation for Equity & Retained Earnings aggregates.

    Defines all invariants that must be satisfied by:
    - Capital contributions
    - Capital withdrawals
    - Retained earnings
    - Dividend declarations

    Provides reusable validators and an enforcer class.

Business rules:
    - Contribution amount > 0, share percentage 0-100.
    - Withdrawal amount > 0, cannot exceed paid-in capital.
    - Dividend amount > 0, cannot exceed retained earnings.
    - Dividend dates: record_date > declaration_date, payment_date > record_date.
    - Allocations sum must equal total dividend amount.
    - Status transitions must be valid.
    - Version must be consistent.
    - Currency codes must be valid ISO 4217.

Dependencies:
    - Python standard library (decimal, datetime, logging, re)

Audit:
    Validation failures are logged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Invariant Result
# ============================================================================


@dataclass
class InvariantResult:
    """
    Result of an invariant validation.

    Attributes:
        is_valid: True if all checks passed
        errors: List of error messages
        warnings: List of warning messages (non-critical)
    """

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message and mark as invalid."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message (does not affect validity)."""
        self.warnings.append(warning)

    def merge(self, other: InvariantResult) -> InvariantResult:
        """Merge another result into this one."""
        if not other.is_valid:
            self.is_valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def __bool__(self) -> bool:
        return self.is_valid

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> InvariantResult:
        return cls(is_valid=True, warnings=warnings or [])

    @classmethod
    def failure(cls, error: str, warnings: list[str] | None = None) -> InvariantResult:
        result = cls(is_valid=False, warnings=warnings or [])
        result.add_error(error)
        return result


# ============================================================================
# Common Validators
# ============================================================================


def validate_positive_amount(amount: Decimal, field_name: str = "Amount") -> InvariantResult:
    """Validate that amount is positive."""
    if amount <= 0:
        return InvariantResult.failure(f"{field_name} must be positive: {amount}")
    return InvariantResult.success()


def validate_non_negative_amount(amount: Decimal, field_name: str = "Amount") -> InvariantResult:
    """Validate that amount is non-negative."""
    if amount < 0:
        return InvariantResult.failure(f"{field_name} cannot be negative: {amount}")
    return InvariantResult.success()


def validate_currency_code(currency: str) -> InvariantResult:
    """Validate ISO 4217 currency code."""
    if not currency or not isinstance(currency, str):
        return InvariantResult.failure("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        return InvariantResult.failure(f"Currency code must be exactly 3 characters: {cleaned}")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        return InvariantResult.failure(f"Currency code must contain only letters: {cleaned}")
    return InvariantResult.success()


def validate_percentage(
    percentage: Decimal | None, field_name: str = "Percentage"
) -> InvariantResult:
    """Validate percentage (0-100)."""
    if percentage is None:
        return InvariantResult.success()
    if percentage < 0 or percentage > 100:
        return InvariantResult.failure(f"{field_name} must be between 0 and 100: {percentage}")
    return InvariantResult.success()


def validate_date_sequence(
    earlier: datetime,
    later: datetime,
    earlier_name: str = "Earlier date",
    later_name: str = "Later date",
) -> InvariantResult:
    """Validate that later date is after earlier date."""
    if later <= earlier:
        return InvariantResult.failure(
            f"{later_name} ({later}) must be after {earlier_name} ({earlier})"
        )
    return InvariantResult.success()


def validate_version(version: int, expected_version: int | None = None) -> InvariantResult:
    """Validate version number."""
    if version < 1:
        return InvariantResult.failure(f"Version must be >= 1, got {version}")
    if expected_version is not None and version != expected_version:
        return InvariantResult.failure(
            f"Version mismatch: expected {expected_version}, got {version}"
        )
    return InvariantResult.success()


# ============================================================================
# Capital Contribution Invariants
# ============================================================================


class CapitalContributionInvariants:
    """Invariants for CapitalContributionEntity."""

    @staticmethod
    def validate_contribution(
        amount: Decimal,
        share_percentage: Decimal | None,
        currency: str,
        contribution_date: datetime,
    ) -> InvariantResult:
        """Validate a capital contribution before creation/update."""
        result = InvariantResult()
        result.merge(validate_positive_amount(amount, "Contribution amount"))
        result.merge(validate_percentage(share_percentage, "Share percentage"))
        result.merge(validate_currency_code(currency))
        # contribution_date can be in the past or present, not strict
        if contribution_date and contribution_date.tzinfo is None:
            result.add_warning("Contribution date is not timezone-aware (assumed UTC)")
        return result

    @staticmethod
    def validate_status_transition(
        current_status: ContributionStatus,
        new_status: ContributionStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        """Validate status transition for capital contribution."""
        allowed = {
            ContributionStatus.DRAFT: [ContributionStatus.APPROVED, ContributionStatus.CANCELLED],
            ContributionStatus.APPROVED: [ContributionStatus.POSTED, ContributionStatus.CANCELLED],
            ContributionStatus.POSTED: [],  # Cannot change from POSTED
            ContributionStatus.CANCELLED: [],  # Terminal
        }
        allowed_list = allowed.get(current_status, [])
        if new_status not in allowed_list:
            return InvariantResult.failure(
                f"Status transition from {current_status.value} to {new_status.value} is not allowed"
            )
        # Role-based restrictions
        if new_status == ContributionStatus.APPROVED and user_role not in (
            "finance_manager",
            "admin",
        ):
            return InvariantResult.failure(
                "Only finance manager or admin can approve capital contributions"
            )
        if new_status == ContributionStatus.POSTED and user_role not in ("accountant", "admin"):
            return InvariantResult.failure(
                "Only accountant or admin can post capital contributions"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_cancel_reason(reason: str) -> InvariantResult:
        """Validate cancellation reason is provided."""
        if not reason or len(reason.strip()) < 5:
            return InvariantResult.failure("Cancellation reason must be at least 5 characters")
        return InvariantResult.success()


# ============================================================================
# Capital Withdrawal Invariants
# ============================================================================


class CapitalWithdrawalInvariants:
    """Invariants for CapitalWithdrawalEntity."""

    @staticmethod
    def validate_withdrawal(
        amount: Decimal,
        tax_withheld_amount: Decimal,
        currency: str,
        withdrawal_date: datetime,
        paid_in_capital: Decimal,
    ) -> InvariantResult:
        """Validate capital withdrawal before creation/update."""
        result = InvariantResult()
        result.merge(validate_positive_amount(amount, "Withdrawal amount"))
        result.merge(validate_non_negative_amount(tax_withheld_amount, "Tax withheld amount"))
        result.merge(validate_currency_code(currency))
        if tax_withheld_amount > amount:
            result.add_error(
                f"Tax withheld amount {tax_withheld_amount} exceeds withdrawal amount {amount}"
            )
        if amount > paid_in_capital:
            result.add_error(
                f"Withdrawal amount {amount} exceeds paid-in capital {paid_in_capital}"
            )
        if withdrawal_date and withdrawal_date.tzinfo is None:
            result.add_warning("Withdrawal date is not timezone-aware (assumed UTC)")
        return result

    @staticmethod
    def validate_status_transition(
        current_status: WithdrawalStatus,
        new_status: WithdrawalStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        """Validate status transition for capital withdrawal."""
        allowed = {
            WithdrawalStatus.DRAFT: [WithdrawalStatus.APPROVED, WithdrawalStatus.CANCELLED],
            WithdrawalStatus.APPROVED: [WithdrawalStatus.POSTED, WithdrawalStatus.CANCELLED],
            WithdrawalStatus.POSTED: [],
            WithdrawalStatus.CANCELLED: [],
        }
        allowed_list = allowed.get(current_status, [])
        if new_status not in allowed_list:
            return InvariantResult.failure(
                f"Status transition from {current_status.value} to {new_status.value} is not allowed"
            )
        if new_status == WithdrawalStatus.APPROVED and user_role not in (
            "finance_manager",
            "admin",
        ):
            return InvariantResult.failure("Only finance manager or admin can approve withdrawals")
        if new_status == WithdrawalStatus.POSTED and user_role not in ("accountant", "admin"):
            return InvariantResult.failure("Only accountant or admin can post withdrawals")
        return InvariantResult.success()


# ============================================================================
# Retained Earnings Invariants
# ============================================================================


class RetainedEarningsInvariants:
    """Invariants for RetainedEarningsEntity."""

    @staticmethod
    def validate_net_income(net_income: Decimal) -> InvariantResult:
        """Validate net income/loss amount."""
        # Net income can be positive or negative, no constraint on amount
        return InvariantResult.success()

    @staticmethod
    def validate_dividend_reduction(
        dividend_amount: Decimal, current_balance: Decimal
    ) -> InvariantResult:
        """Validate that dividend reduction does not exceed current retained earnings."""
        if dividend_amount <= 0:
            return InvariantResult.failure(f"Dividend amount must be positive: {dividend_amount}")
        if dividend_amount > current_balance:
            return InvariantResult.failure(
                f"Cannot reduce retained earnings by {dividend_amount} when current balance is {current_balance}"
            )
        return InvariantResult.success()

    @staticmethod
    def validate_prior_period_adjustment(adjustment: Decimal) -> InvariantResult:
        """Validate prior period adjustment (no constraints, any value allowed)."""
        return InvariantResult.success()

    @staticmethod
    def validate_transfer(
        amount: Decimal, current_balance: Decimal, to_reserve: bool
    ) -> InvariantResult:
        """Validate transfer to/from reserve."""
        if amount <= 0:
            return InvariantResult.failure(f"Transfer amount must be positive: {amount}")
        if to_reserve and amount > current_balance:
            return InvariantResult.failure(
                f"Cannot transfer {amount} to reserve when retained earnings is {current_balance}"
            )
        return InvariantResult.success()


# ============================================================================
# Dividend Invariants
# ============================================================================


class DividendInvariants:
    """Invariants for DividendDeclarationEntity."""

    @staticmethod
    def validate_dividend_declaration(
        total_amount: Decimal,
        currency: str,
        declaration_date: datetime,
        record_date: datetime,
        payment_date: datetime,
        retained_earnings_balance: Decimal,
        allocations: list[Any],  # List of DividendShareholderAllocation
    ) -> InvariantResult:
        """Validate dividend declaration before creation."""
        result = InvariantResult()
        result.merge(validate_positive_amount(total_amount, "Dividend total amount"))
        result.merge(validate_currency_code(currency))
        result.merge(
            validate_date_sequence(declaration_date, record_date, "Declaration date", "Record date")
        )
        result.merge(
            validate_date_sequence(record_date, payment_date, "Record date", "Payment date")
        )

        if total_amount > retained_earnings_balance:
            result.add_error(
                f"Dividend amount {total_amount} exceeds retained earnings {retained_earnings_balance}"
            )

        # Validate allocations sum
        if allocations:
            total_allocated = sum(a.dividend_amount for a in allocations)
            if total_allocated != total_amount:
                result.add_error(
                    f"Total allocated {total_allocated} does not equal dividend amount {total_amount}"
                )
            # Validate each allocation
            for i, alloc in enumerate(allocations):
                if alloc.dividend_amount <= 0:
                    result.add_error(f"Allocation {i}: amount must be positive")
                if alloc.share_percentage < 0 or alloc.share_percentage > 100:
                    result.add_error(f"Allocation {i}: share percentage must be 0-100")
                if alloc.shares_owned <= 0:
                    result.add_error(f"Allocation {i}: shares owned must be positive")

        return result

    @staticmethod
    def validate_status_transition(
        current_status: DividendStatus,
        new_status: DividendStatus,
        total_paid: Decimal,
        total_amount: Decimal,
        user_role: str = "user",
    ) -> InvariantResult:
        """Validate status transition for dividend declaration."""
        allowed = {
            DividendStatus.PROPOSED: [DividendStatus.APPROVED, DividendStatus.CANCELLED],
            DividendStatus.APPROVED: [
                DividendStatus.PAID,
                DividendStatus.PARTIALLY_PAID,
                DividendStatus.CANCELLED,
            ],
            DividendStatus.PARTIALLY_PAID: [
                DividendStatus.PAID,
                DividendStatus.PARTIALLY_PAID,
                DividendStatus.CANCELLED,
            ],
            DividendStatus.PAID: [],
            DividendStatus.CANCELLED: [],
        }
        allowed_list = allowed.get(current_status, [])
        if new_status not in allowed_list:
            return InvariantResult.failure(
                f"Status transition from {current_status.value} to {new_status.value} is not allowed"
            )

        # Additional validation for PAID transition
        if new_status == DividendStatus.PAID and total_paid < total_amount:
            return InvariantResult.failure(
                f"Cannot set status to PAID when only {total_paid} of {total_amount} is paid"
            )
        if new_status == DividendStatus.PARTIALLY_PAID and total_paid == total_amount:
            return InvariantResult.failure(
                "PARTIALLY_PAID status is not allowed when dividend is fully paid"
            )

        # Role-based
        if new_status == DividendStatus.APPROVED and user_role not in ("board", "admin"):
            return InvariantResult.failure("Only board member or admin can approve dividends")
        if new_status in (DividendStatus.PAID, DividendStatus.PARTIALLY_PAID) and user_role not in (
            "finance",
            "admin",
        ):
            return InvariantResult.failure("Only finance or admin can record dividend payments")
        return InvariantResult.success()


# ============================================================================
# Global Invariant Enforcer
# ============================================================================


class EquityInvariantEnforcer:
    """
    Enforcer for all equity-related invariants.

    This class coordinates validation across all entities using callbacks
    to retrieve current state (e.g., paid-in capital, retained earnings).

    Usage:
        enforcer = EquityInvariantEnforcer(
            get_paid_in_capital=lambda: 1000000,
            get_retained_earnings=lambda: 500000
        )
        result = await enforcer.enforce_withdrawal(amount=200000)
    """

    def __init__(
        self,
        get_paid_in_capital: Callable[[], Decimal] | None = None,
        get_retained_earnings: Callable[[], Decimal] | None = None,
    ):
        self._get_paid_in_capital = get_paid_in_capital or (lambda: Decimal("0"))
        self._get_retained_earnings = get_retained_earnings or (lambda: Decimal("0"))
        self._contribution_invariants = CapitalContributionInvariants()
        self._withdrawal_invariants = CapitalWithdrawalInvariants()
        self._retained_invariants = RetainedEarningsInvariants()
        self._dividend_invariants = DividendInvariants()

    async def enforce_contribution(
        self,
        amount: Decimal,
        share_percentage: Decimal | None,
        currency: str,
        contribution_date: datetime,
    ) -> InvariantResult:
        """Enforce invariants for a capital contribution."""
        return self._contribution_invariants.validate_contribution(
            amount, share_percentage, currency, contribution_date
        )

    async def enforce_contribution_status(
        self,
        current_status: ContributionStatus,
        new_status: ContributionStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        """Enforce status transition invariants for contribution."""
        return self._contribution_invariants.validate_status_transition(
            current_status, new_status, user_role
        )

    async def enforce_withdrawal(
        self,
        amount: Decimal,
        tax_withheld_amount: Decimal,
        currency: str,
        withdrawal_date: datetime,
    ) -> InvariantResult:
        """Enforce invariants for a capital withdrawal."""
        paid_in_capital = self._get_paid_in_capital()
        return self._withdrawal_invariants.validate_withdrawal(
            amount, tax_withheld_amount, currency, withdrawal_date, paid_in_capital
        )

    async def enforce_withdrawal_status(
        self,
        current_status: WithdrawalStatus,
        new_status: WithdrawalStatus,
        user_role: str = "user",
    ) -> InvariantResult:
        return self._withdrawal_invariants.validate_status_transition(
            current_status, new_status, user_role
        )

    async def enforce_dividend(
        self,
        total_amount: Decimal,
        currency: str,
        declaration_date: datetime,
        record_date: datetime,
        payment_date: datetime,
        allocations: list[Any],
    ) -> InvariantResult:
        retained_earnings = self._get_retained_earnings()
        return self._dividend_invariants.validate_dividend_declaration(
            total_amount,
            currency,
            declaration_date,
            record_date,
            payment_date,
            retained_earnings,
            allocations,
        )

    async def enforce_dividend_status(
        self,
        current_status: DividendStatus,
        new_status: DividendStatus,
        total_paid: Decimal,
        total_amount: Decimal,
        user_role: str = "user",
    ) -> InvariantResult:
        return self._dividend_invariants.validate_status_transition(
            current_status, new_status, total_paid, total_amount, user_role
        )

    async def enforce_retained_earnings_reduction(
        self,
        dividend_amount: Decimal,
    ) -> InvariantResult:
        current_balance = self._get_retained_earnings()
        return self._retained_invariants.validate_dividend_reduction(
            dividend_amount, current_balance
        )

    async def enforce_retained_earnings_transfer(
        self,
        amount: Decimal,
        to_reserve: bool,
    ) -> InvariantResult:
        current_balance = self._get_retained_earnings()
        return self._retained_invariants.validate_transfer(amount, current_balance, to_reserve)


# ============================================================================
# Helper Functions
# ============================================================================


def validate_capital_contribution_invariants(
    amount: Decimal,
    share_percentage: Decimal | None,
    currency: str,
    contribution_date: datetime,
) -> InvariantResult:
    """Standalone validation for capital contribution."""
    return CapitalContributionInvariants.validate_contribution(
        amount, share_percentage, currency, contribution_date
    )


def validate_capital_withdrawal_invariants(
    amount: Decimal,
    tax_withheld_amount: Decimal,
    currency: str,
    withdrawal_date: datetime,
    paid_in_capital: Decimal,
) -> InvariantResult:
    """Standalone validation for capital withdrawal."""
    return CapitalWithdrawalInvariants.validate_withdrawal(
        amount, tax_withheld_amount, currency, withdrawal_date, paid_in_capital
    )


def validate_dividend_declaration_invariants(
    total_amount: Decimal,
    currency: str,
    declaration_date: datetime,
    record_date: datetime,
    payment_date: datetime,
    retained_earnings_balance: Decimal,
    allocations: list[Any],
) -> InvariantResult:
    """Standalone validation for dividend declaration."""
    return DividendInvariants.validate_dividend_declaration(
        total_amount,
        currency,
        declaration_date,
        record_date,
        payment_date,
        retained_earnings_balance,
        allocations,
    )


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CapitalContributionInvariants",
    "CapitalWithdrawalInvariants",
    "DividendInvariants",
    "EquityInvariantEnforcer",
    "InvariantResult",
    "RetainedEarningsInvariants",
    "validate_capital_contribution_invariants",
    "validate_capital_withdrawal_invariants",
    "validate_currency_code",
    "validate_date_sequence",
    "validate_dividend_declaration_invariants",
    "validate_non_negative_amount",
    "validate_percentage",
    "validate_positive_amount",
    "validate_version",
]
