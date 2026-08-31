#!/usr/bin/env python3
"""
Module: payslip_projection.py
Layer: 6 - Domain / Payroll
Responsibility: Payslip read model.

Defines the payslip projection read model for employee payroll results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.payroll.salary_component_entity import SalaryComponentEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Payslip Projection (Read Model, Immutable)
# ============================================================================


@dataclass(frozen=True)
class PayslipProjection:
    """
    Payslip read model (immutable).

    Business context:
    Provides a formatted payslip for an employee, including all salary
    components, deductions, and net pay.

    Attributes:
        payslip_id: Unique identifier.
        employee_id: Employee ID.
        employee_name: Employee name.
        employee_nik: Employee NIK (optional).
        employee_position: Employee position (optional).
        period_month: Payroll period month.
        period_year: Payroll period year.
        run_number: Payroll run number.
        run_date: Date of payroll calculation.
        gross_salary: Gross salary.
        allowances: List of allowance components.
        deductions: List of deduction components.
        tax: Tax amount (PPh 21).
        net_salary: Net salary.
        bank_account_number: Employee bank account.
        payment_reference: Payment transaction reference.
        payment_date: Date of payment.
        created_at: Creation timestamp.
    """

    payslip_id: UUID
    employee_id: UUID
    employee_name: str
    period_month: int
    period_year: int
    run_number: str
    run_date: datetime
    gross_salary: Decimal
    allowances: list[SalaryComponentEntity]
    deductions: list[SalaryComponentEntity]
    tax: Decimal
    net_salary: Decimal
    employee_nik: str | None = None
    employee_position: str | None = None
    bank_account_number: str | None = None
    payment_reference: str | None = None
    payment_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.gross_salary < 0:
            raise ValueError(f"Gross salary cannot be negative: {self.gross_salary}")
        if self.tax < 0:
            raise ValueError(f"Tax cannot be negative: {self.tax}")
        if self.net_salary < 0:
            raise ValueError(f"Net salary cannot be negative: {self.net_salary}")
        if self.run_date.tzinfo is None:
            raise ValueError("run_date must be timezone-aware")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if not (1 <= self.period_month <= 12):
            raise ValueError(f"Invalid period month: {self.period_month}")
        if self.period_year < 2000 or self.period_year > 2100:
            raise ValueError(f"Invalid period year: {self.period_year}")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_payroll_employee(
        cls,
        employee: Any,  # PayrollEmployeeResult, but avoid import
        payroll_run: Any,  # PayrollRunEntity, but avoid import
        employee_nik: str | None = None,
        employee_position: str | None = None,
    ) -> PayslipProjection:
        """
        Create a payslip from payroll employee result.
        employee and payroll_run are expected to have the necessary attributes.
        """
        # allowances and deductions based on amount sign
        allowances = [c for c in employee.components if c.amount > 0]
        deductions = [c for c in employee.components if c.amount < 0]

        return cls(
            payslip_id=uuid4(),
            employee_id=employee.employee_id,
            employee_name=employee.employee_name,
            employee_nik=employee_nik,
            employee_position=employee_position,
            period_month=payroll_run.period_month,
            period_year=payroll_run.period_year,
            run_number=payroll_run.run_number,
            run_date=payroll_run.calculated_at or payroll_run.created_at,
            gross_salary=employee.gross_salary,
            allowances=allowances,
            deductions=deductions,
            tax=employee.tax,
            net_salary=employee.net_salary,
            bank_account_number=employee.bank_account_number,
            payment_reference=employee.payment_reference,
            payment_date=employee.paid_at,
        )

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    def get_total_allowances(self) -> Decimal:
        """Sum of all allowances."""
        return sum((c.amount for c in self.allowances), Decimal(0))

    def get_total_deductions(self) -> Decimal:
        """Sum of all deductions (absolute values)."""
        return sum((abs(c.amount) for c in self.deductions), Decimal(0))

    def get_component_summary(self) -> dict[str, Decimal]:
        """Return dictionary of component names to amounts."""
        summary = {}
        for allowance in self.allowances:
            summary[f"ALLOWANCE_{allowance.component_name}"] = allowance.amount
        for deduction in self.deductions:
            summary[f"DEDUCTION_{deduction.component_name}"] = abs(deduction.amount)
        summary["TAX"] = self.tax
        return summary

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "payslip_id": str(self.payslip_id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "employee_nik": self.employee_nik,
            "employee_position": self.employee_position,
            "period": f"{self.period_month}/{self.period_year}",
            "run_number": self.run_number,
            "run_date": self.run_date.isoformat(),
            "gross_salary": str(self.gross_salary),
            "total_allowances": str(self.get_total_allowances()),
            "total_deductions": str(self.get_total_deductions()),
            "tax": str(self.tax),
            "net_salary": str(self.net_salary),
            "bank_account_number": self.bank_account_number,
            "payment_reference": self.payment_reference,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "components": {
                "allowances": [c.to_dict() for c in self.allowances],
                "deductions": [c.to_dict() for c in self.deductions],
            },
            "created_at": self.created_at.isoformat(),
        }

    # ------------------------------------------------------------------------
    # HTML/PDF generation
    # ------------------------------------------------------------------------

    def generate_html(self) -> str:
        """Generate HTML representation of payslip."""
        allowances_html = "".join(
            f"<tr><th>{c.component_name}</th><th>{c.description}</th><td class='amount'>{c.amount:,.2f}</td></tr>"
            for c in self.allowances
        )
        deductions_html = "".join(
            f"<tr><th>{c.component_name}</th><th>{c.description}</th><td class='amount'>{abs(c.amount):,.2f}</td></tr>"
            for c in self.deductions
        )
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>Payslip - {self.employee_name}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 40px; }}
        .header {{ text-align: center; margin-bottom: 30px; }}
        .company {{ font-size: 20px; font-weight: bold; }}
        .payslip-title {{ font-size: 24px; margin-top: 10px; }}
        .employee-info {{ margin-bottom: 20px; padding: 10px; background: #f5f5f5; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .amount {{ text-align: right; }}
        .total {{ font-weight: bold; background-color: #e8e8e8; }}
        .footer {{ margin-top: 30px; font-size: 12px; text-align: center; color: #666; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="company">PT Company Name</div>
        <div class="payslip-title">SLIP GAJI</div>
        <div>Periode: {self.period_month}/{self.period_year}</div>
    </div>

    <div class="employee-info">
        <strong>Nama Karyawan:</strong> {self.employee_name}<br>
        <strong>NIK:</strong> {self.employee_nik or "-"}<br>
        <strong>Jabatan:</strong> {self.employee_position or "-"}<br>
        <strong>Tanggal Cetak:</strong> {self.created_at.strftime("%d/%m/%Y %H:%M")}
    </div>

    <h3>Komponen Gaji</h3>
    <table>
        <tr><th>Komponen</th><th>Keterangan</th><th>Jumlah (Rp)</th></tr>
        <tr><td>Gaji Pokok</td><td>-</td><td class='amount'>{self.gross_salary:,.2f}</td></tr>
        {allowances_html}
        {deductions_html}
        <tr><td>PPh 21</td><td>Pajak Penghasilan</td><td class='amount'>{self.tax:,.2f}</td></tr>
        <tr class="total"><td colspan="2"><strong>Take Home Pay</strong></td><td class='amount'><strong>{self.net_salary:,.2f}</strong></td></tr>
    </table>

    <div class="footer">
        Dicetak oleh sistem pada {self.created_at.strftime("%d/%m/%Y %H:%M:%S")}<br>
        Slip gaji ini adalah bukti sah pembayaran gaji.
    </div>
</body>
</html>"""

    def generate_pdf(self) -> bytes:
        """Generate PDF representation (simplified - returns HTML bytes)."""
        return self.generate_html().encode("utf-8")


# ============================================================================
# Aliases for compatibility
# ============================================================================

Payslip = PayslipProjection


# ============================================================================
# Repository Protocol
# ============================================================================


class PayslipRepository:
    """Repository protocol for PayslipProjection."""

    async def get_by_id(self, payslip_id: UUID, legal_entity_id: UUID) -> PayslipProjection | None:
        raise NotImplementedError

    async def get_by_employee(
        self,
        employee_id: UUID,
        legal_entity_id: UUID,
        limit: int = 12,
    ) -> list[PayslipProjection]:
        raise NotImplementedError

    async def get_by_period(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
    ) -> list[PayslipProjection]:
        raise NotImplementedError

    async def save(self, payslip: PayslipProjection, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, payslip_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "Payslip",
    "PayslipProjection",
    "PayslipRepository",
]
