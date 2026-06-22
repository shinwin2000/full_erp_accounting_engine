#!/usr/bin/env python3
"""
Module: ar_payment_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel ar_payment.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class ARPaymentTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "ar_payment"
    __table_args__ = (
        UniqueConstraint(
            "payment_number", "legal_entity_id", name="uq_ar_payment_number_legal_entity"
        ),
        CheckConstraint(
            "payment_number IS NOT NULL AND payment_number != ''", name="ck_ar_payment_number"
        ),
        CheckConstraint("amount > 0", name="ck_ar_payment_amount_positive"),
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'cancelled')", name="ck_ar_payment_status"
        ),
        Index("idx_ar_payment_number", "payment_number"),
        Index("idx_ar_payment_invoice", "invoice_id"),
        Index("idx_ar_payment_date", "payment_date"),
        Index("idx_ar_payment_status", "status"),
        Index("idx_ar_payment_legal_entity", "legal_entity_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_number: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ar_invoice.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account_info: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================
    # Link to the invoice – customer is accessible via invoice.customer
    invoice: Mapped[ARInvoiceTable] = relationship(
        "ARInvoiceTable",
        back_populates="payments",
        foreign_keys=[invoice_id],
    )

    # REMOVED: customer relationship – there is no foreign key to CustomerTable.
    # Use payment.invoice.customer to get the customer.

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def is_failed(self) -> bool:
        return self.status == "failed"

    def complete(self) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot complete payment with status {self.status}")
        self.status = "completed"
        self.increment_version()

    def fail(self, reason: str | None = None) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot fail payment with status {self.status}")
        self.status = "failed"
        if reason and self.notes:
            self.notes = f"{self.notes}\nFailure reason: {reason}"
        self.increment_version()

    def cancel(self, reason: str | None = None) -> None:
        if self.status in ("completed", "cancelled"):
            raise ValueError(f"Cannot cancel payment with status {self.status}")
        self.status = "cancelled"
        if reason and self.notes:
            self.notes = f"{self.notes}\nCancellation reason: {reason}"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "payment_number": self.payment_number,
            "payment_date": self.payment_date.isoformat(),
            "invoice_id": str(self.invoice_id),
            "amount": float(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method,
            "reference_number": self.reference_number,
            "bank_account_info": self.bank_account_info,
            "status": self.status,
            "notes": self.notes,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


ARPaymentReadModel = ARPaymentTable

__all__ = ["ARPaymentReadModel", "ARPaymentTable"]
