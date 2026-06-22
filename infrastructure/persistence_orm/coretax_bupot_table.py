#!/usr/bin/env python3
"""
Module: coretax_bupot_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Tabel untuk Bukti Potong (e-Bupot) PPh 21/23/26/4(2) terintegrasi dengan Coretax DJP.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.ap_invoice_table import APInvoiceTable
    from infrastructure.persistence_orm.ap_payment_table import APPaymentTable
    from infrastructure.persistence_orm.ar_invoice_table import ARInvoiceTable


class BupotType(str, enum.Enum):
    PPH21 = "PPH21"
    PPH23 = "PPH23"
    PPH26 = "PPH26"
    PPH4_AYAT2 = "PPH4_AYAT2"
    PPH_FINAL_LAIN = "PPH_FINAL_LAIN"


class BupotStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class CoretaxBupotTable(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "coretax_bupot"
    __table_args__ = (
        Index("ix_coretax_bupot_npwp_period", "taxpayer_npwp", "tax_period_year", "tax_period_month"),
        Index("ix_coretax_bupot_status_type", "status", "bupot_type"),
        CheckConstraint("tax_rate >= 0 AND tax_rate <= 100", name="ck_bupot_tax_rate"),
        CheckConstraint("tax_amount >= 0", name="ck_bupot_tax_amount"),
        UniqueConstraint("bupot_number", name="uq_bupot_number"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    bupot_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    bupot_type: Mapped[BupotType] = mapped_column(Enum(BupotType), nullable=False, index=True)
    status: Mapped[BupotStatus] = mapped_column(
        Enum(BupotStatus), default=BupotStatus.DRAFT, nullable=False
    )

    taxpayer_npwp: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    taxpayer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    taxpayer_address: Mapped[str | None] = mapped_column(Text)

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    tax_period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    tax_period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    withholding_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))

    tax_object_description: Mapped[str | None] = mapped_column(Text)
    reference_document_number: Mapped[str | None] = mapped_column(String(100))
    reference_document_date: Mapped[date | None] = mapped_column(Date)

    coretax_submission_id: Mapped[str | None] = mapped_column(String(100))
    coretax_status_code: Mapped[str | None] = mapped_column(String(20))
    coretax_status_description: Mapped[str | None] = mapped_column(Text)
    coretax_response_raw: Mapped[dict | None] = mapped_column(JSONB)
    coretax_submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    coretax_approved_at: Mapped[datetime | None] = mapped_column(DateTime)

    void_reason: Mapped[str | None] = mapped_column(Text)

    # Foreign key ke IAMUser (hanya kolom, tanpa relasi untuk menghindari error mapper)
    void_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.iam_user.id", ondelete="SET NULL"),
        nullable=True,
    )
    void_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Foreign keys dengan skema public
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ar_invoice.id", ondelete="SET NULL"),
        nullable=True,
    )
    purchase_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ap_invoice.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.ap_payment.id", ondelete="SET NULL"),
        nullable=True,
    )

    # =========================================================================
    # RELATIONSHIPS
    # =========================================================================

    # Relasi ke AR Invoice (back_populates="bupots" sudah ditambahkan di ARInvoiceTable)
    invoice: Mapped[ARInvoiceTable | None] = relationship(
        "ARInvoiceTable",
        foreign_keys=[invoice_id],
        back_populates="bupots",
    )

    # Relasi ke AP Invoice (back_populates="bupots" sudah ditambahkan di APInvoiceTable)
    purchase_invoice: Mapped[APInvoiceTable | None] = relationship(
        "APInvoiceTable",
        foreign_keys=[purchase_invoice_id],
        back_populates="bupots",
    )

    # Relasi ke AP Payment (back_populates="bupots" sudah ditambahkan di APPaymentTable)
    payment: Mapped[APPaymentTable | None] = relationship(
        "APPaymentTable",
        foreign_keys=[payment_id],
        back_populates="bupots",
    )

    # =========================================================================
    # RELASI void_by_user DIHAPUS untuk menghindari error mapper
    # Akses user void melalui query terpisah atau tambahkan relasi nanti
    # jika IAMUserTable sudah terdefinisi dengan baik.
    # =========================================================================

    # =========================================================================
    # BUSINESS METHODS
    # =========================================================================

    def mark_submitted(self, submission_id: str, response: dict) -> None:
        self.status = BupotStatus.SUBMITTED
        self.coretax_submission_id = submission_id
        self.coretax_response_raw = response
        self.coretax_submitted_at = datetime.utcnow()
        if hasattr(self, "increment_version"):
            self.increment_version()

    def mark_approved(self, response: dict) -> None:
        self.status = BupotStatus.APPROVED
        self.coretax_response_raw = response
        self.coretax_approved_at = datetime.utcnow()
        if hasattr(self, "increment_version"):
            self.increment_version()

    def mark_rejected(self, reason: str, response: dict) -> None:
        self.status = BupotStatus.REJECTED
        self.coretax_status_description = reason
        self.coretax_response_raw = response
        if hasattr(self, "increment_version"):
            self.increment_version()

    def void(self, reason: str, user_id: uuid.UUID) -> None:
        self.status = BupotStatus.VOID
        self.void_reason = reason
        self.void_by = user_id
        self.void_at = datetime.utcnow()
        if hasattr(self, "increment_version"):
            self.increment_version()

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "bupot_number": self.bupot_number,
            "bupot_type": self.bupot_type.value,
            "status": self.status.value,
            "taxpayer_npwp": self.taxpayer_npwp,
            "taxpayer_name": self.taxpayer_name,
            "taxpayer_address": self.taxpayer_address,
            "transaction_date": self.transaction_date.isoformat(),
            "tax_period_month": self.tax_period_month,
            "tax_period_year": self.tax_period_year,
            "gross_amount": float(self.gross_amount),
            "tax_rate": float(self.tax_rate),
            "tax_amount": float(self.tax_amount),
            "withholding_amount": float(self.withholding_amount) if self.withholding_amount else None,
            "tax_object_description": self.tax_object_description,
            "reference_document_number": self.reference_document_number,
            "reference_document_date": self.reference_document_date.isoformat() if self.reference_document_date else None,
            "coretax_submission_id": self.coretax_submission_id,
            "coretax_status_code": self.coretax_status_code,
            "coretax_status_description": self.coretax_status_description,
            "coretax_response_raw": self.coretax_response_raw,
            "coretax_submitted_at": self.coretax_submitted_at.isoformat() if self.coretax_submitted_at else None,
            "coretax_approved_at": self.coretax_approved_at.isoformat() if self.coretax_approved_at else None,
            "void_reason": self.void_reason,
            "void_by": str(self.void_by) if self.void_by else None,
            "void_at": self.void_at.isoformat() if self.void_at else None,
            "invoice_id": str(self.invoice_id) if self.invoice_id else None,
            "purchase_invoice_id": str(self.purchase_invoice_id) if self.purchase_invoice_id else None,
            "payment_id": str(self.payment_id) if self.payment_id else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<CoretaxBupot {self.bupot_number} ({self.bupot_type.value})>"


__all__ = ["BupotStatus", "BupotType", "CoretaxBupotTable"]
