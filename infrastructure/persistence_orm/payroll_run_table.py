#!/usr/bin/env python3
"""
Module: payroll_run_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel payroll_run.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    # NB: relasi "payslips" memakai PayslipTable (tabel 'payslip'), yaitu
    # model yang benar-benar dipakai oleh repository aktif
    # (sqlalchemy_payroll_repository_impl.py) dan EmployeeTable.payslips.
    # PayrollPayslipTable (tabel 'payroll_payslip') adalah model lama yang
    # tidak lagi dipakai di mana pun, sengaja TIDAK dihubungkan ke sini
    # untuk menghindari konflik reverse_property/back_populates.
    from infrastructure.persistence_orm.payslip_table import PayslipTable
    from infrastructure.persistence_orm.salary_component_table import SalaryComponentTable


class PayrollRunTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "payroll_run"
    __table_args__ = (
        UniqueConstraint("run_number", "legal_entity_id", name="uq_payroll_run_number_legal_entity"),
        CheckConstraint("run_number IS NOT NULL", name="ck_payroll_run_number"),
        CheckConstraint("period_year >= 2000", name="ck_payroll_run_year"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="ck_payroll_run_month"),
        CheckConstraint(
            "status IN ('calculated', 'approved', 'paid', 'cancelled')",
            name="ck_payroll_run_status",
        ),
        CheckConstraint("total_employees >= 0", name="ck_payroll_run_employees_nonneg"),
        CheckConstraint("total_net_salary >= 0", name="ck_payroll_run_net_salary_nonneg"),
        Index("idx_payroll_run_legal_entity", "legal_entity_id"),
        Index("idx_payroll_run_period", "period_year", "period_month"),
        Index("idx_payroll_run_status", "status"),
        Index("idx_payroll_run_number", "run_number"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_number: Mapped[str] = mapped_column(String(50), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    total_employees: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_net_salary: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_tax: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="calculated")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Salary components
    salary_components: Mapped[list[SalaryComponentTable]] = relationship(
        "SalaryComponentTable",
        back_populates="payroll_run",
        foreign_keys="[SalaryComponentTable.payroll_run_id]",
        cascade="all, delete-orphan",
    )

    # Payslips
    payslips: Mapped[list[PayslipTable]] = relationship(
        "PayslipTable",
        back_populates="payroll_run",
        foreign_keys="[PayslipTable.payroll_run_id]",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_calculated(self) -> bool:
        return self.status == "calculated"

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
    def average_net_salary_per_employee(self) -> Decimal:
        if self.total_employees == 0:
            return Decimal(0)
        return self.total_net_salary / self.total_employees

    # ========================================================================
    # METHODS
    # ========================================================================

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "calculated":
            raise ValueError(f"Cannot approve payroll run with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def mark_paid(self, paid_by: uuid.UUID, payment_run_id: uuid.UUID) -> None:
        if self.status != "approved":
            raise ValueError(f"Cannot mark payroll run as paid with status {self.status}")
        self.status = "paid"
        self.paid_by = paid_by
        self.paid_at = datetime.utcnow()
        self.payment_run_id = payment_run_id
        self.increment_version()

    def cancel(self) -> None:
        if self.status == "paid":
            raise ValueError("Cannot cancel a paid payroll run")
        self.status = "cancelled"
        self.increment_version()

    def update_totals(
        self,
        total_employees: int,
        total_net_salary: Decimal,
        total_tax: Decimal,
        total_deductions: Decimal,
    ) -> None:
        self.total_employees = total_employees
        self.total_net_salary = total_net_salary
        self.total_tax = total_tax
        self.total_deductions = total_deductions
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "run_number": self.run_number,
            "period_year": self.period_year,
            "period_month": self.period_month,
            "total_employees": self.total_employees,
            "total_net_salary": float(self.total_net_salary),
            "total_tax": float(self.total_tax),
            "total_deductions": float(self.total_deductions),
            "currency": self.currency,
            "status": self.status,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "paid_by": str(self.paid_by) if self.paid_by else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
        }

__all__ = ["PayrollRunTable"]
