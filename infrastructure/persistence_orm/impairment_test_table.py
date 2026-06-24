#!/usr/bin/env python3
"""
Module: impairment_test_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk tabel impairment_test.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable


class ImpairmentTestTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "impairment_test"
    __table_args__ = (
        CheckConstraint("test_date IS NOT NULL", name="ck_impairment_test_date"),
        CheckConstraint("carrying_amount >= 0", name="ck_impairment_carrying_nonneg"),
        CheckConstraint("recoverable_amount >= 0", name="ck_impairment_recoverable_nonneg"),
        CheckConstraint("impairment_loss >= 0", name="ck_impairment_loss_nonneg"),
        Index("idx_impairment_test_asset", "asset_id"),
        Index("idx_impairment_test_date", "test_date"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("fixed_asset.id"), nullable=False
    )
    test_date: Mapped[date] = mapped_column(Date, nullable=False)
    carrying_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    recoverable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    impairment_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    asset: Mapped[FixedAssetTable] = relationship(
        "FixedAssetTable",
        back_populates="impairment_tests",
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "test_date": self.test_date.isoformat(),
            "carrying_amount": float(self.carrying_amount),
            "recoverable_amount": float(self.recoverable_amount),
            "impairment_loss": float(self.impairment_loss),
            "currency": self.currency,
            "reason": self.reason,
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


__all__ = ["ImpairmentTestTable"]
