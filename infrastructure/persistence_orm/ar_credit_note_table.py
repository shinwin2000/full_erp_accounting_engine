#!/usr/bin/env python3
"""
Module: ar_credit_note_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ar_credit_note.
               Tabel ini menyimpan data credit note untuk Account Receivable,
               yaitu pengurangan piutang karena retur penjualan, diskon setelah
               faktur, atau koreksi lainnya. Credit note mengurangi outstanding
               balance invoice terkait.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID, NUMERIC)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap credit note dicatat di event store. Credit note tidak dapat
       dihapus, hanya bisa dibatalkan dengan credit note koreksi.
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
    from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable


class ARCreditNoteTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel ar_credit_note.
    """

    __tablename__ = "ar_credit_note"
    __table_args__ = (
        UniqueConstraint(
            "credit_note_number", "legal_entity_id", name="uq_ar_credit_note_number_legal_entity"
        ),
        CheckConstraint(
            "credit_note_number IS NOT NULL AND credit_note_number != ''",
            name="ck_ar_credit_note_number",
        ),
        CheckConstraint("amount > 0", name="ck_ar_credit_note_amount_positive"),
        CheckConstraint(
            "status IN ('draft', 'active', 'applied', 'cancelled')", name="ck_ar_credit_note_status"
        ),
        Index("idx_ar_credit_note_number", "credit_note_number"),
        Index("idx_ar_credit_note_invoice", "invoice_id"),
        Index("idx_ar_credit_note_date", "credit_note_date"),
        Index("idx_ar_credit_note_status", "status"),
        Index("idx_ar_credit_note_legal_entity", "legal_entity_id"),
        {"schema": "public", "extend_existing": True},
    )

    # Credit Note Identification
    credit_note_number: Mapped[str] = mapped_column(String(50), nullable=False)
    credit_note_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Reference to Invoice Header (with schema)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ar_invoice.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Financials
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Reason and Type
    reason_code: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # return, discount, correction, bad_debt
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    # Approval & Allocation Audit Info
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    invoice: Mapped[ARInvoiceTable] = relationship(
        "ARInvoiceTable",
        foreign_keys=[invoice_id],
        back_populates="credit_notes",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_applied(self) -> bool:
        return self.status == "applied"

    # ========================================================================
    # METHODS
    # ========================================================================

    def apply(self, applied_by: uuid.UUID) -> None:
        """Apply credit note to invoice (reduces outstanding balance)."""
        if self.status != "active":
            raise ValueError(f"Cannot apply credit note with status {self.status}")
        self.status = "applied"
        self.applied_at = datetime.utcnow()
        self.applied_by = applied_by
        self.increment_version()

    def cancel(self, cancelled_by: uuid.UUID) -> None:
        """Cancel credit note."""
        if self.status == "cancelled":
            raise ValueError("Credit note already cancelled")
        self.status = "cancelled"
        self.increment_version()


__all__ = ["ARCreditNoteTable"]
