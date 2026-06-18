#!/usr/bin/env python3
"""
Module: intangible_revaluation_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel intangible_revaluation.
               Tabel ini menyimpan history revaluasi aset tidak berwujud (intangible assets),
               sesuai dengan metode revaluasi yang diizinkan oleh PSAK/IFRS.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class IntangibleRevaluationTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "intangible_revaluation"
    __table_args__ = (
        CheckConstraint("revaluation_date IS NOT NULL", name="ck_intangible_reval_date"),
        CheckConstraint("old_carrying_amount >= 0", name="ck_intangible_reval_old_carrying_nonneg"),
        CheckConstraint("new_carrying_amount >= 0", name="ck_intangible_reval_new_carrying_nonneg"),
        CheckConstraint("surplus_deficit IS NOT NULL", name="ck_intangible_reval_surplus"),
        Index("idx_intangible_reval_asset", "asset_id"),
        Index("idx_intangible_reval_date", "revaluation_date")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("intangible_asset.id"), nullable=False)
    revaluation_date: Mapped[date] = mapped_column(Date, nullable=False)

    old_acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    old_accumulated_amortization: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    old_impairment_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    old_carrying_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)

    new_acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_accumulated_amortization: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_impairment_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    new_carrying_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)

    surplus_deficit: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Relationship – string reference
    asset: Mapped[IntangibleAssetTable] = relationship(
        "IntangibleAssetTable", back_populates="revaluations"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "revaluation_date": self.revaluation_date.isoformat(),
            "old_acquisition_cost": float(self.old_acquisition_cost),
            "old_accumulated_amortization": float(self.old_accumulated_amortization),
            "old_impairment_loss": float(self.old_impairment_loss),
            "old_carrying_amount": float(self.old_carrying_amount),
            "new_acquisition_cost": float(self.new_acquisition_cost),
            "new_accumulated_amortization": float(self.new_accumulated_amortization),
            "new_impairment_loss": float(self.new_impairment_loss),
            "new_carrying_amount": float(self.new_carrying_amount),
            "surplus_deficit": float(self.surplus_deficit),
            "currency": self.currency,
            "reason": self.reason,
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["IntangibleRevaluationTable"]
