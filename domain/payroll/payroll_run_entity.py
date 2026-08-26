# domain/payroll/payroll_run_entity.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Module: payroll_run_entity.py
Layer: 6 - Domain / Payroll
Responsibility: Payroll run entity for monthly payroll processing.

Defines the payroll run entity that represents a single payroll
processing batch for a specific period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.payroll.payslip_projection import PayslipProjection
from domain.payroll.salary_component_entity import SalaryComponentEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class PayrollRunStatus(Enum):
    """Status of a payroll run."""

    DRAFT = "draft"
    CALCULATED = "calculated"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"


class PayrollPeriod(Enum):
    """Payroll period frequency."""

    MONTHLY = "monthly"
    SEMI_MONTHLY = "semi_monthly"
    WEEKLY = "weekly"
    DAILY = "daily"


# Alias for compatibility
PayrollFrequency = PayrollPeriod


# ============================================================================
# Payroll Employee Result (Value Object)
# ============================================================================


@dataclass(frozen=True)
class PayrollEmployeeResult:
    """
    Result of payroll calculation for a single employee (immutable).

    Attributes:
        employee_id: Employee ID.
        employee_name: Employee name.
        gross_salary: Gross salary before deductions.
        allowances: Total allowances amount.
        deductions: Total deductions amount.
        tax: Tax amount (PPh 21).
        net_salary: Net salary after deductions and tax.
        components: List of salary components.
        bank_account_number: Employee bank account for payment.
        payment_reference: Payment transaction reference.
        paid_at: Timestamp when payment was made.
    """

    employee_id: UUID
    employee_name: str
    gross_salary: Decimal
    allowances: Decimal
    deductions: Decimal
    tax: Decimal
    net_salary: Decimal
    components: list[SalaryComponentEntity] = field(default_factory=list)
    bank_account_number: str | None = None
    payment_reference: str | None = None
    paid_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.gross_salary < 0:
            raise ValueError(f"Gross salary cannot be negative: {self.gross_salary}")
        if self.deductions < 0:
            raise ValueError(f"Deductions cannot be negative: {self.deductions}")
        if self.tax < 0:
            raise ValueError(f"Tax cannot be negative: {self.tax}")
        if self.net_salary < 0:
            raise ValueError(f"Net salary cannot be negative: {self.net_salary}")

    def to_payslip(self, run: PayrollRunEntity) -> PayslipProjection:
        """
        Convert to PayslipProjection.
        Menggunakan import statis di dalam fungsi untuk menghindari circular import.
        """
        # Static import inside function to avoid circular dependency
        from domain.payroll.payslip_projection import PayslipProjection

        return PayslipProjection.from_payroll_employee(self, run)

    def mark_paid(self, payment_reference: str, paid_at: datetime) -> PayrollEmployeeResult:
        """Return a new instance with payment info."""
        return PayrollEmployeeResult(
            employee_id=self.employee_id,
            employee_name=self.employee_name,
            gross_salary=self.gross_salary,
            allowances=self.allowances,
            deductions=self.deductions,
            tax=self.tax,
            net_salary=self.net_salary,
            components=self.components,
            bank_account_number=self.bank_account_number,
            payment_reference=payment_reference,
            paid_at=paid_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "gross_salary": str(self.gross_salary),
            "allowances": str(self.allowances),
            "deductions": str(self.deductions),
            "tax": str(self.tax),
            "net_salary": str(self.net_salary),
            "bank_account_number": self.bank_account_number,
            "payment_reference": self.payment_reference,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }


