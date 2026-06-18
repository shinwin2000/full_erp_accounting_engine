#!/usr/bin/env python3
"""
Module: test_psak_rules.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk aturan PSAK (Pernyataan Standar Akuntansi Keuangan) Indonesia.
    Menguji pengakuan, pengukuran, dan penyajian sesuai standar PSAK yang diadopsi.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from policy_engine.psak.psak_01_presentation import PSAK1
from policy_engine.psak.psak_02_cash_flow import PSAK2
from policy_engine.psak.psak_14_inventories import PSAK14
from policy_engine.psak.psak_16_property_plant_equipment import (
    DepreciationMethodPSAK,
    PSAK16Rules,
    PSAK16Validator,
)
from policy_engine.psak.psak_19_intangible_assets import PSAK19
from policy_engine.psak.psak_22_business_combinations import PSAK22
from policy_engine.psak.psak_72_revenue import PSAK72
from policy_engine.psak.psak_73_leases import PSAK73
from policy_engine.psak.psak_aggregator import PSAKAggregator


class TestPSAK1Presentation:
    """PSAK 1: Penyajian Laporan Keuangan."""

    def test_comparative_figures_required(self):
        laporan = PSAK1.generate_comparative_report(tahun=2025)
        assert laporan.has_comparative_figures is True
        assert laporan.tahun_berjalan == 2025
        assert laporan.tahun_sebelumnya == 2024

    def test_going_concern_disclosure(self):
        assert PSAK1.is_going_concern_disclosed() is True


class TestPSAK2CashFlow:
    """PSAK 2: Laporan Arus Kas."""

    def test_allowed_methods(self):
        metode = PSAK2.get_allowed_methods()
        assert "langsung" in metode
        assert "tidak_langsung" in metode

    def test_operating_cash_flow_calculation(self):
        laba_bersih = Decimal("100000000")
        penyusutan = Decimal("20000000")
        piutang_naik = Decimal("-5000000")
        kas_operasi = laba_bersih + penyusutan + piutang_naik
        assert kas_operasi == Decimal("115000000")
        assert PSAK2.validate_operating_cash_flow(kas_operasi) is True


class TestPSAK14Inventories:
    """PSAK 14: Persediaan."""

    def test_inventory_cost_includes_all_necessary_components(self):
        cost = PSAK14.calculate_inventory_cost(
            purchase_price=Decimal("100000"),
            freight=Decimal("5000"),
            import_duties=Decimal("2000"),
            handling=Decimal("1000"),
        )
        assert cost == Decimal("108000")

    def test_net_realizable_value(self):
        nr = PSAK14.net_realizable_value(
            selling_price=Decimal("150000"),
            cost_to_complete=Decimal("10000"),
            cost_to_sell=Decimal("5000"),
        )
        assert nr == Decimal("135000")

    def test_inventory_written_down_to_nrv(self):
        cost = Decimal("120000")
        nrv = Decimal("100000")
        write_down = cost - nrv
        assert write_down == Decimal("20000")
        assert PSAK14.is_write_down_required(cost, nrv) is True


class TestPSAK16PPE:
    """PSAK 16: Aset Tetap (menggunakan implementasi dari psak_16_property_plant_equipment)."""

    def test_straight_line_depreciation(self):
        dep = PSAK16Rules.calculate_depreciation(
            cost=Decimal("100000000"),
            salvage_value=Decimal("10000000"),
            useful_life_years=10,
            method=DepreciationMethodPSAK.STRAIGHT_LINE,
            current_year=1,
        )
        assert dep == Decimal("9000000")

    def test_declining_balance_depreciation(self):
        cost = Decimal("100000000")
        salvage = Decimal("0")
        useful_life = 5
        rate = Decimal(2) / Decimal(useful_life)  # double declining = 0.4
        year1_dep = cost * rate
        year2_dep = (cost - year1_dep) * rate

        dep_year1 = PSAK16Rules.calculate_depreciation(
            cost=cost,
            salvage_value=salvage,
            useful_life_years=useful_life,
            method=DepreciationMethodPSAK.DECLINING_BALANCE,
            current_year=1,
        )
        assert dep_year1 == year1_dep
        # Assert manual perhitungan year1 dan year2 (karena method hanya output tahun pertama)
        assert year1_dep == Decimal("40000000")
        assert year2_dep == Decimal("24000000")

    def test_revaluation_allowed_for_active_market(self):
        validator = PSAK16Validator()
        # Revaluasi dengan appraisal yang valid
        result = validator._rules.validate_revaluation_model(
            fair_value=Decimal("500000000"),
            carrying_amount=Decimal("300000000"),
            has_appraisal=True,
        )
        assert result.is_compliant is True
        # Revaluasi tanpa appraisal harus ditolak
        result2 = validator._rules.validate_revaluation_model(
            fair_value=Decimal("500000000"),
            carrying_amount=Decimal("300000000"),
            has_appraisal=False,
        )
        assert result2.is_compliant is False
        assert "independent appraisal" in result2.errors[0]


class TestPSAK19IntangibleAssets:
    """PSAK 19: Aset Tak Berwujud."""

    def test_amortization_limited_life(self):
        amort = PSAK19.amortize(
            cost=Decimal("50000000"),
            residual_value=Decimal("0"),
            useful_life=5,
            method="straight_line",
        )
        assert amort.annual == Decimal("10000000")

    def test_indefinite_life_no_amortization(self):
        with pytest.raises(ValueError, match="indefinite life"):
            PSAK19.amortize(cost=Decimal("50000000"), useful_life=None, method="straight_line")


class TestPSAK22BusinessCombinations:
    """PSAK 22: Kombinasi Bisnis."""

    def test_goodwill_calculation(self):
        goodwill = PSAK22.calculate_goodwill(
            purchase_price=Decimal("1000000000"),
            fair_value_of_identifiable_net_assets=Decimal("800000000"),
        )
        assert goodwill == Decimal("200000000")

    def test_nci_measurement_options(self):
        methods = PSAK22.get_nci_measurement_methods()
        assert "proportionate_share" in methods
        assert "fair_value" in methods


class TestPSAK72Revenue:
    """PSAK 72: Pendapatan dari Kontrak dengan Pelanggan (IFRS 15)."""

    def test_five_step_model(self):
        transaction = PSAK72.create_transaction(
            contract_price=Decimal("5000000"),
            performance_obligations=[
                {"description": "Barang A", "standalone_price": Decimal("3000000")},
                {"description": "Jasa B", "standalone_price": Decimal("3000000")},
            ],
        )
        allocated = PSAK72.allocate_transaction_price(transaction)
        # Total standalone 6jt, proporsi Barang A = 3/6 * 5jt = 2.5jt
        assert allocated["Barang A"] == Decimal("2500000")
        assert allocated["Jasa B"] == Decimal("2500000")

    def test_revenue_recognized_when_control_transferred(self):
        assert PSAK72.is_control_transferred(delivery_date=date.today()) is True


class TestPSAK73Leases:
    """PSAK 73: Sewa (IFRS 16)."""

    def test_lessee_recognizes_asset_and_liability(self):
        lease = PSAK73.recognize_lease(
            payment=Decimal("10000000"),
            discount_rate=Decimal("0.05"),
            lease_term=5,
        )
        assert lease.right_of_use_asset > Decimal("0")
        assert lease.lease_liability > Decimal("0")
        assert lease.lease_liability == lease.right_of_use_asset  # initial


class TestPSAKAggregator:
    """Uji agregator semua PSAK."""

    def test_aggregator_contains_all_standards(self):
        agg = PSAKAggregator()
        standar_list = agg.list_standards()
        assert len(standar_list) >= 27
        assert "PSAK 1" in standar_list
        assert "PSAK 73" in standar_list

    def test_validate_all_returns_compliance_report(self):
        agg = PSAKAggregator()
        report = agg.validate_all()
        assert report.total_standards == 27
        assert report.compliant_standards >= 0
