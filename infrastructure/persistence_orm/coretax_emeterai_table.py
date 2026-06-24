#!/usr/bin/env python3
"""
Module: coretax_emeterai_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Coretax e-Meterai table for electronic stamp duty.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class CoretaxEMeteraiTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "coretax_emeterai"
    __table_args__ = (
        Index("idx_coretax_emeterai_npwp", "npwp"),
        Index("idx_coretax_emeterai_status", "status"),
        UniqueConstraint("meterai_code", name="uq_coretax_emeterai_code"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meterai_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    npwp: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_transaction_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_on_document: Mapped[str | None] = mapped_column(String(200), nullable=True)
    used_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    def mark_used(self, used_by: uuid.UUID, document_id: str) -> None:
        self.status = "used"
        self.used_at = datetime.utcnow()
        self.used_by = used_by
        self.used_on_document = document_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "meterai_code": self.meterai_code,
            "npwp": self.npwp,
            "value": float(self.value),
            "status": self.status,
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else None,
            "purchase_transaction_id": self.purchase_transaction_id,
            "used_at": self.used_at.isoformat() if self.used_at else None,
            "used_on_document": self.used_on_document,
            "used_by": str(self.used_by) if self.used_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["CoretaxEMeteraiTable"]
