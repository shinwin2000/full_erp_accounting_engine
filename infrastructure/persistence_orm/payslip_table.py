#!/usr/bin/env python3
"""
Module: payslip_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel payslip (slip gaji).
               Model ini menyimpan detail slip gaji per karyawan per periode.
               Digunakan sebagai read model untuk payroll dan mendukung:
               - Perhitungan komponen gaji (basic salary, allowances, overtime, bonus)
               - Perhitungan potongan (tax, BPJS, pension, loan)
               - Status workflow (generated, approved, paid, cancelled)
               - Rekonsiliasi dengan payment run
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC, JSONB)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap payslip dihasilkan dari payroll run dan immutable setelah approved.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.employee_table import EmployeeTable
    from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable


class PayslipTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel payslip.
    Menyimpan slip gaji per karyawan per periode.
    """

    __tablename__ = "payslip"
    __table_args__ = (
        UniqueConstraint(
            "payslip_number", "legal_entity_id", name="uq_payslip_number_legal_entity"
        ),
        CheckConstraint("payslip_number IS NOT NULL AND payslip_number != ''", name="ck_payslip_number"),
        CheckConstraint("employee_id IS NOT NULL", name="ck_payslip_employee"),
        CheckConstraint("payroll_run_id IS NOT NULL", name="ck_payslip_run"),
        CheckConstraint("net_pay >= 0", name="ck_payslip_net_nonneg"),
        CheckConstraint(
            "status IN ('generated', 'approved', 'paid', 'cancelled')",
            name="ck_payslip_status",
        ),
        CheckConstraint("period_year >= 2000", name="ck_payslip_year"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_payslip_month"),
        Index("idx_payslip_legal_entity", "legal_entity_id"),
        Index("idx_payslip_employee", "employee_id"),
        Index("idx_payslip_run", "payroll_run_id"),
        Index("idx_payslip_number", "payslip_number"),
        Index("idx_payslip_status", "status"),
        Index("idx_payslip_period", "period_year", "period_month"),
        Index("idx_payslip_payment_date", "payment_date"),
        Index("idx_payslip_net_pay", "net_pay"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identification
    payslip_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    # Period
    period_year: Mapped[int] = mapped_column(nullable=False)
    period_month: Mapped[int] = mapped_column(nullable=False)

    # Employee (denormalized for read performance)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("public.employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(100), nullable=True)
    employment_status: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Payroll run reference
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("public.payroll_run.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Income components
    basic_salary: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    allowances: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    overtime: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    bonus: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    thirteenth_month: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    other_income: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))

    # Deduction components
    tax_pph21: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    bpjs_employment: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    bpjs_health: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    bpjs_pension: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    loan_deduction: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    cooperative_deduction: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    other_deductions: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))

    # Totals
    gross_income: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    net_pay: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))

    # Currency
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Payment details
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # Status workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="generated")

    # Approval
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Additional data (JSON)
    earnings_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deductions_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tax_calculation_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    employee: Mapped[EmployeeTable] = relationship(
        "EmployeeTable",
        foreign_keys=[employee_id],
        back_populates="payslips",  # harus ditambahkan di EmployeeTable
    )
    payroll_run: Mapped[PayrollRunTable] = relationship(
        "PayrollRunTable",
        foreign_keys=[payroll_run_id],
        back_populates="payslips",  # harus ditambahkan di PayrollRunTable
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_generated(self) -> bool:
        return self.status == "generated"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_paid(self) -> bool:
        return self.status == "paid"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def period_display(self) -> str:
        return f"{self.period_year}-{self.period_month:02d}"

    @property
    def total_income(self) -> Decimal:
        return (self.basic_salary + self.allowances + self.overtime + self.bonus +
                self.thirteenth_month + self.other_income)

    @property
    def total_deductions_calc(self) -> Decimal:
        return (self.tax_pph21 + self.bpjs_employment + self.bpjs_health +
                self.bpjs_pension + self.loan_deduction + self.cooperative_deduction +
                self.other_deductions)

    @property
    def is_balanced(self) -> bool:
        expected_net = self.total_income - self.total_deductions_calc
        return abs(expected_net - self.net_pay) <= Decimal("0.01")

    @property
    def tax_rate_effective(self) -> Decimal:
        if self.gross_income == 0:
            return Decimal(0)
        return (self.tax_pph21 / self.gross_income * 100).quantize(Decimal("0.01"))

    # ========================================================================
    # BUSINESS METHODS (Immutable transformations)
    # ========================================================================

    def approve(self, approved_by: uuid.UUID) -> PayslipTable:
        if self.status != "generated":
            raise ValueError(f"Cannot approve payslip with status {self.status}")
        from dataclasses import replace
        new = replace(self)
        new.status = "approved"
        new.approved_by = approved_by
        new.approved_at = datetime.utcnow()
        new.version += 1
        new.updated_at = datetime.utcnow()
        return new

    def mark_paid(self, payment_date: date, payment_reference: str | None = None,
                  payment_run_id: uuid.UUID | None = None) -> PayslipTable:
        if self.status not in ("generated", "approved"):
            raise ValueError(f"Cannot mark payslip as paid with status {self.status}")
        from dataclasses import replace
        new = replace(self)
        new.status = "paid"
        new.payment_date = payment_date
        if payment_reference:
            new.payment_reference = payment_reference
        if payment_run_id:
            new.payment_run_id = payment_run_id
        new.version += 1
        new.updated_at = datetime.utcnow()
        return new

    def cancel(self) -> PayslipTable:
        if self.status == "paid":
            raise ValueError("Cannot cancel a paid payslip")
        from dataclasses import replace
        new = replace(self)
        new.status = "cancelled"
        new.version += 1
        new.updated_at = datetime.utcnow()
        return new

    def recalculate(self) -> PayslipTable:
        from dataclasses import replace
        new = replace(self)
        new.gross_income = new.total_income
        new.total_deductions = new.total_deductions_calc
        new.net_pay = new.gross_income - new.total_deductions
        if new.net_pay < 0:
            new.net_pay = Decimal(0)
        new.version += 1
        new.updated_at = datetime.utcnow()
        return new

    def update_notes(self, notes: str) -> PayslipTable:
        if self.status == "paid":
            raise ValueError("Cannot update notes for a paid payslip")
        from dataclasses import replace
        new = replace(self)
        new.notes = notes
        new.version += 1
        new.updated_at = datetime.utcnow()
        return new

    # ========================================================================
    # FACTORY METHODS
    # ========================================================================

    @classmethod
    def create(
        cls,
        legal_entity_id: uuid.UUID,
        payslip_number: str,
        employee_id: uuid.UUID,
        employee_code: str,
        employee_name: str,
        payroll_run_id: uuid.UUID,
        period_year: int,
        period_month: int,
        basic_salary: Decimal = Decimal(0),
        allowances: Decimal = Decimal(0),
        overtime: Decimal = Decimal(0),
        bonus: Decimal = Decimal(0),
        thirteenth_month: Decimal = Decimal(0),
        other_income: Decimal = Decimal(0),
        tax_pph21: Decimal = Decimal(0),
        bpjs_employment: Decimal = Decimal(0),
        bpjs_health: Decimal = Decimal(0),
        bpjs_pension: Decimal = Decimal(0),
        loan_deduction: Decimal = Decimal(0),
        cooperative_deduction: Decimal = Decimal(0),
        other_deductions: Decimal = Decimal(0),
        currency: str = "IDR",
        bank_account: str | None = None,
        position: str | None = None,
        department: str | None = None,
        employment_status: str | None = None,
        earnings_breakdown: dict | None = None,
        deductions_breakdown: dict | None = None,
        tax_calculation_detail: dict | None = None,
        notes: str | None = None,
        created_by: uuid.UUID | None = None,
    ) -> PayslipTable:
        gross_income = (basic_salary + allowances + overtime + bonus +
                        thirteenth_month + other_income)
        total_deductions = (tax_pph21 + bpjs_employment + bpjs_health +
                            bpjs_pension + loan_deduction + cooperative_deduction +
                            other_deductions)
        net_pay = gross_income - total_deductions
        if net_pay < 0:
            net_pay = Decimal(0)

        now = datetime.utcnow()
        return cls(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            payslip_number=payslip_number,
            period_year=period_year,
            period_month=period_month,
            employee_id=employee_id,
            employee_code=employee_code,
            employee_name=employee_name,
            position=position,
            department=department,
            employment_status=employment_status,
            payroll_run_id=payroll_run_id,
            basic_salary=basic_salary,
            allowances=allowances,
            overtime=overtime,
            bonus=bonus,
            thirteenth_month=thirteenth_month,
            other_income=other_income,
            tax_pph21=tax_pph21,
            bpjs_employment=bpjs_employment,
            bpjs_health=bpjs_health,
            bpjs_pension=bpjs_pension,
            loan_deduction=loan_deduction,
            cooperative_deduction=cooperative_deduction,
            other_deductions=other_deductions,
            gross_income=gross_income,
            total_deductions=total_deductions,
            net_pay=net_pay,
            currency=currency,
            bank_account=bank_account,
            earnings_breakdown=earnings_breakdown,
            deductions_breakdown=deductions_breakdown,
            tax_calculation_detail=tax_calculation_detail,
            notes=notes,
            status="generated",
            created_by=created_by,
            created_at=now,
            updated_at=now,
            version=1,
            deleted_at=None,
        )

    @classmethod
    def from_payroll_run(
        cls,
        payroll_run: PayrollRunTable,
        employee: EmployeeTable,
        payslip_number: str,
        basic_salary: Decimal,
        allowances: Decimal = Decimal(0),
        overtime: Decimal = Decimal(0),
        bonus: Decimal = Decimal(0),
        other_income: Decimal = Decimal(0),
        loan_deduction: Decimal = Decimal(0),
        other_deductions: Decimal = Decimal(0),
        **kwargs,
    ) -> PayslipTable:
        return cls.create(
            legal_entity_id=payroll_run.legal_entity_id,
            payslip_number=payslip_number,
            employee_id=employee.id,
            employee_code=employee.employee_code,
            employee_name=employee.full_name,
            payroll_run_id=payroll_run.id,
            period_year=payroll_run.period_year,
            period_month=payroll_run.period_month,
            basic_salary=basic_salary,
            allowances=allowances,
            overtime=overtime,
            bonus=bonus,
            other_income=other_income,
            loan_deduction=loan_deduction,
            other_deductions=other_deductions,
            **kwargs,
        )

    # ========================================================================
    # SERIALIZATION
    # ========================================================================

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "payslip_number": self.payslip_number,
            "period_year": self.period_year,
            "period_month": self.period_month,
            "employee_id": str(self.employee_id),
            "employee_code": self.employee_code,
            "employee_name": self.employee_name,
            "position": self.position,
            "department": self.department,
            "employment_status": self.employment_status,
            "payroll_run_id": str(self.payroll_run_id),
            "basic_salary": str(self.basic_salary),
            "allowances": str(self.allowances),
            "overtime": str(self.overtime),
            "bonus": str(self.bonus),
            "thirteenth_month": str(self.thirteenth_month),
            "other_income": str(self.other_income),
            "tax_pph21": str(self.tax_pph21),
            "bpjs_employment": str(self.bpjs_employment),
            "bpjs_health": str(self.bpjs_health),
            "bpjs_pension": str(self.bpjs_pension),
            "loan_deduction": str(self.loan_deduction),
            "cooperative_deduction": str(self.cooperative_deduction),
            "other_deductions": str(self.other_deductions),
            "gross_income": str(self.gross_income),
            "total_deductions": str(self.total_deductions),
            "net_pay": str(self.net_pay),
            "currency": self.currency,
            "payment_date": self.payment_date.isoformat() if self.payment_date else None,
            "bank_account": self.bank_account,
            "payment_reference": self.payment_reference,
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "status": self.status,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "earnings_breakdown": self.earnings_breakdown,
            "deductions_breakdown": self.deductions_breakdown,
            "tax_calculation_detail": self.tax_calculation_detail,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "version": self.version,
        }

    def to_db_record(self) -> dict:
        return {
            "id": self.id,
            "legal_entity_id": self.legal_entity_id,
            "payslip_number": self.payslip_number,
            "period_year": self.period_year,
            "period_month": self.period_month,
            "employee_id": self.employee_id,
            "employee_code": self.employee_code,
            "employee_name": self.employee_name,
            "position": self.position,
            "department": self.department,
            "employment_status": self.employment_status,
            "payroll_run_id": self.payroll_run_id,
            "basic_salary": self.basic_salary,
            "allowances": self.allowances,
            "overtime": self.overtime,
            "bonus": self.bonus,
            "thirteenth_month": self.thirteenth_month,
            "other_income": self.other_income,
            "tax_pph21": self.tax_pph21,
            "bpjs_employment": self.bpjs_employment,
            "bpjs_health": self.bpjs_health,
            "bpjs_pension": self.bpjs_pension,
            "loan_deduction": self.loan_deduction,
            "cooperative_deduction": self.cooperative_deduction,
            "other_deductions": self.other_deductions,
            "gross_income": self.gross_income,
            "total_deductions": self.total_deductions,
            "net_pay": self.net_pay,
            "currency": self.currency,
            "payment_date": self.payment_date,
            "bank_account": self.bank_account,
            "payment_reference": self.payment_reference,
            "payment_run_id": self.payment_run_id,
            "status": self.status,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "earnings_breakdown": self.earnings_breakdown,
            "deductions_breakdown": self.deductions_breakdown,
            "tax_calculation_detail": self.tax_calculation_detail,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "version": self.version,
        }

    def __str__(self) -> str:
        return f"Payslip {self.payslip_number} - {self.employee_name} - {self.period_display}"

    def __repr__(self) -> str:
        return f"PayslipTable(id={self.id}, number={self.payslip_number}, status={self.status})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PayslipTable):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


PayslipReadModel = PayslipTable

__all__ = ["PayslipReadModel", "PayslipTable"]
