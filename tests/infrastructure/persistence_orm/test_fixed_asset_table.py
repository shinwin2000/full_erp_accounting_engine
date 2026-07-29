# tests/infrastructure/persistence_orm/test_fixed_asset_table.py
# Comprehensive tests for infrastructure/persistence_orm/fixed_asset_table.py

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable


class TestFixedAssetTable:
    """Tests for the FixedAssetTable ORM model."""

    def test_tablename_defined(self):
        assert hasattr(FixedAssetTable, "__tablename__")
        assert isinstance(FixedAssetTable.__tablename__, str)
        assert len(FixedAssetTable.__tablename__) > 0

    def test_instantiation(self):
        instance = FixedAssetTable(
            id=uuid4(),
            asset_code="FA-001",
            asset_name="Mesin Produksi",
            asset_category="Machinery",
            acquisition_date=date(2023, 1, 1),
            acquisition_cost=Decimal("100000000"),
            residual_value=Decimal("10000000"),
            currency="IDR",
            useful_life_years=5,
            depreciation_method="straight_line",
            depreciation_rate=Decimal("20"),
            accumulated_depreciation=Decimal("0"),
            last_depreciation_date=None,
            current_period_depreciation=Decimal("0"),
            location="Gudang A",
            responsible_party="John Doe",
            status="active",
            is_active=True,
            revaluation_frequency="never",
            notes="Test asset",
        )
        assert isinstance(instance, FixedAssetTable)
        assert instance.asset_code == "FA-001"
        assert instance.acquisition_cost == Decimal("100000000")

    # -------------------- Fixtures --------------------
    @pytest.fixture
    def asset_straight_line(self):
        return FixedAssetTable(
            id=uuid4(),
            asset_code="FA-001",
            asset_name="Machine",
            asset_category="Machinery",
            acquisition_date=date(2023, 1, 1),
            acquisition_cost=Decimal("100000000"),
            residual_value=Decimal("10000000"),
            currency="IDR",
            useful_life_years=5,
            depreciation_method="straight_line",
            accumulated_depreciation=Decimal("18000000"),  # 2 years depreciation
            last_depreciation_date=date(2024, 12, 31),
            current_period_depreciation=Decimal("9000000"),
            location="Warehouse",
            status="active",
            is_active=True,
            version=1,
        )

    @pytest.fixture
    def asset_fully_depreciated(self):
        return FixedAssetTable(
            id=uuid4(),
            asset_code="FA-002",
            asset_name="Old Machine",
            asset_category="Machinery",
            acquisition_date=date(2018, 1, 1),
            acquisition_cost=Decimal("50000000"),
            residual_value=Decimal("5000000"),
            currency="IDR",
            useful_life_years=5,
            depreciation_method="straight_line",
            accumulated_depreciation=Decimal("45000000"),
            last_depreciation_date=date(2022, 12, 31),
            current_period_depreciation=Decimal("9000000"),
            location="Warehouse",
            status="fully_depreciated",
            is_active=True,
            version=1,
        )

    @pytest.fixture
    def asset_impaired(self):
        return FixedAssetTable(
            id=uuid4(),
            asset_code="FA-003",
            asset_name="Damaged Machine",
            asset_category="Machinery",
            acquisition_date=date(2020, 1, 1),
            acquisition_cost=Decimal("80000000"),
            residual_value=Decimal("8000000"),
            currency="IDR",
            useful_life_years=5,
            depreciation_method="straight_line",
            accumulated_depreciation=Decimal("24000000"),
            last_depreciation_date=date(2024, 6, 30),
            current_period_depreciation=Decimal("8000000"),
            status="impaired",
            is_active=False,
            version=1,
        )

    # -------------------- Property Tests --------------------
    def test_net_book_value(self, asset_straight_line):
        # acquisition_cost 100,000,000 - accumulated_depreciation 18,000,000 = 82,000,000
        assert asset_straight_line.net_book_value == Decimal("82000000")

    def test_net_book_value_minimum_zero(self):
        asset = FixedAssetTable(
            acquisition_cost=Decimal("1000000"),
            accumulated_depreciation=Decimal("1500000"),
        )
        assert asset.net_book_value == Decimal(0)

    def test_is_fully_depreciated_true(self, asset_fully_depreciated):
        # net_book_value = 50,000,000 - 45,000,000 = 5,000,000 which equals residual_value 5,000,000
        assert asset_fully_depreciated.is_fully_depreciated is True

    def test_is_fully_depreciated_false(self, asset_straight_line):
        # net_book_value = 82,000,000 > residual_value 10,000,000
        assert asset_straight_line.is_fully_depreciated is False

    def test_depreciation_percentage(self):
        asset = FixedAssetTable(useful_life_years=5)
        assert asset.depreciation_percentage == Decimal("20")

        asset.useful_life_years = 0
        assert asset.depreciation_percentage == Decimal(0)

    def test_depreciation_percentage_precision(self):
        asset = FixedAssetTable(useful_life_years=3)
        # 100 / 3 = 33.333... but Decimal(100) / Decimal(3) gives 33.333...
        assert asset.depreciation_percentage == Decimal(100) / Decimal(3)

    def test_remaining_useful_life_years(self, asset_straight_line):
        # annual depreciation = acquisition_cost * (20% / 100) = 20,000,000
        # remaining_value = net_book_value - residual_value = 82,000,000 - 10,000,000 = 72,000,000
        # remaining years = 72,000,000 / 20,000,000 = 3.6
        expected = Decimal("3.6")
        assert asset_straight_line.remaining_useful_life_years == expected

    def test_remaining_useful_life_years_fully_depreciated(self, asset_fully_depreciated):
        # net_book_value = 5,000,000, residual_value = 5,000,000, remaining_value = 0
        assert asset_fully_depreciated.remaining_useful_life_years == Decimal(0)

    def test_remaining_useful_life_years_zero_cost(self):
        asset = FixedAssetTable(
            acquisition_cost=Decimal(0),
            residual_value=Decimal(0),
            useful_life_years=5,
            depreciation_rate=Decimal("20"),
            accumulated_depreciation=Decimal(0),
        )
        assert asset.remaining_useful_life_years == Decimal(0)

    def test_remaining_useful_life_years_zero_depreciation_rate(self):
        asset = FixedAssetTable(
            acquisition_cost=Decimal("1000000"),
            residual_value=Decimal("1000000"),
            useful_life_years=5,
            depreciation_rate=Decimal(0),
            accumulated_depreciation=Decimal(0),
        )
        # depreciation_percentage = 0, so return 0
        assert asset.remaining_useful_life_years == Decimal(0)

    def test_is_active_asset(self, asset_straight_line):
        assert asset_straight_line.is_active_asset is True
        asset_straight_line.status = "fully_depreciated"
        assert asset_straight_line.is_active_asset is False
        asset_straight_line.status = "active"
        asset_straight_line.is_active = False
        assert asset_straight_line.is_active_asset is False

    # -------------------- Method Tests --------------------
    def test_record_depreciation(self, asset_straight_line):
        period_date = date(2025, 1, 1)
        amount = Decimal("9000000")
        asset_straight_line.record_depreciation(amount, period_date)
        assert asset_straight_line.accumulated_depreciation == Decimal("27000000")
        assert asset_straight_line.current_period_depreciation == amount
        assert asset_straight_line.last_depreciation_date == period_date
        assert asset_straight_line.version == 2

    def test_record_depreciation_triggers_fully_depreciated(self):
        asset = FixedAssetTable(
            acquisition_cost=Decimal("10000000"),
            residual_value=Decimal("2000000"),
            accumulated_depreciation=Decimal("7000000"),
            status="active",
            version=1,
        )
        amount = Decimal("2000000")  # This will make net_book_value = 1,000,000 < residual 2,000,000
        asset.record_depreciation(amount, date.today())
        # net_book_value = 10,000,000 - 9,000,000 = 1,000,000 <= residual 2,000,000 => fully_depreciated
        assert asset.status == "fully_depreciated"

    def test_revalue(self, asset_straight_line):
        new_cost = Decimal("120000000")
        new_accum = Decimal("20000000")
        old_version = asset_straight_line.version
        asset_straight_line.revalue(new_cost, new_accum)
        assert asset_straight_line.acquisition_cost == new_cost
        assert asset_straight_line.accumulated_depreciation == new_accum
        assert asset_straight_line.version == old_version + 1

    def test_dispose(self, asset_straight_line):
        disposal_date = date(2025, 1, 1)
        old_version = asset_straight_line.version
        asset_straight_line.dispose(disposal_date)
        assert asset_straight_line.status == "disposed"
        assert asset_straight_line.is_active is False
        assert asset_straight_line.version == old_version + 1

    def test_impair(self, asset_straight_line):
        impairment_loss = Decimal("15000000")
        old_cost = asset_straight_line.acquisition_cost
        old_version = asset_straight_line.version
        asset_straight_line.impair(impairment_loss)
        assert asset_straight_line.acquisition_cost == old_cost - impairment_loss
        assert asset_straight_line.status == "impaired"
        assert asset_straight_line.version == old_version + 1

    def test_activate(self, asset_straight_line):
        asset_straight_line.status = "disposed"
        asset_straight_line.is_active = False
        old_version = asset_straight_line.version
        asset_straight_line.activate()
        assert asset_straight_line.status == "active"
        assert asset_straight_line.is_active is True
        assert asset_straight_line.version == old_version + 1

    def test_can_depreciate_active(self, asset_straight_line):
        as_of_date = date(2025, 1, 15)
        assert asset_straight_line.can_depreciate(as_of_date) is True

    def test_can_depreciate_impaired(self, asset_impaired):
        as_of_date = date(2024, 7, 15)
        # impaired asset can still depreciate if not fully depreciated
        assert asset_impaired.can_depreciate(as_of_date) is True

    def test_can_depreciate_fully_depreciated(self, asset_fully_depreciated):
        as_of_date = date(2023, 1, 1)
        assert asset_fully_depreciated.can_depreciate(as_of_date) is False

    def test_can_depreciate_status_disposed(self, asset_straight_line):
        asset_straight_line.status = "disposed"
        assert asset_straight_line.can_depreciate(date.today()) is False

    def test_can_depreciate_last_depreciation_after_as_of(self, asset_straight_line):
        asset_straight_line.last_depreciation_date = date(2025, 1, 10)
        as_of_date = date(2025, 1, 1)
        assert asset_straight_line.can_depreciate(as_of_date) is False

    def test_can_depreciate_last_depreciation_before_as_of(self, asset_straight_line):
        asset_straight_line.last_depreciation_date = date(2024, 12, 31)
        as_of_date = date(2025, 1, 1)
        assert asset_straight_line.can_depreciate(as_of_date) is True
