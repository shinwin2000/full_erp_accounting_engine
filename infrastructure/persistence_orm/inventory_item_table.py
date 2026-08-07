#!/usr/bin/env python3
"""
Module: inventory_item_table.py
Layer: Infrastructure (Persistence ORM)
Responsibility: Model SQLAlchemy untuk tabel inventory_item (Master Barang).

Struktur kolom mengikuti spesifikasi ERP/Accounting production-ready:
    1. Identitas Barang
    2. Kategori
    3. Unit of Measure (UOM)
    4. Harga
    5. Pajak
    6. Stock Control
    7. Warehouse
    8. Supplier
    9. Accounting (sinkron ke Chart of Accounts)
    10. Manufacturing (opsional)
    11. Expired Item
    12. Serial Number
    13. Gambar
    14. Status
    15. Audit

Catatan kompatibilitas: kolom lama (category, unit_of_measure, currency_code,
tax_rate_purchase/sales, valuation_method) DIPERTAHANKAN agar data & kode yang
sudah ada tidak patah, dan kolom baru yang lebih terstruktur (category_id,
base_uom_id, inventory_method, purchase_tax_id, dst.) ditambahkan berdampingan.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
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
    from infrastructure.persistence_orm.account_table import AccountTable
    from infrastructure.persistence_orm.inventory_batch_table import InventoryBatchTable
    from infrastructure.persistence_orm.inventory_category_table import InventoryCategoryTable
    from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
    from infrastructure.persistence_orm.inventory_image_table import InventoryImageTable
    from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
    from infrastructure.persistence_orm.inventory_price_history_table import (
        InventoryPriceHistoryTable,
    )
    from infrastructure.persistence_orm.inventory_serial_number_table import (
        InventorySerialNumberTable,
    )
    from infrastructure.persistence_orm.supplier_table import SupplierTable
    from infrastructure.persistence_orm.uom_table import UomTable
    from infrastructure.persistence_orm.warehouse_table import WarehouseTable


class InventoryItemTable(Base, TimestampMixin, SoftDeleteMixin, VersionMixin, LegalEntityMixin):
    """Model untuk tabel inventory_item (Master Item)."""

    __tablename__ = "inventory_item"
    __table_args__ = (
        UniqueConstraint(
            "item_code", "legal_entity_id", name="uq_inventory_item_code_legal_entity"
        ),
        UniqueConstraint("sku", "legal_entity_id", name="uq_inventory_item_sku_legal_entity"),
        UniqueConstraint("barcode", name="uq_inventory_item_barcode"),
        CheckConstraint("item_code IS NOT NULL AND item_code != ''", name="ck_inventory_item_code"),
        CheckConstraint("item_name IS NOT NULL AND item_name != ''", name="ck_inventory_item_name"),
        CheckConstraint(
            "item_type IN ('raw_material', 'work_in_process', 'finished_good', 'trading')",
            name="ck_inventory_item_type",
        ),
        CheckConstraint(
            "inventory_type IN ("
            "'raw_material', 'finished_goods', 'semi_finished', 'service', "
            "'sparepart', 'consumable', 'asset', 'non_inventory')",
            name="ck_inventory_item_inventory_type",
        ),
        CheckConstraint(
            "unit_of_measure IS NOT NULL AND unit_of_measure != ''", name="ck_inventory_item_uom"
        ),
        CheckConstraint(
            "valuation_method IN ('FIFO', 'LIFO', 'AVERAGE', 'STANDARD')",
            name="ck_inventory_item_valuation",
        ),
        CheckConstraint(
            "inventory_method IN ('FIFO', 'LIFO', 'AVERAGE', 'STANDARD')",
            name="ck_inventory_item_inventory_method",
        ),
        CheckConstraint("current_stock >= 0", name="ck_inventory_item_stock_nonneg"),
        CheckConstraint("reorder_point >= 0", name="ck_inventory_item_reorder_nonneg"),
        CheckConstraint("standard_cost >= 0", name="ck_inventory_item_std_cost_nonneg"),
        CheckConstraint("selling_price >= 0", name="ck_inventory_item_selling_price_nonneg"),
        CheckConstraint("conversion_factor > 0", name="ck_inventory_item_conversion_factor_pos"),
        CheckConstraint(
            "minimum_order_qty >= 0", name="ck_inventory_item_min_order_qty_nonneg"
        ),
        Index("idx_inventory_item_code", "item_code"),
        Index("idx_inventory_item_sku", "sku"),
        Index("idx_inventory_item_barcode", "barcode"),
        Index("idx_inventory_item_name", "item_name"),
        Index("idx_inventory_item_type", "item_type"),
        Index("idx_inventory_item_inventory_type", "inventory_type"),
        Index("idx_inventory_item_legal_entity", "legal_entity_id"),
        Index("idx_inventory_item_warehouse", "warehouse_id"),
        Index("idx_inventory_item_valuation", "valuation_method"),
        Index("idx_inventory_item_stock_status", "current_stock", "reorder_point"),
        Index("idx_inventory_item_is_active", "is_active"),
        Index("idx_inventory_item_category", "category_id"),
        Index("idx_inventory_item_supplier", "default_supplier_id"),
        Index("idx_inventory_item_expired_date", "expired_date"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # ========================================================================
    # 1. IDENTITAS BARANG
    # ========================================================================
    item_code: Mapped[str] = mapped_column(String(30), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    part_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    item_alias: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    specification: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    serial_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    batch_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    qr_code: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ========================================================================
    # 2. KATEGORI
    # ========================================================================
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)  # legacy free-text
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True
    )
    subcategory_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inventory_category.id", ondelete="SET NULL"), nullable=True
    )
    item_group: Mapped[str | None] = mapped_column(String(50), nullable=True)
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="trading")  # legacy
    inventory_type: Mapped[str] = mapped_column(String(20), nullable=False, default="finished_goods")

    # ========================================================================
    # 3. UNIT OF MEASURE (UOM)
    # ========================================================================
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")  # legacy base uom
    base_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uom.id", ondelete="SET NULL"), nullable=True
    )
    purchase_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uom.id", ondelete="SET NULL"), nullable=True
    )
    sales_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uom.id", ondelete="SET NULL"), nullable=True
    )
    conversion_factor: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=1)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    length: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    width: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    height: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    # ========================================================================
    # 4. HARGA
    # ========================================================================
    cost_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    standard_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    last_cost: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)  # = last_purchase_price
    selling_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    minimum_selling_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    wholesale_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    retail_price: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    discount_allowed: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="IDR")

    # ========================================================================
    # 5. PAJAK
    # ========================================================================
    tax_rate_purchase: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=11)  # legacy
    tax_rate_sales: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=11)  # legacy
    purchase_tax_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    sales_tax_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tax_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ========================================================================
    # 6. STOCK CONTROL
    # ========================================================================
    current_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    reserved_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    available_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    incoming_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    outgoing_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    minimum_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    min_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # legacy alias
    maximum_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)
    max_stock: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)  # legacy alias
    reorder_level: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)  # legacy alias
    reorder_qty: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)  # legacy alias
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # ========================================================================
    # 7. WAREHOUSE
    # ========================================================================
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse.id", ondelete="SET NULL"), nullable=True
    )  # = default_warehouse_id
    default_bin: Mapped[str | None] = mapped_column(String(30), nullable=True)
    rack: Mapped[str | None] = mapped_column(String(30), nullable=True)
    shelf: Mapped[str | None] = mapped_column(String(30), nullable=True)
    location: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ========================================================================
    # 8. SUPPLIER
    # ========================================================================
    default_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("supplier.id", ondelete="SET NULL"), nullable=True
    )
    supplier_item_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    minimum_order_qty: Mapped[Decimal] = mapped_column(Numeric(20, 2), nullable=False, default=0)

    # ========================================================================
    # 9. ACCOUNTING (sinkron ke Chart of Accounts)
    # ========================================================================
    inventory_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    cogs_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    sales_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    purchase_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    adjustment_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id", ondelete="SET NULL"), nullable=True
    )
    valuation_method: Mapped[str] = mapped_column(String(10), nullable=False, default="FIFO")  # legacy
    inventory_method: Mapped[str] = mapped_column(String(10), nullable=False, default="FIFO")

    # ========================================================================
    # 10. MANUFACTURING (opsional)
    # ========================================================================
    bom_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bom_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    production_time: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    routing_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # 11. EXPIRED ITEM
    # ========================================================================
    expired_tracking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manufacture_date: Mapped[Date | None] = mapped_column(Date, nullable=True)
    expired_date: Mapped[Date | None] = mapped_column(Date, nullable=True)

    # ========================================================================
    # 12. SERIAL NUMBER
    # ========================================================================
    serial_tracking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    warranty_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_tracking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ========================================================================
    # 13. GAMBAR
    # ========================================================================
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ========================================================================
    # 14. STATUS
    # ========================================================================
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # = active
    sellable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    purchasable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stock_item: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_negative_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON field untuk data tambahan yang belum punya kolom khusus
    extra_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default={})

    # ========================================================================
    # 15. AUDIT (created_at/updated_at/deleted_at/version dari mixin)
    # ========================================================================
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # ========================================================================
    # RELATIONSHIPS
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

    batches: Mapped[list[InventoryBatchTable]] = relationship(
        "InventoryBatchTable",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    serial_numbers: Mapped[list[InventorySerialNumberTable]] = relationship(
        "InventorySerialNumberTable",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    price_history: Mapped[list[InventoryPriceHistoryTable]] = relationship(
        "InventoryPriceHistoryTable",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    images: Mapped[list[InventoryImageTable]] = relationship(
        "InventoryImageTable",
        back_populates="item",
        cascade="all, delete-orphan",
    )

    warehouse: Mapped[WarehouseTable | None] = relationship(
        "WarehouseTable",
        back_populates="items",
        foreign_keys=[warehouse_id],
    )

    category_ref: Mapped[InventoryCategoryTable | None] = relationship(
        "InventoryCategoryTable",
        back_populates="items",
        foreign_keys=[category_id],
    )

    base_uom: Mapped[UomTable | None] = relationship(
        "UomTable",
        back_populates="items_base",
        foreign_keys=[base_uom_id],
    )

    default_supplier: Mapped[SupplierTable | None] = relationship(
        "SupplierTable",
        foreign_keys=[default_supplier_id],
    )

    inventory_account: Mapped[AccountTable | None] = relationship(
        "AccountTable", foreign_keys=[inventory_account_id]
    )
    cogs_account: Mapped[AccountTable | None] = relationship(
        "AccountTable", foreign_keys=[cogs_account_id]
    )
    sales_account: Mapped[AccountTable | None] = relationship(
        "AccountTable", foreign_keys=[sales_account_id]
    )
    purchase_account: Mapped[AccountTable | None] = relationship(
        "AccountTable", foreign_keys=[purchase_account_id]
    )
    adjustment_account: Mapped[AccountTable | None] = relationship(
        "AccountTable", foreign_keys=[adjustment_account_id]
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

    @property
    def computed_available_stock(self) -> Decimal:
        return self.current_stock - self.reserved_stock

    # ========================================================================
    # METHODS
    # ========================================================================

    def recompute_available_stock(self) -> None:
        """Sinkronkan kolom available_stock berdasarkan current_stock - reserved_stock."""
        self.available_stock = self.current_stock - self.reserved_stock

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
        self.recompute_available_stock()
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
