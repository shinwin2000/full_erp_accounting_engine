#!/usr/bin/env python3
"""
Module: amortization_schedule_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk jadwal amortisasi aset tidak berwujud.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin, UUIDMixin


class AmortizationStatus(str, enum.Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    SKIPPED = "SKIPPED"
    ADJUSTED = "ADJUSTED"


class AmortizationScheduleTable(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "amortization_schedule"
    __table_args__ = (
        CheckConstraint("planned_amount >= 0", name="ck_amort_planned_nonneg"),
        CheckConstraint("actual_amount IS NULL OR actual_amount >= 0", name="ck_amort_actual_nonneg"),
        Index("ix_amort_asset_period", "asset_id", "period_date", unique=True),
        Index("ix_amort_status", "status"),
        {"schema": "public"},
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.intangible_asset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_date: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    fiscal_period: Mapped[int] = mapped_column(nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    remaining_carrying_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    status: Mapped[AmortizationStatus] = mapped_column(
        Enum(AmortizationStatus), default=AmortizationStatus.PENDING, nullable=False, index=True
    )
    journal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("public.journal_header.id", ondelete="SET NULL"), nullable=True
    )
    journal_entry_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adjustment_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # =========================================================================
    # RELATIONSHIPS are defined via backrefs on the parent side:
    #   - IntangibleAssetTable.amortization_schedules (backref="asset")
    #   - JournalHeaderTable.amortization_schedules (backref="amortization_schedules")
    # No explicit relationship definitions are needed here.
    # =========================================================================

    def mark_posted(self, actual: Decimal, journal_id: uuid.UUID, journal_number: str) -> None:
        self.actual_amount = actual
        self.journal_id = journal_id
        self.journal_entry_number = journal_number
        self.status = AmortizationStatus.POSTED

    def skip(self, reason: str) -> None:
        self.status = AmortizationStatus.SKIPPED
        self.adjustment_reason = reason

    def adjust(self, new_amount: Decimal, reason: str, journal_id: uuid.UUID, journal_number: str) -> None:
        self.actual_amount = new_amount
        self.adjustment_reason = reason
        self.journal_id = journal_id
        self.journal_entry_number = journal_number
        self.status = AmortizationStatus.ADJUSTED


__all__ = ["AmortizationScheduleTable", "AmortizationStatus"]