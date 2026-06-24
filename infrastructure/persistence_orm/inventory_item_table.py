#!/usr/bin/env python3
"""
Module: inventory_item_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Mendefinisikan model SQLAlchemy untuk tabel inventory_item.
               Tabel ini menyimpan data master item/barang, termasuk kode item,
               nama, unit of measure, harga standar, metode valuasi, stok saat ini,
               dan reorder point. Digunakan oleh modul Inventory untuk tracking
               stok dan valuation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from infrastructure.persistence_orm.base_model import (
    Base,
    LegalEntityMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
)

if TYPE_CHECKING:
    from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
    from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
    from infrastructure.persistence_orm.warehouse_table import WarehouseTable


class InventoryItemTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """
    Model untuk tabel inventory_item.
    """

    __tablename__ = "inventory_item"
    __table_args__ = (
        UniqueConstraint(
            "item_code", "legal_entity_id", name="uq_inventory_item_code_legal_entity"
        ),
        CheckConstraint("item_code IS NOT NULL AND item_code != ''", name="ck_inventory_item_code"),
        CheckConstraint("item_name IS NOT NULL AND item_name != ''", name="ck_inventory_item_name"),
        CheckConstraint(
            "item_type IN ('raw_material', 'work_in_process', 'finished_good', 'trading')",
            name="ck_inventory_item_type",
        ),
        CheckConstraint(
            "unit_of_measure IS NOT NULL AND unit_of_measure != ''", name="ck_inventory_item_uom"
        ),
        CheckConstraint(
            "valuation_method IN ('FIFO', 'LIFO', 'AVERAGE', 'STANDARD')",
            name="ck_inventory_item_valuation",
        ),
        CheckConstraint("current_stock >= 0", name="ck_inventory_item_stock_nonneg"),
        CheckConstraint("reorder_point >= 0", name="ck_inventory_item_reorder_nonneg"),
        CheckConstraint("standard_cost >= 0", name="ck_inventory_item_std_cost_nonneg"),
        CheckConstraint("selling_price >= 0", name="ck_inventory_item_selling_price_nonneg"),
        Index("idx_inventory_item_code", "item_code"),
        Index("idx_inventory_item_name", "item_name"),
        Index("idx_inventory_item_type", "item_type"),
        Index("idx_inventory_item_legal_entity", "legal_entity_id"),
        Index("idx_inventory_item_warehouse", "warehouse_id"),
        Index("idx_inventory_item_valuation", "valuation_method"),
        Index("idx_inventory_item_stock_status", "current_stock", "reorder_point"),
        Index("idx_inventory_item_is_active", "is_active"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic identification
    item_code: Mapped[str] = mapped_column(String(30), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="trading")
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")

    # Classification
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Reorder and stock management
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    max_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    # Costing
    standard_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    last_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    valuation_method: Mapped[str] = mapped_column(String(10), nullable=False, default="FIFO")

    # Pricing
    selling_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # Stock (denormalized)
    current_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # Tax
    tax_rate_purchase: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=11)
    tax_rate_sales: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=11)

    # Warehouse (foreign key with schema)
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("warehouse.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Additional info
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # JSON field untuk menyimpan data tambahan (dulu bernama 'metadata', sekarang 'extra_data' untuk menghindari reserved attribute)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={})

    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS (menggunakan backref agar child tidak perlu referensi)
    # ========================================================================

    movements: Mapped[list[InventoryMovementTable]] = relationship(
        "InventoryMovementTable",
        backref="item",
        cascade="all, delete-orphan",
    )

    fifo_layers: Mapped[list[InventoryFIFOLayerTable]] = relationship(
        "InventoryFIFOLayerTable",
        backref="item",
        cascade="all, delete-orphan",
    )

    warehouse: Mapped[WarehouseTable | None] = relationship(
        "WarehouseTable",
        back_populates="items",
        foreign_keys=[warehouse_id],
    )

    # ========================================================================
    # PROPERTIES
    # ========================================================================

    @property
    def is_low_stock(self) -> bool:
        return self.current_stock <= self.reorder_point

    @property
    def is_out_of_stock(self) -> bool:
        return self.current_stock <= 0

    @property
    def stock_value(self) -> Decimal:
        return self.current_stock * self.average_cost

    @property
    def total_value(self) -> Decimal:
        return self.stock_value

    # ========================================================================
    # METHODS
    # ========================================================================

    def update_stock(
        self,
        quantity_delta: Decimal,
        new_quantity: Decimal,
        new_average_cost: Decimal | None = None,
    ) -> None:
        self.current_stock = new_quantity
        if new_average_cost is not None:
            self.average_cost = new_average_cost
        self.last_cost = new_average_cost if new_average_cost else self.last_cost
        self.increment_version()

    def update_standard_cost(self, new_standard_cost: Decimal, effective_date: str) -> None:
        old = self.standard_cost
        self.standard_cost = new_standard_cost
        if not self.extra_data:
            self.extra_data = {}
        if "cost_history" not in self.extra_data:
            self.extra_data["cost_history"] = []
        self.extra_data["cost_history"].append(
            {"date": effective_date, "old_cost": float(old), "new_cost": float(new_standard_cost)}
        )
        self.increment_version()

    def activate(self) -> None:
        self.is_active = True
        self.increment_version()

    def deactivate(self) -> None:
        self.is_active = False
        self.increment_version()


__all__ = ["InventoryItemTable"]
