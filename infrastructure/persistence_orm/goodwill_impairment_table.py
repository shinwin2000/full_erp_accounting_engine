#!/usr/bin/env python3
"""
Module: goodwill_impairment_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk mencatat impairment test dan impairment loss
               pada goodwill. Setiap impairment test menghasilkan record
               terpisah. Mendukung penelusuran historis dan perhitungan
               cadangan impairment.
Dependencies:
- sqlalchemy, uuid, decimal, datetime
- base_model, LegalEntityMixin, TimestampMixin
Audit: Setiap impairment test dicatat dan tidak dapat dihapus (immutable).
"""

from __future__ import annotations
from uuid import UUID

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin, TimestampMixin


class GoodwillImpairmentTable(Base, TimestampMixin, LegalEntityMixin):
    """Tabel untuk impairment goodwill (PSAK 48 / IFRS 36)."""

    __tablename__ = "goodwill_impairment"
    __table_args__ = (
        CheckConstraint("impairment_loss >= 0", name="ck_goodwill_imp_loss_nonneg"),
        CheckConstraint("recoverable_amount >= 0", name="ck_goodwill_recoverable_nonneg"),
        CheckConstraint(
            "impairment_source IN ('annual_test', 'trigger_based', 'disposal', 'reversal')",
            name="ck_goodwill_imp_source",
        ),
        Index("idx_goodwill_imp_goodwill", "goodwill_id"),
        Index("idx_goodwill_imp_date", "test_date"),
        Index("idx_goodwill_imp_approved_by", "approved_by"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Relasi ke goodwill
    goodwill_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("goodwill.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Data impairment test
    test_date: Mapped[date] = mapped_column(Date, nullable=False)
    test_period: Mapped[str] = mapped_column(String(10), nullable=False)  # 'annual', 'quarterly', 'trigger'
    recoverable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    carrying_amount_before: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    impairment_loss: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    carrying_amount_after: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # Metode perhitungan recoverable amount
    valuation_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default="fair_value_less_cost"
    )  # 'fair_value_less_cost', 'value_in_use'
    discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    growth_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Sumber impairment
    impairment_source: Mapped[str] = mapped_column(String(20), nullable=False, default="annual_test")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Persetujuan dan audit
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================
    goodwill: Mapped[GoodwillTable] = relationship(
        "GoodwillTable", back_populates="impairments"
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def impairment_ratio(self) -> Decimal:
        """Ratio of impairment loss to carrying amount before."""
        if self.carrying_amount_before == 0:
            return Decimal(0)
        return (self.impairment_loss / self.carrying_amount_before) * 100

    @property
    def is_reversal(self) -> bool:
        """Check if this record is a reversal of previous impairment."""
        return self.impairment_source == "reversal"

    @property
    def is_trigger_based(self) -> bool:
        return self.impairment_source == "trigger_based"

    # ========================================================================
    # METHODS
    # ========================================================================
    def approve(self, approved_by: uuid.UUID) -> None:
        """Approve impairment test result."""
        self.approved_by = approved_by
        self.approved_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "goodwill_id": str(self.goodwill_id),
            "test_date": self.test_date.isoformat(),
            "test_period": self.test_period,
            "recoverable_amount": float(self.recoverable_amount),
            "carrying_amount_before": float(self.carrying_amount_before),
            "impairment_loss": float(self.impairment_loss),
            "carrying_amount_after": float(self.carrying_amount_after),
            "valuation_method": self.valuation_method,
            "discount_rate": float(self.discount_rate) if self.discount_rate else None,
            "growth_rate": float(self.growth_rate) if self.growth_rate else None,
            "impairment_source": self.impairment_source,
            "description": self.description,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


__all__ = ["GoodwillImpairmentTable"]