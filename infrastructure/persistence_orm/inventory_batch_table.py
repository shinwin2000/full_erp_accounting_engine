#!/usr/bin/env python3
"""
Module: inventory_batch_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel inventory_batch (Batch/Lot),
               dipakai bila inventory_item.batch_required = True.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String, UniqueConstraint
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


class InventoryBatchTable(Base, TimestampMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "inventory_batch"
    __table_args__ = (
        UniqueConstraint("item_id", "batch_number", "warehouse_id", name="uq_inventory_batch_item_number_wh"),
        CheckConstraint("batch_number IS NOT NULL AND batch_number != ''", name="ck_inventory_batch_number"),
        CheckConstraint("quantity >= 0", name="ck_inventory_batch_qty_nonneg"),
        Index("idx_inventory_batch_item", "item_id"),
        Index("idx_inventory_batch_number", "batch_number"),
        Index("idx_inventory_batch_expired_date", "expired_date"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_item.id", ondelete="CASCADE"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True
    )
    batch_number: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    manufacture_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    expired_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    supplier_batch_ref: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")  # active/expired/quarantine/consumed

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    item: Mapped[InventoryItemTable] = relationship("InventoryItemTable", back_populates="batches")
    warehouse: Mapped[WarehouseTable | None] = relationship("WarehouseTable")

    @property
    def is_expired(self) -> bool:
        from datetime import date as _date

        return bool(self.expired_date and self.expired_date < _date.today())

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "batch_number": self.batch_number,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
            "manufacture_date": self.manufacture_date.isoformat() if self.manufacture_date else None,
            "expired_date": self.expired_date.isoformat() if self.expired_date else None,
            "status": self.status,
            "is_expired": self.is_expired,
        }


__all__ = ["InventoryBatchTable"]
