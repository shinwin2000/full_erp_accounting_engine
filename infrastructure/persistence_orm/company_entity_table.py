#!/usr/bin/env python3
"""
Module: company_entity_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel company_entity.
               Tabel ini menyimpan data perusahaan (legal entity) termasuk nama,
               NPWP, alamat, dan status.
Dependencies:
- sqlalchemy.orm (Mapped, mapped_column)
- infrastructure.persistence_orm.base_model (Base, TimestampMixin)
Audit: Setiap perubahan data perusahaan dicatat di event store.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence_orm.base_model import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class CompanyEntityTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin):
    __tablename__ = "company_entity"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_entity_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    npwp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    province: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="ID")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "legal_name": self.legal_name,
            "trade_name": self.trade_name,
            "entity_type": self.entity_type,
            "status": self.status,
            "npwp": self.npwp,
            "address": self.address,
            "city": self.city,
            "province": self.province,
            "postal_code": self.postal_code,
            "country": self.country,
            "created_at": self.created_at.isoformat() if hasattr(self, "created_at") else None,
            "updated_at": self.updated_at.isoformat() if hasattr(self, "updated_at") else None,
        }


__all__ = ["CompanyEntityTable"]
