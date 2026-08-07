#!/usr/bin/env python3
"""
Module: inventory_serial_number_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel inventory_serial_number,
               dipakai bila inventory_item.serial_required = True.
"""

from __future__ import annotations

import uuid
from datetime import date as date_
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
    from infrastructure.persistence_orm.warehouse_table import WarehouseTable


class InventorySerialNumberTable(Base, TimestampMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "inventory_serial_number"
    __table_args__ = (
        UniqueConstraint("item_id", "serial_number", name="uq_inventory_serial_item_number"),
        CheckConstraint("serial_number IS NOT NULL AND serial_number != ''", name="ck_inventory_serial_number"),
        CheckConstraint(
            "status IN ('in_stock', 'reserved', 'sold', 'returned', 'scrapped')",
            name="ck_inventory_serial_status",
        ),
        Index("idx_inventory_serial_item", "item_id"),
        Index("idx_inventory_serial_number", "serial_number"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True
    )
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_stock")
    warranty_start_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    warranty_end_date: Mapped[date_ | None] = mapped_column(Date, nullable=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sold_at: Mapped[date_ | None] = mapped_column(Date, nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    item: Mapped[InventoryItemTable] = relationship("InventoryItemTable", back_populates="serial_numbers")
    warehouse: Mapped[WarehouseTable | None] = relationship("WarehouseTable")

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "serial_number": self.serial_number,
            "status": self.status,
            "warranty_start_date": self.warranty_start_date.isoformat() if self.warranty_start_date else None,
            "warranty_end_date": self.warranty_end_date.isoformat() if self.warranty_end_date else None,
        }


__all__ = ["InventorySerialNumberTable"]
