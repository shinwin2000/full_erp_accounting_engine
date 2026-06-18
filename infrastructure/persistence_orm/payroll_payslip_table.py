#!/usr/bin/env python3
"""
Module: payroll_payslip_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Read model untuk slip gaji (payslip).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class PayslipTable(Base, TimestampMixin):
    __tablename__ = "payroll_payslip"
    __table_args__ = (
        Index("idx_payslip_employee", "employee_id"),
        Index("idx_payslip_run", "payroll_run_id"),
        CheckConstraint("net_pay >= 0", name="ck_payslip_net_nonneg")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payslip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    gross_income: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    total_deductions: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    net_pay: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=0)
    bank_account: Mapped[str] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="GENERATED")

    @property
    def is_generated(self) -> bool:
        return self.status == "GENERATED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "payslip_id": str(self.payslip_id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "payroll_run_id": str(self.payroll_run_id),
            "period": self.period,
            "gross_income": float(self.gross_income),
            "total_deductions": float(self.total_deductions),
            "net_pay": float(self.net_pay),
            "bank_account": self.bank_account,
            "status": self.status,
        }


PayrollPayslipTable = PayslipTable
PayslipReadModel = PayslipTable

__all__ = ["PayrollPayslipTable", "PayslipReadModel", "PayslipTable"]
