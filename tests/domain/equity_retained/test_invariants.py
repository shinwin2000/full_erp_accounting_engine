# domain/equity_retained/test_invariants.py
"""
Comprehensive unit tests for Equity & Retained Earnings invariants.

Covers:
- InvariantResult (construction, add_error, merge, to_dict, bool, classmethods)
- All validator functions (positive_amount, non_negative_amount, currency_code, percentage, date_sequence, version)
- CapitalContributionInvariants (validate_contribution, validate_status_transition, validate_cancel_reason)
- CapitalWithdrawalInvariants (validate_withdrawal, validate_status_transition)
- RetainedEarningsInvariants (validate_net_income, validate_dividend_reduction, validate_prior_period_adjustment, validate_transfer)
- DividendInvariants (validate_dividend_declaration, validate_status_transition)
- EquityInvariantEnforcer (all enforce_* methods with mocked callbacks)
- Standalone helper functions (validate_capital_contribution_invariants, etc.)
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

import pytest

from domain.equity_retained.invariants import (
    CapitalContributionInvariants,
    CapitalWithdrawalInvariants,
    DividendInvariants,
    EquityInvariantEnforcer,
    InvariantResult,
    RetainedEarningsInvariants,
    validate_capital_contribution_invariants,
    validate_capital_withdrawal_invariants,
    validate_currency_code,
    validate_date_sequence,
    validate_dividend_declaration_invariants,
    validate_non_negative_amount,
    validate_percentage,
    validate_positive_amount,
    validate_version,
)

# =============================================================================
# Mock Enums (since they're not imported from invariants.py)
# =============================================================================

class ContributionStatus(Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"


class WithdrawalStatus(Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    POSTED = "posted"
    CANCELLED = "cancelled"


class DividendStatus(Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    CANCELLED = "cancelled"


@dataclass
class MockAllocation:
    dividend_amount: Decimal
    share_percentage: Decimal
    shares_owned: int


# =============================================================================
# Tests for InvariantResult
# =============================================================================

class TestInvariantResult:
    def test_default_initialization(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_initialization_with_values(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["e1"]
        assert result.warnings == ["w1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("invalid amount")
        assert result.is_valid is False
        assert result.errors == ["invalid amount"]

    def test_add_warning(self):
        result = InvariantResult()
        result.add_warning("date not timezone-aware")
        assert result.is_valid is True  # warnings don't affect validity
        assert result.warnings == ["date not timezone-aware"]

    def test_merge_valid(self):
        r1 = InvariantResult()
        r2 = InvariantResult()
        merged = r1.merge(r2)
        assert merged.is_valid is True
        assert merged.errors == []
        assert merged.warnings == []

    def test_merge_invalid(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e2"]
        assert merged.warnings == ["w2"]

    def test_merge_multiple(self):
        r1 = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e1", "e2"]
        assert merged.warnings == ["w1", "w2"]

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False

    def test_success_classmethod(self):
        result = InvariantResult.success()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        result_with_warnings = InvariantResult.success(warnings=["w1"])
        assert result_with_warnings.warnings == ["w1"]

    def test_failure_classmethod(self):
        result = InvariantResult.failure("error", warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["error"]
        assert result.warnings == ["w1"]


# =============================================================================
# Tests for Validator Functions
# =============================================================================

class TestValidators:
    def test_validate_positive_amount_valid(self):
        result = validate_positive_amount(Decimal("10.00"))
        assert result.is_valid is True

    def test_validate_positive_amount_invalid_zero(self):
        result = validate_positive_amount(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_positive_amount_invalid_negative(self):
        result = validate_positive_amount(Decimal("-5"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_non_negative_amount_valid_positive(self):
        result = validate_non_negative_amount(Decimal("10"))
        assert result.is_valid is True

    def test_validate_non_negative_amount_valid_zero(self):
        result = validate_non_negative_amount(Decimal("0"))
        assert result.is_valid is True

    def test_validate_non_negative_amount_invalid_negative(self):
        result = validate_non_negative_amount(Decimal("-1"))
        assert result.is_valid is False
        assert "negative" in result.errors[0]

    def test_validate_currency_code_valid(self):
        result = validate_currency_code("USD")
        assert result.is_valid is True

    def test_validate_currency_code_invalid_length(self):
        result = validate_currency_code("US")
        assert result.is_valid is False
        assert "exactly 3" in result.errors[0]

    def test_validate_currency_code_invalid_chars(self):
        result = validate_currency_code("U1D")
        assert result.is_valid is False
        assert "letters" in result.errors[0]

    def test_validate_currency_code_empty(self):
        result = validate_currency_code("")
        assert result.is_valid is False

    def test_validate_percentage_valid(self):
        result = validate_percentage(Decimal("50"))
        assert result.is_valid is True
        result = validate_percentage(Decimal("0"))
        assert result.is_valid is True
        result = validate_percentage(Decimal("100"))
        assert result.is_valid is True

    def test_validate_percentage_invalid_above_100(self):
        result = validate_percentage(Decimal("101"))
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]

    def test_validate_percentage_invalid_negative(self):
        result = validate_percentage(Decimal("-1"))
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]

    def test_validate_percentage_none(self):
        result = validate_percentage(None)
        assert result.is_valid is True

    def test_validate_date_sequence_valid(self):
        earlier = datetime(2025, 1, 1, tzinfo=UTC)
        later = datetime(2025, 1, 2, tzinfo=UTC)
        result = validate_date_sequence(earlier, later)
        assert result.is_valid is True

    def test_validate_date_sequence_invalid_equal(self):
        dt = datetime(2025, 1, 1, tzinfo=UTC)
        result = validate_date_sequence(dt, dt)
        assert result.is_valid is False
        assert "must be after" in result.errors[0]

    def test_validate_date_sequence_invalid_earlier(self):
        earlier = datetime(2025, 1, 2, tzinfo=UTC)
        later = datetime(2025, 1, 1, tzinfo=UTC)
        result = validate_date_sequence(earlier, later)
        assert result.is_valid is False
        assert "must be after" in result.errors[0]

    def test_validate_version_valid(self):
        result = validate_version(1)
        assert result.is_valid is True
        result = validate_version(5)
        assert result.is_valid is True

    def test_validate_version_invalid_zero(self):
        result = validate_version(0)
        assert result.is_valid is False
        assert ">= 1" in result.errors[0]

    def test_validate_version_mismatch(self):
        result = validate_version(1, expected_version=2)
        assert result.is_valid is False
        assert "mismatch" in result.errors[0]

    def test_validate_version_match(self):
        result = validate_version(2, expected_version=2)
        assert result.is_valid is True


# =============================================================================
# Tests for CapitalContributionInvariants
# =============================================================================

class TestCapitalContributionInvariants:
    def test_validate_contribution_valid(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is True

    def test_validate_contribution_invalid_amount_negative(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("-100"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=datetime.now(UTC),
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_contribution_invalid_percentage(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("101"),
            currency="USD",
            contribution_date=datetime.now(UTC),
        )
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]

    def test_validate_contribution_warning_on_naive_date(self):
        # contribution_date without timezone
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=None,
            currency="USD",
            contribution_date=datetime(2025, 1, 1),  # naive
        )
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "timezone-aware" in result.warnings[0]

    def test_validate_status_transition_valid(self):
        result = CapitalContributionInvariants.validate_status_transition(
            ContributionStatus.DRAFT, ContributionStatus.APPROVED, user_role="finance_manager"
        )
        assert result.is_valid is True

    def test_validate_status_transition_invalid_role(self):
        result = CapitalContributionInvariants.validate_status_transition(
            ContributionStatus.DRAFT, ContributionStatus.APPROVED, user_role="user"
        )
        assert result.is_valid is False
        assert "Only finance manager or admin" in result.errors[0]

    def test_validate_status_transition_invalid_transition(self):
        result = CapitalContributionInvariants.validate_status_transition(
            ContributionStatus.POSTED, ContributionStatus.CANCELLED, user_role="admin"
        )
        assert result.is_valid is False
        assert "not allowed" in result.errors[0]

    def test_validate_cancel_reason_valid(self):
        result = CapitalContributionInvariants.validate_cancel_reason("Too long reason")
        assert result.is_valid is True

    def test_validate_cancel_reason_too_short(self):
        result = CapitalContributionInvariants.validate_cancel_reason("no")
        assert result.is_valid is False
        assert "at least 5 characters" in result.errors[0]

    def test_validate_cancel_reason_empty(self):
        result = CapitalContributionInvariants.validate_cancel_reason("")
        assert result.is_valid is False


# =============================================================================
# Tests for CapitalWithdrawalInvariants
# =============================================================================

class TestCapitalWithdrawalInvariants:
    def test_validate_withdrawal_valid(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("5000"),
            tax_withheld_amount=Decimal("500"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is True

    def test_validate_withdrawal_exceeds_capital(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("15000"),
            tax_withheld_amount=Decimal("0"),
            currency="USD",
            withdrawal_date=datetime.now(UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is False
        assert "exceeds paid-in capital" in result.errors[0]

    def test_validate_withdrawal_tax_exceeds_amount(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("1200"),
            currency="USD",
            withdrawal_date=datetime.now(UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is False
        assert "exceeds withdrawal amount" in result.errors[0]

    def test_validate_withdrawal_negative_tax(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("-100"),
            currency="USD",
            withdrawal_date=datetime.now(UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_withdrawal_naive_date_warning(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("0"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1),  # naive
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is True
        assert "timezone-aware" in result.warnings[0]

    def test_validate_status_transition_valid(self):
        result = CapitalWithdrawalInvariants.validate_status_transition(
            WithdrawalStatus.DRAFT, WithdrawalStatus.APPROVED, user_role="finance_manager"
        )
        assert result.is_valid is True

    def test_validate_status_transition_invalid_role(self):
        result = CapitalWithdrawalInvariants.validate_status_transition(
            WithdrawalStatus.DRAFT, WithdrawalStatus.APPROVED, user_role="user"
        )
        assert result.is_valid is False
        assert "Only finance manager or admin" in result.errors[0]


# =============================================================================
# Tests for RetainedEarningsInvariants
# =============================================================================

class TestRetainedEarningsInvariants:
    def test_validate_net_income_always_valid(self):
        result = RetainedEarningsInvariants.validate_net_income(Decimal("1000"))
        assert result.is_valid is True
        result = RetainedEarningsInvariants.validate_net_income(Decimal("-500"))
        assert result.is_valid is True

    def test_validate_dividend_reduction_valid(self):
        result = RetainedEarningsInvariants.validate_dividend_reduction(
            dividend_amount=Decimal("500"),
            current_balance=Decimal("1000"),
        )
        assert result.is_valid is True

    def test_validate_dividend_reduction_exceeds_balance(self):
        result = RetainedEarningsInvariants.validate_dividend_reduction(
            dividend_amount=Decimal("1500"),
            current_balance=Decimal("1000"),
        )
        assert result.is_valid is False
        assert "exceeds current retained earnings" in result.errors[0]

    def test_validate_dividend_reduction_zero(self):
        result = RetainedEarningsInvariants.validate_dividend_reduction(
            dividend_amount=Decimal("0"),
            current_balance=Decimal("1000"),
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_prior_period_adjustment_always_valid(self):
        result = RetainedEarningsInvariants.validate_prior_period_adjustment(Decimal("100"))
        assert result.is_valid is True
        result = RetainedEarningsInvariants.validate_prior_period_adjustment(Decimal("-100"))
        assert result.is_valid is True

    def test_validate_transfer_valid_to_reserve(self):
        result = RetainedEarningsInvariants.validate_transfer(
            amount=Decimal("200"),
            current_balance=Decimal("1000"),
            to_reserve=True,
        )
        assert result.is_valid is True

    def test_validate_transfer_exceeds_balance_to_reserve(self):
        result = RetainedEarningsInvariants.validate_transfer(
            amount=Decimal("1200"),
            current_balance=Decimal("1000"),
            to_reserve=True,
        )
        assert result.is_valid is False
        assert "cannot transfer" in result.errors[0]

    def test_validate_transfer_from_reserve_always_valid(self):
        result = RetainedEarningsInvariants.validate_transfer(
            amount=Decimal("1000"),
            current_balance=Decimal("1000"),
            to_reserve=False,
        )
        assert result.is_valid is True

    def test_validate_transfer_zero_amount(self):
        result = RetainedEarningsInvariants.validate_transfer(
            amount=Decimal("0"),
            current_balance=Decimal("1000"),
            to_reserve=True,
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]


# =============================================================================
# Tests for DividendInvariants
# =============================================================================

class TestDividendInvariants:
    def test_validate_dividend_declaration_valid(self):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_exceeds_retained_earnings(self):
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("3000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
        assert "exceeds retained earnings" in result.errors[0]

    def test_validate_dividend_declaration_invalid_dates(self):
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 10, tzinfo=UTC),
            record_date=datetime(2025, 1, 1, tzinfo=UTC),
            payment_date=datetime(2025, 1, 5, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
        # Should have at least one date sequence error
        assert any("must be after" in err for err in result.errors)

    def test_validate_dividend_declaration_allocations_sum_mismatch(self):
        allocations = [
            MockAllocation(dividend_amount=Decimal("500"), share_percentage=Decimal("50"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is False
        assert "does not equal" in result.errors[0]

    def test_validate_dividend_declaration_invalid_allocation(self):
        allocations = [
            MockAllocation(dividend_amount=Decimal("-100"), share_percentage=Decimal("50"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("1100"), share_percentage=Decimal("50"), shares_owned=1000),
        ]
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is False
        # Should have errors for allocation amount negative and sum mismatch
        assert any("positive" in err for err in result.errors)
        assert any("does not equal" in err for err in result.errors)

    def test_validate_status_transition_valid(self):
        result = DividendInvariants.validate_status_transition(
            DividendStatus.PROPOSED,
            DividendStatus.APPROVED,
            total_paid=Decimal("0"),
            total_amount=Decimal("1000"),
            user_role="board",
        )
        assert result.is_valid is True

    def test_validate_status_transition_invalid_role(self):
        result = DividendInvariants.validate_status_transition(
            DividendStatus.PROPOSED,
            DividendStatus.APPROVED,
            total_paid=Decimal("0"),
            total_amount=Decimal("1000"),
            user_role="user",
        )
        assert result.is_valid is False
        assert "Only board member or admin" in result.errors[0]

    def test_validate_status_transition_paid_without_full_payment(self):
        result = DividendInvariants.validate_status_transition(
            DividendStatus.APPROVED,
            DividendStatus.PAID,
            total_paid=Decimal("500"),
            total_amount=Decimal("1000"),
            user_role="finance",
        )
        assert result.is_valid is False
        assert "Cannot set status to PAID when only" in result.errors[0]

    def test_validate_status_transition_partially_paid_when_fully_paid(self):
        result = DividendInvariants.validate_status_transition(
            DividendStatus.APPROVED,
            DividendStatus.PARTIALLY_PAID,
            total_paid=Decimal("1000"),
            total_amount=Decimal("1000"),
            user_role="finance",
        )
        assert result.is_valid is False
        assert "PARTIALLY_PAID status is not allowed when fully paid" in result.errors[0]


# =============================================================================
# Tests for EquityInvariantEnforcer
# =============================================================================

class TestEquityInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        # Provide simple synchronous callbacks returning fixed values
        def get_paid_in_capital():
            return Decimal("10000")
        def get_retained_earnings():
            return Decimal("5000")
        return EquityInvariantEnforcer(
            get_paid_in_capital=get_paid_in_capital,
            get_retained_earnings=get_retained_earnings,
        )

    @pytest.mark.asyncio
    async def test_enforce_contribution_valid(self, enforcer):
        result = await enforcer.enforce_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_contribution_invalid(self, enforcer):
        result = await enforcer.enforce_contribution(
            amount=Decimal("-100"),
            share_percentage=Decimal("101"),
            currency="US",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is False
        assert len(result.errors) >= 2

    @pytest.mark.asyncio
    async def test_enforce_contribution_status_valid(self, enforcer):
        result = await enforcer.enforce_contribution_status(
            ContributionStatus.DRAFT,
            ContributionStatus.APPROVED,
            user_role="finance_manager",
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_withdrawal_valid(self, enforcer):
        result = await enforcer.enforce_withdrawal(
            amount=Decimal("2000"),
            tax_withheld_amount=Decimal("200"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_withdrawal_exceeds_capital(self, enforcer):
        result = await enforcer.enforce_withdrawal(
            amount=Decimal("15000"),
            tax_withheld_amount=Decimal("0"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is False
        assert "exceeds paid-in capital" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_withdrawal_status_valid(self, enforcer):
        result = await enforcer.enforce_withdrawal_status(
            WithdrawalStatus.DRAFT,
            WithdrawalStatus.APPROVED,
            user_role="finance_manager",
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_dividend_valid(self, enforcer):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = await enforcer.enforce_dividend(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            allocations=allocations,
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_dividend_exceeds_retained_earnings(self, enforcer):
        result = await enforcer.enforce_dividend(
            total_amount=Decimal("6000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            allocations=[],
        )
        assert result.is_valid is False
        assert "exceeds retained earnings" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_dividend_status_valid(self, enforcer):
        result = await enforcer.enforce_dividend_status(
            DividendStatus.PROPOSED,
            DividendStatus.APPROVED,
            total_paid=Decimal("0"),
            total_amount=Decimal("1000"),
            user_role="board",
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_retained_earnings_reduction_valid(self, enforcer):
        result = await enforcer.enforce_retained_earnings_reduction(
            dividend_amount=Decimal("1000"),
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_retained_earnings_reduction_exceeds_balance(self, enforcer):
        result = await enforcer.enforce_retained_earnings_reduction(
            dividend_amount=Decimal("6000"),
        )
        assert result.is_valid is False
        assert "exceeds current retained earnings" in result.errors[0]

    @pytest.mark.asyncio
    async def test_enforce_retained_earnings_transfer_valid_to_reserve(self, enforcer):
        result = await enforcer.enforce_retained_earnings_transfer(
            amount=Decimal("1000"),
            to_reserve=True,
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_retained_earnings_transfer_exceeds_balance(self, enforcer):
        result = await enforcer.enforce_retained_earnings_transfer(
            amount=Decimal("6000"),
            to_reserve=True,
        )
        assert result.is_valid is False
        assert "cannot transfer" in result.errors[0]


# =============================================================================
# Tests for Standalone Helper Functions
# =============================================================================

class TestStandaloneHelpers:
    def test_validate_capital_contribution_invariants(self):
        result = validate_capital_contribution_invariants(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is True

    def test_validate_capital_withdrawal_invariants(self):
        result = validate_capital_withdrawal_invariants(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("100"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
            paid_in_capital=Decimal("5000"),
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_invariants(self):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = validate_dividend_declaration_invariants(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 1, tzinfo=UTC),
            record_date=datetime(2025, 1, 10, tzinfo=UTC),
            payment_date=datetime(2025, 1, 20, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_invariants_invalid(self):
        result = validate_dividend_declaration_invariants(
            total_amount=Decimal("3000"),
            currency="USD",
            declaration_date=datetime(2025, 1, 10, tzinfo=UTC),
            record_date=datetime(2025, 1, 1, tzinfo=UTC),
            payment_date=datetime(2025, 1, 5, tzinfo=UTC),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
