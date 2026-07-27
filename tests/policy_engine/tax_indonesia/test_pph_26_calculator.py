# tests/policy_engine/tax_indonesia/test_pph_26_calculator.py
"""
Comprehensive tests for policy_engine/tax_indonesia/pph_26_calculator.py.

Covers:
- Enums: PPh26IncomeType, TreatyStatus
- Exceptions: PPh26Error, TreatyRateNotFoundError
- TreatyRate: construction, to_dict
- PPh26CalculationResult: construction, to_dict, hash
- PPh26TreatyRegistry: _get_registry, get_rate, get_treaty_article, add_treaty_rate
- PPh26Calculator:
  - __init__, singleton
  - _get_default_rate
  - calculate (simple wrapper)
  - _calculate_full (comprehensive calculation with treaty, exemption, overrides)
  - calculate_dividend, calculate_interest, calculate_royalty, calculate_service
  - add_treaty_rate, get_treaty_rate
  - get_requirements_summary
  - calculate_tax_simple (classmethod)
  - validate, get_rate, calculate_tax (compatibility methods)
- Module-level get_pph26_calculator
- Edge cases: negative gross, exempt, treaty rate override, fallback default
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from policy_engine.tax_indonesia.pph_26_calculator import (
    PPh26CalculationResult,
    PPh26Calculator,
    PPh26Error,
    PPh26IncomeType,
    PPh26TreatyRegistry,
    TreatyRate,
    TreatyRateNotFoundError,
    TreatyStatus,
    get_pph26_calculator,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_registry():
    """Mock the dynamic rate registry."""
    registry = MagicMock()
    registry.get_pph26_default_rate.return_value = Decimal("20")
    registry.get_pph26_treaty_rate.return_value = Decimal("10")
    registry.set = MagicMock()
    return registry


@pytest.fixture
def calculator(mock_registry):
    """PPh26Calculator with mocked registry."""
    with patch(
        "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
    ) as mock_get:
        mock_get.return_value = mock_registry
        # Reset singleton
        PPh26Calculator._instance = None
        calc = PPh26Calculator()
        return calc


@pytest.fixture
def sample_treaty_rate():
    return TreatyRate(
        country_code="SG",
        income_type=PPh26IncomeType.DIVIDEND,
        rate=Decimal("10"),
        article="Article 10",
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        effective_to=None,
        condition="Minimal 25% ownership",
    )


@pytest.fixture
def transaction_id():
    return uuid4()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestPPh26IncomeType:
    def test_members(self):
        assert PPh26IncomeType.DIVIDEND.value == "dividen"
        assert PPh26IncomeType.INTEREST.value == "bunga"
        assert PPh26IncomeType.ROYALTY.value == "royalti"
        assert PPh26IncomeType.SERVICE.value == "jasa"
        assert PPh26IncomeType.RENTAL.value == "sewa"
        assert PPh26IncomeType.PRIZE_AWARD.value == "hadiah_penghargaan"
        assert PPh26IncomeType.PENSION.value == "pensiun"
        assert PPh26IncomeType.OTHER_INCOME.value == "penghasilan_lainnya"


class TestTreatyStatus:
    def test_members(self):
        assert TreatyStatus.HAS_TREATY.value == "ada_p3b"
        assert TreatyStatus.NO_TREATY.value == "tidak_ada_p3b"
        assert TreatyStatus.TREATY_APPLIED.value == "p3b_diterapkan"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_pph26_error(self):
        with pytest.raises(PPh26Error):
            raise PPh26Error("test")

    def test_treaty_rate_not_found_error(self):
        with pytest.raises(TreatyRateNotFoundError):
            raise TreatyRateNotFoundError("test")


# ============================================================================
# Tests for TreatyRate
# ============================================================================

class TestTreatyRate:
    def test_construction(self, sample_treaty_rate):
        assert sample_treaty_rate.country_code == "SG"
        assert sample_treaty_rate.rate == Decimal("10")
        assert sample_treaty_rate.article == "Article 10"
        assert sample_treaty_rate.effective_from == datetime(2020, 1, 1, tzinfo=UTC)

    def test_to_dict(self, sample_treaty_rate):
        d = sample_treaty_rate.to_dict()
        assert d["country_code"] == "SG"
        assert d["income_type"] == "dividen"
        assert d["rate"] == "10"
        assert d["article"] == "Article 10"
        assert d["condition"] == "Minimal 25% ownership"
        assert "effective_from" in d
        assert d["effective_to"] is None


# ============================================================================
# Tests for PPh26CalculationResult
# ============================================================================

class TestPPh26CalculationResult:
    def test_construction(self, transaction_id):
        calc_id = uuid4()
        result = PPh26CalculationResult(
            calculation_id=calc_id,
            transaction_id=transaction_id,
            income_type=PPh26IncomeType.DIVIDEND,
            gross_amount=Decimal("1000000"),
            tariff=Decimal("20"),
            tax_amount=Decimal("200000"),
            treaty_status=TreatyStatus.NO_TREATY,
            country_code=None,
        )
        assert result.calculation_id == calc_id
        assert result.gross_amount == Decimal("1000000")
        assert result.tax_amount == Decimal("200000")
        assert result.hash_sha256 != ""

    def test_compute_hash(self, transaction_id):
        result = PPh26CalculationResult(
            calculation_id=uuid4(),
            transaction_id=transaction_id,
            income_type=PPh26IncomeType.DIVIDEND,
            gross_amount=Decimal("1000000"),
            tariff=Decimal("20"),
            tax_amount=Decimal("200000"),
            treaty_status=TreatyStatus.NO_TREATY,
        )
        h1 = result._compute_hash()
        h2 = result._compute_hash()
        assert h1 == h2
        # Change something should change hash
        result2 = PPh26CalculationResult(
            calculation_id=result.calculation_id,
            transaction_id=transaction_id,
            income_type=PPh26IncomeType.DIVIDEND,
            gross_amount=Decimal("2000000"),
            tariff=Decimal("20"),
            tax_amount=Decimal("400000"),
            treaty_status=TreatyStatus.NO_TREATY,
        )
        assert result2._compute_hash() != h1

    def test_to_dict(self, transaction_id):
        result = PPh26CalculationResult(
            calculation_id=uuid4(),
            transaction_id=transaction_id,
            income_type=PPh26IncomeType.DIVIDEND,
            gross_amount=Decimal("1000000"),
            tariff=Decimal("20"),
            tax_amount=Decimal("200000"),
            treaty_status=TreatyStatus.NO_TREATY,
            country_code="US",
            treaty_rate_applied=None,
            treaty_article=None,
            description="Test",
        )
        d = result.to_dict()
        assert d["gross_amount"] == "1000000"
        assert d["tax_amount"] == "200000"
        assert d["treaty_status"] == "tidak_ada_p3b"
        assert d["country_code"] == "US"
        assert "hash" in d


# ============================================================================
# Tests for PPh26TreatyRegistry
# ============================================================================

class TestPPh26TreatyRegistry:
    def test_get_registry(self, mock_registry):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            registry = PPh26TreatyRegistry._get_registry()
            assert registry == mock_registry

    def test_get_rate_found(self, mock_registry):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            rate = PPh26TreatyRegistry.get_rate(
                "SG", PPh26IncomeType.DIVIDEND, datetime.now(UTC)
            )
            assert rate == Decimal("10")
            mock_registry.get_pph26_treaty_rate.assert_called_once_with("SG", "dividen")

    def test_get_rate_not_found(self, mock_registry):
        mock_registry.get_pph26_treaty_rate.return_value = None
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            rate = PPh26TreatyRegistry.get_rate(
                "XX", PPh26IncomeType.DIVIDEND, datetime.now(UTC)
            )
            assert rate is None

    def test_get_treaty_article(self):
        assert PPh26TreatyRegistry.get_treaty_article("SG", PPh26IncomeType.DIVIDEND) == "Article 10"
        assert PPh26TreatyRegistry.get_treaty_article("SG", PPh26IncomeType.INTEREST) == "Article 11"
        assert PPh26TreatyRegistry.get_treaty_article("SG", PPh26IncomeType.ROYALTY) == "Article 12"
        assert PPh26TreatyRegistry.get_treaty_article("SG", PPh26IncomeType.SERVICE) == "Article 13"

    def test_add_treaty_rate(self, mock_registry, sample_treaty_rate):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            PPh26TreatyRegistry.add_treaty_rate(sample_treaty_rate)
            mock_registry.set.assert_called_once_with(
                "treaty_SG_dividen", Decimal("10")
            )


# ============================================================================
# Tests for PPh26Calculator
# ============================================================================

class TestPPh26Calculator:
    def test_singleton(self, calculator):
        calc2 = PPh26Calculator()
        assert calc2 is calculator

    def test__get_default_rate(self, calculator, mock_registry):
        rate = calculator._get_default_rate()
        assert rate == Decimal("20")
        mock_registry.get_pph26_default_rate.assert_called_once()

    # ---- calculate (simple) ----

    def test_calculate_no_treaty(self, calculator):
        tax = calculator.calculate(
            gross_income=Decimal("1000000"),
            country_code="US",
            has_treaty=False,
        )
        # 20% of 1,000,000 = 200,000
        assert tax == Decimal("200000")

    def test_calculate_with_treaty_rate_override(self, calculator):
        tax = calculator.calculate(
            gross_income=Decimal("1000000"),
            country_code="SG",
            has_treaty=True,
            treaty_rate=Decimal("10"),
        )
        assert tax == Decimal("100000")  # 10% of 1,000,000

    def test_calculate_with_treaty_from_registry(self, calculator, mock_registry):
        tax = calculator.calculate(
            gross_income=Decimal("1000000"),
            country_code="SG",
            has_treaty=True,
        )
        assert tax == Decimal("100000")  # 10% from registry

    def test_calculate_with_treaty_not_found_fallback(self, calculator, mock_registry):
        mock_registry.get_pph26_treaty_rate.return_value = None
        tax = calculator.calculate(
            gross_income=Decimal("1000000"),
            country_code="XX",
            has_treaty=True,
        )
        assert tax == Decimal("200000")  # fallback to 20%

    # ---- _calculate_full ----

    def test_calculate_full_no_treaty(self, calculator, transaction_id):
        result = calculator._calculate_full(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code=None,
            has_treaty=False,
        )
        assert result.tax_amount == Decimal("200000")
        assert result.tariff == Decimal("20")
        assert result.treaty_status == TreatyStatus.NO_TREATY
        assert result.country_code is None

    def test_calculate_full_with_treaty(self, calculator, transaction_id):
        result = calculator._calculate_full(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code="SG",
            has_treaty=True,
        )
        assert result.tax_amount == Decimal("100000")
        assert result.tariff == Decimal("10")
        assert result.treaty_status == TreatyStatus.TREATY_APPLIED
        assert result.treaty_article == "Article 10"
        assert result.country_code == "SG"

    def test_calculate_full_with_treaty_override(self, calculator, transaction_id):
        result = calculator._calculate_full(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code="SG",
            has_treaty=True,
            treaty_rate_override=Decimal("5"),
        )
        assert result.tax_amount == Decimal("50000")
        assert result.tariff == Decimal("5")
        assert result.treaty_status == TreatyStatus.TREATY_APPLIED
        assert result.treaty_article == "Manual override"

    def test_calculate_full_exempt(self, calculator, transaction_id):
        result = calculator._calculate_full(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code=None,
            has_treaty=False,
            is_exempt=True,
            exemption_reason="Treaty exemption",
        )
        assert result.tax_amount == Decimal("0")
        assert result.tariff == Decimal("0")
        assert result.description == "Exempted: Treaty exemption"

    def test_calculate_full_negative_gross_raises(self, calculator, transaction_id):
        with pytest.raises(ValueError, match="Gross amount cannot be negative"):
            calculator._calculate_full(
                transaction_id=transaction_id,
                gross_amount=Decimal("-100"),
                income_type=PPh26IncomeType.DIVIDEND,
            )

    def test_calculate_full_effective_date(self, calculator, transaction_id):
        as_of = datetime.now(UTC) - timedelta(days=10)
        # If registry returns rate based on date, we test that it's passed
        with patch.object(calculator._treaty_registry, "get_rate") as mock_get_rate:
            mock_get_rate.return_value = Decimal("15")
            result = calculator._calculate_full(
                transaction_id=transaction_id,
                gross_amount=Decimal("1000000"),
                income_type=PPh26IncomeType.DIVIDEND,
                country_code="SG",
                has_treaty=True,
                effective_date=as_of,
            )
            mock_get_rate.assert_called_once_with("SG", PPh26IncomeType.DIVIDEND, as_of)
            assert result.tariff == Decimal("15")

    # ---- calculate_dividend, etc. ----

    def test_calculate_dividend(self, calculator, transaction_id):
        result = calculator.calculate_dividend(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            country_code="SG",
            has_treaty=True,
        )
        assert result.income_type == PPh26IncomeType.DIVIDEND
        assert result.tax_amount == Decimal("100000")

    def test_calculate_interest(self, calculator, transaction_id):
        result = calculator.calculate_interest(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            country_code="US",
            has_treaty=False,
        )
        assert result.income_type == PPh26IncomeType.INTEREST
        assert result.tax_amount == Decimal("200000")

    def test_calculate_royalty(self, calculator, transaction_id):
        result = calculator.calculate_royalty(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            country_code="JP",
            has_treaty=True,
        )
        assert result.income_type == PPh26IncomeType.ROYALTY

    def test_calculate_service(self, calculator, transaction_id):
        result = calculator.calculate_service(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            country_code="DE",
            has_treaty=False,
        )
        assert result.income_type == PPh26IncomeType.SERVICE

    # ---- add_treaty_rate, get_treaty_rate ----

    def test_add_treaty_rate(self, calculator, sample_treaty_rate):
        with patch.object(calculator._treaty_registry, "add_treaty_rate") as mock_add:
            calculator.add_treaty_rate(sample_treaty_rate)
            mock_add.assert_called_once_with(sample_treaty_rate)

    def test_get_treaty_rate(self, calculator):
        as_of = datetime.now(UTC)
        with patch.object(calculator._treaty_registry, "get_rate") as mock_get:
            mock_get.return_value = Decimal("10")
            rate = calculator.get_treaty_rate("SG", PPh26IncomeType.DIVIDEND, as_of)
            assert rate == Decimal("10")
            mock_get.assert_called_once_with("SG", PPh26IncomeType.DIVIDEND, as_of)

    # ---- get_requirements_summary ----

    def test_get_requirements_summary(self, calculator, mock_registry):
        summary = calculator.get_requirements_summary()
        assert "default_rate" in summary
        assert "20%" in summary["default_rate"]
        assert "treaty_reduction" in summary
        assert "types_of_income" in summary
        assert "exemptions" in summary

    # ---- calculate_tax_simple (classmethod) ----

    def test_calculate_tax_simple_no_treaty(self, mock_registry):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            tax = PPh26Calculator.calculate_tax_simple(
                gross_income=Decimal("1000000"),
                country_code="US",
                has_treaty=False,
            )
            assert tax == Decimal("200000")

    def test_calculate_tax_simple_with_treaty_override(self, mock_registry):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            tax = PPh26Calculator.calculate_tax_simple(
                gross_income=Decimal("1000000"),
                country_code="SG",
                has_treaty=True,
                treaty_rate=10,
            )
            assert tax == Decimal("100000")

    def test_calculate_tax_simple_treaty_from_registry(self, mock_registry):
        with patch(
            "policy_engine.tax_indonesia.pph_26_calculator.get_dynamic_rate_registry"
        ) as mock_get:
            mock_get.return_value = mock_registry
            tax = PPh26Calculator.calculate_tax_simple(
                gross_income=Decimal("1000000"),
                country_code="SG",
                has_treaty=True,
            )
            assert tax == Decimal("100000")
            mock_registry.get_pph26_treaty_rate.assert_called_once_with("SG", "dividen")

    # ---- validate ----

    def test_validate(self, calculator):
        assert calculator.validate({}) is True
        assert calculator.validate({"some": "data"}) is True

    # ---- get_rate ----

    def test_get_rate(self, calculator, mock_registry):
        rate = calculator.get_rate()
        assert rate == Decimal("20")
        # With tax_type parameter (ignored)
        rate2 = calculator.get_rate("PPH26")
        assert rate2 == Decimal("20")

    # ---- calculate_tax (compatibility) ----

    def test_calculate_tax(self, calculator, transaction_id):
        tax = calculator.calculate_tax(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code="SG",
            has_treaty=True,
        )
        assert tax == Decimal("100000")

    def test_calculate_tax_exempt(self, calculator, transaction_id):
        tax = calculator.calculate_tax(
            transaction_id=transaction_id,
            gross_amount=Decimal("1000000"),
            income_type=PPh26IncomeType.DIVIDEND,
            country_code="SG",
            has_treaty=True,
            is_exempt=True,
            exemption_reason="Test",
        )
        assert tax == Decimal("0")


# ============================================================================
# Test for module-level get_pph26_calculator
# ============================================================================

def test_get_pph26_calculator():
    # Reset singleton
    import policy_engine.tax_indonesia.pph_26_calculator as module
    module._pph26_calculator_instance = None
    calc1 = get_pph26_calculator()
    calc2 = get_pph26_calculator()
    assert calc1 is calc2
    assert isinstance(calc1, PPh26Calculator)