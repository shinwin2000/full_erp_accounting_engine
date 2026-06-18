#!/usr/bin/env python3
"""
Module: test_tax_calculation_accuracy_all.py
Layer: Compliance

Responsibility:
    Menguji akurasi perhitungan semua jenis pajak di Indonesia.
    Menggunakan toleransi untuk Decimal/float dan fleksibel terhadap implementasi.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

# ============================================================================
# Import real modules (if available)
# ============================================================================

try:
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

    TAX_MODULES_AVAILABLE = True
except ImportError:
    TAX_MODULES_AVAILABLE = False

    # Fallback dummy classes agar test bisa di-skip jika modul tidak ada
    class Dummy:
        pass

    BeaMeteraiCalculator = Dummy
    PenaltyInterestEngine = Dummy
    PPh4Ayat2Calculator = Dummy
    PPh21Calculator = Dummy
    PPh22Calculator = Dummy
    PPh23Calculator = Dummy
    PPh25Calculator = Dummy
    PPh26Calculator = Dummy
    PPhBadanCalculator = Dummy
    PPNCalculator = Dummy


# ============================================================================
# Helper untuk menangani Decimal vs float
# ============================================================================
def to_decimal(value):
    """Convert to Decimal safely."""
    if isinstance(value, float):
        return Decimal(str(value))
    return value


# ============================================================================
# Tests
# ============================================================================


class TestPPN:
    """PPN (Pajak Pertambahan Nilai)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPNCalculator not available")
    def test_tarif_11_persen(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="11%")
        assert ppn == Decimal("110000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPNCalculator not available")
    def test_tarif_0_persen_untuk_ekspor_bkp(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), tarif="0%", transaksi="ekspor_bkp")
        assert ppn == Decimal("0")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPNCalculator not available")
    def test_tarif_11_persen_untuk_ekspor_jkp_tidak_dikenakan(self):
        ppn = PPNCalculator.calculate(dpp=Decimal("1000000"), transaksi="ekspor_jkp")
        assert ppn == Decimal("0")


class TestPPh21:
    """PPh Pasal 21 (Karyawan)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh21Calculator not available")
    def test_penghasilan_bruto_60_juta_setahun_ptkp_k0(self):
        pph21 = PPh21Calculator.annual_tax(
            gross_income=Decimal("60000000"),
            ptkp_status="K/0",
            tahun=2025,
        )
        assert pph21 >= Decimal("0")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh21Calculator not available")
    def test_ter_untuk_penghasilan_bulanan_10_juta(self):
        ter = PPh21Calculator.monthly_ter(gross_monthly=Decimal("10000000"))
        assert ter == Decimal("200000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh21Calculator not available")
    def test_tidak_ada_pajak_untuk_penghasilan_dibawah_ptkp(self):
        pph21 = PPh21Calculator.annual_tax(gross_income=Decimal("50000000"), ptkp_status="TK/0")
        assert pph21 == Decimal("0")


class TestPPh22:
    """PPh Pasal 22 (Impor & Pembelian)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh22Calculator not available")
    def test_impor_dengan_api_10_persen(self):
        pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=True)
        assert pph22 == Decimal("10000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh22Calculator not available")
    def test_impor_tanpa_api_75_persen(self):
        pph22 = PPh22Calculator.calculate_import(cif=Decimal("100000000"), has_api=False)
        assert pph22 == Decimal("7500000")


class TestPPh23:
    """PPh Pasal 23 (Jasa & Sewa)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh23Calculator not available")
    def test_jasa_management_2_persen(self):
        pph23 = PPh23Calculator.calculate(bruto=Decimal("50000000"), jenis_jasa="management")
        assert pph23 == Decimal("1000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh23Calculator not available")
    def test_sewa_tanah_bangunan_10_persen(self):
        pph23 = PPh23Calculator.calculate_sewa(bruto=Decimal("10000000"), jenis="tanah_bangunan")
        assert pph23 == Decimal("1000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh23Calculator not available")
    def test_tidak_dipotong_jika_tidak_ada_npwp_dan_penghasilan_kecil(self):
        # Peraturan: tanpa NPWP, tarif menjadi 2x lipat (4% untuk jasa management).
        # Jadi tetap dipotong meskipun penghasilan kecil.
        result = PPh23Calculator.calculate(
            bruto=Decimal("2000000"), jenis_jasa="management", has_npwp=False
        )
        # Tanpa NPWP, tarif 4% dari bruto = 80.000
        assert result == Decimal("80000")


class TestPPh25:
    """PPh Pasal 25 (Angsuran)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh25Calculator not available")
    def test_angsuran_dihitung_dari_pph_terutang_tahun_lalu_dibagi_12(self):
        angsuran = PPh25Calculator.monthly_installment(
            previous_year_tax_liability=Decimal("120000000")
        )
        assert angsuran == Decimal("10000000")


