#!/usr/bin/env python3
"""
Module: inventory_image_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel inventory_image — menyimpan
               banyak foto/lampiran per item (item.image_url hanya foto utama).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import Base, LegalEntityMixin, TimestampMixin

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable


class InventoryImageTable(Base, TimestampMixin, LegalEntityMixin):
    __tablename__ = "inventory_image"
    __table_args__ = (
        Index("idx_inventory_image_item", "item_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False
    )
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, default="image")  # image / attachment
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    item: Mapped[InventoryItemTable] = relationship("InventoryItemTable", back_populates="images")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "file_url": self.file_url,
            "file_type": self.file_type,
            "file_name": self.file_name,
            "is_primary": self.is_primary,
            "sort_order": self.sort_order,
        }


__all__ = ["InventoryImageTable"]
