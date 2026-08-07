#!/usr/bin/env python3
"""
Module: inventory_category_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel master Kategori Barang (hierarkis:
               category -> subcategory lewat self-reference parent_id).
               Dipakai oleh inventory_item.category_id / subcategory_id.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
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


class InventoryCategoryTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Master kategori/sub-kategori barang."""

    __tablename__ = "inventory_category"
    __table_args__ = (
        UniqueConstraint(
            "category_code", "legal_entity_id", name="uq_inventory_category_code_legal_entity"
        ),
        CheckConstraint("category_code IS NOT NULL AND category_code != ''", name="ck_inv_category_code"),
        CheckConstraint("category_name IS NOT NULL AND category_name != ''", name="ck_inv_category_name"),
        Index("idx_inv_category_code", "category_code"),
        Index("idx_inv_category_parent", "parent_id"),
        Index("idx_inv_category_legal_entity", "legal_entity_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    category_code: Mapped[str] = mapped_column(String(30), nullable=False)
    category_name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    children: Mapped[list[InventoryCategoryTable]] = relationship(
        "InventoryCategoryTable",
        backref="parent",
        remote_side=[id],
    )

    items: Mapped[list[InventoryItemTable]] = relationship(
        "InventoryItemTable",
        foreign_keys="[InventoryItemTable.category_id]",
        back_populates="category_ref",
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "category_code": self.category_code,
            "category_name": self.category_name,
            "description": self.description,
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "is_active": self.is_active,
        }


__all__ = ["InventoryCategoryTable"]
