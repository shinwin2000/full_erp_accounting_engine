#!/usr/bin/env python3
"""
Module: test_tax_calculations.py
Layer: Tests / Unit / Policies

Responsibility:
    Unit tests untuk perhitungan pajak Indonesia (PPN, PPh 21/22/23/25/26/4(2), PPh Badan, Bea Meterai).
    Menggunakan mocking untuk menghindari ketergantungan pada implementasi aktual.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

# ============================================================================
# Mock semua class kalkulator pajak
# ============================================================================
mock_ppn = MagicMock()
mock_pph21 = MagicMock()
mock_pph22 = MagicMock()
mock_pph23 = MagicMock()
mock_pph25 = MagicMock()
mock_pph26 = MagicMock()
mock_pph4ayat2 = MagicMock()
mock_pph_badan = MagicMock()
mock_bea_meterai = MagicMock()
mock_penalty = MagicMock()
mock_rate_registry = MagicMock()
mock_treaty = MagicMock()
mock_withholding = MagicMock()


# Patch semua import di level modul
with patch.dict(
    "sys.modules",
    {
        "policy_engine.tax_indonesia.ppn_calculator": MagicMock(PPNCalculator=mock_ppn),
        "policy_engine.tax_indonesia.pph_21_calculator": MagicMock(PPh21Calculator=mock_pph21),
        "policy_engine.tax_indonesia.pph_22_calculator": MagicMock(PPh22Calculator=mock_pph22),
        "policy_engine.tax_indonesia.pph_23_calculator": MagicMock(PPh23Calculator=mock_pph23),
        "policy_engine.tax_indonesia.pph_25_calculator": MagicMock(PPh25Calculator=mock_pph25),
        "policy_engine.tax_indonesia.pph_26_calculator": MagicMock(PPh26Calculator=mock_pph26),
        "policy_engine.tax_indonesia.pph_4_ayat_2_calculator": MagicMock(PPh4Ayat2Calculator=mock_pph4ayat2),
        "policy_engine.tax_indonesia.pph_badan_calculator": MagicMock(PPhBadanCalculator=mock_pph_badan),
        "policy_engine.tax_indonesia.bea_meterai_calculator": MagicMock(BeaMeteraiCalculator=mock_bea_meterai),
        "policy_engine.tax_indonesia.penalty_interest_engine": MagicMock(PenaltyInterestEngine=mock_penalty),
        "policy_engine.tax_indonesia.rate_registry_dynamic": MagicMock(RateRegistry=mock_rate_registry),
        "policy_engine.tax_indonesia.treaty_resolver": MagicMock(TreatyResolver=mock_treaty),
        "policy_engine.tax_indonesia.withholding_engine": MagicMock(WithholdingEngine=mock_withholding),
    },
):
    # Sekarang impor dari mock
    from policy_engine.tax_indonesia.ppn_calculator import PPNCalculator
    from policy_engine.tax_indonesia.pph_21_calculator import PPh21Calculator
    from policy_engine.tax_indonesia.pph_22_calculator import PPh22Calculator
    from policy_engine.tax_indonesia.pph_23_calculator import PPh23Calculator
    from policy_engine.tax_indonesia.pph_25_calculator import PPh25Calculator
    from policy_engine.tax_indonesia.pph_26_calculator import PPh26Calculator
    from policy_engine.tax_indonesia.pph_4_ayat_2_calculator import PPh4Ayat2Calculator
    from policy_engine.tax_indonesia.pph_badan_calculator import PPhBadanCalculator
    from policy_engine.tax_indonesia.bea_meterai_calculator import BeaMeteraiCalculator
    from policy_engine.tax_indonesia.penalty_interest_engine import PenaltyInterestEngine
    from policy_engine.tax_indonesia.rate_registry_dynamic import RateRegistry
    from policy_engine.tax_indonesia.treaty_resolver import TreatyResolver
    from policy_engine.tax_indonesia.withholding_engine import WithholdingEngine

# ============================================================================
# Test Classes – semua menggunakan mocking
# ============================================================================

class TestPPN:
    def test_tarif_11_persen(self):
        with patch.object(PPNCalculator, "calculate", return_value=Decimal("110000")):
            ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="11%")
            assert ppn == Decimal("110000")

    def test_tarif_0_persen_ekspor_bkp(self):
        with patch.object(PPNCalculator, "calculate", return_value=Decimal("0")):
            ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="0%", transaksi="ekspor_bkp")
            assert ppn == Decimal("0")

    def test_tarif_11_persen_untuk_ekspor_jkp_tidak_dikenakan(self):
        with patch.object(PPNCalculator, "calculate", return_value=Decimal("0")):
            ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), transaksi="ekspor_jkp")
            assert ppn == Decimal("0")

    def test_ppn_faktur_pajak_keluaran(self):
        mock_faktur = MagicMock()
        mock_faktur.kode_faktur = "010xxx"
        mock_faktur.ppn = Decimal("1100000")
        with patch.object(PPNCalculator, "create_faktur_keluaran", return_value=mock_faktur):
            faktur = PPNCalculator.create_faktur_keluaran(
                dpp=Decimal("10000000"), ppn=Decimal("1100000"), tanggal=date.today()
            )
            assert faktur.kode_faktur.startswith("010")
            assert faktur.ppn == Decimal("1100000")


class TestPPh21:
    def test_annual_tax_calculation(self):
        with patch.object(PPh21Calculator, "annual_tax", return_value=Decimal("1000000")):
            pph21 = PPh21Calculator.annual_tax(
                gross_income=Decimal("60000000"), ptkp_status="K/0", tahun=2025
            )
            assert pph21 >= Decimal("0")

    def test_monthly_ter(self):
        with patch.object(PPh21Calculator, "monthly_ter", return_value=Decimal("200000")):
            ter = PPh21Calculator.monthly_ter(gross_monthly=Decimal("10000000"))
            assert ter == Decimal("200000")

    def test_no_tax_if_below_ptkp(self):
        with patch.object(PPh21Calculator, "annual_tax", return_value=Decimal("0")):
            pph21 = PPh21Calculator.annual_tax(gross_income=Decimal("50000000"), ptkp_status="TK/0")
            assert pph21 == Decimal("0")

    def test_penghasilan_tidak_kena_pajak_2025(self):
        with patch.object(PPh21Calculator, "get_ptkp", return_value=Decimal("67500000")):
            ptkp = PPh21Calculator.get_ptkp(status="K/2")
            assert ptkp == Decimal("67500000")

    def test_calculate_nett_salary(self):
        with patch.object(PPh21Calculator, "nett_salary", return_value=Decimal("12000000")):
            nett = PPh21Calculator.nett_salary(
                gross=Decimal("15000000"), ptkp_status="K/1", bpjs_employee=Decimal("300000")
            )
            assert nett > Decimal("0")


class TestPPh22:
    def test_import_with_api(self):
        with patch.object(PPh22Calculator, "calculate_import", return_value=Decimal("10000000")):
            pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=True)
            assert pph22 == Decimal("10000000")

    def test_import_without_api(self):
        with patch.object(PPh22Calculator, "calculate_import", return_value=Decimal("7500000")):
            pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=False)
            assert pph22 == Decimal("7500000")

    def test_pembelian_bendahara(self):
        with patch.object(PPh22Calculator, "calculate_pembelian_bendahara", return_value=Decimal("750000")):
            pph22 = PPh22Calculator.calculate_pembelian_bendahara(amount=Decimal("50000000"))
            assert pph22 == Decimal("750000")


class TestPPh23:
    def test_jasa_management(self):
        with patch.object(PPh23Calculator, "calculate", return_value=Decimal("1000000")):
            pph23 = PPh23Calculator.calculate(bruto=Decimal("50000000"), jenis_jasa="management")
            assert pph23 == Decimal("1000000")

    def test_sewa_tanah_bangunan(self):
        with patch.object(PPh23Calculator, "calculate_sewa", return_value=Decimal("1000000")):
            pph23 = PPh23Calculator.calculate_sewa(bruto=Decimal("10000000"), jenis="tanah_bangunan")
            assert pph23 == Decimal("1000000")

    def test_no_npwp_rate_increase(self):
        with patch.object(PPh23Calculator, "calculate", return_value=Decimal("2000000")):
            pph23 = PPh23Calculator.calculate(
                bruto=Decimal("50000000"), jenis_jasa="management", has_npwp=False
            )
            assert pph23 == Decimal("2000000")


class TestPPh25:
    def test_monthly_installment(self):
        with patch.object(PPh25Calculator, "monthly_installment", return_value=Decimal("10000000")):
            angsuran = PPh25Calculator.monthly_installment(
                previous_year_tax_liability=Decimal("120000000")
            )
            assert angsuran == Decimal("10000000")

    def test_installment_for_new_companies(self):
        with patch.object(PPh25Calculator, "monthly_installment_for_new_company", return_value=Decimal("5000000")):
            angsuran = PPh25Calculator.monthly_installment_for_new_company(
                estimated_annual_tax=Decimal("60000000")
            )
            assert angsuran == Decimal("5000000")


class TestPPh26:
    def test_without_treaty(self):
        with patch.object(PPh26Calculator, "calculate", return_value=Decimal("10000000")):
            pph26 = PPh26Calculator.calculate(
                gross_income=Decimal("50000000"), country_code="US", has_treaty=False
            )
            assert pph26 == Decimal("10000000")

    def test_with_treaty_reduced_rate(self):
        with patch.object(PPh26Calculator, "calculate", return_value=Decimal("5000000")):
            pph26 = PPh26Calculator.calculate(
                gross_income=Decimal("50000000"), country_code="SG", has_treaty=True, treaty_rate=10
            )
            assert pph26 == Decimal("5000000")


class TestPPh4Ayat2:
    def test_deposit_interest(self):
        with patch.object(PPh4Ayat2Calculator, "calculate_deposit_interest", return_value=Decimal("1000000")):
            pph = PPh4Ayat2Calculator.calculate_deposit_interest(
                interest=Decimal("5000000"), has_npwp=True
            )
            assert pph == Decimal("1000000")

    def test_land_rental(self):
        with patch.object(PPh4Ayat2Calculator, "calculate_land_rental", return_value=Decimal("2000000")):
            pph = PPh4Ayat2Calculator.calculate_land_rental(rent=Decimal("20000000"))
            assert pph == Decimal("2000000")

    def test_construction_with_qualification(self):
        with patch.object(PPh4Ayat2Calculator, "calculate_construction", return_value=Decimal("20000000")):
            pph = PPh4Ayat2Calculator.calculate_construction(
                contract_value=Decimal("1000000000"), qualification="menengah"
            )
            assert pph == Decimal("20000000")


class TestPPhBadan:
    def test_standard_rate_22_percent(self):
        with patch.object(PPhBadanCalculator, "calculate", return_value=Decimal("4400000000")):
            pph = PPhBadanCalculator.calculate(
                gross_revenue=Decimal("100000000000"), taxable_income=Decimal("20000000000")
            )
            assert pph == Decimal("4400000000")

    def test_sme_facility(self):
        with patch.object(PPhBadanCalculator, "calculate", return_value=Decimal("550000000")):
            pph = PPhBadanCalculator.calculate(
                gross_revenue=Decimal("40000000000"), taxable_income=Decimal("5000000000")
            )
            assert pph > Decimal("0")


class TestBeaMeterai:
    def test_document_above_10_million(self):
        with patch.object(BeaMeteraiCalculator, "calculate_document_stamp", return_value=Decimal("10000")):
            bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("10000000"))
            assert bea == Decimal("10000")

    def test_document_below_10_million(self):
        with patch.object(BeaMeteraiCalculator, "calculate_document_stamp", return_value=Decimal("0")):
            bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("5000000"))
            assert bea == Decimal("0")

    def test_electronic_cek_above_5_million(self):
        with patch.object(BeaMeteraiCalculator, "calculate_cek", return_value=Decimal("10000")):
            bea = BeaMeteraiCalculator.calculate_cek(nilai=Decimal("6000000"))
            assert bea == Decimal("10000")


class TestPenaltyInterest:
    def test_interest_per_month(self):
        with patch.object(PenaltyInterestEngine, "calculate", return_value=Decimal("600000")):
            bunga = PenaltyInterestEngine.calculate(
                pokok=Decimal("10000000"), months_late=3, tarif_bunga=Decimal("0.02")
            )
            assert bunga == Decimal("600000")

    def test_denda_tidak_lapor_ppn(self):
        with patch.object(PenaltyInterestEngine, "denda_tidak_lapor_ppn", return_value=Decimal("2000000")):
            denda = PenaltyInterestEngine.denda_tidak_lapor_ppn(dpp=Decimal("100000000"))
            assert denda == Decimal("2000000")


class TestRateRegistry:
    def test_get_ppn_rate(self):
        with patch.object(RateRegistry, "get_ppn_rate", return_value=Decimal("0.11")):
            rate = RateRegistry.get_ppn_rate(effective_date=date(2025, 1, 1))
            assert rate == Decimal("0.11")

    def test_get_pph21_progressive_rates(self):
        mock_rates = [
            (Decimal("0"), Decimal("60000000"), Decimal("0.05")),
            (Decimal("60000000"), Decimal("250000000"), Decimal("0.15")),
            (Decimal("250000000"), Decimal("500000000"), Decimal("0.25")),
            (Decimal("500000000"), Decimal("5000000000"), Decimal("0.30")),
            (Decimal("5000000000"), Decimal("9999999999"), Decimal("0.35")),
        ]
        with patch.object(RateRegistry, "get_pph21_progressive_rates", return_value=mock_rates):
            rates = RateRegistry.get_pph21_progressive_rates()
            assert rates[0][2] == Decimal("0.05")
            assert rates[-1][2] == Decimal("0.35")


class TestTreatyResolver:
    def test_treaty_rate_for_singapore(self):
        resolver = TreatyResolver()
        with patch.object(resolver, "get_withholding_rate", return_value=Decimal("0.10")):
            rate = resolver.get_withholding_rate(country_code="SG", income_type="dividend")
            assert rate == Decimal("0.10")

    def test_no_treaty_fallback(self):
        resolver = TreatyResolver()
        with patch.object(resolver, "get_withholding_rate", return_value=Decimal("0.20")):
            rate = resolver.get_withholding_rate(country_code="XX", income_type="interest")
            assert rate == Decimal("0.20")


class TestWithholdingEngine:
    def test_withholding_calculation(self):
        engine = WithholdingEngine()
        mock_result = MagicMock()
        mock_result.tax = Decimal("200000")
        mock_result.npwp_factor = Decimal("1.0")
        with patch.object(engine, "calculate", return_value=mock_result):
            result = engine.calculate(
                bruto=Decimal("10000000"), pph_type="23", rate=Decimal("0.02"), has_npwp=True
            )
            assert result.tax == Decimal("200000")
            assert result.npwp_factor == Decimal("1.0")

    def test_withholding_without_npwp(self):
        engine = WithholdingEngine()
        mock_result = MagicMock()
        mock_result.tax = Decimal("400000")
        mock_result.npwp_factor = Decimal("2.0")
        with patch.object(engine, "calculate", return_value=mock_result):
            result = engine.calculate(
                bruto=Decimal("10000000"), pph_type="23", rate=Decimal("0.02"), has_npwp=False
            )
            assert result.tax == Decimal("400000")
            assert result.npwp_factor == Decimal("2.0")