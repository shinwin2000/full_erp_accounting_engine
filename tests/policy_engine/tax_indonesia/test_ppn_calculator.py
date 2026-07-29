# tests/policy_engine/tax_indonesia/test_ppn_calculator.py
"""
Comprehensive unit tests for policy_engine/tax_indonesia/ppn_calculator.py.
Covers all enums, result dataclass, calculator methods, class methods,
and singleton accessor with proper Decimal assertions.
"""

from datetime import date
from decimal import Decimal

import pytest

from policy_engine.tax_indonesia.ppn_calculator import (
    PPNCalculationResult,
    PPNCalculator,
    PPNStatus,
    PPNTariff,
    PPNType,
    get_ppn_calculator,
)

# ============================================================================
# Enum Tests
# ============================================================================

class TestPPNTariff:
    def test_members(self):
        assert PPNTariff.RATE_11.value == Decimal("11")
        assert PPNTariff.RATE_12.value == Decimal("12")

    def test_member_type(self):
        assert isinstance(PPNTariff.RATE_11, PPNTariff)
        assert isinstance(PPNTariff.RATE_12, PPNTariff)


class TestPPNStatus:
    def test_members(self):
        assert PPNStatus.TAXABLE.value == "taxable"
        assert PPNStatus.NON_TAXABLE.value == "non_taxable"
        assert PPNStatus.EXEMPT.value == "exempt"
        assert PPNStatus.ZERO_RATED.value == "zero_rated"


class TestPPNType:
    def test_members(self):
        assert PPNType.OUTPUT.value == "output"
        assert PPNType.INPUT.value == "input"


# ============================================================================
# PPNCalculationResult Tests
# ============================================================================

class TestPPNCalculationResult:
    def test_construction(self):
        result = PPNCalculationResult(
            dpp=Decimal("1000000"),
            tariff=Decimal("11"),
            ppn_amount=Decimal("110000"),
            ppn_status=PPNStatus.TAXABLE,
            ppn_type=PPNType.OUTPUT,
            rounding_method="HALF_UP",
        )
        assert result.dpp == Decimal("1000000")
        assert result.tariff == Decimal("11")
        assert result.ppn_amount == Decimal("110000")
        assert result.ppn_status == PPNStatus.TAXABLE
        assert result.ppn_type == PPNType.OUTPUT
        assert result.rounding_method == "HALF_UP"

    def test_to_dict(self):
        result = PPNCalculationResult(
            dpp=Decimal("1000000"),
            tariff=Decimal("11"),
            ppn_amount=Decimal("110000"),
            ppn_status=PPNStatus.TAXABLE,
            ppn_type=PPNType.OUTPUT,
        )
        d = result.to_dict()
        assert d["dpp"] == "1000000"
        assert d["tariff"] == "11"
        assert d["ppn_amount"] == "110000"
        assert d["ppn_status"] == "taxable"
        assert d["ppn_type"] == "output"


# ============================================================================
# PPNCalculator Tests
# ============================================================================

