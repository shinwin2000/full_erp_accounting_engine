# infrastructure/persistence_orm/goods_receipt_note_table.py
#!/usr/bin/env python3
"""
Module: goods_receipt_note_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk Goods Receipt Note (GRN).
Fitur lengkap: event recording, confirm, cancel, reconstruct.
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
    from infrastructure.persistence_orm.goods_receipt_note_table import GoodsReceiptNoteLineTable
    from infrastructure.persistence_orm.purchase_order_table import PurchaseOrderTable
    from infrastructure.persistence_orm.supplier_table import SupplierTable


class GoodsReceiptNoteTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "goods_receipt_note"
    __table_args__ = (
        UniqueConstraint("grn_number", "legal_entity_id", name="uq_grn_number_legal_entity"),
        CheckConstraint("grn_number IS NOT NULL AND grn_number != ''", name="ck_grn_number"),
        CheckConstraint("supplier_id IS NOT NULL", name="ck_grn_supplier"),
        CheckConstraint("status IN ('draft', 'confirmed', 'cancelled')", name="ck_grn_status"),
        Index("idx_grn_legal_entity", "legal_entity_id"),
        Index("idx_grn_po", "purchase_order_id"),
        Index("idx_grn_number", "grn_number", unique=True),
        Index("idx_grn_date", "receipt_date"),
        Index("idx_grn_status", "status"),
        Index("idx_grn_supplier", "supplier_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grn_number: Mapped[str] = mapped_column(String(50), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("purchase_order.id", ondelete="RESTRICT"),
        nullable=False,
    )
    receipt_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("supplier.id", ondelete="RESTRICT"),
        nullable=False,
    )
    supplier_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=datetime.utcnow
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    supplier: Mapped[SupplierTable] = relationship(
        "SupplierTable",
        back_populates="goods_receipt_notes",
        foreign_keys=[supplier_id],
    )
    purchase_order: Mapped[PurchaseOrderTable] = relationship(
        "PurchaseOrderTable",
        back_populates="goods_receipt_notes",
        foreign_keys=[purchase_order_id],
    )
    ap_invoices: Mapped[list[APInvoiceTable]] = relationship(
        "APInvoiceTable",
        back_populates="goods_receipt_note",
        foreign_keys="[APInvoiceTable.goods_receipt_note_id]",
    )
    lines: Mapped[list[GoodsReceiptNoteLineTable]] = relationship(
        "GoodsReceiptNoteLineTable",
        back_populates="grn",
        cascade="all, delete-orphan",
        order_by="GoodsReceiptNoteLineTable.line_number",
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
    def reconstruct(cls, events: list[dict[str, Any]]) -> GoodsReceiptNoteTable:
        instance = cls(
            id=uuid.UUID(events[0]["data"]["id"]),
            grn_number=events[0]["data"]["grn_number"],
            purchase_order_id=uuid.UUID(events[0]["data"]["purchase_order_id"]),
            receipt_date=date.fromisoformat(events[0]["data"]["receipt_date"]),
            supplier_id=uuid.UUID(events[0]["data"]["supplier_id"]),
            supplier_name=events[0]["data"]["supplier_name"],
            status=events[0]["data"]["status"],
            notes=events[0]["data"].get("notes"),
        )
        for ev in events[1:]:
            if ev["event_type"] == "Confirmed":
                instance.confirm(record_event=False)
            elif ev["event_type"] == "Cancelled":
                instance.cancel(record_event=False)
        return instance

    # =========================================================================
    # BUSINESS METHODS
    # =========================================================================
    def confirm(self, record_event: bool = True) -> None:
        if self.status != "draft":
            raise ValueError(f"Only draft GRN can be confirmed, current status: {self.status}")
        self.status = "confirmed"
        self.increment_version()
        if record_event:
            self._record_event("Confirmed", {"previous_status": "draft"})

    def cancel(self, record_event: bool = True) -> None:
        if self.status == "cancelled":
            raise ValueError("GRN is already cancelled")
        # Boleh cancel dari status confirmed atau draft
        self.status = "cancelled"
        self.increment_version()
        if record_event:
            self._record_event("Cancelled", {"previous_status": self.status})


class GoodsReceiptNoteLineTable(Base, TimestampMixin):
    __tablename__ = "goods_receipt_note_lines"
    __table_args__ = (
        UniqueConstraint("grn_id", "line_number", name="uq_grn_line_number"),
        CheckConstraint("received_quantity > 0", name="ck_grn_line_qty_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_grn_line_unit_cost_nonneg"),
        Index("idx_grn_line_grn", "grn_id"),
        Index("idx_grn_line_po_line", "purchase_order_line_id"),
        Index("idx_grn_line_product", "product_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    grn_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goods_receipt_note.id", ondelete="CASCADE"),
        nullable=False,
    )
    purchase_order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_code: Mapped[str] = mapped_column(String(50), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    grn: Mapped[GoodsReceiptNoteTable] = relationship(
        "GoodsReceiptNoteTable",
        back_populates="lines",
        foreign_keys=[grn_id],
    )


__all__ = ["GoodsReceiptNoteLineTable", "GoodsReceiptNoteTable"]
