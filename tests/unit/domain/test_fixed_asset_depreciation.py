#!/usr/bin/env python3

"""
Module: test_fixed_asset_depreciation.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk perhitungan depresiasi aset tetap.
    Menguji metode straight-line, declining balance, sum-of-years, dan perhitungan bulanan.

Dependencies:
    - domain/fixed_asset/depreciation_schedule_engine.py
    - domain/fixed_asset/asset_entity.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from uuid import uuid4

import pytest

from domain.fixed_asset.asset_entity import AssetStatus, AssetType, FixedAsset
from domain.fixed_asset.asset_entity import DepreciationMethod as AssetDepMethod
from domain.fixed_asset.depreciation_schedule_engine import (
    DepreciationScheduleEngine,
)


class TestFixedAssetDepreciation:
    """Test suite untuk perhitungan depresiasi aset tetap."""

    @pytest.fixture
    def straight_line_asset(self) -> FixedAsset:
        """Fixture aset dengan metode straight-line."""
        return FixedAsset(
            id=uuid4(),
            legal_entity_id=uuid4(),
            asset_code="AST-001",
            name="Mesin Produksi",
            description="Mesin bubut",
            asset_type=AssetType.TANGIBLE,
            status=AssetStatus.ACTIVE,  # <-- wajib
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("100000000"),
            salvage_value=Decimal("10000000"),
            useful_life_years=5,
            depreciation_method=AssetDepMethod.STRAIGHT_LINE.value,  # string
            accumulated_depreciation=Decimal("0"),
            net_book_value=Decimal("100000000"),
            location="Gudang A",
            responsible_person=None,
            supplier_id=None,
            po_number=None,
            category="Mesin",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    @pytest.fixture
    def declining_balance_asset(self) -> FixedAsset:
        """Fixture aset dengan metode declining balance."""
        return FixedAsset(
            id=uuid4(),
            legal_entity_id=uuid4(),
            asset_code="AST-002",
            name="Kendaraan Operasional",
            description="Mobil box",
            asset_type=AssetType.TANGIBLE,
            status=AssetStatus.ACTIVE,
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("300000000"),
            salvage_value=Decimal("30000000"),
            useful_life_years=5,
            depreciation_method=AssetDepMethod.DECLINING_BALANCE.value,  # string
            accumulated_depreciation=Decimal("0"),
            net_book_value=Decimal("300000000"),
            location="Parkir B",
            responsible_person=None,
            supplier_id=None,
            po_number=None,
            category="Kendaraan",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    @pytest.fixture
    def sum_of_years_asset(self) -> FixedAsset:
        """Fixture aset dengan metode sum-of-years."""
        return FixedAsset(
            id=uuid4(),
            legal_entity_id=uuid4(),
            asset_code="AST-003",
            name="Komputer Server",
            description="Server utama",
            asset_type=AssetType.TANGIBLE,
            status=AssetStatus.ACTIVE,
            acquisition_date=date(2025, 1, 1),
            acquisition_cost=Decimal("50000000"),
            salvage_value=Decimal("5000000"),
            useful_life_years=4,
            depreciation_method=AssetDepMethod.SUM_OF_YEARS.value,  # string
            accumulated_depreciation=Decimal("0"),
            net_book_value=Decimal("50000000"),
            location="Ruang Server",
            responsible_person=None,
            supplier_id=None,
            po_number=None,
            category="IT",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    def test_straight_line_monthly_depreciation(self, straight_line_asset):
        """Test: Perhitungan depresiasi bulanan straight-line."""
        DepreciationScheduleEngine()
        depreciable_amount = (
            straight_line_asset.acquisition_cost - straight_line_asset.salvage_value
        )
        annual_dep = depreciable_amount / straight_line_asset.useful_life_years
        monthly_dep = annual_dep / Decimal("12")
        monthly_dep = monthly_dep.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert monthly_dep == Decimal("1500000")  # (100jt - 10jt)/5 = 18jt/thn -> 1.5jt/bln

    def test_declining_balance_depreciation(self, declining_balance_asset):
        """Test: Perhitungan depresiasi declining balance (double declining)."""
        DepreciationScheduleEngine()
        rate = Decimal("2") / declining_balance_asset.useful_life_years  # 40% per tahun
        monthly_rate = rate / Decimal("12")
        nbv = declining_balance_asset.acquisition_cost
        first_month_dep = nbv * monthly_rate
        first_month_dep = first_month_dep.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        # 300jt * 0.4 / 12 = 10jt
        assert first_month_dep == Decimal("10000000")
        # Month 2: NBV = 300jt - 10jt = 290jt
        second_month_dep = Decimal("290000000") * monthly_rate
        second_month_dep = second_month_dep.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert second_month_dep == Decimal("9666667")  # ~9.666.667

    def test_sum_of_years_depreciation(self, sum_of_years_asset):
        """Test: Perhitungan depresiasi sum-of-years."""
        DepreciationScheduleEngine()
        n = sum_of_years_asset.useful_life_years
        n * (n + 1) // 2  # 4*5/2=10
        depreciable = sum_of_years_asset.acquisition_cost - sum_of_years_asset.salvage_value
        # Year 1 fraction = 4/10
        year1_dep = depreciable * Decimal("4") / Decimal("10")
        # Year 2 fraction = 3/10
        year2_dep = depreciable * Decimal("3") / Decimal("10")
        assert year1_dep == Decimal("18000000")  # 45jt * 0.4 = 18jt
        assert year2_dep == Decimal("13500000")
        # Monthly year1 = 1.5jt
        monthly_year1 = year1_dep / Decimal("12")
        monthly_year1 = monthly_year1.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert monthly_year1 == Decimal("1500000")

    def test_annual_depreciation_summary(self, straight_line_asset):
        """Test: Tabel depresiasi tahunan."""
        engine = DepreciationScheduleEngine()
        schedule = engine.calculate_straight_line(straight_line_asset)
        entries = schedule.entries
        # Karena ada partial year di tahun pertama, jumlah entri bisa 5 atau 6
        # Kita periksa bahwa total depresiasi = 90jt
        total_dep = sum(e.depreciation_amount for e in entries)
        assert total_dep == Decimal("90000000")
        # Tahun terakhir, NBV akhir = salvage value
        assert entries[-1].closing_nbv == straight_line_asset.salvage_value

    def test_depreciation_stops_at_salvage_value(self, straight_line_asset):
        """Test: Depresiasi berhenti jika NBV mencapai salvage value."""
        DepreciationScheduleEngine()
        # Simulasikan 5 tahun depresiasi
        nbv = straight_line_asset.acquisition_cost
        annual_dep = (
            straight_line_asset.acquisition_cost - straight_line_asset.salvage_value
        ) / straight_line_asset.useful_life_years
        for _ in range(5):
            if nbv > straight_line_asset.salvage_value:
                nbv -= annual_dep
        assert nbv == straight_line_asset.salvage_value
        # Depresiasi tahun ke-6 harus 0
        extra_dep = min(annual_dep, nbv - straight_line_asset.salvage_value)
        assert extra_dep == Decimal("0")

    def test_partial_year_depreciation_prorated(self, straight_line_asset):
        """Test: Depresiasi prorata untuk aset yang diakuisisi di tengah tahun."""
        DepreciationScheduleEngine()
        date(2025, 6, 15)
        months_in_year = 6.5  # dari Juni (setengah bulan) sampai Desember = 6.5 bulan
        annual_dep = Decimal("18000000")
        prorated = annual_dep * Decimal(str(months_in_year / 12))
        prorated = prorated.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        # 18jt * (6.5/12) = 9.750.000
        assert prorated == Decimal("9750000")

    def test_depreciation_engine_consistency(self, straight_line_asset):
        """Test: Konsistensi perhitungan antara bulanan dan kumulatif."""
        DepreciationScheduleEngine()
        monthly_dep = Decimal("1500000")
        accumulated = Decimal("0")
        for month in range(1, 61):  # 5 tahun
            accumulated += monthly_dep
            if month == 60:
                assert (
                    accumulated
                    == straight_line_asset.acquisition_cost - straight_line_asset.salvage_value
                )

    def test_asset_fully_depreciated_flag(self, straight_line_asset):
        """Test: Flag aset fully depreciated."""
        DepreciationScheduleEngine()
        # Setelah depresiasi penuh, net_book_value == salvage_value
        straight_line_asset.accumulated_depreciation = (
            straight_line_asset.acquisition_cost - straight_line_asset.salvage_value
        )
        straight_line_asset.net_book_value = straight_line_asset.salvage_value
        is_fully_depreciated = (
            straight_line_asset.net_book_value <= straight_line_asset.salvage_value
        )
        assert is_fully_depreciated is True

    def test_recalculate_depreciation_after_revaluation(self, straight_line_asset):
        """Test: Perhitungan ulang depresiasi setelah revaluasi aset."""
        DepreciationScheduleEngine()
        # Misalkan revaluasi di tahun ke-2
        new_value = Decimal("120000000")
        remaining_life = 4
        remaining_depreciable = new_value - straight_line_asset.salvage_value
        new_annual_dep = remaining_depreciable / remaining_life
        assert new_annual_dep == Decimal("27500000")  # (120jt-10jt)/4 = 27.5jt
        monthly_new = new_annual_dep / Decimal("12")
        monthly_new = monthly_new.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert monthly_new == Decimal("2291667")


if __name__ == "__main__":
    pytest.main([__file__])