# ============================================================================
# Payroll Run Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class PayrollRunEntity:
    """
    Payroll run entity (immutable).

    Business context:
    Represents a single payroll processing batch for a specific period.
    Contains the results of payroll calculation for all employees.

    Attributes:
        run_id: Unique identifier.
        run_number: Human-readable run number (e.g., "PAY-2024-01").
        period: Payroll period type.
        period_year: Year of the period.
        period_month: Month of the period (1-12).
        status: Current status.
        employees: List of employee calculation results.
        total_gross: Sum of gross salaries.
        total_deductions: Sum of deductions.
        total_tax: Sum of tax amounts.
        total_net: Sum of net salaries.
        calculated_at: Timestamp when calculation was performed.
        calculated_by: User who performed calculation.
        approved_at: Timestamp when approved.
        approved_by: User who approved.
        paid_at: Timestamp when payment was processed.
        paid_by: User who processed payment.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    run_id: UUID
    run_number: str
    period: PayrollPeriod
    period_year: int
    period_month: int
    status: PayrollRunStatus
    employees: list[PayrollEmployeeResult] = field(default_factory=list)
    total_gross: Decimal = Decimal(0)
    total_deductions: Decimal = Decimal(0)
    total_tax: Decimal = Decimal(0)
    total_net: Decimal = Decimal(0)
    calculated_at: datetime | None = None
    calculated_by: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    paid_at: datetime | None = None
    paid_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        if len(self.run_number.strip()) < 3:
            raise ValueError("Run number must be at least 3 characters")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.period_year < 2000 or self.period_year > 2100:
            raise ValueError(f"Invalid period year: {self.period_year}")
        if not (1 <= self.period_month <= 12):
            raise ValueError(f"Invalid period month: {self.period_month}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ------------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        run_number: str,
        period: PayrollPeriod,
        created_by: str,
        period_year: int | None = None,
        period_month: int | None = None,
    ) -> PayrollRunEntity:
        """Create a new payroll run in DRAFT status."""
        now = datetime.now(UTC)
        year = period_year or now.year
        month = period_month or now.month
        return cls(
            run_id=uuid4(),
            run_number=run_number,
            period=period,
            period_year=year,
            period_month=month,
            status=PayrollRunStatus.DRAFT,
            created_by=created_by,
        )

    # ------------------------------------------------------------------------
    # Employee management
    # ------------------------------------------------------------------------

    def add_employee(
        self,
        employee_id: UUID,
        employee_name: str,
        gross_salary: Decimal,
        deductions: Decimal,
        tax: Decimal,
        net_salary: Decimal,
        components: list[SalaryComponentEntity],
        bank_account_number: str | None = None,
    ) -> PayrollRunEntity:
        """Add or update an employee result in this payroll run."""
        # Remove existing if any
        existing = [e for e in self.employees if e.employee_id != employee_id]
        new_employee = PayrollEmployeeResult(
            employee_id=employee_id,
            employee_name=employee_name,
            gross_salary=gross_salary,
            allowances=Decimal(0),
            deductions=deductions,
            tax=tax,
            net_salary=net_salary,
            components=components,
            bank_account_number=bank_account_number,
        )
        new_employees = [*existing, new_employee]

        return PayrollRunEntity(
            run_id=self.run_id,
            run_number=self.run_number,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            status=self.status,
            employees=new_employees,
            total_gross=self.total_gross,
            total_deductions=self.total_deductions,
            total_tax=self.total_tax,
            total_net=self.total_net,
            calculated_at=self.calculated_at,
            calculated_by=self.calculated_by,
            approved_at=self.approved_at,
            approved_by=self.approved_by,
            paid_at=self.paid_at,
            paid_by=self.paid_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def get_employee_result(self, employee_id: UUID) -> PayrollEmployeeResult | None:
        """Retrieve employee result by ID."""
        for emp in self.employees:
            if emp.employee_id == employee_id:
                return emp
        return None

    # ------------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------------

    def calculate(self) -> PayrollRunEntity:
        """Mark payroll run as calculated (aggregate totals recomputed)."""
        if self.status != PayrollRunStatus.DRAFT:
            raise ValueError(f"Cannot calculate payroll in status {self.status.value}")

        total_gross = sum(e.gross_salary for e in self.employees)
        total_deductions = sum(e.deductions for e in self.employees)
        total_tax = sum(e.tax for e in self.employees)
        total_net = sum(e.net_salary for e in self.employees)

        return PayrollRunEntity(
            run_id=self.run_id,
            run_number=self.run_number,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            status=PayrollRunStatus.CALCULATED,
            employees=self.employees,
            total_gross=total_gross,
            total_deductions=total_deductions,
            total_tax=total_tax,
            total_net=total_net,
            calculated_at=datetime.now(UTC),
            calculated_by=self.created_by,
            approved_at=self.approved_at,
            approved_by=self.approved_by,
            paid_at=self.paid_at,
            paid_by=self.paid_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def approve(self, approved_by: str) -> PayrollRunEntity:
        """Approve the payroll run (CALCULATED -> APPROVED)."""
        if self.status != PayrollRunStatus.CALCULATED:
            raise ValueError(f"Cannot approve payroll in status {self.status.value}")

        return PayrollRunEntity(
            run_id=self.run_id,
            run_number=self.run_number,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            status=PayrollRunStatus.APPROVED,
            employees=self.employees,
            total_gross=self.total_gross,
            total_deductions=self.total_deductions,
            total_tax=self.total_tax,
            total_net=self.total_net,
            calculated_at=self.calculated_at,
            calculated_by=self.calculated_by,
            approved_at=datetime.now(UTC),
            approved_by=approved_by,
            paid_at=self.paid_at,
            paid_by=self.paid_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def process_payment(self, paid_by: str) -> PayrollRunEntity:
        """Process payment (APPROVED -> PAID)."""
        if self.status != PayrollRunStatus.APPROVED:
            raise ValueError(f"Cannot process payment in status {self.status.value}")

        # Mark each employee as paid
        now = datetime.now(UTC)
        paid_employees = [
            e.mark_paid(payment_reference=f"PAY-{self.run_number}-{e.employee_id}", paid_at=now)
            for e in self.employees
        ]

        return PayrollRunEntity(
            run_id=self.run_id,
            run_number=self.run_number,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            status=PayrollRunStatus.PAID,
            employees=paid_employees,
            total_gross=self.total_gross,
            total_deductions=self.total_deductions,
            total_tax=self.total_tax,
            total_net=self.total_net,
            calculated_at=self.calculated_at,
            calculated_by=self.calculated_by,
            approved_at=self.approved_at,
            approved_by=self.approved_by,
            paid_at=now,
            paid_by=paid_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> PayrollRunEntity:
        """Cancel the payroll run (cannot cancel if paid)."""
        if self.status == PayrollRunStatus.PAID:
            raise ValueError("Cannot cancel a paid payroll run")
        if self.status == PayrollRunStatus.CANCELLED:
            raise ValueError("Payroll run already cancelled")

        return PayrollRunEntity(
            run_id=self.run_id,
            run_number=self.run_number,
            period=self.period,
            period_year=self.period_year,
            period_month=self.period_month,
            status=PayrollRunStatus.CANCELLED,
            employees=self.employees,
            total_gross=self.total_gross,
            total_deductions=self.total_deductions,
            total_tax=self.total_tax,
            total_net=self.total_net,
            calculated_at=self.calculated_at,
            calculated_by=self.calculated_by,
            approved_at=self.approved_at,
            approved_by=self.approved_by,
            paid_at=self.paid_at,
            paid_by=self.paid_by,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": str(self.run_id),
            "run_number": self.run_number,
            "period": self.period.value,
            "period_year": self.period_year,
            "period_month": self.period_month,
            "status": self.status.value,
            "employee_count": len(self.employees),
            "total_gross": str(self.total_gross),
            "total_deductions": str(self.total_deductions),
            "total_tax": str(self.total_tax),
            "total_net": str(self.total_net),
            "calculated_at": self.calculated_at.isoformat() if self.calculated_at else None,
            "calculated_by": self.calculated_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": self.approved_by,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "paid_by": self.paid_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Alias for compatibility
# ============================================================================

PayrollRun = PayrollRunEntity


# ============================================================================
# Payroll Run Repository Protocol
# ============================================================================


class PayrollRunRepository:
    """Repository protocol for PayrollRunEntity."""

    async def get_by_id(self, run_id: UUID, legal_entity_id: UUID) -> PayrollRunEntity | None:
        raise NotImplementedError

    async def get_by_period(
        self,
        legal_entity_id: UUID,
        year: int,
        month: int,
    ) -> PayrollRunEntity | None:
        raise NotImplementedError

    async def save(self, payroll_run: PayrollRunEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, run_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "PayrollEmployeeResult",
    "PayrollFrequency",
    "PayrollPeriod",
    "PayrollRun",
    "PayrollRunEntity",
    "PayrollRunRepository",
    "PayrollRunStatus",
]
