#!/usr/bin/env python3
"""
Module: inventory_fifo_layer_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel inventory_fifo_layer.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable


class InventoryFIFOLayerTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    __tablename__ = "inventory_fifo_layer"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_fifo_layer_quantity_positive"),
        CheckConstraint("remaining_quantity >= 0", name="ck_inventory_fifo_layer_remaining_nonneg"),
        CheckConstraint("remaining_quantity <= quantity", name="ck_inventory_fifo_layer_remaining_not_exceed"),
        CheckConstraint("unit_cost >= 0", name="ck_inventory_fifo_layer_unit_cost_nonneg"),
        Index("idx_inventory_fifo_layer_item", "item_id"),
        Index("idx_inventory_fifo_layer_item_remaining", "item_id", "remaining_quantity"),
        Index("idx_inventory_fifo_layer_purchase_date", "purchase_date"),
        Index("idx_inventory_fifo_layer_movement", "movement_id"),
        Index("idx_inventory_fifo_layer_legal_entity", "legal_entity_id"),
        Index("idx_inventory_fifo_layer_remaining_only", "remaining_quantity", "item_id"),
        {"schema": "public", "extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Foreign key ke inventory_item (relasi via backref dari InventoryItemTable)
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.inventory_item.id", ondelete="CASCADE"),
        nullable=False,
    )

    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)

    movement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("public.inventory_movement.id", ondelete="SET NULL"),
        nullable=True,
    )

    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    # Relasi ke movement menggunakan backref agar InventoryMovementTable
    # otomatis mendapat properti 'fifo_layers' tanpa perlu didefinisikan di sana.
    inbound_movement: Mapped[InventoryMovementTable | None] = relationship(
        "InventoryMovementTable",
        foreign_keys=[movement_id],
        backref="fifo_layers",
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================
    @property
    def total_value(self) -> Decimal:
        return self.remaining_quantity * self.unit_cost

    @property
    def is_exhausted(self) -> bool:
        return self.remaining_quantity <= 0

    @property
    def consumption_percentage(self) -> float:
        if self.quantity == 0:
            return 0.0
        consumed = self.quantity - self.remaining_quantity
        return float((consumed / self.quantity) * 100)

    # ========================================================================
    # METHODS
    # ========================================================================
    def consume(self, quantity: Decimal) -> Decimal:
        if quantity <= 0:
            return 0
        if quantity >= self.remaining_quantity:
            consumed = self.remaining_quantity
            self.remaining_quantity = 0
        else:
            consumed = quantity
            self.remaining_quantity -= quantity
        self.increment_version()
        return consumed

    def is_fully_consumed(self) -> bool:
        return self.remaining_quantity <= 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "quantity": float(self.quantity),
            "remaining_quantity": float(self.remaining_quantity),
            "uom": self.uom,
            "unit_cost": float(self.unit_cost),
            "currency": self.currency,
            "purchase_date": self.purchase_date.isoformat(),
            "movement_id": str(self.movement_id) if self.movement_id else None,
            "batch_number": self.batch_number,
            "total_value": float(self.total_value),
            "is_exhausted": self.is_exhausted,
            "consumption_percentage": self.consumption_percentage,
            "legal_entity_id": str(self.legal_entity_id),
        }


__all__ = ["InventoryFIFOLayerTable"]
