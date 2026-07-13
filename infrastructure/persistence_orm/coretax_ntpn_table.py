#!/usr/bin/env python3
"""
Module: coretax_ntpn_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Coretax NTPN (Nomor Transaksi Penerimaan Negara) table.

Perbaikan presisi:
    - Mengubah float() menjadi str() pada nilai moneter (amount) di to_dict()
      untuk menjaga presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Date, DateTime, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base, TimestampMixin


class CoretaxNTPNTable(Base, TimestampMixin):
    __tablename__ = "coretax_ntpn"
    __table_args__ = (
        Index("idx_coretax_ntpn_npwp", "npwp"),
        Index("idx_coretax_ntpn_payment_date", "payment_date"),
        UniqueConstraint("ntpn", name="uq_coretax_ntpn"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ntpn: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    npwp: Mapped[str] = mapped_column(String(20), nullable=False)
    is_valid: Mapped[bool] = mapped_column(default=False, nullable=False)
    validation_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "ntpn": self.ntpn,
            "amount": str(self.amount),  # ganti float -> str untuk presisi
            "payment_date": self.payment_date.isoformat(),
            "npwp": self.npwp,
            "is_valid": self.is_valid,
            "validation_result": self.validation_result,
            "validated_at": self.validated_at.isoformat(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["CoretaxNTPNTable"]
