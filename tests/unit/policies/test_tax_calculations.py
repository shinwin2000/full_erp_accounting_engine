#!/usr/bin/env python3
"""
Module: test_tax_calculations.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk perhitungan pajak Indonesia (PPN, PPh 21/22/23/25/26/4(2), PPh Badan, Bea Meterai).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from policy_engine.tax_indonesia.bea_meterai_calculator import BeaMeteraiCalculator
from policy_engine.tax_indonesia.penalty_interest_engine import PenaltyInterestEngine
from policy_engine.tax_indonesia.pph_4_ayat_2_calculator import PPh4Ayat2Calculator
from policy_engine.tax_indonesia.pph_21_calculator import PPh21Calculator
from policy_engine.tax_indonesia.pph_22_calculator import PPh22Calculator
from policy_engine.tax_indonesia.pph_23_calculator import PPh23Calculator
from policy_engine.tax_indonesia.pph_25_calculator import PPh25Calculator
from policy_engine.tax_indonesia.pph_26_calculator import PPh26Calculator
from policy_engine.tax_indonesia.pph_badan_calculator import PPhBadanCalculator
from policy_engine.tax_indonesia.ppn_calculator import PPNCalculator
from policy_engine.tax_indonesia.rate_registry_dynamic import RateRegistry
from policy_engine.tax_indonesia.treaty_resolver import TreatyResolver
from policy_engine.tax_indonesia.withholding_engine import WithholdingEngine


class TestPPN:
    """PPN (Pajak Pertambahan Nilai)."""

    def test_tarif_11_persen(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="11%")
        assert ppn == Decimal("110000")

    def test_tarif_0_persen_ekspor_bkp(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="0%", transaksi="ekspor_bkp")
        assert ppn == Decimal("0")

    def test_tarif_11_persen_untuk_ekspor_jkp_tidak_dikenakan(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), transaksi="ekspor_jkp")
        assert ppn == Decimal("0")

    def test_ppn_faktur_pajak_keluaran(self):
        faktur = PPNCalculator.create_faktur_keluaran(
            dpp=Decimal("10000000"), ppn=Decimal("1100000"), tanggal=date.today()
        )
        assert faktur.kode_faktur.startswith("010")
        assert faktur.ppn == Decimal("1100000")


class TestPPh21:
    """PPh Pasal 21 (Karyawan)."""

    def test_annual_tax_calculation(self):
        pph21 = PPh21Calculator.annual_tax(
            gross_income=Decimal("60000000"),
            ptkp_status="K/0",
            tahun=2025,
        )
        assert pph21 >= Decimal("0")

    def test_monthly_ter(self):
        ter = PPh21Calculator.monthly_ter(gross_monthly=Decimal("10000000"))
        assert ter == Decimal("200000")  # TER A 2%

    def test_no_tax_if_below_ptkp(self):
        pph21 = PPh21Calculator.annual_tax(gross_income=Decimal("50000000"), ptkp_status="TK/0")
        assert pph21 == Decimal("0")

    def test_penghasilan_tidak_kena_pajak_2025(self):
        ptkp = PPh21Calculator.get_ptkp(status="K/2")
        assert ptkp == Decimal("67500000")  # 54jt + 4.5jt + (2*4.5jt)

    def test_calculate_nett_salary(self):
        nett = PPh21Calculator.nett_salary(
            gross=Decimal("15000000"), ptkp_status="K/1", bpjs_employee=Decimal("300000")
        )
        assert nett > Decimal("0")


class TestPPh22:
    """PPh Pasal 22 (Impor & Pembelian)."""

    def test_import_with_api(self):
        pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=True)
        assert pph22 == Decimal("10000000")  # 10%

    def test_import_without_api(self):
        pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=False)
        assert pph22 == Decimal("7500000")  # 7.5%

    def test_pembelian_bendahara(self):
        pph22 = PPh22Calculator.calculate_pembelian_bendahara(amount=Decimal("50000000"))
        assert pph22 == Decimal("750000")  # 1.5%


class TestPPh23:
    """PPh Pasal 23 (Jasa & Sewa)."""

    def test_jasa_management(self):
        pph23 = PPh23Calculator.calculate(bruto=Decimal("50000000"), jenis_jasa="management")
        assert pph23 == Decimal("1000000")  # 2%

    def test_sewa_tanah_bangunan(self):
        pph23 = PPh23Calculator.calculate_sewa(bruto=Decimal("10000000"), jenis="tanah_bangunan")
        assert pph23 == Decimal("1000000")  # 10%

    def test_no_npwp_rate_increase(self):
        pph23 = PPh23Calculator.calculate(
            bruto=Decimal("50000000"), jenis_jasa="management", has_npwp=False
        )
        # Sesuai regulasi: 2% x 200% (kenaikan 100%) = 4% dari 50jt = 2jt
        assert pph23 == Decimal("2000000")


class TestPPh25:
    """PPh Pasal 25 (Angsuran)."""

    def test_monthly_installment(self):
        angsuran = PPh25Calculator.monthly_installment(
            previous_year_tax_liability=Decimal("120000000")
        )
        assert angsuran == Decimal("10000000")

    def test_installment_for_new_companies(self):
        angsuran = PPh25Calculator.monthly_installment_for_new_company(
            estimated_annual_tax=Decimal("60000000")
        )
        assert angsuran == Decimal("5000000")


class TestPPh26:
    """PPh Pasal 26 (WPLN)."""

    def test_without_treaty(self):
        pph26 = PPh26Calculator.calculate(
            gross_income=Decimal("50000000"), country_code="US", has_treaty=False
        )
        assert pph26 == Decimal("10000000")  # 20%

    def test_with_treaty_reduced_rate(self):
        pph26 = PPh26Calculator.calculate(
            gross_income=Decimal("50000000"), country_code="SG", has_treaty=True, treaty_rate=10
        )
        assert pph26 == Decimal("5000000")


class TestPPh4Ayat2:
    """PPh Final Pasal 4 ayat 2."""

    def test_deposit_interest(self):
        pph = PPh4Ayat2Calculator.calculate_deposit_interest(
            interest=Decimal("5000000"), has_npwp=True
        )
        assert pph == Decimal("1000000")  # 20%

    def test_land_rental(self):
        pph = PPh4Ayat2Calculator.calculate_land_rental(rent=Decimal("20000000"))
        assert pph == Decimal("2000000")  # 10%

    def test_construction_with_qualification(self):
        pph = PPh4Ayat2Calculator.calculate_construction(
            contract_value=Decimal("1000000000"), qualification="menengah"
        )
        assert pph == Decimal("20000000")  # 2%


class TestPPhBadan:
    """PPh Badan (CIT)."""

    def test_standard_rate_22_percent(self):
        pph = PPhBadanCalculator.calculate(
            gross_revenue=Decimal("100000000000"),
            taxable_income=Decimal("20000000000"),
        )
        assert pph == Decimal("4400000000")  # 22% * 20M

    def test_sme_facility(self):
        pph = PPhBadanCalculator.calculate(
            gross_revenue=Decimal("40000000000"),
            taxable_income=Decimal("5000000000"),
        )
        # 11% for portion up to 4.8M (max)
        assert pph > Decimal("0")


class TestBeaMeterai:
    """Bea Meterai."""

    def test_document_above_10_million(self):
        bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("10000000"))
        assert bea == Decimal("10000")

    def test_document_below_10_million(self):
        bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("5000000"))
        assert bea == Decimal("0")

    def test_electronic_cek_above_5_million(self):
        bea = BeaMeteraiCalculator.calculate_cek(nilai=Decimal("6000000"))
        assert bea == Decimal("10000")


class TestPenaltyInterest:
    """Denda dan bunga pajak."""

    def test_interest_per_month(self):
        bunga = PenaltyInterestEngine.calculate(
            pokok=Decimal("10000000"),
            months_late=3,
            tarif_bunga=Decimal("0.02"),
        )
        assert bunga == Decimal("600000")

    def test_denda_tidak_lapor_ppn(self):
        denda = PenaltyInterestEngine.denda_tidak_lapor_ppn(dpp=Decimal("100000000"))
        assert denda == Decimal("2000000")  # 2%


class TestRateRegistry:
    """Registry tarif pajak dinamis."""

    def test_get_ppn_rate(self):
        rate = RateRegistry.get_ppn_rate(effective_date=date(2025, 1, 1))
        assert rate == Decimal("0.11")

    def test_get_pph21_progressive_rates(self):
        rates = RateRegistry.get_pph21_progressive_rates()
        assert rates[0] == (Decimal("0"), Decimal("60000000"), Decimal("0.05"))
        assert rates[-1][2] == Decimal("0.35")


class TestTreatyResolver:
    """Resolver tax treaty."""

    def test_treaty_rate_for_singapore(self):
        resolver = TreatyResolver()
        rate = resolver.get_withholding_rate(country_code="SG", income_type="dividend")
        assert rate == Decimal("0.10")  # asumsi

    def test_no_treaty_fallback(self):
        resolver = TreatyResolver()
        rate = resolver.get_withholding_rate(country_code="XX", income_type="interest")
        assert rate == Decimal("0.20")  # default


class TestWithholdingEngine:
    """Mesin pemotongan pajak."""

    def test_withholding_calculation(self):
        engine = WithholdingEngine()
        result = engine.calculate(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=True,
        )
        assert result.tax == Decimal("200000")
        assert result.npwp_factor == 1.0

    def test_withholding_without_npwp(self):
        engine = WithholdingEngine()
        result = engine.calculate(
            bruto=Decimal("10000000"),
            pph_type="23",
            rate=Decimal("0.02"),
            has_npwp=False,
        )
        assert result.tax == Decimal("400000")
        assert result.npwp_factor == 2.0
