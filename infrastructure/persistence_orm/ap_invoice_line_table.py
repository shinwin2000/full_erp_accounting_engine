#!/usr/bin/env python3
"""
Module: ap_invoice_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk line items AP invoice.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class APInvoiceLineTable(Base, TimestampMixin):
    __tablename__ = "ap_invoice_line"
    __table_args__ = (
        CheckConstraint("line_number > 0", name="ck_ap_invoice_line_number_positive"),
        CheckConstraint("quantity > 0", name="ck_ap_invoice_line_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_ap_invoice_line_unit_price_nonneg"),
        CheckConstraint("amount >= 0", name="ck_ap_invoice_line_amount_nonneg"),
        Index("idx_ap_invoice_line_invoice", "invoice_id"),
        Index("idx_ap_invoice_line_account", "account_code")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ap_invoice.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    account_code: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=Decimal(1))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal(0))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal(0))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(50), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationship
    invoice: Mapped[APInvoiceTable] = relationship("APInvoiceTable", back_populates="lines")

    @property
    def net_amount(self) -> Decimal:
        return self.quantity * self.unit_price

    def recalc_total(self) -> None:
        net = self.net_amount
        self.amount = net
        self.tax_amount = net * (self.tax_rate / 100)
        self.total_amount = self.amount + self.tax_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "line_number": self.line_number,
            "description": self.description,
            "account_code": self.account_code,
            "quantity": float(self.quantity),
            "unit_price": float(self.unit_price),
            "amount": float(self.amount),
            "tax_rate": float(self.tax_rate),
            "tax_amount": float(self.tax_amount),
            "total_amount": float(self.total_amount),
            "cost_center": self.cost_center,
            "project_id": str(self.project_id) if self.project_id else None,
        }


__all__ = ["APInvoiceLineTable"]
