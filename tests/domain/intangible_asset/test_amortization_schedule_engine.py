# test_amortization_schedule_engine.py
# Comprehensive tests for domain/intangible_asset/amortization_schedule_engine.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from domain.intangible_asset.amortization_schedule_engine import (
    AmortizationEntry,
    AmortizationSchedule,
    AmortizationScheduleEngine,
    _days_in_year,
    _prorate_factor,
    _round_decimal,
    calculate_amortization_rate,
    calculate_remaining_useful_life,
    is_fully_amortized,
)


# =============================================================================
# Mock Asset Class for Testing
# =============================================================================

class MockIntangibleAsset:
    """Mock implementation of IntangibleAssetEntity for testing."""

    def __init__(
        self,
        asset_id: UUID | None = None,
        asset_code: str = "TEST-001",
        asset_name: str = "Test Asset",
        acquisition_date: datetime | None = None,
        cost: Decimal = Decimal("100000"),
        residual_value: Decimal = Decimal("0"),
        useful_life_years: int = 5,
        has_indefinite_life: bool = False,
        amortization_method: Any = None,
        currency: str = "IDR",
    ):
        self.asset_id = asset_id or uuid4()
        self.asset_code = asset_code
        self.asset_name = asset_name
        self.acquisition_date = acquisition_date or datetime(2020, 1, 1, tzinfo=UTC)
        self.cost = cost
        self.residual_value = residual_value
        self.useful_life_years = useful_life_years
        self.has_indefinite_life = has_indefinite_life
        self.amortization_method = amortization_method
        self.currency = currency

    @property
    def is_amortizable(self) -> bool:
        return self.cost > self.residual_value and self.useful_life_years > 0

    @property
    def amortizable_amount(self) -> Decimal:
        return max(self.cost - self.residual_value, Decimal("0"))


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestHelperFunctions:
    def test_days_in_year_leap(self):
        assert _days_in_year(2020) == 366
        assert _days_in_year(2024) == 366
        assert _days_in_year(2000) == 366

    def test_days_in_year_non_leap(self):
        assert _days_in_year(2021) == 365
        assert _days_in_year(2022) == 365
        assert _days_in_year(2023) == 365

    def test_prorate_factor_asset_before_period(self):
        asset_date = datetime(2020, 1, 1, tzinfo=UTC)
        period_start = datetime(2020, 1, 1, tzinfo=UTC)
        period_end = datetime(2020, 12, 31, tzinfo=UTC)
        assert _prorate_factor(asset_date, period_start, period_end) == Decimal("1")

    def test_prorate_factor_asset_after_period(self):
        asset_date = datetime(2021, 1, 1, tzinfo=UTC)
        period_start = datetime(2020, 1, 1, tzinfo=UTC)
        period_end = datetime(2020, 12, 31, tzinfo=UTC)
        assert _prorate_factor(asset_date, period_start, period_end) == Decimal("0")

    def test_prorate_factor_partial(self):
        asset_date = datetime(2020, 6, 30, tzinfo=UTC)
        period_start = datetime(2020, 1, 1, tzinfo=UTC)
        period_end = datetime(2020, 12, 31, tzinfo=UTC)
        result = _prorate_factor(asset_date, period_start, period_end)
        # 184 days remaining / 366 days total = 0.5027...
        assert result == Decimal("184") / Decimal("366")

    def test_prorate_factor_zero_days(self):
        asset_date = datetime(2020, 1, 1, tzinfo=UTC)
        period_start = datetime(2020, 1, 1, tzinfo=UTC)
        period_end = datetime(2020, 1, 1, tzinfo=UTC)
        assert _prorate_factor(asset_date, period_start, period_end) == Decimal("0")

    def test_round_decimal(self):
        assert _round_decimal(Decimal("10.12345")) == Decimal("10.12")
        assert _round_decimal(Decimal("10.125")) == Decimal("10.12")  # ROUND_HALF_EVEN
        assert _round_decimal(Decimal("10.135")) == Decimal("10.14")  # ROUND_HALF_EVEN
        assert _round_decimal(Decimal("10.1"), places=0) == Decimal("10")
        assert _round_decimal(Decimal("10.5"), places=0) == Decimal("10")  # ROUND_HALF_EVEN


# =============================================================================
# AmortizationEntry Tests
# =============================================================================

