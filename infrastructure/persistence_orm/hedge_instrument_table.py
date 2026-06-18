#!/usr/bin/env python3
"""
Module: hedge_instrument_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk instrument lindung nilai (derivatif, forward, swap, dll).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model
Audit: Setiap perubahan instrument hedge dicatat.
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


class HedgeInstrumentTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "hedge_instrument"
    __table_args__ = (
        Index("idx_hedge_instrument_code", "instrument_code", "legal_entity_id", unique=True),
        Index("idx_hedge_instrument_status", "status"),
        Index("idx_hedge_instrument_type", "instrument_type"),
        Index("idx_hedge_instrument_maturity", "maturity_date")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instrument_code: Mapped[str] = mapped_column(String(50), nullable=False)
    instrument_type: Mapped[str] = mapped_column(String(30), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(200), nullable=False)
    notional_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    fixed_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    floating_index: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fair_value: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_active_instrument(self) -> bool:
        return self.status == "active"

    def activate(self) -> None:
        if self.status != "inactive":
            self.status = "active"
            self.increment_version()

    def deactivate(self) -> None:
        self.status = "inactive"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "instrument_code": self.instrument_code,
            "instrument_type": self.instrument_type,
            "counterparty": self.counterparty,
            "notional_amount": float(self.notional_amount),
            "currency": self.currency,
            "start_date": self.start_date.isoformat(),
            "maturity_date": self.maturity_date.isoformat(),
            "fixed_rate": float(self.fixed_rate) if self.fixed_rate else None,
            "floating_index": self.floating_index,
            "fair_value": float(self.fair_value),
            "status": self.status,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["HedgeInstrumentTable"]
