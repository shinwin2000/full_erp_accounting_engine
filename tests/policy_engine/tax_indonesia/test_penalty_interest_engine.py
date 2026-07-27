# tests/policy_engine/tax_indonesia/test_penalty_interest_engine.py
"""
Comprehensive unit tests for penalty_interest_engine.py.

Covers:
- Enums: PenaltyType, TaxObligationType
- PenaltyCalculationResult: construction, to_dict
- PenaltyInterestEngine:
  - Private methods: _get_penalty_interest_rate, _get_late_filing_fine
  - Public methods: calculate_penalty, get_interest_rate,
    calculate_late_payment_interest, calculate_late_filing_penalty,
    calculate_tax_correction_penalty, calculate_total_penalty,
    get_grace_period, get_requirements_summary, validate, get_rate, calculate_tax
  - Class methods: calculate, denda_tidak_lapor_ppn
- Singleton accessor: get_penalty_interest_engine
- Edge cases: on-time payments, late payments, zero amounts, registry fallbacks
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from policy_engine.tax_indonesia.penalty_interest_engine import (
    PenaltyCalculationResult,
    PenaltyInterestEngine,
    PenaltyType,
    TaxObligationType,
    get_penalty_interest_engine,
)
from policy_engine.tax_indonesia.rate_registry_dynamic import TaxType


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_registry():
    """Mock RateRegistry with predictable values."""
    with patch(
        "policy_engine.tax_indonesia.penalty_interest_engine.get_dynamic_rate_registry"
    ) as mock_get:
        registry = MagicMock()
        registry.get_penalty_interest_rate.return_value = Decimal("2")  # 2% per month
        registry.get_late_filing_fine.side_effect = lambda key: {
            "monthly_ppn": Decimal("500000"),
            "monthly_pph": Decimal("100000"),
            "annual_corporate": Decimal("1000000"),
            "annual_individual": Decimal("100000"),
        }.get(key, Decimal(0))
        registry.get_grace_period.return_value = 0
        mock_get.return_value = registry
        yield registry


@pytest.fixture
def engine(mock_registry):
    """PenaltyInterestEngine instance with mocked registry."""
    # Reset singleton to ensure fresh instance
    PenaltyInterestEngine._instance = None
    engine = PenaltyInterestEngine()
    return engine


@pytest.fixture
def due_date():
    return datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def payment_date_on_time(due_date):
    return due_date


@pytest.fixture
def payment_date_late(due_date):
    return due_date + timedelta(days=10)


@pytest.fixture
def filing_date_late(due_date):
    return due_date + timedelta(days=5)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPenaltyType:
    def test_members(self):
        assert PenaltyType.INTEREST.value == "interest"
        assert PenaltyType.FINE.value == "fine"
        assert PenaltyType.CRIMINAL.value == "criminal"
        assert PenaltyType.ESCALATED.value == "escalated"


class TestTaxObligationType:
    def test_members(self):
        assert TaxObligationType.MONTHLY_RETURN.value == "monthly_return"
        assert TaxObligationType.ANNUAL_RETURN.value == "annual_return"
        assert TaxObligationType.TAX_PAYMENT.value == "tax_payment"
        assert TaxObligationType.WITHHOLDING.value == "withholding"


# ============================================================================
# Tests for PenaltyCalculationResult
# ============================================================================

class TestPenaltyCalculationResult:
    def test_construction(self, due_date, payment_date_late):
        result = PenaltyCalculationResult(
            penalty_type=PenaltyType.INTEREST,
            tax_type=TaxType.PPN,
            due_date=due_date,
            payment_date=payment_date_late,
            days_late=10,
            tax_amount=Decimal("1000000"),
            interest_rate=Decimal("2"),
            penalty_amount=Decimal("200000"),
            description="Late payment",
        )
        assert result.penalty_type == PenaltyType.INTEREST
        assert result.days_late == 10
        assert result.penalty_amount == Decimal("200000")

    def test_to_dict(self, due_date, payment_date_late):
        result = PenaltyCalculationResult(
            penalty_type=PenaltyType.INTEREST,
            tax_type=TaxType.PPN,
            due_date=due_date,
            payment_date=payment_date_late,
            days_late=10,
            tax_amount=Decimal("1000000"),
            interest_rate=Decimal("2"),
            penalty_amount=Decimal("200000"),
            description="Late payment",
        )
        d = result.to_dict()
        assert d["penalty_type"] == "interest"
        assert d["days_late"] == 10
        assert d["tax_amount"] == "1000000"
        assert d["penalty_amount"] == "200000"
        assert "due_date" in d
        assert "payment_date" in d


# ============================================================================
# Tests for PenaltyInterestEngine
# ============================================================================

class TestPenaltyInterestEngine:
    def test_singleton(self):
        e1 = PenaltyInterestEngine()
        e2 = PenaltyInterestEngine()
        assert e1 is e2

    def test_initialization_uses_registry(self, mock_registry):
        engine = PenaltyInterestEngine()
        assert engine._registry == mock_registry

    # ---- Private methods ----

    def test_get_penalty_interest_rate(self, engine, mock_registry):
        rate = engine._get_penalty_interest_rate()
        assert rate == Decimal("2")
        mock_registry.get_penalty_interest_rate.assert_called_once()

    def test_get_late_filing_fine(self, engine, mock_registry):
        fine = engine._get_late_filing_fine("monthly_ppn")
        assert fine == Decimal("500000")
        mock_registry.get_late_filing_fine.assert_called_with("monthly_ppn")

    # ---- Public methods ----

    def test_calculate_penalty(self, engine):
        result = engine.calculate_penalty(
            pokok=Decimal("1000000"),
            months_late=3,
            tarif_bunga=Decimal("2")
        )
        # 1,000,000 * 2% * 3 = 60,000
        assert result == Decimal("60000")

        # With rounding
        result2 = engine.calculate_penalty(
            pokok=Decimal("999999"),
            months_late=2,
            tarif_bunga=Decimal("2.5")
        )
        # 999,999 * 0.025 * 2 = 49,999.95 -> rounded up to 50,000
        assert result2 == Decimal("50000")

    def test_get_interest_rate(self, engine, mock_registry):
        rate = engine.get_interest_rate()
        assert rate == Decimal("2")
        mock_registry.get_penalty_interest_rate.assert_called_once()

        # With as_of parameter (just calls same)
        rate2 = engine.get_interest_rate(as_of=datetime.now(UTC))
        assert rate2 == Decimal("2")

    def test_calculate_late_payment_interest_on_time(self, engine, due_date):
        result = engine.calculate_late_payment_interest(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=due_date,
            tax_type=TaxType.PPN
        )
        assert result.days_late == 0
        assert result.penalty_amount == Decimal(0)
        assert "on time" in result.description

    def test_calculate_late_payment_interest_late(self, engine, due_date, payment_date_late):
        result = engine.calculate_late_payment_interest(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=payment_date_late,
            tax_type=TaxType.PPN
        )
        # 10 days late => months_late = max(1, (10+29)//30) = max(1, 1) = 1
        # penalty = 1,000,000 * 2% * 1 = 20,000
        assert result.days_late == 10
        assert result.interest_rate == Decimal("2")
        assert result.penalty_amount == Decimal("20000")
        assert "1 month(s)" in result.description

    def test_calculate_late_payment_interest_35_days(self, engine, due_date):
        payment_date = due_date + timedelta(days=35)
        result = engine.calculate_late_payment_interest(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=payment_date,
            tax_type=TaxType.PPN
        )
        # 35 days => months_late = max(1, (35+29)//30) = max(1, 2) = 2
        assert result.days_late == 35
        assert result.penalty_amount == Decimal("40000")  # 1,000,000 * 2% * 2

    def test_calculate_late_filing_penalty_on_time(self, engine, due_date):
        result = engine.calculate_late_filing_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            filing_date=due_date,
            tax_type=TaxType.PPN,
            is_annual=False
        )
        assert result.penalty_amount == Decimal(0)
        assert "on time" in result.description

    def test_calculate_late_filing_penalty_monthly_ppn(self, engine, due_date, filing_date_late):
        result = engine.calculate_late_filing_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            filing_date=filing_date_late,
            tax_type=TaxType.PPN,
            is_annual=False
        )
        # Should use monthly_ppn fine = 500,000
        assert result.penalty_amount == Decimal("500000")
        assert result.days_late == 5
        assert "Masa" in result.description

    def test_calculate_late_filing_penalty_monthly_pph(self, engine, due_date, filing_date_late):
        result = engine.calculate_late_filing_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            filing_date=filing_date_late,
            tax_type=TaxType.PPH_21,
            is_annual=False
        )
        # Should use monthly_pph fine = 100,000
        assert result.penalty_amount == Decimal("100000")

    def test_calculate_late_filing_penalty_annual_individual(self, engine, due_date, filing_date_late):
        result = engine.calculate_late_filing_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            filing_date=filing_date_late,
            tax_type=TaxType.PPH_21,
            is_annual=True
        )
        # Should use annual_individual fine = 100,000
        assert result.penalty_amount == Decimal("100000")

    def test_calculate_late_filing_penalty_annual_corporate(self, engine, due_date, filing_date_late):
        result = engine.calculate_late_filing_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            filing_date=filing_date_late,
            tax_type=TaxType.PPH_25,
            is_annual=True
        )
        # Should use annual_corporate fine = 1,000,000
        assert result.penalty_amount == Decimal("1000000")

    def test_calculate_late_filing_penalty_fallback(self, engine, due_date, filing_date_late):
        # Override mock to return 0 for monthly_pph to test fallback
        with patch.object(engine._registry, "get_late_filing_fine", return_value=Decimal(0)):
            result = engine.calculate_late_filing_penalty(
                tax_amount=Decimal("1000000"),
                due_date=due_date,
                filing_date=filing_date_late,
                tax_type=TaxType.PPH_21,
                is_annual=False
            )
            # Fallback to 100,000 (hardcoded in method)
            assert result.penalty_amount == Decimal("100000")

    def test_calculate_tax_correction_penalty(self, engine, due_date):
        correction_date = due_date + timedelta(days=30)
        result = engine.calculate_tax_correction_penalty(
            underpayment=Decimal("500000"),
            correction_date=correction_date,
            original_due_date=due_date,
            tax_type=TaxType.PPN
        )
        assert result.penalty_type == PenaltyType.ESCALATED
        assert result.penalty_amount == Decimal("500000")
        assert result.interest_rate == Decimal("100")
        assert result.days_late == 30
        assert "Tax correction penalty" in result.description

    def test_calculate_total_penalty_only_interest(self, engine, due_date, payment_date_late):
        result = engine.calculate_total_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=payment_date_late,
            filing_date=None,
            tax_type=TaxType.PPN,
            is_annual=False
        )
        assert result["total_penalty"] == "20000"
        assert len(result["breakdown"]) == 1
        assert result["breakdown"][0]["penalty_type"] == "interest"
        assert result["days_late"] == 10

    def test_calculate_total_penalty_with_filing(self, engine, due_date, payment_date_late, filing_date_late):
        result = engine.calculate_total_penalty(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=payment_date_late,
            filing_date=filing_date_late,
            tax_type=TaxType.PPN,
            is_annual=False
        )
        # interest = 20,000, fine = 500,000 => total 520,000
        assert result["total_penalty"] == "520000"
        assert len(result["breakdown"]) == 2
        assert result["breakdown"][0]["penalty_type"] == "interest"
        assert result["breakdown"][1]["penalty_type"] == "fine"
        assert result["days_late"] == max(10, 5)  # 10

    def test_get_grace_period(self, engine, mock_registry):
        result = engine.get_grace_period(TaxType.PPN)
        assert result == 0
        mock_registry.get_grace_period.assert_called_once_with(TaxType.PPN)

    def test_get_requirements_summary(self, engine, mock_registry):
        summary = engine.get_requirements_summary()
        assert "default_interest_rate" in summary
        assert summary["default_interest_rate"] == "2%"
        assert "late_filing_fines" in summary
        assert summary["late_filing_fines"]["monthly_ppn"] == "500000"
        assert "tax_correction_penalty" in summary
        assert summary["tax_correction_penalty"] == "100% - 200%"

    def test_validate(self, engine):
        assert engine.validate({}) is True
        assert engine.validate({"some": "data"}) is True

    def test_get_rate(self, engine, mock_registry):
        rate = engine.get_rate()
        assert rate == Decimal("2")
        # With tax_type parameter (ignored)
        rate2 = engine.get_rate("PPN")
        assert rate2 == Decimal("2")

    def test_calculate_tax(self, engine, due_date, payment_date_late):
        result = engine.calculate_tax(
            tax_amount=Decimal("1000000"),
            due_date=due_date,
            payment_date=payment_date_late,
            tax_type=TaxType.PPN
        )
        assert result == Decimal("20000")  # same as interest penalty

    # ---- Class methods ----

    def test_classmethod_calculate(self):
        result = PenaltyInterestEngine.calculate(
            pokok=Decimal("1000000"),
            months_late=3,
            tarif_bunga=Decimal("2.5")
        )
        # 1,000,000 * 0.025 * 3 = 75,000
        assert result == Decimal("75000")

    def test_classmethod_denda_tidak_lapor_ppn(self):
        # Use patch to avoid hitting real registry
        with patch(
            "policy_engine.tax_indonesia.penalty_interest_engine.get_dynamic_rate_registry"
        ) as mock_get:
            registry = MagicMock()
            registry.get_late_filing_fine.return_value = Decimal("2")  # 2%
            mock_get.return_value = registry

            result = PenaltyInterestEngine.denda_tidak_lapor_ppn(
                dpp=Decimal("1000000")
            )
            # 2% * 1,000,000 = 20,000
            assert result == Decimal("20000")


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_penalty_interest_engine():
    # Reset singleton
    PenaltyInterestEngine._instance = None
    e1 = get_penalty_interest_engine()
    e2 = get_penalty_interest_engine()
    assert e1 is e2
    assert isinstance(e1, PenaltyInterestEngine)