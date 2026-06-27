#!/usr/bin/env python3
"""
Module: revaluation_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel revaluation.
               Tabel ini menyimpan history revaluasi aset tetap (fixed asset).
               Mencatat perubahan nilai perolehan, akumulasi penyusutan, dan NBV.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable


class RevaluationTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "revaluation"
    __table_args__ = (
        CheckConstraint("revaluation_date IS NOT NULL", name="ck_revaluation_date"),
        CheckConstraint("old_acquisition_cost >= 0", name="ck_revaluation_old_cost_nonneg"),
        CheckConstraint("new_acquisition_cost >= 0", name="ck_revaluation_new_cost_nonneg"),
        CheckConstraint("old_nbv >= 0", name="ck_revaluation_old_nbv_nonneg"),
        CheckConstraint("new_nbv >= 0", name="ck_revaluation_new_nbv_nonneg"),
        Index("idx_revaluation_asset", "asset_id"),
        Index("idx_revaluation_date", "revaluation_date"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fixed_asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    revaluation_date: Mapped[date] = mapped_column(Date, nullable=False)
    old_acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    old_accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    old_nbv: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_nbv: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    surplus_deficit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # =========================================================================
    # RELATIONSHIPS � menggunakan backref agar FixedAssetTable otomatis mendapat 'revaluations'
    # =========================================================================
    asset: Mapped[FixedAssetTable] = relationship(
        "FixedAssetTable",
        backref="revaluations",
        foreign_keys=[asset_id],
    )

    # =========================================================================
    # SERIALIZATION
    # =========================================================================
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "revaluation_date": self.revaluation_date.isoformat(),
            "old_acquisition_cost": float(self.old_acquisition_cost),
            "new_acquisition_cost": float(self.new_acquisition_cost),
            "old_accumulated_depreciation": float(self.old_accumulated_depreciation),
            "new_accumulated_depreciation": float(self.new_accumulated_depreciation),
            "old_nbv": float(self.old_nbv),
            "new_nbv": float(self.new_nbv),
            "surplus_deficit": float(self.surplus_deficit),
            "currency": self.currency,
            "reason": self.reason,
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["RevaluationTable"]
