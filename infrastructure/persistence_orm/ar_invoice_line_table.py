#!/usr/bin/env python3
"""
Module: ar_invoice_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ar_invoice_line.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable


class ARInvoiceLineTable(Base, TimestampMixin):
    __tablename__ = "ar_invoice_line"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_ar_invoice_line_quantity_pos"),
        CheckConstraint("unit_price >= 0", name="ck_ar_invoice_line_unit_price_nonneg"),
        CheckConstraint("total_amount >= 0", name="ck_ar_invoice_line_total_nonneg"),
        CheckConstraint("tax_rate >= 0", name="ck_ar_invoice_line_tax_rate_nonneg"),
        CheckConstraint(
            "discount_percent >= 0 AND discount_percent <= 100",
            name="ck_ar_invoice_line_discount_range",
        ),
        Index("idx_ar_invoice_line_invoice", "invoice_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ar_invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    account_code: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # =========================================================================
    # RELATIONSHIP
    # =========================================================================
    invoice: Mapped[ARInvoiceTable] = relationship(
        "ARInvoiceTable",
        back_populates="lines",
        foreign_keys=[invoice_id],
    )

    # =========================================================================
    # PROPERTIES
    # =========================================================================
    @property
    def net_amount(self) -> Decimal:
        discount = self.quantity * self.unit_price * (self.discount_percent / 100)
        return (self.quantity * self.unit_price) - discount

    @property
    def tax_amount(self) -> Decimal:
        return self.net_amount * (self.tax_rate / 100)

    @property
    def final_amount(self) -> Decimal:
        return self.net_amount + self.tax_amount

    # =========================================================================
    # METHODS
    # =========================================================================
    def recalc_total(self) -> None:
        net = self.quantity * self.unit_price
        discount = net * (self.discount_percent / 100)
        after_discount = net - discount
        tax = after_discount * (self.tax_rate / 100)
        self.total_amount = after_discount + tax

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_id": str(self.invoice_id),
            "line_number": self.line_number,
            "description": self.description,
            "quantity": float(self.quantity),
            "unit_price": float(self.unit_price),
            "tax_rate": float(self.tax_rate),
            "discount_percent": float(self.discount_percent),
            "account_code": self.account_code,
            "total_amount": float(self.total_amount),
            "currency": self.currency,
            "net_amount": float(self.net_amount),
            "tax_amount": float(self.tax_amount),
            "final_amount": float(self.final_amount),
        }


__all__ = ["ARInvoiceLineTable"]
