#!/usr/bin/env python3
"""
Module: hedge_effectiveness_test_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk menyimpan hasil uji efektivitas lindung nilai (IAS 39 / IFRS 9).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model (Base, LegalEntityMixin, TimestampMixin)
Audit: Setiap uji efektivitas dicatat.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class HedgeEffectivenessTestTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "hedge_effectiveness_test"
    __table_args__ = (
        Index("idx_hedge_test_instrument", "hedge_instrument_id"),
        Index("idx_hedge_test_date", "test_date"),
        Index("idx_hedge_test_result", "result")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hedge_instrument_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    test_date: Mapped[date] = mapped_column(Date, nullable=False)
    prospective_range_low: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    prospective_range_high: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    retrospective_result: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    result: Mapped[str] = mapped_column(String(10), nullable=False)  # effective, ineffective
    ineffectiveness_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    performed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_effective(self) -> bool:
        return self.result == "effective"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "hedge_instrument_id": str(self.hedge_instrument_id),
            "test_date": self.test_date.isoformat(),
            "prospective_range_low": float(self.prospective_range_low),
            "prospective_range_high": float(self.prospective_range_high),
            "retrospective_result": float(self.retrospective_result),
            "result": self.result,
            "ineffectiveness_amount": float(self.ineffectiveness_amount),
            "notes": self.notes,
            "performed_by": str(self.performed_by) if self.performed_by else None,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["HedgeEffectivenessTestTable"]
