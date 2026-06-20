#!/usr/bin/env python3
"""
Module: purchase_order_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk purchase_order dan purchase_order_line.
Fitur lengkap: event recording, approve, cancel, close, record_receipt, reconstruct.
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

if TYPE_CHECKING:
    from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
    from infrastructure.persistence_orm.goods_receipt_note_table import GoodsReceiptNoteTable
    from infrastructure.persistence_orm.supplier_table import SupplierTable


class PurchaseOrderTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "purchase_order"
    __table_args__ = (
        UniqueConstraint("po_number", "legal_entity_id", name="uq_purchase_order_number_legal_entity"),
        CheckConstraint("po_number IS NOT NULL AND po_number != ''", name="ck_po_number"),
        CheckConstraint("supplier_id IS NOT NULL", name="ck_po_supplier"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partially_received', 'fully_received', 'cancelled', 'closed')",
            name="ck_po_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_po_total_nonneg"),
        CheckConstraint("received_amount >= 0", name="ck_po_received_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_po_paid_nonneg"),
        CheckConstraint("received_amount <= total_amount", name="ck_po_received_not_exceed"),
        Index("idx_po_number", "po_number"),
        Index("idx_po_supplier", "supplier_id"),
        Index("idx_po_date", "po_date"),
        Index("idx_po_status", "status"),
        Index("idx_po_legal_entity", "legal_entity_id"),
        Index("idx_po_expected_date", "expected_delivery_date"),
        Index("idx_po_approved_by", "approved_by"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False)
    po_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.supplier.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    received_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(25), nullable=False, default="draft")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    payment_term_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    incoterm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable",
        back_populates="purchase_orders",
        foreign_keys=[supplier_id],
    )
    goods_receipt_notes: Mapped[list["GoodsReceiptNoteTable"]] = relationship(
        "GoodsReceiptNoteTable",
        back_populates="purchase_order",
        foreign_keys="[GoodsReceiptNoteTable.purchase_order_id]",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list["APInvoiceTable"]] = relationship(
        "APInvoiceTable",
        back_populates="purchase_order",
        foreign_keys="[APInvoiceTable.purchase_order_id]",
        cascade="all, delete-orphan",
    )
    lines: Mapped[list["PurchaseOrderLineTable"]] = relationship(
        "PurchaseOrderLineTable",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLineTable.line_number",
    )

    # =========================================================================
    # EVENT STORING
    # =========================================================================
    _events: list[dict[str, Any]] = []

    def _record_event(self, event_type: str, data: dict[str, Any]) -> None:
        event = {
            "event_type": event_type,
            "aggregate_id": str(self.id),
            "timestamp": datetime.utcnow().isoformat(),
            "data": data,
        }
        self._events.append(event)

    def clear_events(self) -> None:
        self._events.clear()

    def get_events(self) -> list[dict[str, Any]]:
        return self._events.copy()

    @classmethod
    def reconstruct(cls, events: list[dict[str, Any]]) -> PurchaseOrderTable:
        first = events[0]["data"]
        instance = cls(
            id=uuid.UUID(first["id"]),
            po_number=first["po_number"],
            po_date=date.fromisoformat(first["po_date"]),
            supplier_id=uuid.UUID(first["supplier_id"]),
            total_amount=Decimal(first["total_amount"]),
            received_amount=Decimal(first["received_amount"]),
            paid_amount=Decimal(first["paid_amount"]),
            tax_amount=Decimal(first["tax_amount"]),
            discount_amount=Decimal(first["discount_amount"]),
            currency=first["currency"],
            status=first["status"],
        )
        for ev in events[1:]:
            typ = ev["event_type"]
            d = ev["data"]
            if typ == "Submitted":
                instance.submit(record_event=False)
            elif typ == "Approved":
                instance.approve(uuid.UUID(d["approved_by"]), record_event=False)
            elif typ == "ReceiptRecorded":
                instance.record_receipt(Decimal(d["amount"]), record_event=False)
            elif typ == "Cancelled":
                instance.cancel(record_event=False)
            elif typ == "Closed":
                instance.close(record_event=False)
        return instance

    # =========================================================================
    # PROPERTIES
    # =========================================================================
    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.received_amount

    @property
    def is_fully_received(self) -> bool:
        return self.status == "fully_received" or self.outstanding_amount <= 0

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def days_to_expected_delivery(self) -> int | None:
        if self.expected_delivery_date:
            delta = (self.expected_delivery_date - date.today()).days
            return max(0, delta)
        return None

    @property
    def is_overdue_delivery(self) -> bool:
        if self.expected_delivery_date and self.status not in ("fully_received", "closed"):
            return date.today() > self.expected_delivery_date
        return False

    # =========================================================================
    # STATE TRANSITIONS
    # =========================================================================
    def submit(self, record_event: bool = True) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit PO with status {self.status}")
        self.status = "submitted"
        self.increment_version()
        if record_event:
            self._record_event("Submitted", {"previous_status": "draft"})

    def approve(self, approved_by: uuid.UUID, record_event: bool = True) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve PO with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()
        if record_event:
            self._record_event("Approved", {
                "approved_by": str(approved_by),
                "approved_at": self.approved_at.isoformat()
            })

    def reject(self) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject PO with status {self.status}")
        self.status = "draft"
        self.increment_version()
        self._record_event("Rejected", {"new_status": "draft"})

    def record_receipt(self, amount: Decimal, record_event: bool = True) -> None:
        if amount <= 0:
            raise ValueError("Receipt amount must be positive")
        new_received = self.received_amount + amount
        old_status = self.status
        if new_received >= self.total_amount:
            self.status = "fully_received"
            self.received_amount = self.total_amount
        else:
            self.status = "partially_received"
            self.received_amount = new_received
        self.actual_delivery_date = date.today()
        self.increment_version()
        if record_event:
            self._record_event("ReceiptRecorded", {
                "amount": str(amount),
                "old_received": str(self.received_amount - amount),
                "new_received": str(self.received_amount),
                "old_status": old_status,
                "new_status": self.status
            })

    def cancel(self, record_event: bool = True) -> None:
        if self.status in ("cancelled", "closed"):
            raise ValueError(f"Cannot cancel PO with status {self.status}")
        self.status = "cancelled"
        self.increment_version()
        if record_event:
            self._record_event("Cancelled", {"previous_status": self.status})

    def close(self, record_event: bool = True) -> None:
        if self.status != "fully_received":
            raise ValueError(f"Cannot close PO with status {self.status}")
        self.status = "closed"
        self.increment_version()
        if record_event:
            self._record_event("Closed", {"previous_status": "fully_received"})


class PurchaseOrderLineTable(Base, TimestampMixin):
    __tablename__ = "purchase_order_line"
    __table_args__ = (
        UniqueConstraint("po_id", "line_number", name="uq_po_line_number"),
        CheckConstraint("quantity > 0", name="ck_po_line_qty_positive"),
        CheckConstraint("unit_price >= 0", name="ck_po_line_unit_price_nonneg"),
        Index("idx_po_line_po", "po_id"),
        Index("idx_po_line_product", "product_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.purchase_order.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    purchase_order: Mapped["PurchaseOrderTable"] = relationship(
        "PurchaseOrderTable",
        back_populates="lines",
        foreign_keys=[po_id],
    )


__all__ = ["PurchaseOrderLineTable", "PurchaseOrderTable"]