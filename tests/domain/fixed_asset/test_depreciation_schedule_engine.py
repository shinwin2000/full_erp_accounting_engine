# test_depreciation_schedule_engine.py
# ====================================
# Comprehensive tests for domain/fixed_asset/depreciation_schedule_engine.py.
# Covers all enums, exceptions, data classes, and all methods of DepreciationScheduleEngine.
# Includes decimal precision tests for flagged methods.

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.fixed_asset.depreciation_schedule_engine import (
    DepreciationEntry,
    DepreciationError,
    DepreciationMethod,
    DepreciationSchedule,
    DepreciationScheduleEngine,
    InsufficientUnitsError,
    InvalidDepreciationMethodError,
    NegativeDepreciationError,
    calculate_remaining_useful_life,
    is_fully_depreciated,
)


# ----------------------------------------------------------------------
# Helper: Mock FixedAsset
# ----------------------------------------------------------------------
class MockFixedAsset:
    """Mock FixedAsset with required attributes for testing."""

    def __init__(
        self,
        asset_id=None,
        asset_code="ASSET-001",
        name="Test Asset",
        acquisition_date=date(2025, 1, 1),
        acquisition_cost=Decimal("10000"),
        salvage_value=Decimal("1000"),
        useful_life_years=5,
        depreciation_method="straight_line",
        currency="IDR",
        is_depreciable=True,
        is_fully_depreciated=False,
    ):
        self.id = asset_id or uuid4()
        self.asset_code = asset_code
        self.name = name
        self.acquisition_date = acquisition_date
        self.acquisition_cost = acquisition_cost
        self.salvage_value = salvage_value
        self.useful_life_years = useful_life_years
        self.depreciation_method = depreciation_method
        self.currency = currency
        self.is_depreciable = is_depreciable
        self.is_fully_depreciated = is_fully_depreciated


# ----------------------------------------------------------------------
# Enums
# ----------------------------------------------------------------------
class TestDepreciationMethod:
    def test_members_exist(self):
        assert hasattr(DepreciationMethod, "STRAIGHT_LINE")
        assert hasattr(DepreciationMethod, "DOUBLE_DECLINING")
        assert hasattr(DepreciationMethod, "SUM_OF_YEARS_DIGITS")
        assert hasattr(DepreciationMethod, "UNITS_OF_PRODUCTION")

    def test_member_is_instance(self):
        assert isinstance(DepreciationMethod.STRAIGHT_LINE, DepreciationMethod)

    def test_display_name(self):
        assert DepreciationMethod.STRAIGHT_LINE.display_name() == "Garis Lurus"
        assert DepreciationMethod.DOUBLE_DECLINING.display_name() == "Saldo Menurun Ganda"
        assert DepreciationMethod.SUM_OF_YEARS_DIGITS.display_name() == "Jumlah Angka Tahun"
        assert DepreciationMethod.UNITS_OF_PRODUCTION.display_name() == "Unit Produksi"

    def test_from_string(self):
        assert DepreciationMethod.from_string("straight_line") == DepreciationMethod.STRAIGHT_LINE
        assert DepreciationMethod.from_string("double_declining") == DepreciationMethod.DOUBLE_DECLINING
        assert DepreciationMethod.from_string("sum_of_years_digits") == DepreciationMethod.SUM_OF_YEARS_DIGITS
        assert DepreciationMethod.from_string("units_of_production") == DepreciationMethod.UNITS_OF_PRODUCTION
        assert DepreciationMethod.from_string("unknown") is None


# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class TestExceptions:
    def test_depreciation_error(self):
        err = DepreciationError("test")
        assert isinstance(err, ValueError)
        assert str(err) == "test"

    def test_invalid_depreciation_method_error(self):
        err = InvalidDepreciationMethodError("test")
        assert isinstance(err, DepreciationError)

    def test_negative_depreciation_error(self):
        err = NegativeDepreciationError("test")
        assert isinstance(err, DepreciationError)

    def test_insufficient_units_error(self):
        err = InsufficientUnitsError("test")
        assert isinstance(err, DepreciationError)


