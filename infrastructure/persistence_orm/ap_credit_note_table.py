#!/usr/bin/env python3
"""
Module: ap_credit_note_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ap_credit_note.
               Tabel ini menyimpan data credit note untuk Account Payable,
               yaitu pengurangan hutang karena retur pembelian, diskon setelah
               faktur, atau koreksi lainnya. Credit note mengurangi outstanding
               balance invoice terkait.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount) di to_dict()
      untuk menghindari kehilangan presisi dan memenuhi aturan MNY-003.
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


class APCreditNoteTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "ap_credit_note"
    __table_args__ = (
        UniqueConstraint(
            "credit_note_number", "legal_entity_id", name="uq_ap_credit_note_number_legal_entity"
        ),
        CheckConstraint(
            "credit_note_number IS NOT NULL AND credit_note_number != ''",
            name="ck_ap_credit_note_number",
        ),
        CheckConstraint("amount > 0", name="ck_ap_credit_note_amount_positive"),
        CheckConstraint(
            "status IN ('active', 'applied', 'cancelled')", name="ck_ap_credit_note_status"
        ),
        Index("idx_ap_credit_note_number", "credit_note_number"),
        Index("idx_ap_credit_note_invoice", "invoice_id"),
        Index("idx_ap_credit_note_date", "credit_note_date"),
        Index("idx_ap_credit_note_status", "status"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    credit_note_number: Mapped[str] = mapped_column(String(50), nullable=False)
    credit_note_date: Mapped[date] = mapped_column(Date, nullable=False)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ap_invoice.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    invoice: Mapped[APInvoiceTable] = relationship(
        "APInvoiceTable",
        back_populates="credit_notes",
        foreign_keys=[invoice_id],
    )

    # =========================================================================
    # PROPERTIES
    # =========================================================================

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def is_applied(self) -> bool:
        return self.status == "applied"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    # =========================================================================
    # METHODS
    # =========================================================================

    def apply(self, applied_by: uuid.UUID) -> None:
        if self.status != "active":
            raise ValueError(f"Cannot apply credit note with status {self.status}")
        self.status = "applied"
        self.applied_at = datetime.utcnow()
        self.applied_by = applied_by
        self.increment_version()

    def cancel(self, cancelled_by: uuid.UUID) -> None:
        if self.status == "cancelled":
            raise ValueError("Credit note already cancelled")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "credit_note_number": self.credit_note_number,
            "credit_note_date": self.credit_note_date.isoformat(),
            "invoice_id": str(self.invoice_id),
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "currency": self.currency,
            "reason": self.reason,
            "reference_number": self.reference_number,
            "status": self.status,
            "is_active": self.is_active,
            "is_applied": self.is_applied,
            "is_cancelled": self.is_cancelled,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "applied_by": str(self.applied_by) if self.applied_by else None,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["APCreditNoteTable"]