class TestPPNCalculator:
    @pytest.fixture
    def calculator(self):
        return PPNCalculator(PPNTariff.RATE_11)

    def test_construction_default(self):
        calc = PPNCalculator()
        assert calc._tariff == PPNTariff.RATE_11

    def test_construction_custom(self):
        calc = PPNCalculator(PPNTariff.RATE_12)
        assert calc._tariff == PPNTariff.RATE_12

    def test_set_tariff(self, calculator):
        calculator.set_tariff(PPNTariff.RATE_12)
        assert calculator._tariff == PPNTariff.RATE_12

    # ---- calculate (main) ----
    @pytest.mark.parametrize("dpp,tarif,transaksi,expected", [
        (Decimal("1000000"), None, "", Decimal("110000")),  # 11%
        (Decimal("1000000"), "0%", "", Decimal("0")),      # 0%
        (Decimal("1000000"), None, "ekspor_bkp", Decimal("0")),
        (Decimal("1000000"), None, "ekspor_jkp", Decimal("0")),
        (Decimal("1000000"), "11%", "", Decimal("110000")),
    ])
    def test_calculate(self, calculator, dpp, tarif, transaksi, expected):
        result = calculator.calculate(dpp, tarif, transaksi)
        assert result == expected

    # ---- calculate_output_tax ----
    def test_calculate_output_tax_taxable(self, calculator):
        result = calculator.calculate_output_tax(Decimal("1000000"), PPNStatus.TAXABLE)
        assert result.dpp == Decimal("1000000")
        assert result.tariff == Decimal("11")
        assert result.ppn_amount == Decimal("110000")
        assert result.ppn_status == PPNStatus.TAXABLE
        assert result.ppn_type == PPNType.OUTPUT

    def test_calculate_output_tax_with_rounding(self, calculator):
        # DPP 1,234,567 with 11% = 135,802.37 (rounded up)
        result = calculator.calculate_output_tax(Decimal("1234567"), PPNStatus.TAXABLE, use_rounding=True)
        # 1234567 * 0.11 = 135802.37 exactly? Actually 1234567 * 11 / 100 = 135802.37, so rounding half up gives same
        assert result.ppn_amount == Decimal("135802.37")

    def test_calculate_output_tax_non_taxable(self, calculator):
        result = calculator.calculate_output_tax(Decimal("1000000"), PPNStatus.NON_TAXABLE)
        assert result.ppn_amount == Decimal("0")
        assert result.ppn_status == PPNStatus.NON_TAXABLE
        assert result.tariff == Decimal("0")

    def test_calculate_output_tax_exempt(self, calculator):
        result = calculator.calculate_output_tax(Decimal("1000000"), PPNStatus.EXEMPT)
        assert result.ppn_amount == Decimal("0")
        assert result.ppn_status == PPNStatus.EXEMPT
        assert result.tariff == Decimal("0")

    def test_calculate_output_tax_zero_rated(self, calculator):
        result = calculator.calculate_output_tax(Decimal("1000000"), PPNStatus.ZERO_RATED)
        assert result.ppn_amount == Decimal("0")
        assert result.ppn_status == PPNStatus.ZERO_RATED

    # ---- calculate_input_tax ----
    def test_calculate_input_tax_creditable(self, calculator):
        result = calculator.calculate_input_tax(Decimal("1000000"), PPNStatus.TAXABLE, creditable=True)
        assert result.ppn_amount == Decimal("110000")
        assert result.ppn_type == PPNType.INPUT
        assert result.ppn_status == PPNStatus.TAXABLE

    def test_calculate_input_tax_not_creditable(self, calculator):
        result = calculator.calculate_input_tax(Decimal("1000000"), PPNStatus.TAXABLE, creditable=False)
        assert result.ppn_amount == Decimal("0")
        assert result.ppn_type == PPNType.INPUT

    def test_calculate_input_tax_non_taxable(self, calculator):
        result = calculator.calculate_input_tax(Decimal("1000000"), PPNStatus.NON_TAXABLE, creditable=True)
        assert result.ppn_amount == Decimal("0")
        assert result.ppn_status == PPNStatus.NON_TAXABLE

    # ---- calculate_ppn_from_gross ----
    def test_calculate_ppn_from_gross_output(self, calculator):
        # Gross = DPP + PPN = 1,000,000 + 110,000 = 1,110,000
        # PPN = 1,110,000 * (11 / 111) = 110,000
        result = calculator.calculate_ppn_from_gross(Decimal("1110000"), is_output=True)
        assert result.dpp == Decimal("1000000")
        assert result.ppn_amount == Decimal("110000")
        assert result.ppn_type == PPNType.OUTPUT

    def test_calculate_ppn_from_gross_input(self, calculator):
        result = calculator.calculate_ppn_from_gross(Decimal("1110000"), is_output=False)
        assert result.ppn_type == PPNType.INPUT

    def test_calculate_ppn_from_gross_rounding(self, calculator):
        # Gross = 1,234,567 => 11/111 = 0.099099... => PPN = 122,342.69? Let's compute
        # 1234567 * 11 / 111 = 122,342.6937 => rounded 122,342.69
        result = calculator.calculate_ppn_from_gross(Decimal("1234567"), use_rounding=True)
        # Calculate expected: 1234567 * 11 / 111 = 122342.693693..., rounded half up = 122342.69
        # DPP = gross - ppn = 1234567 - 122342.69 = 1112224.31
        assert result.ppn_amount == Decimal("122342.69")
        assert result.dpp == Decimal("1112224.31")

    # ---- calculate_ppn_compensation ----
    def test_compensation_underpayment(self, calculator):
        result = calculator.calculate_ppn_compensation(Decimal("200000"), Decimal("150000"))
        assert result["status"] == "UNDERPAYMENT"
        assert result["amount"] == Decimal("50000")
        assert "Kurang bayar" in result["description"]

    def test_compensation_overpayment(self, calculator):
        result = calculator.calculate_ppn_compensation(Decimal("150000"), Decimal("200000"))
        assert result["status"] == "OVERPAYMENT"
        assert result["amount"] == Decimal("50000")
        assert "Lebih bayar" in result["description"]

    def test_compensation_nil(self, calculator):
        result = calculator.calculate_ppn_compensation(Decimal("100000"), Decimal("100000"))
        assert result["status"] == "NIL"
        assert result["amount"] == Decimal("0")
        assert "Nihil" in result["description"]

    # ---- calculate_input_tax_creditability ----
    def test_creditability_full(self, calculator):
        # Taxable sales equal total sales => full credit
        credit = calculator.calculate_input_tax_creditability(
            ppn_input=Decimal("100000"),
            related_to_taxable_sales=Decimal("500000"),
            total_sales=Decimal("500000")
        )
        assert credit == Decimal("100000")

    def test_creditability_partial(self, calculator):
        # 60% taxable sales
        credit = calculator.calculate_input_tax_creditability(
            ppn_input=Decimal("100000"),
            related_to_taxable_sales=Decimal("300000"),
            total_sales=Decimal("500000")
        )
        # 100000 * 0.6 = 60000
        assert credit == Decimal("60000")

    def test_creditability_zero_total_sales(self, calculator):
        credit = calculator.calculate_input_tax_creditability(
            ppn_input=Decimal("100000"),
            related_to_taxable_sales=Decimal("0"),
            total_sales=Decimal("0")
        )
        assert credit == Decimal("0")

    def test_creditability_zero_ppn_input(self, calculator):
        credit = calculator.calculate_input_tax_creditability(
            ppn_input=Decimal("0"),
            related_to_taxable_sales=Decimal("500000"),
            total_sales=Decimal("1000000")
        )
        assert credit == Decimal("0")

    # ---- get_requirements_summary ----
    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert summary["current_tariff"] == "11"
        assert "RATE_12" in summary["available_tariffs"]
        assert "taxable" in summary["status_types"]
        assert "output" in summary["ppn_types"]

    # ---- validate ----
    def test_validate(self, calculator):
        assert calculator.validate({}) is True

    # ---- get_rate ----
    def test_get_rate(self, calculator):
        assert calculator.get_rate() == Decimal("11")

    # ---- Class methods ----
    def test_calculate_tax_simple(self):
        # 11% of 1,000,000
        result = PPNCalculator.calculate_tax_simple(Decimal("1000000"))
        assert result == Decimal("110000")

        # 0% (ekspor)
        result2 = PPNCalculator.calculate_tax_simple(Decimal("1000000"), tarif="0%")
        assert result2 == Decimal("0")
        result3 = PPNCalculator.calculate_tax_simple(Decimal("1000000"), transaksi="ekspor_bkp")
        assert result3 == Decimal("0")

        # 11% with other tarif? If tarif is None, default 11
        result4 = PPNCalculator.calculate_tax_simple(Decimal("1000000"), "11%")
        assert result4 == Decimal("110000")

    def test_create_faktur_keluaran(self):
        tanggal = date(2026, 7, 23)
        faktur = PPNCalculator.create_faktur_keluaran(Decimal("1000000"), Decimal("110000"), tanggal)
        assert faktur.kode_faktur == "010"
        assert faktur.nomor_faktur == f"010.{tanggal.year}.{tanggal.month:02d}.00000001"
        assert faktur.ppn == Decimal("110000")
        assert faktur.dpp == Decimal("1000000")
        assert faktur.tanggal == tanggal
        assert faktur.status == "SUBMITTED"
        assert faktur.qr_code == f"QR-{faktur.nomor_faktur}"

    # ---- singleton ----
    def test_get_ppn_calculator(self):
        calc1 = get_ppn_calculator()
        calc2 = get_ppn_calculator()
        assert calc1 is calc2
        assert isinstance(calc1, PPNCalculator)
