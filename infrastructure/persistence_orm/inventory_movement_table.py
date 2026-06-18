#!/usr/bin/env python3
"""
Module: inventory_movement_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel inventory_movement.
               Tabel ini menyimpan setiap pergerakan stok (in/out/adjustment/transfer)
               untuk setiap item. Mencatat quantity, unit cost, total cost, referensi
               transaksi (sales order, purchase order, production order, dll),
               warehouse asal/tujuan, batch number, dan expiry date.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)


class InventoryMovementTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel inventory_movement.
    """

    __tablename__ = "inventory_movement"
    __table_args__ = (
        UniqueConstraint(
            "movement_number", "legal_entity_id", name="uq_inventory_movement_number_legal_entity"
        ),
        CheckConstraint(
            "movement_number IS NOT NULL AND movement_number != ''",
            name="ck_inventory_movement_number",
        ),
        CheckConstraint(
            "movement_type IN ('IN', 'OUT', 'ADJUSTMENT', 'TRANSFER_IN', 'TRANSFER_OUT')",
            name="ck_inventory_movement_type",
        ),
        CheckConstraint("quantity > 0", name="ck_inventory_movement_quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="ck_inventory_movement_unit_cost_nonneg"),
        CheckConstraint("total_cost >= 0", name="ck_inventory_movement_total_cost_nonneg"),
        CheckConstraint(
            "reference_type IS NOT NULL AND reference_type != ''",
            name="ck_inventory_movement_ref_type",
        ),
        Index("idx_inventory_movement_number", "movement_number"),
        Index("idx_inventory_movement_item", "item_id"),
        Index("idx_inventory_movement_type", "movement_type"),
        Index("idx_inventory_movement_date", "movement_date"),
        Index("idx_inventory_movement_warehouse", "warehouse_id"),
        Index("idx_inventory_movement_to_warehouse", "to_warehouse_id"),
        Index("idx_inventory_movement_reference", "reference_type", "reference_id"),
        Index("idx_inventory_movement_batch", "batch_number"),
        Index("idx_inventory_movement_legal_entity", "legal_entity_id")
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Movement identification
    movement_number: Mapped[str] = mapped_column(String(50), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(15), nullable=False)

    # Item reference
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_item.id"), nullable=False
    )

    # Quantities
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False)
    uom: Mapped[str] = mapped_column(String(10), nullable=False)

    # Cost
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Date
    movement_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Reference
    reference_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Warehouse
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse.id"), nullable=False
    )
    to_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse.id"), nullable=True
    )

    # Batch tracking
    batch_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Additional info
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
    # ========================================================================

    from_warehouse: Mapped[WarehouseTable] = relationship(
        "WarehouseTable", back_populates="movements_from",
        foreign_keys="[InventoryMovementTable.warehouse_id]"
    )
    to_warehouse: Mapped[WarehouseTable | None] = relationship(
        "WarehouseTable", back_populates="movements_to",
        foreign_keys="[InventoryMovementTable.to_warehouse_id]"
    )
    item: Mapped[InventoryItemTable] = relationship(
        "InventoryItemTable", back_populates="movements"
    )
    warehouse: Mapped[WarehouseTable] = relationship("WarehouseTable", foreign_keys=[warehouse_id])
    to_warehouse: Mapped[WarehouseTable | None] = relationship(
        "WarehouseTable", foreign_keys=[to_warehouse_id]
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_inbound(self) -> bool:
        return self.movement_type in ("IN", "TRANSFER_IN")

    @property
    def is_outbound(self) -> bool:
        return self.movement_type in ("OUT", "TRANSFER_OUT")

    @property
    def is_adjustment(self) -> bool:
        return self.movement_type == "ADJUSTMENT"

    @property
    def is_transfer(self) -> bool:
        return self.movement_type in ("TRANSFER_IN", "TRANSFER_OUT")

    # ========================================================================
    # METHODS
    # ========================================================================

    def reverse(self, reason: str, reversed_by: uuid.UUID) -> None:
        """Not a typical method, but for completeness."""
        self.increment_version()


__all__ = ["InventoryMovementTable"]