class TestAmortizationEntry:
    def test_construction(self):
        now = datetime.now(UTC)
        entry = AmortizationEntry(
            period=1,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("100000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("80000"),
            accumulated_amortization=Decimal("20000"),
            is_partial=False,
        )
        assert entry.period == 1
        assert entry.period_start == now
        assert entry.period_end == now + timedelta(days=365)
        assert entry.opening_nbv == Decimal("100000")
        assert entry.amortization_amount == Decimal("20000")
        assert entry.closing_nbv == Decimal("80000")
        assert entry.accumulated_amortization == Decimal("20000")
        assert entry.is_partial is False

    def test_to_dict(self):
        now = datetime.now(UTC)
        entry = AmortizationEntry(
            period=2,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("80000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("60000"),
            accumulated_amortization=Decimal("40000"),
            is_partial=True,
        )
        d = entry.to_dict()
        assert d["period"] == 2
        assert d["period_start"] == now.isoformat()
        assert d["period_end"] == (now + timedelta(days=365)).isoformat()
        assert d["opening_nbv"] == "80000"
        assert d["amortization_amount"] == "20000"
        assert d["closing_nbv"] == "60000"
        assert d["accumulated_amortization"] == "40000"
        assert d["is_partial"] is True

    def test_from_dict_roundtrip(self):
        now = datetime.now(UTC)
        original = AmortizationEntry(
            period=3,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("60000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("40000"),
            accumulated_amortization=Decimal("60000"),
            is_partial=False,
        )
        d = original.to_dict()
        reconstructed = AmortizationEntry.from_dict(d)
        assert reconstructed.period == original.period
        assert reconstructed.period_start == original.period_start
        assert reconstructed.period_end == original.period_end
        assert reconstructed.opening_nbv == original.opening_nbv
        assert reconstructed.amortization_amount == original.amortization_amount
        assert reconstructed.closing_nbv == original.closing_nbv
        assert reconstructed.accumulated_amortization == original.accumulated_amortization
        assert reconstructed.is_partial == original.is_partial


# =============================================================================
# AmortizationSchedule Tests
# =============================================================================

class TestAmortizationSchedule:
    def test_construction(self):
        asset_id = uuid4()
        now = datetime.now(UTC)
        entry = AmortizationEntry(
            period=1,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("100000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("80000"),
            accumulated_amortization=Decimal("20000"),
        )
        schedule = AmortizationSchedule(
            asset_id=asset_id,
            asset_code="TEST-001",
            asset_name="Test Asset",
            acquisition_date=now,
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            amortization_method="straight_line",
            entries=[entry],
            total_amortization=Decimal("20000"),
            final_nbv=Decimal("80000"),
            currency="IDR",
        )
        assert schedule.asset_id == asset_id
        assert schedule.asset_code == "TEST-001"
        assert schedule.asset_name == "Test Asset"
        assert schedule.acquisition_date == now
        assert schedule.cost == Decimal("100000")
        assert schedule.residual_value == Decimal("0")
        assert schedule.useful_life_years == 5
        assert schedule.amortization_method == "straight_line"
        assert len(schedule.entries) == 1
        assert schedule.total_amortization == Decimal("20000")
        assert schedule.final_nbv == Decimal("80000")
        assert schedule.currency == "IDR"

    def test_to_dict(self):
        asset_id = uuid4()
        now = datetime.now(UTC)
        entry = AmortizationEntry(
            period=1,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("100000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("80000"),
            accumulated_amortization=Decimal("20000"),
        )
        schedule = AmortizationSchedule(
            asset_id=asset_id,
            asset_code="TEST-001",
            asset_name="Test Asset",
            acquisition_date=now,
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            amortization_method="straight_line",
            entries=[entry],
            total_amortization=Decimal("20000"),
            final_nbv=Decimal("80000"),
            currency="IDR",
        )
        d = schedule.to_dict()
        assert d["asset_id"] == str(asset_id)
        assert d["asset_code"] == "TEST-001"
        assert d["asset_name"] == "Test Asset"
        assert d["acquisition_date"] == now.isoformat()
        assert d["cost"] == "100000"
        assert d["residual_value"] == "0"
        assert d["useful_life_years"] == 5
        assert d["amortization_method"] == "straight_line"
        assert len(d["entries"]) == 1
        assert d["total_amortization"] == "20000"
        assert d["final_nbv"] == "80000"
        assert d["currency"] == "IDR"

    def test_from_dict_roundtrip(self):
        asset_id = uuid4()
        now = datetime.now(UTC)
        entry = AmortizationEntry(
            period=1,
            period_start=now,
            period_end=now + timedelta(days=365),
            opening_nbv=Decimal("100000"),
            amortization_amount=Decimal("20000"),
            closing_nbv=Decimal("80000"),
            accumulated_amortization=Decimal("20000"),
        )
        original = AmortizationSchedule(
            asset_id=asset_id,
            asset_code="TEST-001",
            asset_name="Test Asset",
            acquisition_date=now,
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            amortization_method="straight_line",
            entries=[entry],
            total_amortization=Decimal("20000"),
            final_nbv=Decimal("80000"),
            currency="IDR",
        )
        d = original.to_dict()
        reconstructed = AmortizationSchedule.from_dict(d)
        assert reconstructed.asset_id == original.asset_id
        assert reconstructed.asset_code == original.asset_code
        assert reconstructed.asset_name == original.asset_name
        assert reconstructed.acquisition_date == original.acquisition_date
        assert reconstructed.cost == original.cost
        assert reconstructed.residual_value == original.residual_value
        assert reconstructed.useful_life_years == original.useful_life_years
        assert reconstructed.amortization_method == original.amortization_method
        assert len(reconstructed.entries) == len(original.entries)
        assert reconstructed.total_amortization == original.total_amortization
        assert reconstructed.final_nbv == original.final_nbv
        assert reconstructed.currency == original.currency

    def test_from_dict_handles_unknown_method(self):
        asset_id = uuid4()
        now = datetime.now(UTC)
        data = {
            "asset_id": str(asset_id),
            "asset_code": "TEST-001",
            "asset_name": "Test Asset",
            "acquisition_date": now.isoformat(),
            "cost": "100000",
            "residual_value": "0",
            "useful_life_years": 5,
            "amortization_method": "unknown_method",
            "entries": [],
            "total_amortization": "0",
            "final_nbv": "100000",
            "currency": "IDR",
        }
        schedule = AmortizationSchedule.from_dict(data)
        assert schedule.amortization_method == "straight_line"


# =============================================================================
# AmortizationScheduleEngine Tests
# =============================================================================

class TestAmortizationScheduleEngine:
    def test_construction(self):
        engine = AmortizationScheduleEngine()
        assert engine.ROUNDING_PLACES == 2
        assert engine.ROUNDING == ROUND_HALF_EVEN

    # ---- Straight Line ----
    def test_straight_line_full_schedule(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset, end_date=datetime(2025, 12, 31, tzinfo=UTC))

        assert len(schedule.entries) == 5
        assert schedule.total_amortization == Decimal("100000")
        assert schedule.final_nbv == Decimal("0")
        for entry in schedule.entries:
            assert entry.amortization_amount == Decimal("20000")
            assert entry.is_partial is False

    def test_straight_line_with_residual_value(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("10000"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset, end_date=datetime(2025, 12, 31, tzinfo=UTC))

        assert len(schedule.entries) == 5
        assert schedule.total_amortization == Decimal("90000")
        assert schedule.final_nbv == Decimal("10000")
        for entry in schedule.entries:
            assert entry.amortization_amount == Decimal("18000")

    def test_straight_line_partial_first_year(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 6, 30, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset, end_date=datetime(2025, 12, 31, tzinfo=UTC))

        # Partial first year: 185 days / 366 days * 20000 = 10109.29
        expected_partial = Decimal("20000") * Decimal("185") / Decimal("366")
        expected_partial = _round_decimal(expected_partial)
        assert schedule.entries[0].is_partial is True
        assert schedule.entries[0].amortization_amount == expected_partial
        # Remaining 4 years should be full
        for entry in schedule.entries[1:5]:
            assert entry.amortization_amount == Decimal("20000")

    def test_straight_line_indefinite_life(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=0,
            has_indefinite_life=True,
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset)
        assert schedule.amortization_method == "no_amortization"
        assert len(schedule.entries) == 0
        assert schedule.total_amortization == Decimal("0")

    def test_straight_line_zero_amortizable(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("100000"),
            useful_life_years=5,
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset)
        assert len(schedule.entries) == 0
        assert schedule.total_amortization == Decimal("0")

    def test_straight_line_end_date_before_acquisition(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(
            asset,
            end_date=datetime(2019, 12, 31, tzinfo=UTC)
        )
        assert len(schedule.entries) == 0
        assert schedule.total_amortization == Decimal("0")

    # ---- Declining Balance ----
    def test_declining_balance_double_declining(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_declining_balance(
            asset,
            rate_multiplier=Decimal("2"),
            switch_to_straight_line=False,
            end_date=datetime(2025, 12, 31, tzinfo=UTC),
        )
        # Year 1: 100000 * 0.4 = 40000
        # Year 2: 60000 * 0.4 = 24000
        # Year 3: 36000 * 0.4 = 14400
        # Year 4: 21600 * 0.4 = 8640
        # Year 5: 12960 * 0.4 = 5184 (adjusted to reach 0)
        assert schedule.total_amortization == Decimal("100000")
        assert schedule.final_nbv == Decimal("0")
        # Check first entry
        assert schedule.entries[0].amortization_amount == Decimal("40000")
        assert schedule.entries[1].amortization_amount == Decimal("24000")
        assert schedule.entries[2].amortization_amount == Decimal("14400")
        assert schedule.entries[3].amortization_amount == Decimal("8640")
        assert schedule.entries[4].amortization_amount == Decimal("12960")  # final adjustment

    def test_declining_balance_with_switch_to_straight_line(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_declining_balance(
            asset,
            rate_multiplier=Decimal("2"),
            switch_to_straight_line=True,
            end_date=datetime(2025, 12, 31, tzinfo=UTC),
        )
        # Year 1: 40000
        # Year 2: 24000
        # Year 3: 14400 (DDB) vs 12000 (SL) -> use DDB 14400
        # Year 4: 8640 (DDB) vs 10800 (SL) -> switch to SL 10800
        # Year 5: 10800
        # Total should be 100000
        assert schedule.total_amortization == Decimal("100000")
        assert schedule.final_nbv == Decimal("0")

    def test_declining_balance_indefinite_life(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=0,
            has_indefinite_life=True,
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_declining_balance(asset)
        assert schedule.amortization_method == "no_amortization"
        assert len(schedule.entries) == 0

    def test_declining_balance_zero_useful_life_raises(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=0,
        )
        engine = AmortizationScheduleEngine()
        with pytest.raises(ValueError, match="Useful life must be positive"):
            engine.calculate_declining_balance(asset)

    # ---- Units of Production ----
    def test_units_of_production(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        units_by_period = [
            (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 12, 31, tzinfo=UTC), Decimal("2000")),
            (datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 12, 31, tzinfo=UTC), Decimal("3000")),
            (datetime(2022, 1, 1, tzinfo=UTC), datetime(2022, 12, 31, tzinfo=UTC), Decimal("2500")),
            (datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 12, 31, tzinfo=UTC), Decimal("1500")),
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC), Decimal("1000")),
        ]
        schedule = engine.calculate_units_of_production(
            asset,
            total_units=Decimal("10000"),
            units_produced_by_period=units_by_period,
        )
        # Rate per unit = 100000 / 10000 = 10
        assert schedule.total_amortization == Decimal("100000")
        assert schedule.final_nbv == Decimal("0")
        # Check per period
        expected = [20000, 30000, 25000, 15000, 10000]
        for i, entry in enumerate(schedule.entries):
            assert entry.amortization_amount == Decimal(expected[i])

    def test_units_of_production_with_residual_value(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("10000"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        units_by_period = [
            (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 12, 31, tzinfo=UTC), Decimal("2000")),
            (datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 12, 31, tzinfo=UTC), Decimal("3000")),
            (datetime(2022, 1, 1, tzinfo=UTC), datetime(2022, 12, 31, tzinfo=UTC), Decimal("2500")),
            (datetime(2023, 1, 1, tzinfo=UTC), datetime(2023, 12, 31, tzinfo=UTC), Decimal("1500")),
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 12, 31, tzinfo=UTC), Decimal("1000")),
        ]
        schedule = engine.calculate_units_of_production(
            asset,
            total_units=Decimal("10000"),
            units_produced_by_period=units_by_period,
        )
        # Rate per unit = 90000 / 10000 = 9
        assert schedule.total_amortization == Decimal("90000")
        assert schedule.final_nbv == Decimal("10000")

    def test_units_of_production_indefinite_life(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=0,
            has_indefinite_life=True,
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_units_of_production(asset, Decimal("10000"), [])
        assert schedule.amortization_method == "no_amortization"

    def test_units_of_production_zero_total_units_raises(self):
        asset = MockIntangibleAsset()
        engine = AmortizationScheduleEngine()
        with pytest.raises(ValueError, match="Total units must be positive"):
            engine.calculate_units_of_production(asset, Decimal("0"), [])

    def test_units_of_production_zero_amortizable(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("100000"),
            useful_life_years=5,
        )
        engine = AmortizationScheduleEngine()
        units_by_period = [
            (datetime(2020, 1, 1, tzinfo=UTC), datetime(2020, 12, 31, tzinfo=UTC), Decimal("1000")),
        ]
        schedule = engine.calculate_units_of_production(
            asset, Decimal("10000"), units_by_period
        )
        assert len(schedule.entries) == 0

    # ---- Calculate Amortization ----
    def test_calculate_amortization_straight_line(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.calculate_amortization(
            asset,
            as_of_date=datetime(2022, 12, 31, tzinfo=UTC),
        )
        assert result == Decimal("60000")  # 3 years * 20000

    def test_calculate_amortization_declining_balance(self):
        from domain.intangible_asset.amortization_method_enum import AmortizationMethod
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
            amortization_method=AmortizationMethod.DECLINING_BALANCE,
        )
        engine = AmortizationScheduleEngine()
        result = engine.calculate_amortization(
            asset,
            as_of_date=datetime(2022, 12, 31, tzinfo=UTC),
        )
        # DDB: 40000 + 24000 + 14400 = 78400
        assert result == Decimal("78400")

    def test_calculate_amortization_indefinite_life(self):
        asset = MockIntangibleAsset(
            has_indefinite_life=True,
        )
        engine = AmortizationScheduleEngine()
        result = engine.calculate_amortization(asset)
        assert result == Decimal("0")

    def test_calculate_amortization_units_of_production_raises(self):
        from domain.intangible_asset.amortization_method_enum import AmortizationMethod
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
            amortization_method=AmortizationMethod.UNITS_OF_PRODUCTION,
        )
        engine = AmortizationScheduleEngine()
        with pytest.raises(ValueError, match="Units of production requires manual unit data"):
            engine.calculate_amortization(asset)

    # ---- Calculate Amortization As Of ----
    def test_calculate_amortization_as_of(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        # Halfway through year 3 (2022-06-30)
        result = engine.calculate_amortization_as_of(
            asset,
            as_of_date=datetime(2022, 6, 30, tzinfo=UTC),
        )
        # 2 full years + half of year 3 = 20000*2 + 10000 = 50000
        assert result == Decimal("50000")

    def test_calculate_amortization_as_of_before_acquisition(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.calculate_amortization_as_of(
            asset,
            as_of_date=datetime(2019, 12, 31, tzinfo=UTC),
        )
        assert result == Decimal("0")

    # ---- Get Monthly Amortization ----
    def test_get_monthly_amortization(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_monthly_amortization(asset)
        expected = Decimal("100000") / Decimal(5) / Decimal("12")
        expected = _round_decimal(expected)
        assert result == expected

    def test_get_monthly_amortization_with_residual(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("10000"),
            useful_life_years=5,
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_monthly_amortization(asset)
        expected = Decimal("90000") / Decimal(5) / Decimal("12")
        expected = _round_decimal(expected)
        assert result == expected

    def test_get_monthly_amortization_indefinite_life(self):
        asset = MockIntangibleAsset(has_indefinite_life=True)
        engine = AmortizationScheduleEngine()
        result = engine.get_monthly_amortization(asset)
        assert result == Decimal("0")

    # ---- Get Yearly Amortization ----
    def test_get_yearly_amortization(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_yearly_amortization(asset, year=3)
        assert result == Decimal("20000")

    def test_get_yearly_amortization_year_not_found(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_yearly_amortization(asset, year=10)
        assert result == Decimal("0")

    # ---- Get Remaining Amortization ----
    def test_get_remaining_amortization(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_remaining_amortization(
            asset,
            as_of_date=datetime(2022, 12, 31, tzinfo=UTC),
        )
        assert result == Decimal("40000")  # 2 years remaining

    def test_get_remaining_amortization_indefinite_life(self):
        asset = MockIntangibleAsset(has_indefinite_life=True)
        engine = AmortizationScheduleEngine()
        result = engine.get_remaining_amortization(asset)
        assert result == Decimal("0")

    # ---- Get Remaining Months ----
    def test_get_remaining_months(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_remaining_months(
            asset,
            as_of_date=datetime(2022, 12, 31, tzinfo=UTC),
        )
        # 24 months remaining (2 years)
        assert result == 24

    def test_get_remaining_months_indefinite_life(self):
        asset = MockIntangibleAsset(has_indefinite_life=True)
        engine = AmortizationScheduleEngine()
        result = engine.get_remaining_months(asset)
        assert result == 0

    def test_get_remaining_months_zero_monthly(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("100000"),
            useful_life_years=5,
        )
        engine = AmortizationScheduleEngine()
        result = engine.get_remaining_months(asset)
        assert result == 0

    # ---- Is Fully Amortized ----
    def test_is_fully_amortized_true(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.is_fully_amortized(
            asset,
            as_of_date=datetime(2025, 12, 31, tzinfo=UTC),
        )
        assert result is True

    def test_is_fully_amortized_false(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = engine.is_fully_amortized(
            asset,
            as_of_date=datetime(2022, 12, 31, tzinfo=UTC),
        )
        assert result is False

    def test_is_fully_amortized_indefinite_life(self):
        asset = MockIntangibleAsset(has_indefinite_life=True)
        engine = AmortizationScheduleEngine()
        result = engine.is_fully_amortized(asset)
        assert result is False

    # ---- Get Schedule Summary ----
    def test_get_schedule_summary(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        schedule = engine.calculate_straight_line(asset)
        summary = engine.get_schedule_summary(schedule)
        assert summary["asset_id"] == str(asset.asset_id)
        assert summary["asset_code"] == asset.asset_code
        assert summary["asset_name"] == asset.asset_name
        assert summary["total_periods"] == 5
        assert summary["total_amortization"] == "100000"
        assert summary["final_nbv"] == "0"
        assert Decimal(summary["avg_monthly"]) > Decimal("0")


# =============================================================================
# Module-Level Function Tests
# =============================================================================

class TestModuleFunctions:
    def test_calculate_remaining_useful_life(self):
        asset = MockIntangibleAsset(
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        result = calculate_remaining_useful_life(
            asset,
            as_of_date=datetime(2022, 6, 30, tzinfo=UTC),
        )
        # 2.5 years elapsed, remaining 2.5 years
        assert result > 2.4 and result < 2.6

    def test_calculate_remaining_useful_life_indefinite(self):
        asset = MockIntangibleAsset(
            useful_life_years=0,
            has_indefinite_life=True,
        )
        result = calculate_remaining_useful_life(
            asset,
            as_of_date=datetime.now(UTC),
        )
        assert result == 0.0

    def test_calculate_remaining_useful_life_before_acquisition(self):
        asset = MockIntangibleAsset(
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        result = calculate_remaining_useful_life(
            asset,
            as_of_date=datetime(2019, 12, 31, tzinfo=UTC),
        )
        assert result == 5.0

    def test_is_fully_amortized_module_function(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        result = is_fully_amortized(
            asset,
            as_of_date=datetime(2025, 12, 31, tzinfo=UTC),
        )
        assert result is True

    def test_is_fully_amortized_with_engine(self):
        asset = MockIntangibleAsset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=5,
            acquisition_date=datetime(2020, 1, 1, tzinfo=UTC),
        )
        engine = AmortizationScheduleEngine()
        result = is_fully_amortized(
            asset,
            as_of_date=datetime(2025, 12, 31, tzinfo=UTC),
            engine=engine,
        )
        assert result is True

    def test_calculate_amortization_rate(self):
        asset = MockIntangibleAsset(useful_life_years=5)
        result = calculate_amortization_rate(asset)
        assert result == Decimal("20.00")

    def test_calculate_amortization_rate_indefinite_life(self):
        asset = MockIntangibleAsset(has_indefinite_life=True)
        result = calculate_amortization_rate(asset)
        assert result == Decimal("0")

    def test_calculate_amortization_rate_zero_useful_life(self):
        asset = MockIntangibleAsset(useful_life_years=0)
        result = calculate_amortization_rate(asset)
        assert result == Decimal("0")