#!/usr/bin/env python3
"""
Module: salary_component_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel salary_component.
               Tabel ini menyimpan komponen gaji (earnings, deductions, tax, benefit)
               untuk setiap karyawan dalam payroll run. Mendukung perhitungan
               fixed amount, percentage, atau formula.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- infrastructure.persistence_orm.base_model
Audit: Setiap komponen gaji dicatat di event store.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount, computed_amount)
      di to_dict() untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String
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
    from infrastructure.persistence_orm.employee_table import EmployeeTable
    from infrastructure.persistence_orm.payroll_run_table import PayrollRunTable


class SalaryComponentTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "salary_component"
    __table_args__ = (
        CheckConstraint("component_name IS NOT NULL", name="ck_salary_component_name"),
        CheckConstraint(
            "component_type IN ('earnings', 'deductions', 'tax', 'benefit')",
            name="ck_salary_component_type",
        ),
        CheckConstraint(
            "calculation_type IN ('fixed', 'percentage', 'formula')",
            name="ck_salary_component_calc",
        ),
        CheckConstraint("amount >= 0", name="ck_salary_component_amount_nonneg"),
        Index("idx_salary_component_employee", "employee_id"),
        Index("idx_salary_component_payroll_run", "payroll_run_id"),
        Index("idx_salary_component_type", "component_type"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="CASCADE"),
        nullable=False,
    )
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("payroll_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    component_name: Mapped[str] = mapped_column(String(100), nullable=False)
    component_type: Mapped[str] = mapped_column(String(20), nullable=False)
    calculation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="fixed")
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    rate_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # Menggunakan back_populates yang cocok dengan relasi di EmployeeTable
    # (salary_components) dan PayrollRunTable (salary_components).
    # =========================================================================
    employee: Mapped[EmployeeTable] = relationship(
        "EmployeeTable",
        back_populates="salary_components",
        foreign_keys=[employee_id],
    )

    payroll_run: Mapped[PayrollRunTable] = relationship(
        "PayrollRunTable",
        back_populates="salary_components",
        foreign_keys=[payroll_run_id],
    )

    # =========================================================================
    # PROPERTIES
    # =========================================================================
    @property
    def is_earnings(self) -> bool:
        return self.component_type == "earnings"

    @property
    def is_deduction(self) -> bool:
        return self.component_type == "deductions"

    @property
    def is_tax(self) -> bool:
        return self.component_type == "tax"

    @property
    def is_fixed(self) -> bool:
        return self.calculation_type == "fixed"

    @property
    def is_percentage(self) -> bool:
        return self.calculation_type == "percentage"

    @property
    def computed_amount(self) -> Decimal:
        """Hitung amount berdasarkan calculation_type."""
        if self.calculation_type == "percentage" and self.rate_percentage is not None:
            return (self.amount * self.rate_percentage / 100).quantize(Decimal("0.01"))
        return self.amount

    # =========================================================================
    # METHODS
    # =========================================================================
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "employee_id": str(self.employee_id),
            "payroll_run_id": str(self.payroll_run_id),
            "component_name": self.component_name,
            "component_type": self.component_type,
            "calculation_type": self.calculation_type,
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "rate_percentage": float(self.rate_percentage) if self.rate_percentage else None,
            "computed_amount": str(self.computed_amount),  # ganti float -> str untuk presisi
            "currency": self.currency,
            "description": self.description,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["SalaryComponentTable"]