# ----------------------------------------------------------------------
# DepreciationEntry
# ----------------------------------------------------------------------
class TestDepreciationEntry:
    def test_construction(self):
        entry = DepreciationEntry(
            period=1,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            opening_nbv=Decimal("10000"),
            depreciation_amount=Decimal("1800"),
            closing_nbv=Decimal("8200"),
            accumulated_depreciation=Decimal("1800"),
            is_partial=False,
        )
        assert entry.period == 1
        assert entry.opening_nbv == Decimal("10000")
        assert entry.depreciation_amount == Decimal("1800")

    def test_to_dict(self):
        entry = DepreciationEntry(
            period=1,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            opening_nbv=Decimal("10000"),
            depreciation_amount=Decimal("1800"),
            closing_nbv=Decimal("8200"),
            accumulated_depreciation=Decimal("1800"),
            is_partial=False,
        )
        d = entry.to_dict()
        assert d["period"] == 1
        assert d["period_start"] == "2025-01-01"
        assert d["opening_nbv"] == "10000"
        assert d["depreciation_amount"] == "1800"


# ----------------------------------------------------------------------
# DepreciationSchedule
# ----------------------------------------------------------------------
class TestDepreciationSchedule:
    def test_construction(self):
        asset_id = uuid4()
        schedule = DepreciationSchedule(
            asset_id=asset_id,
            asset_code="ASSET-001",
            asset_name="Test Asset",
            acquisition_date=date(2025, 1, 1),
            cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            entries=[],
            total_depreciation=Decimal("0"),
            final_nbv=Decimal("10000"),
            currency="IDR",
        )
        assert schedule.asset_id == asset_id
        assert schedule.total_depreciation == Decimal("0")

    def test_to_dict(self):
        asset_id = uuid4()
        schedule = DepreciationSchedule(
            asset_id=asset_id,
            asset_code="ASSET-001",
            asset_name="Test Asset",
            acquisition_date=date(2025, 1, 1),
            cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            entries=[],
            total_depreciation=Decimal("0"),
            final_nbv=Decimal("10000"),
            currency="IDR",
        )
        d = schedule.to_dict()
        assert d["asset_id"] == str(asset_id)
        assert d["asset_code"] == "ASSET-001"
        assert d["cost"] == "10000"
        assert d["entries"] == []


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - Straight Line
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineStraightLine:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_straight_line_full_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_straight_line(asset)
        assert schedule.depreciation_method == DepreciationMethod.STRAIGHT_LINE
        assert schedule.total_depreciation == Decimal("9000")  # (10000 - 1000) * 5 years
        # Check entries: should have 5 entries of 1800 each (9000/5)
        assert len(schedule.entries) == 5
        for entry in schedule.entries:
            assert entry.depreciation_amount == Decimal("1800")
        assert schedule.final_nbv == Decimal("1000")

    def test_calculate_straight_line_partial_first_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 7, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_straight_line(asset, include_partial_first_year=True)
        # First year partial: 184 days (Jul 1 to Dec 31) / 365 = 0.5041, annual 1800 * 0.5041 = 907.38 -> rounded 907.38
        # Then 4 full years of 1800 = 7200, plus remaining to reach salvage?
        # Actually logic: total depreciation = 9000, partial first = round(1800 * 184/365) = 907.38
        # Then remaining years: 4 full years of 1800 = 7200, total = 8107.38, then last adjustment = 892.62
        # Let's assert total matches 9000.
        assert schedule.total_depreciation == Decimal("9000.00")
        assert len(schedule.entries) == 5
        assert schedule.final_nbv == Decimal("1000.00")

    def test_calculate_straight_line_no_depreciation_when_cost_equals_salvage(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("10000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_straight_line(asset)
        assert len(schedule.entries) == 0
        assert schedule.total_depreciation == Decimal("0")
        assert schedule.final_nbv == Decimal("10000")

    def test_calculate_straight_line_useful_life_zero_raises(self, engine):
        asset = MockFixedAsset(useful_life_years=0)
        with pytest.raises(DepreciationError, match="Useful life must be positive"):
            engine.calculate_straight_line(asset)


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - Double Declining
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineDoubleDeclining:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_double_declining_full_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_double_declining(asset)
        # Rate = 2/5 = 0.4
        # Year1: 10000*0.4=4000, NBV=6000
        # Year2: 6000*0.4=2400, NBV=3600
        # Year3: 3600*0.4=1440, NBV=2160
        # Year4: 2160*0.4=864, NBV=1296
        # Year5: 1296*0.4=518.4, but would drop below salvage? Actually salvage=1000, so limit to 1296-1000=296
        # Total depreciation should be 9000.
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")
        assert len(schedule.entries) == 5

    def test_calculate_double_declining_partial_first_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 7, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_double_declining(asset)
        # Partial first year: rate=0.4, factor=184/365=0.5041, depreciation=10000*0.4*0.5041=2016.44
        # Then subsequent years...
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")

    def test_calculate_double_declining_switch_to_straight_line(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_double_declining(asset, switch_to_straight_line=True)
        # Should use SL when SL depreciation > DDB
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")

    def test_calculate_double_declining_multiplier_zero_raises(self, engine):
        asset = MockFixedAsset()
        with pytest.raises(DepreciationError, match="Multiplier must be positive"):
            engine.calculate_double_declining(asset, multiplier=Decimal("0"))


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - Sum of Years' Digits
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineSumOfYearsDigits:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_sum_of_years_digits_full_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_sum_of_years_digits(asset)
        # Sum = 5*6/2=15
        # Year1: 5/15 * 9000 = 3000
        # Year2: 4/15 * 9000 = 2400
        # Year3: 3/15 * 9000 = 1800
        # Year4: 2/15 * 9000 = 1200
        # Year5: 1/15 * 9000 = 600
        # Total = 9000
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")
        assert len(schedule.entries) == 5
        # Check first entry
        assert schedule.entries[0].depreciation_amount == Decimal("3000.00")
        assert schedule.entries[4].depreciation_amount == Decimal("600.00")

    def test_calculate_sum_of_years_digits_partial_first_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 7, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        schedule = engine.calculate_sum_of_years_digits(asset)
        # Partial first year: fraction = 5/15 = 1/3, factor = 184/365, depreciation = 9000 * 1/3 * 184/365 = 1512.33
        # Then remaining years...
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - Units of Production
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineUnitsOfProduction:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_units_of_production(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        total_units = Decimal("10000")
        units_by_period = [
            (date(2025, 1, 1), date(2025, 12, 31), Decimal("2000")),
            (date(2026, 1, 1), date(2026, 12, 31), Decimal("3000")),
            (date(2027, 1, 1), date(2027, 12, 31), Decimal("5000")),
        ]
        schedule = engine.calculate_units_of_production(asset, total_units, units_by_period)
        # Rate per unit = 9000/10000 = 0.9
        # Year1: 2000*0.9=1800
        # Year2: 3000*0.9=2700
        # Year3: 5000*0.9=4500
        # Total = 9000
        assert schedule.total_depreciation == Decimal("9000.00")
        assert schedule.final_nbv == Decimal("1000.00")
        assert len(schedule.entries) == 3
        assert schedule.entries[0].depreciation_amount == Decimal("1800.00")
        assert schedule.entries[1].depreciation_amount == Decimal("2700.00")
        assert schedule.entries[2].depreciation_amount == Decimal("4500.00")

    def test_calculate_units_of_production_total_units_zero_raises(self, engine):
        asset = MockFixedAsset()
        with pytest.raises(DepreciationError, match="Total units must be positive"):
            engine.calculate_units_of_production(asset, Decimal("0"), [])

    def test_calculate_units_of_production_skips_periods_before_acquisition(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 7, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
        )
        units_by_period = [
            (date(2025, 1, 1), date(2025, 6, 30), Decimal("1000")),  # before acquisition
            (date(2025, 7, 1), date(2025, 12, 31), Decimal("2000")),
        ]
        schedule = engine.calculate_units_of_production(asset, Decimal("10000"), units_by_period)
        # Should only include the second period
        assert len(schedule.entries) == 1
        assert schedule.entries[0].period_start == date(2025, 7, 1)


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - Generic calculate_depreciation
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineGeneric:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_depreciation_straight_line(self, engine):
        asset = MockFixedAsset(depreciation_method="straight_line")
        schedule = engine.calculate_depreciation(asset)
        assert schedule.depreciation_method == DepreciationMethod.STRAIGHT_LINE

    def test_calculate_depreciation_double_declining(self, engine):
        asset = MockFixedAsset(depreciation_method="double_declining")
        schedule = engine.calculate_depreciation(asset)
        assert schedule.depreciation_method == DepreciationMethod.DOUBLE_DECLINING

    def test_calculate_depreciation_sum_of_years_digits(self, engine):
        asset = MockFixedAsset(depreciation_method="sum_of_years_digits")
        schedule = engine.calculate_depreciation(asset)
        assert schedule.depreciation_method == DepreciationMethod.SUM_OF_YEARS_DIGITS

    def test_calculate_depreciation_units_of_production_raises(self, engine):
        asset = MockFixedAsset(depreciation_method="units_of_production")
        with pytest.raises(DepreciationError, match="Units of production requires manual unit data"):
            engine.calculate_depreciation(asset)

    def test_calculate_depreciation_unknown_method_raises(self, engine):
        asset = MockFixedAsset(depreciation_method="unknown")
        with pytest.raises(InvalidDepreciationMethodError, match="Unknown depreciation method"):
            engine.calculate_depreciation(asset)


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - calculate_depreciation_as_of (decimal precision)
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineAsOf:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_calculate_depreciation_as_of_before_acquisition(self, engine):
        asset = MockFixedAsset(acquisition_date=date(2025, 1, 1))
        as_of = date(2024, 12, 31)
        result = engine.calculate_depreciation_as_of(asset, as_of)
        assert result == Decimal("0")

    def test_calculate_depreciation_as_of_after_full_life(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2020, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        as_of = date(2026, 1, 1)
        result = engine.calculate_depreciation_as_of(asset, as_of)
        # Should be full depreciation = 9000
        assert result == Decimal("9000.00")

    def test_calculate_depreciation_as_of_mid_year(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        as_of = date(2025, 6, 30)  # half year
        result = engine.calculate_depreciation_as_of(asset, as_of)
        # Straight line: annual = 1800, half = 900
        assert result == Decimal("900.00")

    def test_calculate_depreciation_as_of_precise_partial(self, engine):
        # Test decimal precision: use an asset acquired mid-year and a specific date.
        asset = MockFixedAsset(
            acquisition_date=date(2025, 2, 15),
            acquisition_cost=Decimal("100000"),
            salvage_value=Decimal("0"),
            useful_life_years=5,
        )
        as_of = date(2025, 5, 1)
        # Annual = 20000, days from Feb 15 to May 1 = 75 days (assuming non-leap year)
        # Days in 2025 = 365, factor = 75/365, depreciation = 20000 * 75/365 = 4109.589... -> rounded 4109.59
        # Expected with rounding to 2 decimals.
        expected = Decimal("4109.59")  # Rounding half even.
        result = engine.calculate_depreciation_as_of(asset, as_of)
        assert result == expected


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - get_monthly_depreciation (decimal precision)
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineMonthly:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_get_monthly_depreciation_straight_line(self, engine):
        asset = MockFixedAsset(
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
            is_depreciable=True,
            is_fully_depreciated=False,
            depreciation_method="straight_line",
        )
        monthly = engine.get_monthly_depreciation(asset)
        # Annual = 1800, monthly = 150
        assert monthly == Decimal("150.00")

    def test_get_monthly_depreciation_non_straight_line(self, engine):
        asset = MockFixedAsset(
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
            is_depreciable=True,
            is_fully_depreciated=False,
            depreciation_method="double_declining",
        )
        monthly = engine.get_monthly_depreciation(asset)
        # Total depreciation over life = 9000, months = 60, monthly = 150
        # (but with DDB, total is also 9000, so average monthly = 150)
        assert monthly == Decimal("150.00")

    def test_get_monthly_depreciation_not_depreciable(self, engine):
        asset = MockFixedAsset(is_depreciable=False)
        monthly = engine.get_monthly_depreciation(asset)
        assert monthly == Decimal("0")

    def test_get_monthly_depreciation_fully_depreciated(self, engine):
        asset = MockFixedAsset(is_fully_depreciated=True)
        monthly = engine.get_monthly_depreciation(asset)
        assert monthly == Decimal("0")


# ----------------------------------------------------------------------
# DepreciationScheduleEngine - get_yearly_depreciation (decimal precision)
# ----------------------------------------------------------------------
class TestDepreciationScheduleEngineYearly:
    @pytest.fixture
    def engine(self):
        return DepreciationScheduleEngine()

    def test_get_yearly_depreciation(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        yearly = engine.get_yearly_depreciation(asset, 1)
        # Straight line: year 1 = 1800
        assert yearly == Decimal("1800.00")

    def test_get_yearly_depreciation_year_not_found(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        yearly = engine.get_yearly_depreciation(asset, 10)
        assert yearly == Decimal("0")


# ----------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------
class TestHelpers:
    def test_calculate_remaining_useful_life(self):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            useful_life_years=5,
        )
        as_of = date(2027, 1, 1)
        remaining = calculate_remaining_useful_life(asset, as_of)
        # 2 years passed, remaining = 3
        assert remaining == 3.0

    def test_calculate_remaining_useful_life_before_acquisition(self):
        asset = MockFixedAsset(acquisition_date=date(2025, 1, 1), useful_life_years=5)
        as_of = date(2024, 12, 31)
        remaining = calculate_remaining_useful_life(asset, as_of)
        assert remaining == 5.0

    def test_calculate_remaining_useful_life_after_life(self):
        asset = MockFixedAsset(acquisition_date=date(2020, 1, 1), useful_life_years=5)
        as_of = date(2026, 1, 1)
        remaining = calculate_remaining_useful_life(asset, as_of)
        assert remaining == 0.0

    def test_is_fully_depreciated(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2020, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        as_of = date(2026, 1, 1)
        assert is_fully_depreciated(asset, as_of, engine) is True

    def test_is_fully_depreciated_not_yet(self, engine):
        asset = MockFixedAsset(
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        as_of = date(2025, 12, 31)
        assert is_fully_depreciated(asset, as_of, engine) is False

    def test_is_fully_depreciated_without_engine(self):
        asset = MockFixedAsset(
            acquisition_date=date(2020, 1, 1),
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            useful_life_years=5,
        )
        as_of = date(2026, 1, 1)
        # Should use default engine
        assert is_fully_depreciated(asset, as_of) is True


# ----------------------------------------------------------------------
# Alias test
# ----------------------------------------------------------------------
def test_aliases():
    from domain.fixed_asset.depreciation_schedule_engine import (
        DepreciationEngine,
        DepreciationScheduleLine,
    )
    assert DepreciationEngine is DepreciationScheduleEngine
    assert DepreciationScheduleLine is DepreciationEntry
