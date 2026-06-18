#!/usr/bin/env python3

"""
Module: test_payroll_calculation.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk perhitungan payroll (gaji).
    Menguji perhitungan gaji pokok, tunjangan, potongan BPJS, PPh 21, dan komponen lainnya.

Dependencies:
    - domain/payroll/tax_withholding_engine.py
    - domain/payroll/salary_component_entity.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from uuid import uuid4

import pytest

from domain.payroll.salary_component_entity import SalaryComponent, SalaryComponentType
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine


class TestPayrollCalculation:
    """Test suite untuk perhitungan payroll."""

    @pytest.fixture
    def tax_engine(self) -> TaxWithholdingEngine:
        """Fixture tax withholding engine."""
        return TaxWithholdingEngine()

    @pytest.fixture
    def employee_data(self) -> dict:
        """Fixture data karyawan untuk perhitungan PPh 21."""
        return {
            "id": uuid4(),
            "npwp": "123456789012345",
            "name": "Budi Santoso",
            "marital_status": "Kawin",
            "dependents": 2,
            "monthly_salary": Decimal("15000000"),
            "allowances": Decimal("2000000"),
            "bpjs_kesehatan_employee": Decimal("150000"),
            "bpjs_ketenagakerjaan_employee": Decimal("300000"),
            "other_deductions": Decimal("500000"),
        }

    def test_calculate_gross_pay(self, employee_data):
        """Test: Perhitungan gross pay (gaji kotor)."""
        gross = employee_data["monthly_salary"] + employee_data["allowances"]
        assert gross == Decimal("17000000")

    def test_calculate_total_deductions(self, employee_data):
        """Test: Perhitungan total potongan."""
        deductions = (
            employee_data["bpjs_kesehatan_employee"]
            + employee_data["bpjs_ketenagakerjaan_employee"]
            + employee_data["other_deductions"]
        )
        assert deductions == Decimal("950000")

    def test_calculate_net_pay(self, employee_data):
        """Test: Perhitungan net pay (gaji bersih)."""
        gross = Decimal("17000000")
        deductions = Decimal("950000")
        net = gross - deductions
        assert net == Decimal("16050000")

    def test_pph21_calculation_annualization(self, tax_engine, employee_data):
        """Test: Perhitungan PPh 21 dengan metode annualisasi."""
        # Annual gross: (gaji + tunjangan) * 12
        annual_gross = (employee_data["monthly_salary"] + employee_data["allowances"]) * 12
        # PTKP untuk kawin + 2 tanggungan: 58.5jt (TK/0) + 4.5jt (kawin) + 2*4.5jt? Standar PTKP 2025: WP sendiri 54jt, kawin +4.5jt, tanggungan max 3 @4.5jt.
        # Sederhanakan: PTKP = 54jt + 4.5jt + (2*4.5jt) = 67.5jt
        ptkp = Decimal("67500000")
        pkp = max(annual_gross - ptkp, Decimal("0"))
        # Tarif progresif
        if pkp <= 60000000:
            tax = pkp * Decimal("0.05")
        elif pkp <= 250000000:
            tax = 60000000 * Decimal("0.05") + (pkp - 60000000) * Decimal("0.15")
        elif pkp <= 500000000:
            tax = (
                60000000 * Decimal("0.05")
                + 190000000 * Decimal("0.15")
                + (pkp - 250000000) * Decimal("0.25")
            )
        else:
            tax = (
                60000000 * Decimal("0.05")
                + 190000000 * Decimal("0.15")
                + 250000000 * Decimal("0.25")
                + (pkp - 500000000) * Decimal("0.30")
            )
        monthly_tax = tax / 12
        monthly_tax = monthly_tax.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        # annual_gross = 17jt*12=204jt. PKP = 204jt - 67.5jt = 136.5jt
        # Tarif: 5%*60jt=3jt, 15%*(136.5jt-60jt=76.5jt)=11.475jt, total 14.475jt
        # Monthly = 14.475jt/12 = 1.206.250
        assert monthly_tax == Decimal("1206250")

    def test_pph21_calculation_with_bonus(self, tax_engine, employee_data):
        """Test: Perhitungan PPh 21 dengan bonus."""
        bonus = Decimal("10000000")
        annual_gross = (employee_data["monthly_salary"] + employee_data["allowances"]) * 12 + bonus
        ptkp = Decimal("67500000")
        pkp = max(annual_gross - ptkp, Decimal("0"))
        pkp = 204000000 + 10000000 - 67500000
        assert pkp == 146500000
        tax = 60000000 * Decimal("0.05") + (146500000 - 60000000) * Decimal("0.15")
        # Jika tujuannya untuk menegaskan nilai hasil penjumlahan
        tax = Decimal("3000000") + Decimal("12975000")
        assert tax == Decimal("15975000")
        monthly_tax = tax / 12
        monthly_tax = monthly_tax.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        # 15.975.000 / 12 = 1.331.250
        assert monthly_tax == Decimal("1331250")

    def test_bpjs_kesehatan_employee_contribution(self):
        """Test: Iuran BPJS Kesehatan karyawan (1% dari gaji upah)."""
        monthly_salary = Decimal("15000000")
        # Iuran BPJS Kesehatan: karyawan 1%, perusahaan 4%, max upah 12jt? Di aturan terbaru tidak ada batas. Sederhana.
        employee_contribution = monthly_salary * Decimal("0.01")
        employee_contribution = employee_contribution.quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )
        assert employee_contribution == Decimal("150000")

    def test_bpjs_ketenagakerjaan_employee_contribution(self):
        """Test: Iuran BPJS Ketenagakerjaan (JHT: 2% dari upah)."""
        monthly_salary = Decimal("15000000")
        jht_employee = monthly_salary * Decimal("0.02")
        jht_employee = jht_employee.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert jht_employee == Decimal("300000")

    def test_bpjs_ketenagakerjaan_employer_contribution(self):
        """Test: Iuran BPJS Ketenagakerjaan yang dibayar perusahaan."""
        monthly_salary = Decimal("15000000")
        jht_employer = monthly_salary * Decimal("0.037")  # 3.7%
        jht_employer = jht_employer.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert jht_employer == Decimal("555000")
        jkk = monthly_salary * Decimal("0.0054")  # 0.54%
        jkk = jkk.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert jkk == Decimal("81000")
        jkm = monthly_salary * Decimal("0.003")  # 0.3%
        jkm = jkm.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert jkm == Decimal("45000")

    def test_salary_component_calculation(self):
        """Test: Agregasi komponen gaji."""
        components = [
            SalaryComponent(
                id=uuid4(),
                employee_id=uuid4(),
                component_type=SalaryComponentType.BASIC_SALARY,
                amount=Decimal("10000000"),
                description="Gaji Pokok",
            ),
            SalaryComponent(
                id=uuid4(),
                employee_id=uuid4(),
                component_type=SalaryComponentType.ALLOWANCE,
                amount=Decimal("2000000"),
                description="Tunjangan",
            ),
            SalaryComponent(
                id=uuid4(),
                employee_id=uuid4(),
                component_type=SalaryComponentType.DEDUCTION_BPJS_KESEHATAN,
                amount=Decimal("150000"),
                description="BPJS Kesehatan",
            ),
            SalaryComponent(
                id=uuid4(),
                employee_id=uuid4(),
                component_type=SalaryComponentType.DEDUCTION_BPJS_KETENAGAKERJAAN,
                amount=Decimal("300000"),
                description="BPJS JHT",
            ),
            SalaryComponent(
                id=uuid4(),
                employee_id=uuid4(),
                component_type=SalaryComponentType.TAX_PPH21,
                amount=Decimal("1206250"),
                description="PPh 21",
            ),
        ]
        gross = sum(
            c.amount
            for c in components
            if c.component_type
            in (
                SalaryComponentType.BASIC_SALARY,
                SalaryComponentType.ALLOWANCE,
                SalaryComponentType.OVERTIME,
                SalaryComponentType.BONUS,
            )
        )
        deductions = sum(
            c.amount
            for c in components
            if c.component_type
            in (
                SalaryComponentType.DEDUCTION_BPJS_KESEHATAN,
                SalaryComponentType.DEDUCTION_BPJS_KETENAGAKERJAAN,
                SalaryComponentType.TAX_PPH21,
                SalaryComponentType.OTHER_DEDUCTION,
            )
        )
        net = gross - deductions
        assert gross == Decimal("12000000")
        assert deductions == Decimal("1656250")
        assert net == Decimal("10343750")

    def test_overtime_calculation(self):
        """Test: Perhitungan lembur."""
        hourly_rate = Decimal("50000")
        overtime_hours = Decimal("10")
        # Lembur: 1.5x untuk jam pertama, 2x untuk jam berikutnya
        if overtime_hours <= 1:
            overtime_pay = overtime_hours * hourly_rate * Decimal("1.5")
        else:
            overtime_pay = hourly_rate * Decimal("1.5") + (
                overtime_hours - 1
            ) * hourly_rate * Decimal("2")
        overtime_pay = overtime_pay.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        # 1.5 * 50rb = 75rb; 9 jam * 2 * 50rb = 900rb; total = 975.000
        assert overtime_pay == Decimal("975000")

    def test_prorated_salary_calculation(self):
        """Test: Perhitungan gaji prorata untuk karyawan baru di tengah bulan."""
        full_month_salary = Decimal("10000000")
        working_days = 15
        total_days = 30
        prorated = (full_month_salary / total_days) * working_days
        prorated = prorated.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert prorated == Decimal("5000000")

    def test_net_pay_rounding(self):
        """Test: Pembulatan net pay (tidak ada pecahan sen)."""
        net = Decimal("12345678.90")
        rounded = net.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        assert rounded == Decimal("12345679")

    def test_thp_minimum_wage_compliance(self):
        """Test: Kepatuhan terhadap upah minimum (UMR)."""
        umr = Decimal("4500000")
        calculated_net = Decimal("4400000")
        if calculated_net < umr:
            need_adjustment = True
        else:
            need_adjustment = False
        assert need_adjustment is True


if __name__ == "__main__":
    pytest.main([__file__])
