#!/usr/bin/env python3
"""
Module: hedged_item_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model untuk item yang dilindung nilai (misal: pinjaman, piutang, forecast transaction).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model
Audit: Setiap perubahan hedged item dicatat.
"""

from __future__ import annotations
from uuid import UUID

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


class HedgedItemTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "hedged_item"
    __table_args__ = (
        Index("idx_hedged_item_instrument", "hedge_instrument_id"),
        Index("idx_hedged_item_type", "item_type"),
        Index("idx_hedged_item_status", "status"),
        Index("idx_hedged_item_period", "start_date", "end_date"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hedge_instrument_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    @property
    def is_active_item(self) -> bool:
        return self.status == "active"

    def activate(self) -> None:
        self.status = "active"
        self.increment_version()

    def deactivate(self) -> None:
        self.status = "inactive"
        self.increment_version()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "hedge_instrument_id": str(self.hedge_instrument_id),
            "item_type": self.item_type,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "description": self.description,
            "amount": float(self.amount),
            "currency": self.currency,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["HedgedItemTable"]