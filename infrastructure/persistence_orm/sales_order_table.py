#!/usr/bin/env python3
"""
Module: sales_order_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel sales_order.
               Tabel ini menyimpan data Sales Order (SO) penjualan ke customer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
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


class SalesOrderTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "sales_order"
    __table_args__ = (
        UniqueConstraint("so_number", "legal_entity_id", name="uq_sales_order_number_legal_entity"),
        CheckConstraint("so_number IS NOT NULL AND so_number != ''", name="ck_so_number"),
        CheckConstraint("customer_id IS NOT NULL", name="ck_so_customer"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partially_shipped', 'fully_shipped', 'cancelled', 'closed')",
            name="ck_so_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_so_total_nonneg"),
        CheckConstraint("shipped_amount >= 0", name="ck_so_shipped_nonneg"),
        CheckConstraint("invoiced_amount >= 0", name="ck_so_invoiced_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_so_paid_nonneg"),
        Index("idx_so_number", "so_number"),
        Index("idx_so_customer", "customer_id"),
        Index("idx_so_date", "so_date"),
        Index("idx_so_status", "status"),
        Index("idx_so_legal_entity", "legal_entity_id"),
        Index("idx_so_expected_ship_date", "expected_ship_date"),
        Index("idx_so_approved_by", "approved_by")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Identification
    so_number: Mapped[str] = mapped_column(String(50), nullable=False)
    so_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )

    # Amounts
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    shipped_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    invoiced_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Dates
    expected_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_ship_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="draft")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Approval
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Shipping terms
    shipping_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    incoterm: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Reference
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    customer: Mapped[CustomerTable] = relationship("CustomerTable", back_populates="sales_orders")
    ar_invoices: Mapped[list[ARInvoiceTable]] = relationship(
        "ARInvoiceTable", back_populates="sales_order"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.shipped_amount

    @property
    def is_fully_shipped(self) -> bool:
        return self.status == "fully_shipped" or self.outstanding_amount <= 0

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def days_to_expected_ship(self) -> int | None:
        if self.expected_ship_date:
            delta = (self.expected_ship_date - date.today()).days
            return max(0, delta)
        return None

    @property
    def is_overdue_shipment(self) -> bool:
        if self.expected_ship_date and self.status not in ("fully_shipped", "closed"):
            return date.today() > self.expected_ship_date
        return False

    @property
    def remaining_to_invoice(self) -> Decimal:
        return self.shipped_amount - self.invoiced_amount

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit SO with status {self.status}")
        self.status = "submitted"
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve SO with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def reject(self) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject SO with status {self.status}")
        self.status = "draft"
        self.increment_version()

    def record_shipment(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Shipment amount must be positive")
        new_shipped = self.shipped_amount + amount
        if new_shipped >= self.total_amount:
            self.status = "fully_shipped"
            self.shipped_amount = self.total_amount
        else:
            self.status = "partially_shipped"
            self.shipped_amount = new_shipped
        self.actual_ship_date = date.today()
        self.increment_version()

    def record_invoice(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Invoice amount must be positive")
        self.invoiced_amount += amount
        self.increment_version()

    def record_payment(self, amount: Decimal) -> None:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        self.paid_amount += amount
        self.increment_version()

    def cancel(self) -> None:
        if self.status in ("cancelled", "closed"):
            raise ValueError(f"Cannot cancel SO with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def close(self) -> None:
        if self.status != "fully_shipped":
            raise ValueError(f"Cannot close SO with status {self.status}")
        self.status = "closed"
        self.increment_version()


__all__ = ["SalesOrderTable"]
