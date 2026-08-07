#!/usr/bin/env python3
"""
Module: uom_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel master Unit of Measure (UOM/Satuan).
               Dipakai sebagai referensi base_uom / purchase_uom / sales_uom pada
               inventory_item, dan sebagai dasar konversi satuan.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable


class UomTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Master satuan (Unit of Measure), mis. PCS, KG, BOX, dsb."""

    __tablename__ = "uom"
    __table_args__ = (
        UniqueConstraint("uom_code", "legal_entity_id", name="uq_uom_code_legal_entity"),
        CheckConstraint("uom_code IS NOT NULL AND uom_code != ''", name="ck_uom_code"),
        CheckConstraint("uom_name IS NOT NULL AND uom_name != ''", name="ck_uom_name"),
        Index("idx_uom_code", "uom_code"),
        Index("idx_uom_legal_entity", "legal_entity_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    uom_code: Mapped[str] = mapped_column(String(10), nullable=False)
    uom_name: Mapped[str] = mapped_column(String(50), nullable=False)
    uom_category: Mapped[str | None] = mapped_column(String(30), nullable=True)  # weight, volume, length, count, dst.
    is_base_uom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    base_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )  # self-reference ke UOM dasarnya bila is_base_uom=False (FK diberikan lewat migration)
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    items_base: Mapped[list[InventoryItemTable]] = relationship(
        "InventoryItemTable",
        foreign_keys="[InventoryItemTable.base_uom_id]",
        back_populates="base_uom",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "uom_code": self.uom_code,
            "uom_name": self.uom_name,
            "uom_category": self.uom_category,
            "is_base_uom": self.is_base_uom,
            "base_uom_id": str(self.base_uom_id) if self.base_uom_id else None,
            "conversion_factor": str(self.conversion_factor),
            "is_active": self.is_active,
        }


__all__ = ["UomTable"]
