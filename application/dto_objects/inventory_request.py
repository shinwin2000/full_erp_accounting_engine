#!/usr/bin/env python3
"""
Module: inventory_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects for Inventory Management requests.

Fitur:
- Item management (create, update)
- Stock movement (in/out/adjustment)
- Stock opname (physical count)
- Inter-warehouse transfer
- COGS calculation
- Inventory valuation
- Low stock alerts
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class CreateItemRequestDTO:
    """Request DTO for creating a new inventory item."""

    legal_entity_id: UUID
    sku: str | None = None
    name: str | None = None
    description: str | None = None
    item_type: str = "finished_good"
    uom: str | None = None
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal = Decimal(0)
    selling_price: Decimal = Decimal(0)
    warehouse_code: str | None = None
    is_active: bool = True
    # -- Field tambahan supaya cocok dengan kontrak router (ItemCreateSchema) --
    item_code: str | None = None
    item_name: str | None = None
    unit_of_measure: str | None = None
    reorder_quantity: Decimal | None = None
    valuation_method: str | None = None
    warehouse_id: UUID | None = None
    min_stock: Decimal | None = None
    max_stock: Decimal | None = None
    tax_rate_purchase: Decimal | None = None
    tax_rate_sales: Decimal | None = None
    weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    is_lot_tracked: bool = False
    is_serial_tracked: bool = False
    is_expiry_tracked: bool = False
    created_by: UUID | None = None

    def __post_init__(self) -> None:
        # item_code/item_name (kontrak router baru) dan sku/name (kontrak lama)
        # merujuk konsep yang sama - saling isi kalau salah satu kosong.
        if not self.sku and self.item_code:
            self.sku = self.item_code
        if not self.item_code and self.sku:
            self.item_code = self.sku
        if not self.name and self.item_name:
            self.name = self.item_name
        if not self.item_name and self.name:
            self.item_name = self.name
        if not self.uom and self.unit_of_measure:
            self.uom = self.unit_of_measure
        if not self.unit_of_measure and self.uom:
            self.unit_of_measure = self.uom
        if self.uom is None:
            self.uom = "pcs"
        if self.minimum_stock is None and self.min_stock is not None:
            self.minimum_stock = self.min_stock
        if self.maximum_stock is None and self.max_stock is not None:
            self.maximum_stock = self.max_stock

        if not self.sku or len(self.sku.strip()) < 3:
            raise ValueError("SKU must be at least 3 characters")
        if not self.name:
            raise ValueError("Item name is required")
        # FIX BUG: daftar ini sebelumnya berisi nilai yang TIDAK PERNAH bisa
        # sampai ke sini ("work_in_progress" - salah ketik, seharusnya
        # "work_in_process"; "finished_goods", "packaging", "spare_part",
        # "supplies" - tidak ada di enum ItemType backend sama sekali), dan
        # JUSTRU TIDAK MENCANTUMKAN "work_in_process" yang merupakan nilai
        # SAH dari ItemType enum (lihat fastapi_inventory_router.py). Karena
        # router sudah memvalidasi item_type lewat Pydantic ItemType enum
        # sebelum DTO ini dipanggil, satu-satunya nilai yang mungkin masuk
        # ke sini adalah 7 nilai resmi tsb - daftar disamakan persis supaya
        # tidak ada validasi ganda yang saling bertentangan.
        valid_item_types = [
            "raw_material",
            "work_in_process",
            "finished_good",
            "trading",
            "consumable",
            "service",
            "asset",
        ]
        if self.item_type not in valid_item_types:
            raise ValueError(f"Invalid item_type: {self.item_type}")
        if self.reorder_point is not None and self.reorder_point < 0:
            raise ValueError(f"Reorder point cannot be negative: {self.reorder_point}")
        if self.safety_stock is not None and self.safety_stock < 0:
            raise ValueError(f"Safety stock cannot be negative: {self.safety_stock}")
        if self.standard_cost < 0:
            raise ValueError(f"Standard cost cannot be negative: {self.standard_cost}")
        if self.selling_price < 0:
            raise ValueError(f"Selling price cannot be negative: {self.selling_price}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "uom": self.uom,
            "category": self.category,
            "brand": self.brand,
            "reorder_point": str(self.reorder_point) if self.reorder_point else None,
            "safety_stock": str(self.safety_stock) if self.safety_stock else None,
            "maximum_stock": str(self.maximum_stock) if self.maximum_stock else None,
            "minimum_stock": str(self.minimum_stock) if self.minimum_stock else None,
            "standard_cost": str(self.standard_cost),
            "selling_price": str(self.selling_price),
            "warehouse_code": self.warehouse_code,
            "is_active": self.is_active,
        }


@dataclass(kw_only=True)
class UpdateItemRequestDTO:
    """Request DTO for updating an existing item."""

    item_id: UUID | None = None
    name: str | None = None
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    standard_cost: Decimal | None = None
    selling_price: Decimal | None = None
    minimum_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    is_active: bool | None = None
    # -- Field tambahan supaya cocok dengan kontrak router (ItemUpdateSchema) --
    id: UUID | None = None
    item_name: str | None = None
    item_type: str | None = None
    unit_of_measure: str | None = None
    reorder_quantity: Decimal | None = None
    valuation_method: str | None = None
    warehouse_id: UUID | None = None
    min_stock: Decimal | None = None
    max_stock: Decimal | None = None
    updated_by: UUID | None = None
    legal_entity_id: UUID | None = None
    # -- Alias untuk kompatibilitas dengan pembacaan di service (uom/warehouse_code) --
    uom: str | None = None
    warehouse_code: str | None = None

    def __post_init__(self) -> None:
        # item_id/id dan name/item_name dan minimum_stock-maximum_stock/min_stock-max_stock
        # merujuk konsep yang sama - saling isi kalau salah satu kosong.
        if self.item_id is None and self.id is not None:
            self.item_id = self.id
        if self.id is None and self.item_id is not None:
            self.id = self.item_id
        if self.name is None and self.item_name is not None:
            self.name = self.item_name
        if self.minimum_stock is None and self.min_stock is not None:
            self.minimum_stock = self.min_stock
        if self.maximum_stock is None and self.max_stock is not None:
            self.maximum_stock = self.max_stock
        if self.uom is None and self.unit_of_measure is not None:
            self.uom = self.unit_of_measure
        # FIX BUG: baris ini sebelumnya memasukkan UUID gudang (warehouse_id)
        # mentah-mentah ke warehouse_code (field string bebas yang di sisi
        # domain/database TIDAK terhubung ke kolom FK warehouse_id yang
        # sebenarnya) - akibatnya pilihan gudang di form Barang/Item selalu
        # gagal tersimpan secara diam-diam. warehouse_id sekarang dikirim
        # apa adanya ke service, yang memetakannya ke kolom FK yang benar.

        if self.item_id is None:
            raise ValueError("item_id is required")
        if not any(
            [
                self.name,
                self.description,
                self.category,
                self.brand,
                self.reorder_point,
                self.safety_stock,
                self.standard_cost,
                self.selling_price,
                self.minimum_stock,
                self.maximum_stock,
                self.is_active is not None,
                self.item_type,
                self.unit_of_measure,
                self.reorder_quantity,
                self.valuation_method,
                self.warehouse_id,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.name and len(self.name.strip()) < 2:
            raise ValueError("Item name must be at least 2 characters")
        if self.reorder_point is not None and self.reorder_point < 0:
            raise ValueError(f"Reorder point cannot be negative: {self.reorder_point}")
        if self.safety_stock is not None and self.safety_stock < 0:
            raise ValueError(f"Safety stock cannot be negative: {self.safety_stock}")
        # FIX BUG: CreateItemRequestDTO sudah menolak standard_cost/selling_price
        # negatif sejak awal, tapi UpdateItemRequestDTO ini TIDAK PERNAH punya
        # validasi yang sama - jadi item yang sudah ada bisa diedit sampai
        # harganya minus (terbukti dari screenshot user: "Harga Jual" -4,00
        # sempat bisa masuk ke form update tanpa ditolak).
        if self.standard_cost is not None and self.standard_cost < 0:
            raise ValueError(f"Standard cost cannot be negative: {self.standard_cost}")
        if self.selling_price is not None and self.selling_price < 0:
            raise ValueError(f"Selling price cannot be negative: {self.selling_price}")
        if self.minimum_stock is not None and self.minimum_stock < 0:
            raise ValueError(f"Minimum stock cannot be negative: {self.minimum_stock}")
        if self.maximum_stock is not None and self.maximum_stock < 0:
            raise ValueError(f"Maximum stock cannot be negative: {self.maximum_stock}")
        if self.reorder_quantity is not None and self.reorder_quantity < 0:
            raise ValueError(f"Reorder quantity cannot be negative: {self.reorder_quantity}")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"item_id": str(self.item_id)}
        if self.name is not None:
            result["name"] = self.name
        if self.description is not None:
            result["description"] = self.description
        if self.category is not None:
            result["category"] = self.category
        if self.brand is not None:
            result["brand"] = self.brand
        if self.reorder_point is not None:
            result["reorder_point"] = str(self.reorder_point)
        if self.safety_stock is not None:
            result["safety_stock"] = str(self.safety_stock)
        if self.standard_cost is not None:
            result["standard_cost"] = str(self.standard_cost)
        if self.selling_price is not None:
            result["selling_price"] = str(self.selling_price)
        if self.minimum_stock is not None:
            result["minimum_stock"] = str(self.minimum_stock)
        if self.maximum_stock is not None:
            result["maximum_stock"] = str(self.maximum_stock)
        if self.is_active is not None:
            result["is_active"] = self.is_active
        return result


@dataclass(kw_only=True)
class StockMovementRequestDTO:
    """Request DTO for stock movement (in/out/adjustment)."""

    legal_entity_id: UUID
    item_id: UUID
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal | None = None
    reference_document_type: str | None = None
    reference_document_number: str | None = None
    movement_date: date | None = None
    warehouse_code: str | None = None
    notes: str | None = None
    # -- Field tambahan supaya cocok dengan kontrak router inventory (movements API) --
    reference_type: str | None = None
    reference_id: UUID | None = None
    warehouse_id: UUID | None = None
    to_warehouse_id: UUID | None = None
    batch_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    created_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        valid_movement_types = [
            "IN",
            "OUT",
            "ADJUSTMENT",
            "ADJUSTMENT_IN",
            "ADJUSTMENT_OUT",
            "TRANSFER_IN",
            "TRANSFER_OUT",
            "RETURN_IN",
            "RETURN_OUT",
            "SCRAP",
            "SAMPLE",
        ]
        if self.movement_type not in valid_movement_types:
            raise ValueError(f"Invalid movement_type: {self.movement_type}")
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if self.movement_date is None:
            from datetime import date

            object.__setattr__(self, "movement_date", date.today())
        # reference_type/reference_document_type dan reference_id/reference_document_number
        # adalah dua penamaan untuk konsep yang sama - saling isi kalau salah satu kosong.
        if self.reference_type and not self.reference_document_type:
            object.__setattr__(self, "reference_document_type", self.reference_type)
        if not self.reference_type and self.reference_document_type:
            object.__setattr__(self, "reference_type", self.reference_document_type)
        if self.warehouse_id and not self.warehouse_code:
            object.__setattr__(self, "warehouse_code", str(self.warehouse_id))

    def to_dict(self) -> dict[str, Any]:
        # movement_date is guaranteed non-None after __post_init__
        assert self.movement_date is not None
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "item_id": str(self.item_id),
            "movement_type": self.movement_type,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost) if self.unit_cost else None,
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "movement_date": self.movement_date.isoformat(),
            "warehouse_code": self.warehouse_code,
            "notes": self.notes,
            "reference_type": self.reference_type,
            "reference_id": str(self.reference_id) if self.reference_id else None,
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "to_warehouse_id": str(self.to_warehouse_id) if self.to_warehouse_id else None,
            "batch_number": self.batch_number,
            "serial_number": self.serial_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "created_by": str(self.created_by) if self.created_by else None,
        }


@dataclass(kw_only=True)
class StockOpnameRequestDTO:
    """Request DTO for stock opname (physical count session).

    FIX BUG PRE-EXISTING (bukan hasil perbaikan sebelumnya - ini bug lama
    yang belum pernah ketahuan): DTO ini SEBELUMNYA cuma mendukung SATU
    item per opname (item_id + physical_quantity tunggal). Padahal
    endpoint router (StockOpnameCreateSchema) dan form frontend (Stock
    Opname & Valuasi) sama-sama dirancang untuk SATU SESI hitung fisik
    per GUDANG yang berisi BANYAK baris item sekaligus (warehouse_id +
    lines[]). Setiap kali endpoint create dipanggil, langsung TypeError
    "unexpected keyword argument 'warehouse_id'" - fitur ini tidak
    pernah bisa dipakai sama sekali sejak awal. DTO ditulis ulang
    mengikuti bentuk yang benar-benar dikirim router.
    """

    legal_entity_id: UUID
    warehouse_id: UUID
    lines: list[dict[str, Any]]
    opname_date: date | None = None
    notes: str | None = None
    created_by: UUID | None = None

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError("Stock opname harus punya minimal 1 baris item")
        for line in self.lines:
            physical_qty = Decimal(str(line.get("physical_quantity", 0)))
            if physical_qty < 0:
                raise ValueError(f"Physical quantity cannot be negative: {physical_qty}")
        if self.opname_date is None:
            object.__setattr__(self, "opname_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        assert self.opname_date is not None
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "warehouse_id": str(self.warehouse_id),
            "lines": self.lines,
            "opname_date": self.opname_date.isoformat(),
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
        }


@dataclass(kw_only=True)
class TransferRequestDTO:
    """Request DTO for inter-warehouse transfer."""

    legal_entity_id: UUID
    item_id: UUID
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    transfer_date: date | None = None
    notes: str | None = None
    requested_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.from_warehouse == self.to_warehouse:
            raise ValueError("Source and destination warehouses cannot be the same")
        if self.transfer_date is None:
            from datetime import date

            object.__setattr__(self, "transfer_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        # transfer_date is guaranteed non-None after __post_init__
        assert self.transfer_date is not None
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "item_id": str(self.item_id),
            "from_warehouse": self.from_warehouse,
            "to_warehouse": self.to_warehouse,
            "quantity": str(self.quantity),
            "transfer_date": self.transfer_date.isoformat(),
            "notes": self.notes,
            "requested_by": str(self.requested_by) if self.requested_by else None,
        }


@dataclass(kw_only=True)
class COGSCalculationRequestDTO:
    """Request DTO for COGS calculation over a period."""

    legal_entity_id: UUID
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_start >= self.period_end:
            raise ValueError("period_start must be before period_end")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }


@dataclass(kw_only=True)
class InventoryValuationRequestDTO:
    """Request DTO for inventory valuation as of a date."""

    legal_entity_id: UUID
    as_of_date: date
    warehouse_code: str | None = None
    valuation_method: str = "FIFO"  # FIFO, LIFO, AVERAGE, STANDARD

    def __post_init__(self) -> None:
        valid_methods = ["FIFO", "LIFO", "AVERAGE", "STANDARD"]
        if self.valuation_method.upper() not in valid_methods:
            raise ValueError(f"Invalid valuation_method: {self.valuation_method}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "warehouse_code": self.warehouse_code,
            "valuation_method": self.valuation_method,
        }


@dataclass(kw_only=True)
class LowStockAlertQueryDTO:
    """Query DTO for low stock alerts."""

    legal_entity_id: UUID
    warehouse_code: str | None = None
    include_zero_stock: bool = False
    threshold_percentage: Decimal = Decimal(
        20
    )  # Alert when stock below reorder point by this percentage

    def __post_init__(self) -> None:
        if self.threshold_percentage < 0 or self.threshold_percentage > 100:
            raise ValueError(
                f"threshold_percentage must be between 0 and 100: {self.threshold_percentage}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "warehouse_code": self.warehouse_code,
            "include_zero_stock": self.include_zero_stock,
            "threshold_percentage": str(self.threshold_percentage),
        }


# Aliases for router compatibility
@dataclass(kw_only=True)
class InterWarehouseTransferRequestDTO:
    """Request DTO transfer antar gudang versi header + banyak item.

    FIX: sebelumnya alias ``InterWarehouseTransferRequest`` menunjuk ke
    ``TransferRequestDTO`` yang bentuknya berbeda total (single item, gudang
    dinyatakan sebagai string ``from_warehouse``/``to_warehouse``). Endpoint
    POST /inventory/inventory/transfers membangun DTO-nya dengan
    ``from_warehouse_id``/``to_warehouse_id``/``items``/``created_by``,
    sehingga pemanggilan itu selalu gagal TypeError "unexpected keyword
    argument". DTO ini mencocokkan apa yang benar-benar dikirim router.
    """

    legal_entity_id: UUID
    from_warehouse_id: UUID
    to_warehouse_id: UUID
    items: list[dict[str, Any]]
    transfer_date: date | None = None
    notes: str | None = None
    created_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("Gudang asal dan gudang tujuan tidak boleh sama")
        if not self.items:
            raise ValueError("Transfer harus punya minimal 1 item")
        for line in self.items:
            qty = Decimal(str(line.get("quantity", 0)))
            if qty <= 0:
                raise ValueError(f"Qty harus lebih besar dari 0: {qty}")
        if self.transfer_date is None:
            object.__setattr__(self, "transfer_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "from_warehouse_id": str(self.from_warehouse_id),
            "to_warehouse_id": str(self.to_warehouse_id),
            "items": self.items,
            "transfer_date": self.transfer_date.isoformat() if self.transfer_date else None,
            "notes": self.notes,
            "created_by": str(self.created_by) if self.created_by else None,
        }


ItemCreateRequest = CreateItemRequestDTO
ItemUpdateRequest = UpdateItemRequestDTO
StockMovementRequest = StockMovementRequestDTO
StockOpnameRequest = StockOpnameRequestDTO
InterWarehouseTransferRequest = InterWarehouseTransferRequestDTO
COGSCalculationRequest = COGSCalculationRequestDTO
InventoryValuationRequest = InventoryValuationRequestDTO
LowStockAlertQuery = LowStockAlertQueryDTO


__all__ = [
    "COGSCalculationRequest",
    "COGSCalculationRequestDTO",
    "CreateItemRequestDTO",
    "InterWarehouseTransferRequest",
    "InterWarehouseTransferRequestDTO",
    "InventoryValuationRequest",
    "InventoryValuationRequestDTO",
    "ItemCreateRequest",
    "ItemUpdateRequest",
    "LowStockAlertQuery",
    "LowStockAlertQueryDTO",
    "StockMovementRequest",
    "StockMovementRequestDTO",
    "StockOpnameRequest",
    "StockOpnameRequestDTO",
    "TransferRequestDTO",
    "UpdateItemRequestDTO",
]
