#!/usr/bin/env python3
"""
Module: fixed_asset_schedule_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk jadwal depresiasi aset tetap (Versi Standar).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable


class FixedAssetScheduleTable(Base, TimestampMixin):
    __tablename__ = "fixed_asset_schedule"
    __table_args__ = (
        Index("idx_fas_asset", "asset_id"),
        Index("idx_fas_period", "period"),
        Index("idx_fas_status", "posted_to_gl"),
        CheckConstraint("depreciation_amount >= 0", name="ck_fas_amount_nonneg"),
        CheckConstraint("accumulated_depreciation >= 0", name="ck_fas_accum_nonneg"),
        CheckConstraint("net_book_value >= 0", name="ck_fas_nbv_nonneg"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.fixed_asset.id"), nullable=False
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    depreciation_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal(0))
    accumulated_depreciation: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal(0))
    net_book_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal(0))
    posted_to_gl: Mapped[str | None] = mapped_column(String(20), nullable=True)
    journal_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    asset: Mapped["FixedAssetTable"] = relationship(
        "FixedAssetTable",
        back_populates="depreciation_schedule",
    )

    @property
    def is_posted(self) -> bool:
        return self.posted_to_gl == "posted"

    @property
    def is_pending(self) -> bool:
        return self.posted_to_gl == "pending" or self.posted_to_gl is None

    def mark_posted(self, journal_id: uuid.UUID) -> None:
        self.posted_to_gl = "posted"
        self.journal_id = journal_id
        self.version = getattr(self, 'version', 0) + 1

    def mark_failed(self) -> None:
        self.posted_to_gl = "failed"
        self.version = getattr(self, 'version', 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "asset_id": str(self.asset_id),
            "period": self.period,
            "depreciation_amount": str(self.depreciation_amount),
            "accumulated_depreciation": str(self.accumulated_depreciation),
            "net_book_value": str(self.net_book_value),
            "posted_to_gl": self.posted_to_gl,
            "journal_id": str(self.journal_id) if self.journal_id else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# Aliases for backward compatibility
DepreciationScheduleTable = FixedAssetScheduleTable
DepreciationScheduleReadModel = FixedAssetScheduleTable
FixedAssetScheduleReadModel = FixedAssetScheduleTable

__all__ = [
    "FixedAssetScheduleTable",
    "DepreciationScheduleTable",
    "DepreciationScheduleReadModel",
    "FixedAssetScheduleReadModel",
]