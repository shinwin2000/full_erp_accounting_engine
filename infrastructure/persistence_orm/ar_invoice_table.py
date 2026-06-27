#!/usr/bin/env python3
"""
Module: ar_invoice_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ar_invoice.
               Tabel ini menyimpan data invoice Account Receivable (piutang),
               termasuk nomor invoice, customer, tanggal, jumlah, status,
               dan informasi pembayaran. Setiap invoice memiliki satu atau
               lebih line items (di tabel ar_invoice_line).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan status invoice (draft, submitted, approved, paid, dll)
       dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
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
    from infrastructure.persistence_orm.ar_credit_note_table import ARCreditNoteTable
    from infrastructure.persistence_orm.ar_invoice_line_table import ARInvoiceLineTable
    from infrastructure.persistence_orm.ar_payment_table import ARPaymentTable
    from infrastructure.persistence_orm.coretax_bupot_table import CoretaxBupotTable
    from infrastructure.persistence_orm.customer_table import CustomerTable
    from infrastructure.persistence_orm.sales_order_table import SalesOrderTable


class ARInvoiceTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel ar_invoice.
    """

    __tablename__ = "ar_invoice"
    __table_args__ = (
        UniqueConstraint(
            "invoice_number", "legal_entity_id", name="uq_ar_invoice_number_legal_entity"
        ),
        CheckConstraint(
            "invoice_number IS NOT NULL AND invoice_number != ''", name="ck_ar_invoice_number"
        ),
        CheckConstraint("total_amount >= 0", name="ck_ar_invoice_total_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_ar_invoice_paid_nonneg"),
        CheckConstraint("paid_amount <= total_amount", name="ck_ar_invoice_paid_not_exceed"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partially_paid', 'paid', 'overdue', 'cancelled')",
            name="ck_ar_invoice_status",
        ),
        Index("idx_ar_invoice_number", "invoice_number"),
        Index("idx_ar_invoice_customer", "customer_id"),
        Index("idx_ar_invoice_date", "invoice_date"),
        Index("idx_ar_invoice_due_date", "due_date"),
        Index("idx_ar_invoice_status", "status"),
        Index("idx_ar_invoice_legal_entity", "legal_entity_id"),
        Index("idx_ar_invoice_sales_order", "sales_order_id"),
        Index("idx_ar_invoice_outstanding", "total_amount", "paid_amount"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Invoice identification
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Customer (foreign key with schema)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customer.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Financial totals
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Description
    description: Mapped[str] = mapped_column(String(500), nullable=False)

    # Reference
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sales_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sales_order.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Tax invoice (faktur pajak)
    tax_invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Approval (if 4-eyes required)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Customer
    customer: Mapped[CustomerTable] = relationship(
        "CustomerTable",
        back_populates="ar_invoices",
        foreign_keys=[customer_id],
    )

    # Sales Order (optional)
    sales_order: Mapped[SalesOrderTable | None] = relationship(
        "SalesOrderTable",
        back_populates="ar_invoices",
        foreign_keys=[sales_order_id],
    )

    # Invoice lines
    lines: Mapped[list[ARInvoiceLineTable]] = relationship(
        "ARInvoiceLineTable",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="ARInvoiceLineTable.line_number",
    )

    # Payments
    payments: Mapped[list[ARPaymentTable]] = relationship(
        "ARPaymentTable",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )

    # Credit Notes
    credit_notes: Mapped[list[ARCreditNoteTable]] = relationship(
        "ARCreditNoteTable",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # Bupots (Coretax) � ditambahkan untuk melengkapi back_populates di CoretaxBupotTable
    # ========================================================================
    bupots: Mapped[list[CoretaxBupotTable]] = relationship(
        "CoretaxBupotTable",
        back_populates="invoice",
        foreign_keys="[CoretaxBupotTable.invoice_id]",
        cascade="all, delete-orphan",
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
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def days_overdue(self) -> int:
        if self.is_paid:
            return 0
        delta = date.today() - self.due_date
        return max(0, delta.days)

    @property
    def payment_percentage(self) -> float:
        if self.total_amount == 0:
            return 100.0
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

    def reject(self, rejected_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject invoice with status {self.status}")
        self.status = "draft"
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

    def write_off(self, amount: Decimal, reason: str) -> None:
        if amount <= 0:
            raise ValueError("Write-off amount must be positive")
        if amount > self.outstanding_amount:
            raise ValueError("Write-off amount exceeds outstanding balance")

        self.paid_amount += amount
        if self.paid_amount >= self.total_amount:
            self.status = "paid"
        self.increment_version()


ARInvoiceReadModel = ARInvoiceTable

__all__ = ["ARInvoiceReadModel", "ARInvoiceTable"]
