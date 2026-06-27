#!/usr/bin/env python3
"""
Module: ap_invoice_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ap_invoice.
Fitur lengkap: event recording, credit note, write off, reconstruct dari event.
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
    from infrastructure.persistence_orm.ap_credit_note_table import APCreditNoteTable
    from infrastructure.persistence_orm.ap_invoice_line_table import APInvoiceLineTable
    from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
    from infrastructure.persistence_orm.coretax_bupot_table import CoretaxBupotTable
    from infrastructure.persistence_orm.goods_receipt_note_table import GoodsReceiptNoteTable
    from infrastructure.persistence_orm.purchase_order_table import PurchaseOrderTable
    from infrastructure.persistence_orm.supplier_table import SupplierTable


class APInvoiceTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "ap_invoice"
    __table_args__ = (
        UniqueConstraint("invoice_number", "legal_entity_id", name="uq_ap_invoice_number_legal_entity"),
        CheckConstraint("invoice_number IS NOT NULL AND invoice_number != ''", name="ck_ap_invoice_number"),
        CheckConstraint("invoice_number_vendor IS NOT NULL AND invoice_number_vendor != ''", name="ck_ap_invoice_vendor_number"),
        CheckConstraint("total_amount >= 0", name="ck_ap_invoice_total_nonneg"),
        CheckConstraint("paid_amount >= 0", name="ck_ap_invoice_paid_nonneg"),
        CheckConstraint("paid_amount <= total_amount", name="ck_ap_invoice_paid_not_exceed"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'partially_paid', 'paid', 'cancelled', 'written_off')",
            name="ck_ap_invoice_status",
        ),
        CheckConstraint(
            "three_way_match_status IN ('pending', 'match', 'mismatch', 'not_applicable')",
            name="ck_ap_invoice_3way_status",
        ),
        Index("idx_ap_invoice_number", "invoice_number"),
        Index("idx_ap_invoice_vendor", "vendor_id"),
        Index("idx_ap_invoice_date", "invoice_date"),
        Index("idx_ap_invoice_due_date", "due_date"),
        Index("idx_ap_invoice_status", "status"),
        Index("idx_ap_invoice_legal_entity", "legal_entity_id"),
        Index("idx_ap_invoice_po", "purchase_order_id"),
        Index("idx_ap_invoice_grn", "goods_receipt_note_id"),
        Index("idx_ap_invoice_3way_status", "three_way_match_status"),
        Index("idx_ap_invoice_vendor_number", "invoice_number_vendor"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_number_vendor: Mapped[str] = mapped_column(String(50), nullable=False)

    # Foreign key ke supplier (dengan skema public)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="RESTRICT"),
        nullable=False,
    )

    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Foreign keys dengan skema public
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_order.id", ondelete="SET NULL"),
        nullable=True,
    )
    goods_receipt_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipt_note.id", ondelete="SET NULL"),
        nullable=True,
    )

    tax_invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    three_way_match_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    supplier: Mapped[SupplierTable] = relationship(
        "SupplierTable",
        back_populates="ap_invoices",
        foreign_keys=[vendor_id],
    )

    purchase_order: Mapped[PurchaseOrderTable | None] = relationship(
        "PurchaseOrderTable",
        back_populates="invoices",
        foreign_keys=[purchase_order_id],
    )

    goods_receipt_note: Mapped[GoodsReceiptNoteTable | None] = relationship(
        "GoodsReceiptNoteTable",
        back_populates="ap_invoices",
        foreign_keys=[goods_receipt_note_id],
    )

    lines: Mapped[list[APInvoiceLineTable]] = relationship(
        "APInvoiceLineTable",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="APInvoiceLineTable.line_number",
    )

    payments: Mapped[list[APPaymentTable]] = relationship(
        "APPaymentTable",
        back_populates="invoice",
        foreign_keys="[APPaymentTable.invoice_id]",
        cascade="all, delete-orphan",
    )

    credit_notes: Mapped[list[APCreditNoteTable]] = relationship(
        "APCreditNoteTable",
        back_populates="invoice",
        foreign_keys="[APCreditNoteTable.invoice_id]",
        cascade="all, delete-orphan",
    )

    # =========================================================================
    # Bupots (Coretax) � ditambahkan untuk melengkapi back_populates di CoretaxBupotTable
    # =========================================================================
    bupots: Mapped[list[CoretaxBupotTable]] = relationship(
        "CoretaxBupotTable",
        back_populates="purchase_invoice",
        foreign_keys="[CoretaxBupotTable.purchase_invoice_id]",
        cascade="all, delete-orphan",
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
    def reconstruct(cls, events: list[dict[str, Any]]) -> APInvoiceTable:
        instance = cls(
            id=uuid.UUID(events[0]["data"]["id"]) if events else uuid.uuid4(),
            invoice_number=events[0]["data"]["invoice_number"],
            invoice_date=date.fromisoformat(events[0]["data"]["invoice_date"]),
            due_date=date.fromisoformat(events[0]["data"]["due_date"]),
            invoice_number_vendor=events[0]["data"]["invoice_number_vendor"],
            vendor_id=uuid.UUID(events[0]["data"]["vendor_id"]),
            total_amount=Decimal(events[0]["data"]["total_amount"]),
            paid_amount=Decimal(events[0]["data"]["paid_amount"]),
            tax_amount=Decimal(events[0]["data"]["tax_amount"]),
            discount_amount=Decimal(events[0]["data"]["discount_amount"]),
            currency=events[0]["data"]["currency"],
            status=events[0]["data"]["status"],
            description=events[0]["data"]["description"],
        )
        for ev in events[1:]:
            ev_type = ev["event_type"]
            data = ev["data"]
            if ev_type == "PaymentRecorded":
                instance.record_payment(Decimal(data["amount"]), record_event=False)
            elif ev_type == "CreditNoteApplied":
                instance.apply_credit_note(Decimal(data["amount"]), data["credit_note_id"], record_event=False)
            elif ev_type == "WrittenOff":
                instance.write_off(data["reason"], record_event=False)
            elif ev_type == "StatusChanged":
                instance.status = data["new_status"]
        return instance

    # =========================================================================
    # PROPERTIES
    # =========================================================================

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
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_3way_match(self) -> bool:
        return self.three_way_match_status == "match"

    @property
    def is_3way_mismatch(self) -> bool:
        return self.three_way_match_status == "mismatch"

    @property
    def days_until_due(self) -> int:
        delta = self.due_date - date.today()
        return delta.days

    @property
    def is_overdue(self) -> bool:
        if self.is_paid:
            return False
        return date.today() > self.due_date

    @property
    def payment_percentage(self) -> float:
        if self.total_amount == 0:
            return 100.0
        return float((self.paid_amount / self.total_amount) * 100)

    # =========================================================================
    # STATE TRANSITIONS
    # =========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit invoice with status {self.status}")
        self.status = "submitted"
        self.increment_version()
        self._record_event("Submitted", {"old_status": "draft", "new_status": "submitted"})

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve invoice with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()
        self._record_event("Approved", {"approved_by": str(approved_by), "approved_at": self.approved_at.isoformat()})

    def reject(self) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot reject invoice with status {self.status}")
        self.status = "draft"
        self.increment_version()
        self._record_event("Rejected", {"new_status": "draft"})

    def record_payment(self, amount: Decimal, record_event: bool = True) -> None:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        if self.is_paid:
            raise ValueError("Invoice already paid")
        new_paid = self.paid_amount + amount
        old_status = self.status
        if new_paid >= self.total_amount:
            self.status = "paid"
            self.paid_amount = self.total_amount
        else:
            self.status = "partially_paid"
            self.paid_amount = new_paid
        self.increment_version()
        if record_event:
            self._record_event("PaymentRecorded", {
                "amount": str(amount),
                "old_paid": str(self.paid_amount - amount),
                "new_paid": str(self.paid_amount),
                "old_status": old_status,
                "new_status": self.status
            })

    def apply_credit_note(self, amount: Decimal, credit_note_id: str, record_event: bool = True) -> None:
        if amount <= 0:
            raise ValueError("Credit note amount must be positive")
        if self.is_paid:
            raise ValueError("Cannot apply credit note to paid invoice")
        if amount > self.outstanding_amount:
            raise ValueError("Credit note amount exceeds outstanding amount")
        self.total_amount -= amount
        if self.paid_amount > self.total_amount:
            self.paid_amount = self.total_amount
        if self.paid_amount >= self.total_amount:
            self.status = "paid"
        elif self.paid_amount > 0:
            self.status = "partially_paid"
        self.increment_version()
        if record_event:
            self._record_event("CreditNoteApplied", {
                "credit_note_id": credit_note_id,
                "amount": str(amount),
                "new_total": str(self.total_amount)
            })

    def write_off(self, reason: str, record_event: bool = True) -> None:
        if self.is_paid:
            raise ValueError("Cannot write off a paid invoice")
        if self.status == "cancelled":
            raise ValueError("Cannot write off cancelled invoice")
        remaining = self.outstanding_amount
        if remaining > 0:
            self.paid_amount = self.total_amount
        self.status = "written_off"
        self.increment_version()
        if record_event:
            self._record_event("WrittenOff", {"reason": reason, "written_off_amount": str(remaining)})

    def cancel(self) -> None:
        if self.is_paid:
            raise ValueError("Cannot cancel paid invoice")
        if self.status in ("paid", "cancelled", "written_off"):
            raise ValueError(f"Cannot cancel invoice with status {self.status}")
        self.status = "cancelled"
        self.increment_version()
        self._record_event("Cancelled", {"previous_status": self.status})

    def set_3way_match_status(self, status: str) -> None:
        allowed = ("pending", "match", "mismatch", "not_applicable")
        if status not in allowed:
            raise ValueError(f"Invalid 3-way match status: {status}")
        self.three_way_match_status = status
        self.increment_version()
        self._record_event("3WayMatchStatusChanged", {"new_status": status})

    def link_to_payment_run(self, payment_run_id: uuid.UUID) -> None:
        self.payment_run_id = payment_run_id
        self.increment_version()
        self._record_event("LinkedToPaymentRun", {"payment_run_id": str(payment_run_id)})


APInvoiceReadModel = APInvoiceTable

__all__ = ["APInvoiceReadModel", "APInvoiceTable"]
