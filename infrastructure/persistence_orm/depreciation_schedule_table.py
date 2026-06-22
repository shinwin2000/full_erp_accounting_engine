#!/usr/bin/env python3
"""
Module: depreciation_schedule_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk jadwal depresiasi aset tetap (Versi Komprehensif).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.fixed_asset_table import FixedAssetTable


class DepreciationScheduleTable(
    Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin
):
    __tablename__ = "depreciation_schedule"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "fiscal_year", "month", name="uq_depreciation_schedule_asset_period"
        ),
        CheckConstraint("depreciation_amount >= 0", name="ck_depreciation_schedule_amount_nonneg"),
        CheckConstraint(
            "accumulated_depreciation >= 0", name="ck_depreciation_schedule_accum_nonneg"
        ),
        CheckConstraint("net_book_value >= 0", name="ck_depreciation_schedule_nbv_nonneg"),
        CheckConstraint(
            "period >= 1 AND period <= 1200", name="ck_depreciation_schedule_period_range"
        ),
        CheckConstraint(
            "fiscal_year >= 2000 AND fiscal_year <= 2100",
            name="ck_depreciation_schedule_year_range",
        ),
        CheckConstraint("month BETWEEN 1 AND 13", name="ck_depreciation_schedule_month_range"),
        CheckConstraint(
            "status IN ('pending', 'posted', 'skipped')", name="ck_depreciation_schedule_status"
        ),
        Index("idx_depreciation_schedule_asset", "asset_id"),
        Index("idx_depreciation_schedule_period", "fiscal_year", "month"),
        Index("idx_depreciation_schedule_status", "status"),
        Index("idx_depreciation_schedule_legal_entity", "legal_entity_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("public.fixed_asset.id"), nullable=False
    )
    period: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)

    depreciation_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    accumulated_depreciation: Mapped[Decimal] = mapped_column(
        Numeric(20, 2), nullable=False, default=0
    )
    net_book_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    journal_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    asset: Mapped[FixedAssetTable] = relationship(
        "FixedAssetTable",
        back_populates="detailed_schedules",
    )

    @property
    def is_posted(self) -> bool:
        return self.status == "posted"

    @property
    def is_pending(self) -> bool:
        return self.status == "pending"

    @property
    def period_display(self) -> str:
        return f"{self.fiscal_year}-{self.month:02d}"

    def mark_posted(self, journal_id: uuid.UUID) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot mark schedule with status {self.status} as posted")
        self.status = "posted"
        self.journal_id = journal_id
        self.posted_at = datetime.utcnow()
        self.increment_version()

    def skip(self, reason: str | None = None) -> None:
        if self.status != "pending":
            raise ValueError(f"Cannot skip schedule with status {self.status}")
        self.status = "skipped"
        if reason:
            self.notes = reason
        self.increment_version()


__all__ = ["DepreciationScheduleTable"]