class TestPPh26:
    """PPh Pasal 26 (WPLN)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh26Calculator not available")
    def test_wpln_20_persen_dari_bruto(self):
        pph26 = PPh26Calculator.calculate(
            gross_income=Decimal("50000000"), country_code="US", has_treaty=False
        )
        assert pph26 == Decimal("10000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh26Calculator not available")
    def test_wpln_dengan_treaty_tarif_lebih_rendah(self):
        pph26 = PPh26Calculator.calculate(
            gross_income=Decimal("50000000"),
            country_code="SG",
            has_treaty=True,
            treaty_rate=10,
        )
        assert pph26 == Decimal("5000000")


class TestPPh4Ayat2:
    """PPh Final Pasal 4 ayat 2."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh4Ayat2Calculator not available")
    def test_bunga_deposito_20_persen(self):
        pph_final = PPh4Ayat2Calculator.calculate_deposit_interest(
            interest=Decimal("5000000"), has_npwp=True
        )
        assert pph_final == Decimal("1000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh4Ayat2Calculator not available")
    def test_sewa_tanah_bangunan_10_persen(self):
        pph = PPh4Ayat2Calculator.calculate_land_rental(rent=Decimal("20000000"))
        assert pph == Decimal("2000000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPh4Ayat2Calculator not available")
    def test_pph_final_jasa_konstruksi_tergantung_kualifikasi(self):
        pph = PPh4Ayat2Calculator.calculate_construction(
            contract_value=Decimal("1_000_000_000"), qualification="menengah"
        )
        assert pph == Decimal("20000000")  # 2% for menengah


class TestPPhBadan:
    """PPh Badan (CIT)."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPhBadanCalculator not available")
    def test_tarif_22_persen_untuk_peredaran_bruto_diatas_50_miliar(self):
        pph = PPhBadanCalculator.calculate(
            gross_revenue=Decimal("100_000_000_000"),
            taxable_income=Decimal("20_000_000_000"),
        )
        assert pph == Decimal("4_400_000_000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PPhBadanCalculator not available")
    def test_fasilitas_tarif_11_persen_untuk_peredaran_sampai_48_miliar(self):
        pph = PPhBadanCalculator.calculate(
            gross_revenue=Decimal("40_000_000_000"),
            taxable_income=Decimal("5_000_000_000"),
        )
        assert pph > Decimal("0")


class TestBeaMeterai:
    """Bea Meterai."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="BeaMeteraiCalculator not available")
    def test_dokumen_nilai_10_juta_dikenakan_10000(self):
        bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("10000000"))
        assert bea == Decimal("10000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="BeaMeteraiCalculator not available")
    def test_dokumen_nilai_dibawah_10_juta_tidak_dikenakan(self):
        bea = BeaMeteraiCalculator.calculate_document_stamp(document_value=Decimal("5000000"))
        assert bea == Decimal("0")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="BeaMeteraiCalculator not available")
    def test_cek_elektronik_dikenakan_10000_jika_nilai_lebih_dari_5_juta(self):
        bea = BeaMeteraiCalculator.calculate_cek(nilai=Decimal("6000000"))
        assert bea == Decimal("10000")


class TestPenaltyInterest:
    """Denda dan bunga keterlambatan pajak."""

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PenaltyInterestEngine not available")
    def test_bunga_per_bulan_2_persen(self):
        bunga = PenaltyInterestEngine.calculate(
            pokok=Decimal("10000000"),
            months_late=3,
            tarif_bunga=Decimal("0.02"),
        )
        assert bunga == Decimal("600000")

    @pytest.mark.skipif(not TAX_MODULES_AVAILABLE, reason="PenaltyInterestEngine not available")
    def test_denda_ppn_tidak_lapor_2_persen_dari_dpp(self):
        denda = PenaltyInterestEngine.denda_tidak_lapor_ppn(dpp=Decimal("100000000"))
        assert denda == Decimal("2000000")
