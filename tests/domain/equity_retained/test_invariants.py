# domain/equity_retained/test_invariants.py
"""
Comprehensive unit tests for Equity & Retained Earnings invariants.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import Enum
from unittest.mock import patch

import pytest

# =============================================================================
# Mock Enums (must be defined before importing invariants to inject them)
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


# =============================================================================
# Inject enums into invariants module
# =============================================================================

import domain.equity_retained.invariants as invariants_module

invariants_module.ContributionStatus = ContributionStatus
invariants_module.WithdrawalStatus = WithdrawalStatus
invariants_module.DividendStatus = DividendStatus

# Now import from invariants
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


@dataclass
class MockAllocation:
    dividend_amount: Decimal
    share_percentage: Decimal
    shares_owned: int


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now(fixed_now):
    with patch("domain.equity_retained.invariants.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


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
        assert result.is_valid is True
        assert result.warnings == ["date not timezone-aware"]

    def test_merge(self):
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
        result = InvariantResult.success(warnings=["w1"])
        assert result.warnings == ["w1"]

    def test_failure_classmethod(self):
        result = InvariantResult.failure("error", warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["error"]
        assert result.warnings == ["w1"]


# =============================================================================
# Tests for Validator Functions (parametrized)
# =============================================================================

class TestValidators:
    @pytest.mark.parametrize("amount,expected_valid", [
        (Decimal("10.00"), True),
        (Decimal("0"), False),
        (Decimal("-5"), False),
    ])
    def test_validate_positive_amount(self, amount, expected_valid):
        result = validate_positive_amount(amount)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "positive" in result.errors[0]

    @pytest.mark.parametrize("amount,expected_valid", [
        (Decimal("10"), True),
        (Decimal("0"), True),
        (Decimal("-1"), False),
    ])
    def test_validate_non_negative_amount(self, amount, expected_valid):
        result = validate_non_negative_amount(amount)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "negative" in result.errors[0]

    @pytest.mark.parametrize("currency,expected_valid,error_substr", [
        ("USD", True, None),
        ("US", False, "exactly 3"),
        ("U1D", False, "letters"),
        ("", False, "non-empty"),
        (None, False, "non-empty"),
    ])
    def test_validate_currency_code(self, currency, expected_valid, error_substr):
        result = validate_currency_code(currency)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert error_substr in result.errors[0] or "must" in result.errors[0]

    @pytest.mark.parametrize("percentage,expected_valid", [
        (Decimal("50"), True),
        (Decimal("0"), True),
        (Decimal("100"), True),
        (Decimal("101"), False),
        (Decimal("-1"), False),
        (None, True),
    ])
    def test_validate_percentage(self, percentage, expected_valid):
        result = validate_percentage(percentage)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "between 0 and 100" in result.errors[0]

    @pytest.mark.parametrize("earlier, later, expected_valid", [
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 2, tzinfo=UTC), True),
        (datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), False),
        (datetime(2025, 1, 2, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), False),
    ])
    def test_validate_date_sequence(self, earlier, later, expected_valid):
        result = validate_date_sequence(earlier, later)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "must be after" in result.errors[0]

    @pytest.mark.parametrize("version, expected_version, expected_valid", [
        (1, None, True),
        (5, None, True),
        (0, None, False),
        (1, 1, True),
        (1, 2, False),
    ])
    def test_validate_version(self, version, expected_version, expected_valid):
        result = validate_version(version, expected_version)
        assert result.is_valid == expected_valid
        if not expected_valid:
            if expected_version is not None:
                assert "mismatch" in result.errors[0]
            else:
                assert ">= 1" in result.errors[0]


# =============================================================================
# Tests for CapitalContributionInvariants
# =============================================================================

class TestCapitalContributionInvariants:
    def test_validate_contribution_valid(self, fixed_now):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=fixed_now,
        )
        assert result.is_valid is True

    def test_validate_contribution_invalid_amount(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("-100"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_contribution_invalid_percentage(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("101"),
            currency="USD",
            contribution_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]

    def test_validate_contribution_naive_date_warning(self):
        result = CapitalContributionInvariants.validate_contribution(
            amount=Decimal("1000"),
            share_percentage=None,
            currency="USD",
            contribution_date=datetime(2025, 1, 1),  # naive
        )
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "timezone-aware" in result.warnings[0]

    @pytest.mark.parametrize("current,new,user_role,expected_valid", [
        (ContributionStatus.DRAFT, ContributionStatus.APPROVED, "finance_manager", True),
        (ContributionStatus.DRAFT, ContributionStatus.APPROVED, "user", False),
        (ContributionStatus.DRAFT, ContributionStatus.CANCELLED, "user", True),
        (ContributionStatus.APPROVED, ContributionStatus.POSTED, "accountant", True),
        (ContributionStatus.APPROVED, ContributionStatus.POSTED, "user", False),
        (ContributionStatus.POSTED, ContributionStatus.APPROVED, "admin", False),
    ])
    def test_validate_status_transition(self, current, new, user_role, expected_valid):
        result = CapitalContributionInvariants.validate_status_transition(current, new, user_role)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "not allowed" in result.errors[0] or "Only" in result.errors[0]

    @pytest.mark.parametrize("reason,expected_valid", [
        ("Valid reason", True),
        ("No", False),
        ("", False),
        ("   ", False),
    ])
    def test_validate_cancel_reason(self, reason, expected_valid):
        result = CapitalContributionInvariants.validate_cancel_reason(reason)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "at least 5 characters" in result.errors[0]


# =============================================================================
# Tests for CapitalWithdrawalInvariants
# =============================================================================

class TestCapitalWithdrawalInvariants:
    def test_validate_withdrawal_valid(self, fixed_now):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("5000"),
            tax_withheld_amount=Decimal("500"),
            currency="USD",
            withdrawal_date=fixed_now,
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is True

    def test_validate_withdrawal_exceeds_capital(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("15000"),
            tax_withheld_amount=Decimal("0"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is False
        assert "exceeds paid-in capital" in result.errors[0]

    def test_validate_withdrawal_tax_exceeds_amount(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("1200"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
            paid_in_capital=Decimal("10000"),
        )
        assert result.is_valid is False
        assert "exceeds withdrawal amount" in result.errors[0]

    def test_validate_withdrawal_negative_tax(self):
        result = CapitalWithdrawalInvariants.validate_withdrawal(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("-100"),
            currency="USD",
            withdrawal_date=datetime(2025, 1, 1, tzinfo=UTC),
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

    @pytest.mark.parametrize("current,new,user_role,expected_valid", [
        (WithdrawalStatus.DRAFT, WithdrawalStatus.APPROVED, "finance_manager", True),
        (WithdrawalStatus.DRAFT, WithdrawalStatus.APPROVED, "user", False),
        (WithdrawalStatus.APPROVED, WithdrawalStatus.POSTED, "accountant", True),
        (WithdrawalStatus.APPROVED, WithdrawalStatus.POSTED, "user", False),
        (WithdrawalStatus.POSTED, WithdrawalStatus.APPROVED, "admin", False),
    ])
    def test_validate_status_transition(self, current, new, user_role, expected_valid):
        result = CapitalWithdrawalInvariants.validate_status_transition(current, new, user_role)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "not allowed" in result.errors[0] or "Only" in result.errors[0]


# =============================================================================
# Tests for RetainedEarningsInvariants
# =============================================================================

class TestRetainedEarningsInvariants:
    def test_validate_net_income_always_valid(self):
        assert RetainedEarningsInvariants.validate_net_income(Decimal("1000")).is_valid is True
        assert RetainedEarningsInvariants.validate_net_income(Decimal("-500")).is_valid is True

    @pytest.mark.parametrize("dividend,balance,expected_valid", [
        (Decimal("500"), Decimal("1000"), True),
        (Decimal("1500"), Decimal("1000"), False),
        (Decimal("0"), Decimal("1000"), False),
        (Decimal("-100"), Decimal("1000"), False),
    ])
    def test_validate_dividend_reduction(self, dividend, balance, expected_valid):
        result = RetainedEarningsInvariants.validate_dividend_reduction(dividend, balance)
        assert result.is_valid == expected_valid
        if not expected_valid:
            if dividend <= 0:
                assert "positive" in result.errors[0]
            else:
                assert "Cannot reduce retained earnings" in result.errors[0]

    @pytest.mark.parametrize("amount,balance,to_reserve,expected_valid", [
        (Decimal("200"), Decimal("1000"), True, True),
        (Decimal("1200"), Decimal("1000"), True, False),
        (Decimal("1000"), Decimal("1000"), False, True),  # from reserve always valid
        (Decimal("0"), Decimal("1000"), True, False),
        (Decimal("-100"), Decimal("1000"), True, False),
    ])
    def test_validate_transfer(self, amount, balance, to_reserve, expected_valid):
        result = RetainedEarningsInvariants.validate_transfer(amount, balance, to_reserve)
        assert result.is_valid == expected_valid
        if not expected_valid:
            if amount <= 0:
                assert "positive" in result.errors[0]
            else:
                assert "Cannot transfer" in result.errors[0]


# =============================================================================
# Tests for DividendInvariants
# =============================================================================

class TestDividendInvariants:
    def test_validate_dividend_declaration_valid(self, fixed_now):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=fixed_now,
            record_date=fixed_now + timedelta(days=9),
            payment_date=fixed_now + timedelta(days=19),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_exceeds_retained_earnings(self, fixed_now):
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("3000"),
            currency="USD",
            declaration_date=fixed_now,
            record_date=fixed_now + timedelta(days=9),
            payment_date=fixed_now + timedelta(days=19),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
        assert "exceeds retained earnings" in result.errors[0]

    def test_validate_dividend_declaration_invalid_dates(self, fixed_now):
        result = DividendInvariants.validate_dividend_declaration(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=fixed_now + timedelta(days=10),
            record_date=fixed_now,
            payment_date=fixed_now + timedelta(days=5),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
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
        assert any("positive" in err.lower() for err in result.errors)

    @pytest.mark.parametrize("current,new,total_paid,total_amount,user_role,expected_valid", [
        (DividendStatus.PROPOSED, DividendStatus.APPROVED, Decimal("0"), Decimal("1000"), "board", True),
        (DividendStatus.PROPOSED, DividendStatus.APPROVED, Decimal("0"), Decimal("1000"), "user", False),
        (DividendStatus.APPROVED, DividendStatus.PAID, Decimal("1000"), Decimal("1000"), "finance", True),
        (DividendStatus.APPROVED, DividendStatus.PAID, Decimal("500"), Decimal("1000"), "finance", False),
        (DividendStatus.APPROVED, DividendStatus.PARTIALLY_PAID, Decimal("500"), Decimal("1000"), "finance", True),
        (DividendStatus.APPROVED, DividendStatus.PARTIALLY_PAID, Decimal("1000"), Decimal("1000"), "finance", False),
        (DividendStatus.PROPOSED, DividendStatus.CANCELLED, Decimal("0"), Decimal("1000"), "user", True),
        (DividendStatus.PROPOSED, DividendStatus.PAID, Decimal("0"), Decimal("1000"), "finance", False),
    ])
    def test_validate_status_transition(self, current, new, total_paid, total_amount, user_role, expected_valid):
        result = DividendInvariants.validate_status_transition(
            current, new, total_paid, total_amount, user_role
        )
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert len(result.errors) > 0


# =============================================================================
# Tests for EquityInvariantEnforcer
# =============================================================================

class TestEquityInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        def get_paid_in_capital():
            return Decimal("10000")
        def get_retained_earnings():
            return Decimal("5000")
        return EquityInvariantEnforcer(
            get_paid_in_capital=get_paid_in_capital,
            get_retained_earnings=get_retained_earnings,
        )

    @pytest.mark.asyncio
    async def test_enforce_contribution_valid(self, enforcer, fixed_now):
        result = await enforcer.enforce_contribution(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=fixed_now,
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
    async def test_enforce_withdrawal_valid(self, enforcer, fixed_now):
        result = await enforcer.enforce_withdrawal(
            amount=Decimal("2000"),
            tax_withheld_amount=Decimal("200"),
            currency="USD",
            withdrawal_date=fixed_now,
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
    async def test_enforce_dividend_valid(self, enforcer, fixed_now):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = await enforcer.enforce_dividend(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=fixed_now,
            record_date=fixed_now + timedelta(days=9),
            payment_date=fixed_now + timedelta(days=19),
            allocations=allocations,
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_dividend_exceeds_retained_earnings(self, enforcer, fixed_now):
        result = await enforcer.enforce_dividend(
            total_amount=Decimal("6000"),
            currency="USD",
            declaration_date=fixed_now,
            record_date=fixed_now + timedelta(days=9),
            payment_date=fixed_now + timedelta(days=19),
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
        # Perbaikan: menggunakan pesan error yang sebenarnya
        assert "Cannot reduce retained earnings" in result.errors[0]

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
        assert "Cannot transfer" in result.errors[0]


# =============================================================================
# Tests for Standalone Helper Functions
# =============================================================================

class TestStandaloneHelpers:
    def test_validate_capital_contribution_invariants(self, fixed_now):
        result = validate_capital_contribution_invariants(
            amount=Decimal("1000"),
            share_percentage=Decimal("25"),
            currency="USD",
            contribution_date=fixed_now,
        )
        assert result.is_valid is True

    def test_validate_capital_withdrawal_invariants(self, fixed_now):
        result = validate_capital_withdrawal_invariants(
            amount=Decimal("1000"),
            tax_withheld_amount=Decimal("100"),
            currency="USD",
            withdrawal_date=fixed_now,
            paid_in_capital=Decimal("5000"),
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_invariants(self, fixed_now):
        allocations = [
            MockAllocation(dividend_amount=Decimal("600"), share_percentage=Decimal("60"), shares_owned=1000),
            MockAllocation(dividend_amount=Decimal("400"), share_percentage=Decimal("40"), shares_owned=800),
        ]
        result = validate_dividend_declaration_invariants(
            total_amount=Decimal("1000"),
            currency="USD",
            declaration_date=fixed_now,
            record_date=fixed_now + timedelta(days=9),
            payment_date=fixed_now + timedelta(days=19),
            retained_earnings_balance=Decimal("2000"),
            allocations=allocations,
        )
        assert result.is_valid is True

    def test_validate_dividend_declaration_invariants_invalid(self, fixed_now):
        result = validate_dividend_declaration_invariants(
            total_amount=Decimal("3000"),
            currency="USD",
            declaration_date=fixed_now + timedelta(days=10),
            record_date=fixed_now,
            payment_date=fixed_now + timedelta(days=5),
            retained_earnings_balance=Decimal("2000"),
            allocations=[],
        )
        assert result.is_valid is False
