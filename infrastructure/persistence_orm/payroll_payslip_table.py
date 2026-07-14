#!/usr/bin/env python3
"""
Module: payroll_payslip_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel payroll_payslip (slip gaji payroll).
               Menyimpan data slip gaji karyawan, termasuk komponen gaji,
               potongan, dan total bersih.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    CreatedByMixin,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class PayrollPayslipTable(
    Base,
    TimestampMixin,
    SoftDeleteMixin,
    VersionMixin,
    LegalEntityMixin,
    CreatedByMixin,
):
    """
    Model untuk tabel payroll_payslip.
    """

    __tablename__ = "payroll_payslip"
    # 🔧 TAMBAHKAN baris ini untuk mengatasi duplikasi jika ada model lain dengan nama tabel sama
    __table_args__ = {'extend_existing': True}

    # Primary Key
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        nullable=False,
    )

    # Foreign Key ke tabel employee
    employee_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Periode gaji
    pay_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    pay_period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Komponen gaji
    gross_salary: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        default=Decimal(0),
    )
    total_deductions: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        default=Decimal(0),
    )
    net_salary: Mapped[Decimal] = mapped_column(
        Numeric(20, 2),
        nullable=False,
        default=Decimal(0),
    )

    # Status dan tanggal pembayaran
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
    )  # draft, approved, paid, cancelled
    payment_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Catatan tambahan
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PayrollPayslipTable(id={self.id}, employee_id={self.employee_id}, "
            f"period={self.pay_period_start} to {self.pay_period_end}, "
            f"net={self.net_salary})>"
        )


__all__ = ["PayrollPayslipTable"]