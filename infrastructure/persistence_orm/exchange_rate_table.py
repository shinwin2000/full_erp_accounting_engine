#!/usr/bin/env python3
"""
Module: exchange_rate_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan nilai tukar mata uang (exchange rates).
               Mendukung multiple sources (BI, bank, internal), bid/ask rates,
               validasi tanggal, dan integrasi dengan legal entity.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin, SoftDeleteMixin, VersionMixin
Audit: Setiap perubahan exchange rate dicatat di event store.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Numeric,
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


class ExchangeRateTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel exchange rate (nilai tukar mata uang).
    """

    __tablename__ = "exchange_rate"
    __table_args__ = (
        UniqueConstraint(
            "from_currency", "to_currency", "rate_date", "legal_entity_id",
            name="uq_exchange_rate_currency_date_legal_entity"
        ),
        CheckConstraint(
            "from_currency != to_currency", name="ck_exchange_rate_diff_currency"
        ),
        CheckConstraint("rate > 0", name="ck_exchange_rate_positive"),
        CheckConstraint("bid_rate > 0", name="ck_exchange_bid_positive"),
        CheckConstraint("ask_rate > 0", name="ck_exchange_ask_positive"),
        CheckConstraint(
            "source IN ('bank_indonesia', 'central_bank', 'internal', 'manual', 'api')",
            name="ck_exchange_rate_source"
        ),
        Index("idx_exchange_rate_date", "rate_date"),
        Index("idx_exchange_rate_currency_pair", "from_currency", "to_currency"),
        Index("idx_exchange_rate_legal_entity", "legal_entity_id"),
        Index("idx_exchange_rate_source", "source"),
        Index("idx_exchange_rate_is_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Currency pair
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False)

    # Date of the exchange rate
    rate_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Rate values (mid rate, bid, ask)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)  # mid rate
    bid_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    ask_rate: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)

    # Source of the rate (e.g., Bank Indonesia, internal, etc.)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")

    # Optional metadata
    source_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g., API endpoint
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Flag for active/inactive (if rate is superseded but kept for historical)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    # Approval (for manually entered rates)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def spread(self) -> Decimal:
        """Ask rate minus bid rate."""
        return self.ask_rate - self.bid_rate

    @property
    def spread_percentage(self) -> float:
        """Spread as percentage of mid rate."""
        if self.rate == 0:
            return 0.0
        return float((self.spread / self.rate) * 100)

    @property
    def inverse_rate(self) -> Decimal:
        """Inverse of mid rate (from to_currency to from_currency)."""
        if self.rate == 0:
            return Decimal(0)
        return Decimal(1) / self.rate

    @property
    def is_approved(self) -> bool:
        return self.approved_by is not None

    # ========================================================================
    # METHODS
    # ========================================================================
    def approve(self, approved_by: uuid.UUID) -> None:
        """Approve this exchange rate (for manual rates)."""
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()
        self.increment_version()

    def deactivate(self) -> None:
        """Deactivate this rate (soft delete equivalent)."""
        self.is_active = False
        self.increment_version()

    def convert(self, amount: Decimal, inverse: bool = False) -> Decimal:
        """
        Convert amount using this exchange rate.
        If inverse=True, uses inverse rate (to_currency to from_currency).
        """
        if amount == 0:
            return Decimal(0)
        rate_to_use = self.inverse_rate if inverse else self.rate
        return (amount * rate_to_use).quantize(Decimal("0.01"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate_date": self.rate_date.isoformat(),
            "rate": float(self.rate),
            "bid_rate": float(self.bid_rate),
            "ask_rate": float(self.ask_rate),
            "spread": float(self.spread),
            "spread_percentage": self.spread_percentage,
            "source": self.source,
            "source_identifier": self.source_identifier,
            "notes": self.notes,
            "is_active": self.is_active,
            "is_approved": self.is_approved,
            "legal_entity_id": str(self.legal_entity_id),
            "version": self.version,
        }


__all__ = ["ExchangeRateTable"]
