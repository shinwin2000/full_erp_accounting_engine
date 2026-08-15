#!/usr/bin/env python3
"""
Module: currency_master_table.py
Layer: Infrastructure / Persistence ORM
Responsibility: SQLAlchemy ORM model untuk tabel currency_master.
               Daftar mata uang yang bisa dipakai di seluruh aplikasi
               (sebelumnya di-hardcode sebagai Python Enum CurrencyCode
               di fastapi_forex_router.py - lihat migrasi
               b2c3d4e5f6a7_add_fx_booking_rate_and_currency_master.py).
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import Base


class CurrencyMasterTable(Base):
    __tablename__ = "currency_master"
    __table_args__ = ({"extend_existing": True},)

    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(10), nullable=True)
    decimal_places: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "symbol": self.symbol,
            "decimal_places": self.decimal_places,
            "is_active": self.is_active,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


__all__ = ["CurrencyMasterTable"]
