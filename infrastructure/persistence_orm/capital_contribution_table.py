#!/usr/bin/env python3
"""
Module: capital_contribution_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel capital_contribution.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, SoftDeleteMixin, TimestampMixin


class CapitalContributionTable(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "capital_contribution"
    __table_args__ = (
        UniqueConstraint("contribution_number", name="uq_capital_contribution_number"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contribution_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    contribution_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shareholder_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    shareholder_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contribution_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legal entity reference (mengikuti skema public)
    legal_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "contribution_number": self.contribution_number,
            "contribution_date": self.contribution_date.isoformat(),
            "shareholder_id": str(self.shareholder_id) if self.shareholder_id else None,
            "shareholder_name": self.shareholder_name,
            "contribution_type": self.contribution_type,
            "amount": str(self.amount),
            "currency": self.currency,
            "notes": self.notes,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "legal_entity_id": str(self.legal_entity_id),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }


__all__ = ["CapitalContributionTable"]
