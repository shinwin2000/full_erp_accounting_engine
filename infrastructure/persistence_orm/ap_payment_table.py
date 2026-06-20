#!/usr/bin/env python3
"""
Module: ap_payment_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ap_payment.
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
    from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
    from infrastructure.persistence_orm.coretax_bupot_table import CoretaxBupotTable
    from infrastructure.persistence_orm.supplier_table import SupplierTable


class APPaymentTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "ap_payment"
    __table_args__ = (
        UniqueConstraint(
            "payment_number", "legal_entity_id", name="uq_ap_payment_number_legal_entity"
        ),
        CheckConstraint(
            "payment_number IS NOT NULL AND payment_number != ''", name="ck_ap_payment_number"
        ),
        CheckConstraint("total_amount >= 0", name="ck_ap_payment_total_nonneg"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'processed', 'cancelled')",
            name="ck_ap_payment_status",
        ),
        CheckConstraint(
            "payment_method IN ('cash', 'transfer', 'giro', 'credit_card')",
            name="ck_ap_payment_method",
        ),
        Index("idx_ap_payment_number", "payment_number"),
        Index("idx_ap_payment_supplier", "supplier_id"),
        Index("idx_ap_payment_date", "payment_date"),
        Index("idx_ap_payment_status", "status"),
        Index("idx_ap_payment_legal_entity", "legal_entity_id"),
        Index("idx_ap_payment_run", "payment_run_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_number: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.supplier.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ap_invoice.id", ondelete="RESTRICT"),
        nullable=False,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    payment_method: Mapped[str] = mapped_column(String(15), nullable=False, default="transfer")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payment_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    supplier: Mapped["SupplierTable"] = relationship(
        "SupplierTable",
        back_populates="ap_payments",
        foreign_keys=[supplier_id],
    )
    invoice: Mapped["APInvoiceTable"] = relationship(
        "APInvoiceTable",
        back_populates="payments",
        foreign_keys=[invoice_id],
    )

    # Relasi ke CoretaxBupotTable - menggunakan kolom payment_id
    bupots: Mapped[list["CoretaxBupotTable"]] = relationship(
        "CoretaxBupotTable",
        back_populates="payment",
        foreign_keys="[CoretaxBupotTable.payment_id]",
        cascade="all, delete-orphan",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_processed(self) -> bool:
        return self.status == "processed"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit payment with status {self.status}")
        self.status = "submitted"
        self.increment_version()

    def approve(self, approved_by: uuid.UUID) -> None:
        if self.status != "submitted":
            raise ValueError(f"Cannot approve payment with status {self.status}")
        self.status = "approved"
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def process(self, bank_reference: str | None = None) -> None:
        if self.status != "approved":
            raise ValueError(f"Cannot process payment with status {self.status}")
        self.status = "processed"
        if bank_reference:
            self.bank_reference = bank_reference
        self.increment_version()

    def cancel(self) -> None:
        if self.status in ("processed", "cancelled"):
            raise ValueError(f"Cannot cancel payment with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "payment_number": self.payment_number,
            "payment_date": self.payment_date.isoformat(),
            "supplier_id": str(self.supplier_id),
            "invoice_id": str(self.invoice_id),
            "total_amount": float(self.total_amount),
            "currency": self.currency,
            "payment_method": self.payment_method,
            "status": self.status,
            "reference_number": self.reference_number,
            "bank_reference": self.bank_reference,
            "payment_run_id": str(self.payment_run_id) if self.payment_run_id else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


APPaymentReadModel = APPaymentTable

__all__ = ["APPaymentReadModel", "APPaymentTable"]