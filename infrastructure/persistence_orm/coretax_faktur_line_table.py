#!/usr/bin/env python3
"""
Module: coretax_faktur_line_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel coretax_faktur_line.
               Tabel ini menyimpan line items dari faktur pajak (keluaran/masukan).

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (unit_price, amount, tax_amount)
      di to_dict() untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
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
    from infrastructure.persistence_orm.coretax_faktur_table import CoretaxFakturTable


class CoretaxFakturLineTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "coretax_faktur_line"
    __table_args__ = (
        CheckConstraint("line_number >= 1", name="ck_cfl_line_number"),
        CheckConstraint("quantity >= 0", name="ck_cfl_quantity_nonneg"),
        CheckConstraint("unit_price >= 0", name="ck_cfl_unit_price_nonneg"),
        CheckConstraint("amount >= 0", name="ck_cfl_amount_nonneg"),
        CheckConstraint("tax_amount >= 0", name="ck_cfl_tax_amount_nonneg"),
        Index("idx_cfl_faktur", "faktur_id"),
        Index("idx_cfl_line_number", "faktur_id", "line_number"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    faktur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("coretax_faktur.id", ondelete="CASCADE"),
        nullable=False,
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    faktur: Mapped[CoretaxFakturTable] = relationship(
        "CoretaxFakturTable",
        back_populates="lines",
        foreign_keys=[faktur_id],
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def total_amount(self) -> Decimal:
        return self.amount + self.tax_amount

    @property
    def ppn_rate(self) -> Decimal:
        if self.amount == 0:
            return Decimal(0)
        return (self.tax_amount / self.amount) * 100

    # ========================================================================
    # METHODS
    # ========================================================================

    def calculate_amount(self) -> None:
        self.amount = self.quantity * self.unit_price
        self.increment_version()

    def set_tax(self, tax_rate: Decimal) -> None:
        self.tax_amount = (self.amount * tax_rate / 100).quantize(Decimal("0.01"))
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "faktur_id": str(self.faktur_id),
            "line_number": self.line_number,
            "description": self.description,
            "quantity": str(self.quantity),      # kuantitas bisa str juga
            "unit_price": str(self.unit_price),  # ganti float -> str
            "amount": str(self.amount),          # ganti float -> str
            "tax_amount": str(self.tax_amount),  # ganti float -> str
            "currency": self.currency,
            "total_amount": str(self.total_amount),  # ganti float -> str
            "ppn_rate": str(self.ppn_rate),      # persentase, juga str untuk konsistensi
        }


__all__ = ["CoretaxFakturLineTable"]