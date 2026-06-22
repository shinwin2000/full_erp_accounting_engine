#!/usr/bin/env python3
"""
Module: disposal_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel disposal.
               Tabel ini menyimpan data penghentian aset tetap (penjualan, scrap, hibah).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
)


class DisposalTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "disposal"
    __table_args__ = (
        CheckConstraint("disposal_date IS NOT NULL", name="ck_disposal_date"),
        CheckConstraint("disposal_proceeds >= 0", name="ck_disposal_proceeds_nonneg"),
        CheckConstraint("disposal_cost >= 0", name="ck_disposal_cost_nonneg"),
        CheckConstraint("nbv_at_disposal >= 0", name="ck_disposal_nbv_nonneg"),
        Index("idx_disposal_asset", "asset_id"),
        Index("idx_disposal_date", "disposal_date"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.fixed_asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    disposal_date: Mapped[date] = mapped_column(Date, nullable=False)
    disposal_proceeds: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    disposal_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    net_proceeds: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    nbv_at_disposal: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    gain_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    buyer_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIP - menggunakan backref agar FixedAssetTable otomatis mendapat 'disposals'
    # =========================================================================
    asset: Mapped[FixedAssetTable] = relationship(
        "FixedAssetTable",
        backref="disposals",
        foreign_keys=[asset_id],
    )


__all__ = ["DisposalTable"]
