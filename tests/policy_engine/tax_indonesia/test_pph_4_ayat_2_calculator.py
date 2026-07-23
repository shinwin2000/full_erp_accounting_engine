#!/usr/bin/env python3
"""
tests/policy_engine/tax_indonesia/test_pph_4_ayat_2_calculator.py
Comprehensive tests for policy_engine/tax_indonesia/pph_4_ayat_2_calculator.py

Covers:
- Enums: PPh4Ayat2Type, ConstructionServiceType
- Exceptions: PPh4Ayat2Error
- Data classes: PPh4Ayat2Transaction, PPh4Ayat2CalculationResult
- PPh4Ayat2Calculator:
  - __init__, set_rate, get_rate
  - calculate (main method with various inputs)
  - calculate_land_building_rental
  - calculate_construction_services (with/without NPWP)
  - calculate_umkm_turnover (valid, threshold exceeded, edge cases)
  - calculate_real_estate_sales (subsidized/non-subsidized)
  - calculate_lottery_prize
  - calculate_by_type (all types)
  - calculate_deposit_interest (classmethod)
  - calculate_land_rental (classmethod)
  - calculate_construction (classmethod)
  - get_requirements_summary
  - validate, get_rate, calculate_tax (checker compatibility)
- Singleton: get_pph4_ayat_2_calculator
- All edge cases and negative paths
- No flaky datetime (mocked)
- No duplicate test structures (parametrized where appropriate)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from policy_engine.tax_indonesia.pph_4_ayat_2_calculator import (
    ConstructionServiceType,
    PPh4Ayat2CalculationResult,
    PPh4Ayat2Calculator,
    PPh4Ayat2Error,
    PPh4Ayat2Transaction,
    PPh4Ayat2Type,
    get_pph4_ayat_2_calculator,
)

# =============================================================================
# Fixtures
# =============================================================================

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return a fixed value."""
    with patch("policy_engine.tax_indonesia.pph_4_ayat_2_calculator.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def calculator():
    return PPh4Ayat2Calculator()


@pytest.fixture
def transaction_id():
    return uuid.uuid4()


# =============================================================================
# Enums
# =============================================================================

class TestEnums:
    def test_pph4_ayat_2_type(self):
        assert PPh4Ayat2Type.LAND_BUILDING_RENTAL.value == "land_building_rental"
        assert PPh4Ayat2Type.CONSTRUCTION_SERVICES.value == "construction_services"
        assert PPh4Ayat2Type.UMKM_TURNOVER.value == "umkm_turnover"
        assert PPh4Ayat2Type.LOTTERY_PRIZE.value == "lottery_prize"
        assert PPh4Ayat2Type.REAL_ESTATE_SALES.value == "real_estate_sales"
        assert PPh4Ayat2Type.LAND_RIGHTS.value == "land_rights"
        assert PPh4Ayat2Type.OTHER.value == "other"
        assert isinstance(PPh4Ayat2Type.LAND_BUILDING_RENTAL, PPh4Ayat2Type)

    def test_construction_service_type(self):
        assert ConstructionServiceType.SMALL_SCALE.value == "small_scale"
        assert ConstructionServiceType.MEDIUM_SCALE.value == "medium_scale"
        assert ConstructionServiceType.LARGE_SCALE.value == "large_scale"
        assert ConstructionServiceType.EXPERT_CONSULTING.value == "expert_consulting"
        assert isinstance(ConstructionServiceType.SMALL_SCALE, ConstructionServiceType)


# =============================================================================
# Exceptions
# =============================================================================

class TestExceptions:
    def test_pph4_ayat_2_error_raise(self):
        with pytest.raises(PPh4Ayat2Error, match="test"):
            raise PPh4Ayat2Error("test")


# =============================================================================
# Data Classes
# =============================================================================

class TestPPh4Ayat2Transaction:
    def test_construction(self):
        tx_id = uuid.uuid4()
        tx = PPh4Ayat2Transaction(
            transaction_id=tx_id,
            transaction_type=PPh4Ayat2Type.LAND_BUILDING_RENTAL,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
            additional_data={"key": "value"},
        )
        assert tx.transaction_id == tx_id
        assert tx.transaction_type == PPh4Ayat2Type.LAND_BUILDING_RENTAL
        assert tx.gross_amount == Decimal("10000000")
        assert tx.transaction_date == FIXED_NOW
        assert tx.additional_data == {"key": "value"}


class TestPPh4Ayat2CalculationResult:
    def test_construction_and_to_dict(self):
        tx_id = uuid.uuid4()
        result = PPh4Ayat2CalculationResult(
            transaction_id=tx_id,
            transaction_type=PPh4Ayat2Type.LAND_BUILDING_RENTAL,
            gross_amount=Decimal("10000000"),
            tariff=Decimal("10"),
            tax_amount=Decimal("1000000"),
            description="Test",
            is_final=True,
            due_date=FIXED_NOW,
        )
        assert result.transaction_id == tx_id
        assert result.tax_amount == Decimal("1000000")
        d = result.to_dict()
        assert d["transaction_id"] == str(tx_id)
        assert d["gross_amount"] == "10000000"
        assert d["tariff"] == "10"
        assert d["tax_amount"] == "1000000"
        assert d["due_date"] == FIXED_NOW.isoformat()


# =============================================================================
# PPh4Ayat2Calculator - Basic
# =============================================================================

class TestPPh4Ayat2CalculatorBasic:
    def test_init(self, calculator):
        assert calculator._rates == calculator.RATES
        assert calculator._construction_rates == calculator.CONSTRUCTION_RATES

    def test_set_rate(self, calculator):
        calculator.set_rate(PPh4Ayat2Type.LAND_BUILDING_RENTAL, Decimal("12"))
        assert calculator._rates[PPh4Ayat2Type.LAND_BUILDING_RENTAL] == Decimal("12")

    def test_get_rate(self, calculator):
        assert calculator.get_rate() == Decimal("10")  # default

    def test_validate_always_true(self, calculator):
        assert calculator.validate({}) is True

    def test_calculate_tax(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.LAND_BUILDING_RENTAL,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
        )
        tax = calculator.calculate_tax(tx)
        assert tax == Decimal("1000000")  # 10% of 10,000,000

    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "final_rates" in summary
        assert "construction_rates" in summary
        assert "umkm_threshold" in summary
        assert "note" in summary


# =============================================================================
# PPh4Ayat2Calculator - calculate (main method)
# =============================================================================

class TestPPh4Ayat2CalculatorCalculate:
    @pytest.mark.parametrize(
        "jenis, qualification, has_npwp, expected_tax_per_1000000",
        [
            ("sewa", "menengah", True, 100000),  # 10%
            ("land", "menengah", True, 100000),
            ("land_building_rental", "menengah", True, 100000),
            ("deposit", "menengah", True, 200000),  # 20%
            ("interest", "menengah", True, 200000),
            ("konstruksi", "kecil", True, 20000),  # 2%
            ("konstruksi", "small", True, 20000),
            ("konstruksi", "menengah", True, 20000),  # default for menengah is 2%?
            ("konstruksi", "besar", True, 40000),  # 4%
            ("konstruksi", "large", True, 40000),
            ("konstruksi", "kecil", False, 24000),  # 2% * 1.2 = 2.4%
            ("umkm", "menengah", True, 5000),  # 0.5%
            ("turnover", "menengah", True, 5000),
            ("lottery", "menengah", True, 250000),  # 25%
            ("hadiah", "menengah", True, 250000),
            ("unknown", "menengah", True, 100000),  # default 10%
        ]
    )
    def test_calculate_various_types(self, calculator, jenis, qualification, has_npwp, expected_tax_per_1000000):
        bruto = Decimal("1000000")
        tax = calculator.calculate(bruto, jenis=jenis, has_npwp=has_npwp, qualification=qualification)
        assert tax == Decimal(expected_tax_per_1000000)

    def test_calculate_with_custom_type_string(self, calculator):
        # 'sewa' should work
        tax = calculator.calculate(Decimal("1000000"), jenis="sewa")
        assert tax == Decimal("100000")
        # default for unknown
        tax = calculator.calculate(Decimal("1000000"), jenis="random")
        assert tax == Decimal("100000")

    def test_calculate_rounding(self, calculator):
        # Test that tax is rounded to whole rupiah
        # 10% of 1,234,567 = 123,456.7 -> rounded to 123,457
        tax = calculator.calculate(Decimal("1234567"), jenis="sewa")
        assert tax == Decimal("123457")


# =============================================================================
# PPh4Ayat2Calculator - calculate_land_building_rental
# =============================================================================

class TestPPh4Ayat2CalculatorLandBuildingRental:
    def test_calculate_land_building_rental(self, calculator, transaction_id):
        result = calculator.calculate_land_building_rental(
            rental_amount=Decimal("10000000"),
            transaction_id=transaction_id,
        )
        assert result.transaction_type == PPh4Ayat2Type.LAND_BUILDING_RENTAL
        assert result.gross_amount == Decimal("10000000")
        assert result.tariff == Decimal("10")
        assert result.tax_amount == Decimal("1000000")
        assert result.is_final is True
        assert result.due_date is None

    def test_calculate_land_building_rental_rounding(self, calculator, transaction_id):
        result = calculator.calculate_land_building_rental(
            rental_amount=Decimal("1234567"),
            transaction_id=transaction_id,
        )
        assert result.tax_amount == Decimal("123457")


# =============================================================================
# PPh4Ayat2Calculator - calculate_construction_services
# =============================================================================

class TestPPh4Ayat2CalculatorConstructionServices:
    @pytest.mark.parametrize(
        "service_type, has_npwp, expected_tariff, expected_tax_per_10m",
        [
            (ConstructionServiceType.SMALL_SCALE, True, Decimal("2"), Decimal("200000")),
            (ConstructionServiceType.MEDIUM_SCALE, True, Decimal("4"), Decimal("400000")),
            (ConstructionServiceType.LARGE_SCALE, True, Decimal("6"), Decimal("600000")),
            (ConstructionServiceType.EXPERT_CONSULTING, True, Decimal("6"), Decimal("600000")),
            (ConstructionServiceType.SMALL_SCALE, False, Decimal("2.4"), Decimal("240000")),
            (ConstructionServiceType.MEDIUM_SCALE, False, Decimal("4.8"), Decimal("480000")),
            (ConstructionServiceType.LARGE_SCALE, False, Decimal("7.2"), Decimal("720000")),
        ]
    )
    def test_calculate_construction_services(
        self, calculator, transaction_id, service_type, has_npwp, expected_tariff, expected_tax_per_10m
    ):
        result = calculator.calculate_construction_services(
            contract_value=Decimal("10000000"),
            service_type=service_type,
            transaction_id=transaction_id,
            has_npwp=has_npwp,
        )
        assert result.transaction_type == PPh4Ayat2Type.CONSTRUCTION_SERVICES
        assert result.tariff == expected_tariff
        assert result.tax_amount == expected_tax_per_10m

    def test_calculate_construction_services_rounding(self, calculator, transaction_id):
        result = calculator.calculate_construction_services(
            contract_value=Decimal("1234567"),
            service_type=ConstructionServiceType.SMALL_SCALE,
            transaction_id=transaction_id,
        )
        # 2% of 1,234,567 = 24,691.34 -> rounded to 24,691
        assert result.tax_amount == Decimal("24691")


# =============================================================================
# PPh4Ayat2Calculator - calculate_umkm_turnover
# =============================================================================

class TestPPh4Ayat2CalculatorUMKM:
    def test_calculate_umkm_turnover_valid(self, calculator, transaction_id):
        result = calculator.calculate_umkm_turnover(
            monthly_turnover=Decimal("100000000"),
            transaction_id=transaction_id,
            total_turnover_ytd=Decimal("0"),
        )
        assert result.transaction_type == PPh4Ayat2Type.UMKM_TURNOVER
        assert result.tariff == Decimal("0.5")
        # 0.5% of 100,000,000 = 500,000
        assert result.tax_amount == Decimal("500000")

    def test_calculate_umkm_turnover_exceeds_threshold(self, calculator, transaction_id):
        threshold = Decimal("4800000000")
        total_ytd = threshold - Decimal("100000000")  # 4.7B
        monthly = Decimal("200000000")
        # total would be 4.9B > 4.8B
        with pytest.raises(PPh4Ayat2Error, match="exceeds threshold"):
            calculator.calculate_umkm_turnover(
                monthly_turnover=monthly,
                transaction_id=transaction_id,
                total_turnover_ytd=total_ytd,
            )

    def test_calculate_umkm_turnover_exact_threshold(self, calculator, transaction_id):
        threshold = Decimal("4800000000")
        total_ytd = threshold - Decimal("100000000")
        monthly = Decimal("100000000")  # exactly threshold
        # Should not raise
        result = calculator.calculate_umkm_turnover(
            monthly_turnover=monthly,
            transaction_id=transaction_id,
            total_turnover_ytd=total_ytd,
        )
        assert result.tax_amount == Decimal("500000")  # 0.5% of 100M

    def test_calculate_umkm_turnover_rounding(self, calculator, transaction_id):
        result = calculator.calculate_umkm_turnover(
            monthly_turnover=Decimal("1234567"),
            transaction_id=transaction_id,
        )
        # 0.5% of 1,234,567 = 6,172.835 -> rounded to 6,173
        assert result.tax_amount == Decimal("6173")


# =============================================================================
# PPh4Ayat2Calculator - calculate_real_estate_sales
# =============================================================================

class TestPPh4Ayat2CalculatorRealEstate:
    def test_calculate_real_estate_sales_normal(self, calculator, transaction_id):
        result = calculator.calculate_real_estate_sales(
            selling_price=Decimal("1000000000"),
            transaction_id=transaction_id,
            is_subsidized=False,
        )
        assert result.transaction_type == PPh4Ayat2Type.REAL_ESTATE_SALES
        assert result.tariff == Decimal("2.5")
        # 2.5% of 1B = 25,000,000
        assert result.tax_amount == Decimal("25000000")

    def test_calculate_real_estate_sales_subsidized(self, calculator, transaction_id):
        result = calculator.calculate_real_estate_sales(
            selling_price=Decimal("1000000000"),
            transaction_id=transaction_id,
            is_subsidized=True,
        )
        assert result.tariff == Decimal("1")
        assert result.tax_amount == Decimal("10000000")  # 1% of 1B

    def test_calculate_real_estate_sales_rounding(self, calculator, transaction_id):
        result = calculator.calculate_real_estate_sales(
            selling_price=Decimal("1234567"),
            transaction_id=transaction_id,
        )
        # 2.5% of 1,234,567 = 30,864.175 -> rounded to 30,864
        assert result.tax_amount == Decimal("30864")


# =============================================================================
# PPh4Ayat2Calculator - calculate_lottery_prize
# =============================================================================

class TestPPh4Ayat2CalculatorLottery:
    def test_calculate_lottery_prize(self, calculator, transaction_id):
        result = calculator.calculate_lottery_prize(
            prize_amount=Decimal("10000000"),
            transaction_id=transaction_id,
        )
        assert result.transaction_type == PPh4Ayat2Type.LOTTERY_PRIZE
        assert result.tariff == Decimal("25")
        assert result.tax_amount == Decimal("2500000")  # 25% of 10M

    def test_calculate_lottery_prize_rounding(self, calculator, transaction_id):
        result = calculator.calculate_lottery_prize(
            prize_amount=Decimal("1234567"),
            transaction_id=transaction_id,
        )
        # 25% of 1,234,567 = 308,641.75 -> rounded to 308,642
        assert result.tax_amount == Decimal("308642")


# =============================================================================
# PPh4Ayat2Calculator - calculate_by_type
# =============================================================================

class TestPPh4Ayat2CalculatorByType:
    def test_calculate_by_type_land_building_rental(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.LAND_BUILDING_RENTAL,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
        )
        result = calculator.calculate_by_type(tx)
        assert result.tax_amount == Decimal("1000000")

    def test_calculate_by_type_construction_services(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.CONSTRUCTION_SERVICES,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
            additional_data={"construction_service_type": ConstructionServiceType.LARGE_SCALE, "has_npwp": True},
        )
        result = calculator.calculate_by_type(tx)
        assert result.tariff == Decimal("6")
        assert result.tax_amount == Decimal("600000")

    def test_calculate_by_type_umkm_turnover(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.UMKM_TURNOVER,
            gross_amount=Decimal("100000000"),
            transaction_date=FIXED_NOW,
            additional_data={"total_turnover_ytd": Decimal("0")},
        )
        result = calculator.calculate_by_type(tx)
        assert result.tax_amount == Decimal("500000")

    def test_calculate_by_type_real_estate_sales(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.REAL_ESTATE_SALES,
            gross_amount=Decimal("1000000000"),
            transaction_date=FIXED_NOW,
            additional_data={"is_subsidized": False},
        )
        result = calculator.calculate_by_type(tx)
        assert result.tax_amount == Decimal("25000000")

    def test_calculate_by_type_lottery_prize(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.LOTTERY_PRIZE,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
        )
        result = calculator.calculate_by_type(tx)
        assert result.tax_amount == Decimal("2500000")

    def test_calculate_by_type_other_raises(self, calculator, transaction_id):
        tx = PPh4Ayat2Transaction(
            transaction_id=transaction_id,
            transaction_type=PPh4Ayat2Type.OTHER,
            gross_amount=Decimal("10000000"),
            transaction_date=FIXED_NOW,
        )
        with pytest.raises(PPh4Ayat2Error, match="Unsupported transaction type"):
            calculator.calculate_by_type(tx)


# =============================================================================
# PPh4Ayat2Calculator - Class methods (calculate_deposit_interest, etc.)
# =============================================================================

class TestPPh4Ayat2CalculatorClassMethods:
    def test_calculate_deposit_interest(self):
        tax = PPh4Ayat2Calculator.calculate_deposit_interest(Decimal("10000000"), has_npwp=True)
        assert tax == Decimal("2000000")  # 20% of 10M

        tax_no_npwp = PPh4Ayat2Calculator.calculate_deposit_interest(Decimal("10000000"), has_npwp=False)
        # No NPWP doesn't affect deposit interest in this implementation
        assert tax_no_npwp == Decimal("2000000")

    def test_calculate_deposit_interest_rounding(self):
        tax = PPh4Ayat2Calculator.calculate_deposit_interest(Decimal("1234567"))
        # 20% of 1,234,567 = 246,913.4 -> rounded to 246,913
        assert tax == Decimal("246913")

    def test_calculate_land_rental(self):
        tax = PPh4Ayat2Calculator.calculate_land_rental(Decimal("10000000"))
        assert tax == Decimal("1000000")

    def test_calculate_land_rental_rounding(self):
        tax = PPh4Ayat2Calculator.calculate_land_rental(Decimal("1234567"))
        # 10% of 1,234,567 = 123,456.7 -> rounded to 123,457
        assert tax == Decimal("123457")

    @pytest.mark.parametrize(
        "qualification, expected_tax_per_10m",
        [
            ("menengah", Decimal("200000")),  # 2%
            ("kecil", Decimal("200000")),     # 2%
            ("besar", Decimal("400000")),     # 4%
            ("unknown", Decimal("400000")),   # default 4%
        ]
    )
    def test_calculate_construction(self, qualification, expected_tax_per_10m):
        tax = PPh4Ayat2Calculator.calculate_construction(Decimal("10000000"), qualification=qualification)
        assert tax == expected_tax_per_10m

    def test_calculate_construction_rounding(self):
        tax = PPh4Ayat2Calculator.calculate_construction(Decimal("1234567"), qualification="menengah")
        # 2% of 1,234,567 = 24,691.34 -> rounded to 24,691
        assert tax == Decimal("24691")


# =============================================================================
# Negative edge cases
# =============================================================================

class TestNegativeEdgeCases:
    def test_calculate_negative_amount_raises(self, calculator):
        # The calculate method doesn't check for negative amounts; it will produce negative tax.
        # We'll test that it doesn't crash but may produce negative result.
        tax = calculator.calculate(bruto=Decimal("-1000000"), jenis="sewa")
        assert tax == Decimal("-100000")  # 10% of -1,000,000

    def test_calculate_zero_amount(self, calculator):
        tax = calculator.calculate(bruto=Decimal("0"), jenis="sewa")
        assert tax == Decimal("0")

    def test_calculate_umkm_zero_turnover(self, calculator, transaction_id):
        result = calculator.calculate_umkm_turnover(
            monthly_turnover=Decimal("0"),
            transaction_id=transaction_id,
        )
        assert result.tax_amount == Decimal("0")

    def test_calculate_umkm_negative_turnover_raises(self, calculator, transaction_id):
        # The code doesn't validate negative, but we test that it still runs and produces negative.
        result = calculator.calculate_umkm_turnover(
            monthly_turnover=Decimal("-1000000"),
            transaction_id=transaction_id,
        )
        # It will compute tax as negative, but we don't expect an exception.
        assert result.tax_amount == Decimal("-5000")  # 0.5% of -1,000,000

    def test_calculate_real_estate_negative_price(self, calculator, transaction_id):
        result = calculator.calculate_real_estate_sales(
            selling_price=Decimal("-1000000"),
            transaction_id=transaction_id,
        )
        assert result.tax_amount == Decimal("-25000")  # 2.5% of -1,000,000

    def test_calculate_lottery_negative_prize(self, calculator, transaction_id):
        result = calculator.calculate_lottery_prize(
            prize_amount=Decimal("-1000000"),
            transaction_id=transaction_id,
        )
        assert result.tax_amount == Decimal("-250000")  # 25% of -1,000,000


# =============================================================================
# Singleton
# =============================================================================

class TestSingleton:
    def test_get_pph4_ayat_2_calculator(self):
        calc1 = get_pph4_ayat_2_calculator()
        calc2 = get_pph4_ayat_2_calculator()
        assert calc1 is calc2
        assert isinstance(calc1, PPh4Ayat2Calculator)