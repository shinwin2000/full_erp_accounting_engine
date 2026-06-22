#!/usr/bin/env python3
"""
Module: fiscal_period_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel fiscal_period.
               Tabel ini menyimpan periode akuntansi (fiscal periods) untuk setiap
               legal entity. Setiap periode memiliki tahun fiskal, bulan/kuartal,
               tanggal mulai dan akhir, serta status (open/closed). Digunakan untuk
               period closing dan validasi tanggal jurnal.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column, relationship)
- sqlalchemy.dialects.postgresql (UUID)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin)
Audit: Setiap perubahan status periode (open/close) dicatat di event store.
       Periode yang sudah closed tidak dapat menerima jurnal baru.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class FiscalPeriodTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel fiscal_period.
    """

    __tablename__ = "fiscal_period"
    __table_args__ = (
        UniqueConstraint(
            "legal_entity_id", "fiscal_year", "period_number", name="uq_fiscal_period_year_period"
        ),
        CheckConstraint("period_number BETWEEN 1 AND 13", name="ck_fiscal_period_number"),
        CheckConstraint(
            "period_type IN ('month', 'quarter', 'year')", name="ck_fiscal_period_type"
        ),
        CheckConstraint("status IN ('open', 'closed', 'locked')", name="ck_fiscal_period_status"),
        CheckConstraint("start_date <= end_date", name="ck_fiscal_period_dates"),
        Index("idx_fiscal_period_legal_entity", "legal_entity_id"),
        Index("idx_fiscal_period_dates", "start_date", "end_date"),
        Index("idx_fiscal_period_status", "status"),
        Index("idx_fiscal_period_year", "fiscal_year"),
        {"schema": "public", "extend_existing": True},
    )

    # Period identification
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_number: Mapped[int] = mapped_column(Integer, nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False, default="month")

    # Date range
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Period name (e.g., "January 2025", "Q1 2025")
    period_name: Mapped[str] = mapped_column(String(50), nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")

    # Closing details
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Notes
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # Relationship to JournalHeaderTable is REMOVED because there is no
    # foreign key in journal_header referencing fiscal_period.id.
    # To add it later, ensure JournalHeaderTable has a period_id column
    # with ForeignKey("public.fiscal_period.id") and define the relationship
    # there with back_populates="period".
    # ========================================================================

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def is_closed(self) -> bool:
        return self.status == "closed"

    @property
    def is_locked(self) -> bool:
        return self.status == "locked"

    @property
    def quarter_number(self) -> int | None:
        """Get quarter number (1-4) for monthly periods."""
        if self.period_type == "month":
            return (self.period_number - 1) // 3 + 1
        return None

    @property
    def display_name(self) -> str:
        """Return period display name."""
        if self.period_type == "month":
            import calendar

            month_name = calendar.month_name[self.period_number]
            return f"{month_name} {self.fiscal_year}"
        elif self.period_type == "quarter":
            return f"Q{self.period_number} {self.fiscal_year}"
        else:
            return f"FY {self.fiscal_year}"

    @property
    def duration_days(self) -> int:
        """Number of days in this period."""
        delta = self.end_date - self.start_date
        return delta.days + 1

    # ========================================================================
    # METHODS
    # ========================================================================

    def contains_date(self, dt: date) -> bool:
        """Check if date falls within this period."""
        return self.start_date <= dt <= self.end_date

    def close(self, closed_by: uuid.UUID) -> None:
        """Close this fiscal period."""
        if self.status == "closed":
            raise ValueError(f"Period {self.period_name} is already closed")
        self.status = "closed"
        self.closed_by = closed_by
        self.closed_at = datetime.now(UTC)
        self.increment_version()

    def open(self) -> None:
        """Reopen a closed period (requires special permission)."""
        if self.status == "open":
            return
        self.status = "open"
        self.closed_by = None
        self.closed_at = None
        self.increment_version()

    def lock(self, locked_by: uuid.UUID) -> None:
        """Lock period (cannot be reopened without audit)."""
        self.status = "locked"
        self.locked_by = locked_by
        self.locked_at = datetime.now(UTC)
        self.increment_version()

    def can_post_journal(self, journal_date: date) -> bool:
        """Check if a journal can be posted to this period."""
        if not self.contains_date(journal_date):
            return False
        return self.status == "open"


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def generate_fiscal_periods(
    legal_entity_id: uuid.UUID, fiscal_year: int, fiscal_year_start_month: int = 1
) -> list[FiscalPeriodTable]:
    """
    Generate all monthly fiscal periods for a given year.
    """
    from calendar import monthrange
    from datetime import date, timedelta

    periods = []

    # Adjust start month
    start_date = date(fiscal_year, fiscal_year_start_month, 1)

    for month_offset in range(12):
        period_year = fiscal_year
        period_month = fiscal_year_start_month + month_offset
        if period_month > 12:
            period_month -= 12
            period_year += 1

        month_start = date(period_year, period_month, 1)
        last_day = monthrange(period_year, period_month)[1]
        month_end = date(period_year, period_month, last_day)

        period = FiscalPeriodTable(
            id=uuid.uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            period_number=month_offset + 1,
            period_type="month",
            start_date=month_start,
            end_date=month_end,
            period_name=month_start.strftime("%B %Y"),
            status="open",
            created_by=None,
        )
        periods.append(period)

    # Add year-end adjustment period (period 13)
    if fiscal_year_start_month == 1:
        adjustment_start = date(fiscal_year, 12, 31)
    else:
        adjustment_start = date(fiscal_year + 1, fiscal_year_start_month - 1, 1)
    adjustment_end = adjustment_start + timedelta(days=30)
    adjustment_period = FiscalPeriodTable(
        id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=fiscal_year,
        period_number=13,
        period_type="month",
        start_date=adjustment_start,
        end_date=adjustment_end,
        period_name=f"Adjustment Period {fiscal_year}",
        status="open",
        created_by=None,
    )
    periods.append(adjustment_period)

    return periods


FiscalPeriodReadModel = FiscalPeriodTable

__all__ = ["FiscalPeriodReadModel", "FiscalPeriodTable", "generate_fiscal_periods"]
