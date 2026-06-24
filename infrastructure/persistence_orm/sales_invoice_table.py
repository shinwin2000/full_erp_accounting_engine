#!/usr/bin/env python3
"""
Module: sales_invoice_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel sales_invoice (faktur penjualan).
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
    from infrastructure.persistence_orm.customer_table import CustomerTable
    from infrastructure.persistence_orm.sales_order_table import SalesOrderTable


class SalesInvoiceTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "sales_invoice"
    __table_args__ = (
        UniqueConstraint(
            "invoice_number", "legal_entity_id", name="uq_sales_invoice_number_legal_entity"
        ),
        CheckConstraint(
            "invoice_number IS NOT NULL AND invoice_number != ''", name="ck_si_number"
        ),
        CheckConstraint("customer_id IS NOT NULL", name="ck_si_customer"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partially_paid', 'paid', 'cancelled')",
            name="ck_si_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_si_total_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_si_paid_nonneg"),
        Index("idx_si_number", "invoice_number"),
        Index("idx_si_customer", "customer_id"),
        Index("idx_si_date", "invoice_date"),
        Index("idx_si_due_date", "due_date"),
        Index("idx_si_status", "status"),
        Index("idx_si_so", "sales_order_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Foreign keys dengan skema public
    customer_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("customer.id", ondelete="RESTRICT"),
        nullable=False,
    )
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sales_order.id", ondelete="SET NULL"),
        nullable=True,
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Relasi ke Customer (backref agar CustomerTable otomatis mendapat 'sales_invoices')
    customer: Mapped[CustomerTable] = relationship(
        "CustomerTable",
        foreign_keys=[customer_id],
        backref="sales_invoices",
    )

    # Relasi ke Sales Order (backref agar SalesOrderTable otomatis mendapat 'sales_invoices')
    sales_order: Mapped[SalesOrderTable | None] = relationship(
        "SalesOrderTable",
        foreign_keys=[sales_order_id],
        backref="sales_invoices",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.paid_amount

    @property
    def is_paid(self) -> bool:
        return self.status == "paid" or self.paid_amount >= self.total_amount

    @property
    def is_partially_paid(self) -> bool:
        return self.status == "partially_paid" or (0 < self.paid_amount < self.total_amount)

    @property
    def is_overdue(self) -> bool:
        if self.is_paid:
            return False
        return date.today() > self.due_date

    @property
    def payment_percentage(self) -> float:
        if self.total_amount == 0:
            return 0.0
        return float((self.paid_amount / self.total_amount) * 100)

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit invoice with status {self.status}")
        self.status = "submitted"
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve invoice with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def record_payment(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        if self.is_paid:
            raise ValueError("Invoice already paid")
        new_paid = self.paid_amount + amount
        if new_paid >= self.total_amount:
            self.status = "paid"
            self.paid_amount = self.total_amount
        else:
            self.status = "partially_paid"
            self.paid_amount = new_paid
        self.increment_version()

    def cancel(self) -> None:
        if self.is_paid:
            raise ValueError("Cannot cancel paid invoice")
        if self.status in ("paid", "cancelled"):
            raise ValueError(f"Cannot cancel invoice with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "customer_id": str(self.customer_id),
            "sales_order_id": str(self.sales_order_id) if self.sales_order_id else None,
            "total_amount": float(self.total_amount),
            "paid_amount": float(self.paid_amount),
            "outstanding_amount": float(self.outstanding_amount),
            "tax_amount": float(self.tax_amount),
            "discount_amount": float(self.discount_amount),
            "currency": self.currency,
            "status": self.status,
            "description": self.description,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


SalesInvoiceReadModel = SalesInvoiceTable

__all__ = ["SalesInvoiceReadModel", "SalesInvoiceTable"]
