#!/usr/bin/env python3
"""
Module: coretax_faktur_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel coretax_faktur.
               Tabel ini menyimpan data faktur pajak (keluaran dan masukan) yang
               dikirim/diterima dari sistem Coretax DJP. Mencakup data penjual,
               pembeli, DPP, PPN, status approval, dan referensi ke dokumen sumber.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class CoretaxFakturTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "coretax_faktur"
    __table_args__ = (
        UniqueConstraint("faktur_number", name="uq_coretax_faktur_number"),
        CheckConstraint(
            "faktur_number IS NOT NULL AND faktur_number != ''", name="ck_cf_faktur_number"
        ),
        CheckConstraint("faktur_type IN ('keluaran', 'masukan')", name="ck_cf_faktur_type"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'rejected', 'cancelled', 'expired')",
            name="ck_cf_status",
        ),
        CheckConstraint("dpp >= 0", name="ck_cf_dpp_nonneg"),
        CheckConstraint("ppn >= 0", name="ck_cf_ppn_nonneg"),
        CheckConstraint("ppn_bm >= 0", name="ck_cf_ppn_bm_nonneg"),
        Index("idx_cf_faktur_number", "faktur_number"),
        Index("idx_cf_npwp_penjual", "npwp_penjual"),
        Index("idx_cf_npwp_pembeli", "npwp_pembeli"),
        Index("idx_cf_status", "status"),
        Index("idx_cf_faktur_date", "faktur_date"),
        Index("idx_cf_reference", "reference_type", "reference_id"),
        Index("idx_cf_legal_entity", "legal_entity_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    faktur_number: Mapped[str] = mapped_column(String(50), nullable=False)
    nsfp_used: Mapped[str | None] = mapped_column(String(20), nullable=True)
    faktur_type: Mapped[str] = mapped_column(String(10), nullable=False)

    npwp_penjual: Mapped[str] = mapped_column(String(20), nullable=False)
    nama_penjual: Mapped[str] = mapped_column(String(200), nullable=False)
    alamat_penjual: Mapped[str] = mapped_column(Text, nullable=False)

    npwp_pembeli: Mapped[str] = mapped_column(String(20), nullable=False)
    nama_pembeli: Mapped[str] = mapped_column(String(200), nullable=False)
    alamat_pembeli: Mapped[str] = mapped_column(Text, nullable=False)

    faktur_date: Mapped[date] = mapped_column(Date, nullable=False)
    dpp: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    ppn: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    ppn_bm: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    approval_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    approval_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    reference_type: Mapped[str] = mapped_column(String(50), nullable=False, default="invoice")
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    xml_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    lines: Mapped[list[CoretaxFakturLineTable]] = relationship(
        "CoretaxFakturLineTable",
        back_populates="faktur",
        cascade="all, delete-orphan",
        order_by="CoretaxFakturLineTable.line_number",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_keluaran(self) -> bool:
        return self.faktur_type == "keluaran"

    @property
    def is_masukan(self) -> bool:
        return self.faktur_type == "masukan"

    @property
    def is_approved(self) -> bool:
        return self.status == "approved"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def is_submitted(self) -> bool:
        return self.status == "submitted"

    @property
    def is_cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def total_amount(self) -> Decimal:
        return self.dpp + self.ppn + self.ppn_bm

    @property
    def tax_amount_total(self) -> Decimal:
        return self.ppn + self.ppn_bm

    # ========================================================================
    # METHODS
    # ========================================================================

    def submit(self) -> None:
        if self.status != "draft":
            raise ValueError(f"Cannot submit faktur with status {self.status}")
        self.status = "submitted"
        self.increment_version()

    def update_status(
        self,
        new_status: str,
        approval_code: str | None = None,
        approval_date: date | None = None,
        rejection_reason: str | None = None,
    ) -> None:
        self.status = new_status
        if approval_code:
            self.approval_code = approval_code
        if approval_date:
            self.approval_date = approval_date
        if rejection_reason:
            self.rejection_reason = rejection_reason
        self.increment_version()

    def cancel(self) -> None:
        if self.status not in ("draft", "submitted", "approved"):
            raise ValueError(f"Cannot cancel faktur with status {self.status}")
        self.status = "cancelled"
        self.increment_version()

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "faktur_number": self.faktur_number,
            "nsfp_used": self.nsfp_used,
            "faktur_type": self.faktur_type,
            "npwp_penjual": self.npwp_penjual,
            "nama_penjual": self.nama_penjual,
            "alamat_penjual": self.alamat_penjual,
            "npwp_pembeli": self.npwp_pembeli,
            "nama_pembeli": self.nama_pembeli,
            "alamat_pembeli": self.alamat_pembeli,
            "faktur_date": self.faktur_date.isoformat(),
            "dpp": float(self.dpp),
            "ppn": float(self.ppn),
            "ppn_bm": float(self.ppn_bm),
            "currency": self.currency,
            "status": self.status,
            "approval_code": self.approval_code,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
            "rejection_reason": self.rejection_reason,
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "xml_content": self.xml_content,
            "extra_metadata": self.extra_metadata,
            "legal_entity_id": str(self.legal_entity_id),
            "created_by": str(self.created_by) if self.created_by else None,
            "version": self.version,
            "lines": [line.to_dict() for line in self.lines] if self.lines else [],
        }


def generate_faktur_number(legal_entity_code: str, year: int, month: int, sequence: int) -> str:
    """Generate faktur number sesuai format Coretax DJP."""
    return f"{legal_entity_code}.{year}.{month:02d}.{sequence:08d}"


__all__ = ["CoretaxFakturTable", "generate_faktur_number"]
