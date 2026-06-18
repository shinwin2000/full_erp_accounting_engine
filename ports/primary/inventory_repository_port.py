#!/usr/bin/env python3
"""
Module: inventory_repository_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory repository untuk Inventory Management
               dengan fitur: item management, stock movement (in/out/adjustment/transfer),
               FIFO valuation, reorder point, stock opname, batch/serial tracking,
               audit trail, dan laporan.
Audit: Setiap perubahan stok, harga, dan item tercatat.
"""

from __future__ import annotations

import asyncio
import csv
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class InventoryItemType(Enum):
    """Jenis item inventaris."""

    RAW_MATERIAL = "raw_material"  # Bahan baku
    WORK_IN_PROGRESS = "work_in_progress"  # Barang dalam proses
    FINISHED_GOODS = "finished_goods"  # Barang jadi
    PACKAGING = "packaging"  # Kemasan
    CONSUMABLE = "consumable"  # Habis pakai
    SPARE_PART = "spare_part"  # Spare part
    ASSET = "asset"  # Aset (non-stock?)


class InventoryMovementType(Enum):
    """Jenis pergerakan stok."""

    PURCHASE_IN = "purchase_in"  # Pembelian masuk
    SALES_OUT = "sales_out"  # Penjualan keluar
    PRODUCTION_IN = "production_in"  # Hasil produksi masuk
    PRODUCTION_OUT = "production_out"  # Bahan baku keluar untuk produksi
    ADJUSTMENT_IN = "adjustment_in"  # Penyesuaian masuk
    ADJUSTMENT_OUT = "adjustment_out"  # Penyesuaian keluar
    TRANSFER_IN = "transfer_in"  # Transfer dari gudang lain
    TRANSFER_OUT = "transfer_out"  # Transfer ke gudang lain
    RETURN_IN = "return_in"  # Retur dari pelanggan
    RETURN_OUT = "return_out"  # Retur ke supplier
    SCRAP = "scrap"  # Barang rusak/hilang
    SAMPLE = "sample"  # Sample keluar


class StockOpnameStatus(Enum):
    """Status stock opname."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(kw_only=True)
class InventoryItem:
    """
    Aggregate Inventory Item (Master Barang).
    """

    # ========== NON-DEFAULT FIELDS ==========
    id: UUID
    item_code: str
    item_name: str
    item_type: InventoryItemType
    legal_entity_id: UUID
    unit_of_measure: str
    reorder_point: Decimal  # Minimal stok sebelum reorder
    reorder_quantity: Decimal  # Jumlah yang dipesan saat reorder
    safety_stock: Decimal  # Stok pengaman
    current_stock: Decimal  # Stok saat ini (seluruh gudang)
    average_cost: Decimal  # Biaya rata-rata (moving average)
    last_purchase_cost: Decimal  # Harga beli terakhir
    standard_cost: Decimal  # Harga standar untuk costing
    cost_method: str  # FIFO, AVERAGE, STANDARD
    sales_price: Decimal  # Harga jual (default)
    is_active: bool
    is_track_lot: bool  # Menggunakan batch/lot number
    is_track_serial: bool  # Menggunakan serial number
    is_track_expiry: bool  # Menggunakan expiry date

    # Properti Opsional tanpa default value awal (Dipaksa None untuk keselarasan urutan)
    default_warehouse_id: UUID | None = None
    category_id: UUID | None = None
    tax_rate_id: UUID | None = None
    weight_kg: Decimal | None = None  # Berat per unit
    volume_m3: Decimal | None = None  # Volume per unit
    notes: str | None = None

    # ========== DEFAULT FIELDS ==========
    dimensions: str | None = "10x20x30 cm"
    currency_code: str = "IDR"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: UUID = field(default_factory=lambda: UUID(int=0))
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "item_type": self.item_type.value,
            "legal_entity_id": str(self.legal_entity_id),
            "unit_of_measure": self.unit_of_measure,
            "reorder_point": float(self.reorder_point),
            "reorder_quantity": float(self.reorder_quantity),
            "safety_stock": float(self.safety_stock),
            "current_stock": float(self.current_stock),
            "average_cost": float(self.average_cost),
            "last_purchase_cost": float(self.last_purchase_cost),
            "standard_cost": float(self.standard_cost),
            "cost_method": self.cost_method,
            "sales_price": float(self.sales_price),
            "currency_code": self.currency_code,
            "is_active": self.is_active,
            "is_track_lot": self.is_track_lot,
            "is_track_serial": self.is_track_serial,
            "is_track_expiry": self.is_track_expiry,
            "default_warehouse_id": str(self.default_warehouse_id)
            if self.default_warehouse_id
            else None,
            "category_id": str(self.category_id) if self.category_id else None,
            "tax_rate_id": str(self.tax_rate_id) if self.tax_rate_id else None,
            "weight_kg": float(self.weight_kg) if self.weight_kg else None,
            "volume_m3": float(self.volume_m3) if self.volume_m3 else None,
            "dimensions": self.dimensions,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by),
            "updated_at": self.updated_at.isoformat(),
            "updated_by": str(self.updated_by),
            "version": self.version,
        }


@dataclass(kw_only=True)
class InventoryMovement:
    """
    Pergerakan stok (transaksi inventaris).
    """

    id: UUID
    item_id: UUID
    warehouse_id: UUID
    movement_type: InventoryMovementType
    quantity: Decimal
    unit_cost: Decimal  # Biaya per unit saat transaksi
    total_cost: Decimal  # quantity * unit_cost
    reference_type: str  # PURCHASE_ORDER, SALES_ORDER, PRODUCTION_ORDER, etc
    reference_id: UUID  # ID dokumen sumber
    movement_date: date
    lot_number: str | None = None  # Jika track lot
    serial_numbers: list[str] | None = None  # Jika track serial
    expiry_date: date | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    notes: str | None = None


@dataclass(kw_only=True)
class FifoLayer:
    """
    Layer FIFO untuk tracking biaya persediaan.
    """

    id: UUID
    item_id: UUID
    warehouse_id: UUID
    layer_date: date
    quantity: Decimal
    unit_cost: Decimal
    remaining_quantity: Decimal
    lot_number: str | None = None
    source_movement_id: UUID  # ID movement yang membuat layer ini

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "warehouse_id": str(self.warehouse_id),
            "layer_date": self.layer_date.isoformat(),
            "quantity": float(self.quantity),
            "unit_cost": float(self.unit_cost),
            "remaining_quantity": float(self.remaining_quantity),
            "lot_number": self.lot_number,
            "source_movement_id": str(self.source_movement_id),
        }


@dataclass(kw_only=True)
class StockOpname:
    """
    Stock opname (penghitungan fisik stok).
    """

    id: UUID
    warehouse_id: UUID
    opname_date: date
    status: StockOpnameStatus
    items: list[
        dict[str, Any]
    ]  # [{item_id, system_stock, physical_stock, difference, adjustment_journal_id}]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: UUID(int=0))
    closed_at: datetime | None = None
    closed_by: UUID | None = None
    notes: str | None = None


class InventoryRepositoryPort:
    """
    Repository in-memory untuk Inventory Management.
    """

    def __init__(self):
        self._items: dict[UUID, InventoryItem] = {}
        self._code_index: dict[tuple[str, UUID], InventoryItem] = {}  # (item_code, legal_entity_id)
        self._movements: list[InventoryMovement] = []
        self._fifo_layers: dict[
            tuple[UUID, UUID], list[FifoLayer]
        ] = {}  # (item_id, warehouse_id) -> layers
        self._stock_opname: dict[UUID, StockOpname] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, entity_type: str, entity_id: UUID, user_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "user_id": str(user_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"INVENTORY AUDIT: {action} on {entity_type} {entity_id} by {user_id}")

    async def _update_item_stock(
        self,
        item_id: UUID,
        warehouse_id: UUID,
        delta: Decimal,
        unit_cost: Decimal,
        user_id: UUID,
        reference_type: str,
        reference_id: UUID,
        movement_type: InventoryMovementType,
        notes: str | None = None,
    ) -> InventoryMovement:
        """Internal: update stok item dan catat movement, serta update FIFO jika perlu."""
        async with self._lock:
            # FIX: Diganti dari get_by_id ke get_item_by_id sesuai deklarasi fungsi publik kelas ini
            item = await self.get_item_by_id(item_id)
            if not item:
                raise ValueError(f"Item {item_id} not found")
            # Hitung total_cost
            total_cost = delta * unit_cost
            # Update stok item (agregat seluruh gudang) - untuk keperluan master
            new_stock = item.current_stock + delta
            if new_stock < -item.safety_stock:
                logger.warning(f"Stock level for item {item.item_code} is negative: {new_stock}")
            item.current_stock = new_stock
            item.updated_at = datetime.now(UTC)
            item.updated_by = user_id
            item.version += 1
            # Update average cost jika movement type pembelian/masuk
            if movement_type in (
                InventoryMovementType.PURCHASE_IN,
                InventoryMovementType.PRODUCTION_IN,
                InventoryMovementType.ADJUSTMENT_IN,
                InventoryMovementType.TRANSFER_IN,
            ):
                total_qty = item.current_stock
                total_value = item.current_stock * item.average_cost
                # Recompute
                if total_qty != 0:
                    new_avg = (total_value + total_cost) / total_qty
                else:
                    new_avg = unit_cost
                item.average_cost = new_avg.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
                item.last_purchase_cost = unit_cost
            # Simpan movement
            movement = InventoryMovement(
                id=uuid4(),
                item_id=item_id,
                warehouse_id=warehouse_id,
                movement_type=movement_type,
                quantity=delta,
                unit_cost=unit_cost,
                total_cost=total_cost,
                reference_type=reference_type,
                reference_id=reference_id,
                movement_date=datetime.now(UTC).date(),
                lot_number=None,
                serial_numbers=None,
                expiry_date=None,
                created_at=datetime.now(UTC),
                created_by=user_id,
                notes=notes,
            )
            self._movements.append(movement)
            # Update FIFO layers jika cost_method = FIFO
            if item.cost_method.upper() == "FIFO":
                await self._update_fifo_layers(
                    item_id, warehouse_id, delta, unit_cost, movement.id, movement_type
                )
            # Update item storage
            self._items[item_id] = item
            return movement

    async def _update_fifo_layers(
        self,
        item_id: UUID,
        warehouse_id: UUID,
        delta: Decimal,
        unit_cost: Decimal,
        movement_id: UUID,
        movement_type: InventoryMovementType,
    ):
        """Update FIFO layers berdasarkan pergerakan stok."""
        key = (item_id, warehouse_id)
        if key not in self._fifo_layers:
            self._fifo_layers[key] = []
        layers = self._fifo_layers[key]
        now_date = datetime.now(UTC).date()
        if delta > 0:  # Stok masuk: tambah layer baru
            new_layer = FifoLayer(
                id=uuid4(),
                item_id=item_id,
                warehouse_id=warehouse_id,
                layer_date=now_date,
                quantity=delta,
                unit_cost=unit_cost,
                remaining_quantity=delta,
                lot_number=None,
                source_movement_id=movement_id,
            )
            layers.append(new_layer)
        elif delta < 0:  # Stok keluar: kurangi dari layer tertua (FIFO)
            remaining_out = -delta
            layers_to_remove = []
            for idx, layer in enumerate(layers):
                if remaining_out <= 0:
                    break
                if layer.remaining_quantity <= 0:
                    layers_to_remove.append(idx)
                    continue
                taken = min(layer.remaining_quantity, remaining_out)
                layer.remaining_quantity -= taken
                remaining_out -= taken
                if layer.remaining_quantity == 0:
                    layers_to_remove.append(idx)
            # Hapus layer yang habis (dari belakang agar index tidak berubah)
            for idx in reversed(layers_to_remove):
                layers.pop(idx)
        # Pruning: hapus layer yang remaining = 0
        self._fifo_layers[key] = [l for l in layers if l.remaining_quantity > 0]

    async def _get_fifo_cost(self, item_id: UUID, warehouse_id: UUID, quantity: Decimal) -> Decimal:
        """Hitung biaya rata-rata FIFO untuk sejumlah quantity keluar (untuk COGS)."""
        key = (item_id, warehouse_id)
        layers = self._fifo_layers.get(key, [])
        remaining = quantity
        total_cost = Decimal(0)
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer.remaining_quantity, remaining)
            total_cost += take * layer.unit_cost
            remaining -= take
        if remaining > 0:
            logger.warning(f"Not enough FIFO layers for item {item_id}, using average cost")
            # Fallback: cari item average cost
            item = await self.get_item_by_id(item_id)
            if item:
                total_cost += remaining * item.average_cost
        return total_cost

    # ==================== ITEM CRUD ====================

    async def add_item(self, item: InventoryItem) -> None:
        """Menambahkan item baru."""
        if not isinstance(item, InventoryItem):
            raise TypeError("item must be InventoryItem")
        if item.id in self._items:
            raise ValueError(f"Item with id {item.id} already exists")
        key = (item.item_code, item.legal_entity_id)
        if key in self._code_index:
            raise ValueError(
                f"Item with code {item.item_code} already exists for this legal entity"
            )
        async with self._lock:
            self._items[item.id] = item
            self._code_index[key] = item
        await self._log_audit(
            "ADD_ITEM",
            "item",
            item.id,
            item.created_by,
            {
                "item_code": item.item_code,
                "item_name": item.item_name,
            },
        )

    async def get_item_by_id(self, item_id: UUID) -> InventoryItem | None:
        return self._items.get(item_id)

    async def get_item_by_sku(self, sku: str, legal_entity_id: UUID) -> InventoryItem | None:
        return self._code_index.get((sku, legal_entity_id))

    async def update_item(self, item: InventoryItem) -> None:
        if item.id not in self._items:
            raise ValueError(f"Item {item.id} not found")
        old = self._items[item.id]
        old_key = (old.item_code, old.legal_entity_id)
        new_key = (item.item_code, item.legal_entity_id)
        if old_key != new_key:
            del self._code_index[old_key]
            self._code_index[new_key] = item
        item.updated_at = datetime.now(UTC)
        item.version += 1
        self._items[item.id] = item
        await self._log_audit(
            "UPDATE_ITEM", "item", item.id, item.updated_by, {"changes": "multiple"}
        )

    async def find_items_by_category(self, category_id: UUID) -> list[InventoryItem]:
        return [i for i in self._items.values() if i.category_id == category_id]

    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID | None = None) -> Decimal:
        """Stok saat ini untuk item di warehouse tertentu atau total jika warehouse None."""
        if warehouse_id is None:
            item = self._items.get(item_id)
            return item.current_stock if item else Decimal(0)
        else:
            # Hitung dari movements (lebih akurat)
            total_in = Decimal(0)
            total_out = Decimal(0)
            for mov in self._movements:
                if mov.item_id == item_id and mov.warehouse_id == warehouse_id:
                    if mov.quantity > 0:
                        total_in += mov.quantity
                    else:
                        total_out += -mov.quantity
            return total_in - total_out

    async def get_all_items(
        self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[InventoryItem]:
        result = list(self._items.values())
        if legal_entity_id:
            result = [i for i in result if i.legal_entity_id == legal_entity_id]
        result.sort(key=lambda x: x.item_code)
        return result[offset : offset + limit]

    # ==================== MOVEMENT / STOCK UPDATE ====================

    async def record_movement(self, movement: InventoryMovement) -> None:
        """Mencatat pergerakan stok dan update stok item."""
        if movement.quantity == 0:
            raise ValueError("Quantity must be non-zero")
        movement_type = movement.movement_type
        sign = (
            1
            if movement_type
            in (
                InventoryMovementType.PURCHASE_IN,
                InventoryMovementType.PRODUCTION_IN,
                InventoryMovementType.ADJUSTMENT_IN,
                InventoryMovementType.TRANSFER_IN,
                InventoryMovementType.RETURN_IN,
            )
            else -1
        )
        delta = movement.quantity * sign
        # Cari unit cost: jika movement_type in, gunakan unit_cost dari movement, jika out, ambil dari FIFO/avg
        if sign == 1:
            unit_cost = movement.unit_cost
        else:
            # Untuk movement keluar, hitung cost berdasarkan metode item
            item = await self.get_item_by_id(movement.item_id)
            if not item:
                raise ValueError(f"Item {movement.item_id} not found")
            if item.cost_method.upper() == "FIFO":
                unit_cost = (
                    await self._get_fifo_cost(
                        movement.item_id, movement.warehouse_id, movement.quantity
                    )
                    / movement.quantity
                )
            else:  # AVERAGE or STANDARD
                unit_cost = item.average_cost
            # Override movement dengan cost yang dihitung
            movement.unit_cost = unit_cost
            movement.total_cost = movement.quantity * unit_cost
        # Update stok
        updated_movement = await self._update_item_stock(
            item_id=movement.item_id,
            warehouse_id=movement.warehouse_id,
            delta=delta,
            unit_cost=movement.unit_cost,
            user_id=movement.created_by,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            movement_type=movement_type,
            notes=movement.notes,
        )
        await self._log_audit(
            "RECORD_MOVEMENT",
            "movement",
            updated_movement.id,
            movement.created_by,
            {
                "item_id": str(movement.item_id),
                "quantity": float(movement.quantity),
                "type": movement_type.value,
            },
        )

    async def get_movements_by_item(
        self, item_id: UUID, start_date: date, end_date: date
    ) -> list[InventoryMovement]:
        result = []
        for mov in self._movements:
            if mov.item_id == item_id and start_date <= mov.movement_date <= end_date:
                result.append(mov)
        return sorted(result, key=lambda x: x.movement_date)

    async def get_movements_by_reference(
        self, reference_type: str, reference_id: UUID
    ) -> list[InventoryMovement]:
        return [
            mov
            for mov in self._movements
            if mov.reference_type == reference_type and mov.reference_id == reference_id
        ]

    # ==================== VALUATION ====================

    async def get_inventory_value(
        self, legal_entity_id: UUID, as_of_date: date, valuation_method: str = "AVERAGE"
    ) -> Decimal:
        """Menghitung total nilai persediaan pada tanggal tertentu."""
        total_value = Decimal(0)
        items = await self.get_all_items(legal_entity_id)
        for item in items:
            stock = await self.get_current_stock(item.id, None)
            if stock <= 0:
                continue
            if valuation_method.upper() == "FIFO":
                # Estimasi nilai FIFO dari layers
                value = Decimal(0)
                layers = self._fifo_layers.get((item.id, item.default_warehouse_id or uuid4()), [])
                remaining = stock
                for layer in layers:
                    take = min(layer.remaining_quantity, remaining)
                    value += take * layer.unit_cost
                    remaining -= take
                    if remaining <= 0:
                        break
                total_value += value
            else:  # AVERAGE or STANDARD
                total_value += stock * item.average_cost
        return total_value

    async def get_fifo_layers(self, item_id: UUID, warehouse_id: UUID) -> list[FifoLayer]:
        key = (item_id, warehouse_id)
        return self._fifo_layers.get(key, [])

    # ==================== REORDER & LOW STOCK ====================

    async def get_items_below_reorder_point(self, legal_entity_id: UUID) -> list[InventoryItem]:
        """Item dengan stok di bawah reorder point."""
        result = []
        items = await self.get_all_items(legal_entity_id)
        for item in items:
            stock = await self.get_current_stock(item.id, None)
            if stock <= item.reorder_point:
                result.append(item)
        return result

    async def get_recommended_po_items(
        self, legal_entity_id: UUID
    ) -> list[tuple[InventoryItem, Decimal]]:
        """Item yang perlu dipesan ulang dengan kuantitas rekomendasi."""
        result = []
        items = await self.get_all_items(legal_entity_id)
        for item in items:
            stock = await self.get_current_stock(item.id, None)
            if stock <= item.reorder_point:
                qty_to_order = max(
                    item.reorder_quantity, (item.reorder_point - stock) + item.safety_stock
                )
                result.append((item, qty_to_order))
        return result

    # ==================== STOCK OPNAME ====================

    async def create_stock_opname(
        self, warehouse_id: UUID, created_by: UUID, notes: str | None = None
    ) -> UUID:
        """Membuat stock opname baru."""
        opname_id = uuid4()
        opname = StockOpname(
            id=opname_id,
            warehouse_id=warehouse_id,
            opname_date=datetime.now(UTC).date(),
            status=StockOpnameStatus.DRAFT,
            items=[],
            created_at=datetime.now(UTC),
            created_by=created_by,
            closed_at=None,
            closed_by=None,
            notes=notes,
        )
        self._stock_opname[opname_id] = opname
        await self._log_audit(
            "CREATE_OPNAME",
            "stock_opname",
            opname_id,
            created_by,
            {"warehouse_id": str(warehouse_id)},
        )
        return opname_id

    async def record_opname_item(
        self, opname_id: UUID, item_id: UUID, physical_stock: Decimal, user_id: UUID
    ) -> None:
        """Mencatat hasil hitung fisik untuk satu item dalam stock opname."""
        opname = self._stock_opname.get(opname_id)
        if not opname:
            raise ValueError(f"Opname {opname_id} not found")
        if opname.status != StockOpnameStatus.DRAFT:
            raise ValueError("Opname already completed or cancelled")
        system_stock = await self.get_current_stock(item_id, opname.warehouse_id)
        difference = physical_stock - system_stock
        # Simpan dalam items list
        opname.items.append(
            {
                "item_id": str(item_id),
                "system_stock": float(system_stock),
                "physical_stock": float(physical_stock),
                "difference": float(difference),
                "adjustment_journal_id": None,
            }
        )
        await self._log_audit(
            "RECORD_OPNAME_ITEM",
            "stock_opname",
            opname_id,
            user_id,
            {"item_id": str(item_id), "diff": float(difference)},
        )

    async def complete_stock_opname(
        self, opname_id: UUID, closed_by: UUID, auto_adjust: bool = True
    ) -> dict[str, Any]:
        """Menyelesaikan stock opname, opsional membuat adjustment otomatis."""
        opname = self._stock_opname.get(opname_id)
        if not opname:
            raise ValueError(f"Opname {opname_id} not found")
        if opname.status != StockOpnameStatus.DRAFT:
            raise ValueError("Opname already completed")
        adjustments = []
        for item_data in opname.items:
            diff = Decimal(str(item_data["difference"]))
            if diff != 0 and auto_adjust:
                # Buat adjustment movement
                item_id = UUID(item_data["item_id"])
                if diff > 0:
                    mov_type = InventoryMovementType.ADJUSTMENT_IN
                    quantity = diff
                else:
                    mov_type = InventoryMovementType.ADJUSTMENT_OUT
                    quantity = -diff
                # Cari cost untuk adjustment (gunakan average cost)
                item = await self.get_item_by_id(item_id)
                unit_cost = item.average_cost if item else Decimal(0)
                movement = InventoryMovement(
                    id=uuid4(),
                    item_id=item_id,
                    warehouse_id=opname.warehouse_id,
                    movement_type=mov_type,
                    quantity=quantity,
                    unit_cost=unit_cost,
                    total_cost=quantity * unit_cost,
                    reference_type="STOCK_OPNAME",
                    reference_id=opname_id,
                    movement_date=opname.opname_date,
                    lot_number=None,
                    serial_numbers=None,
                    expiry_date=None,
                    created_at=datetime.now(UTC),
                    created_by=closed_by,
                    notes=f"Auto adjustment from stock opname {opname_id}",
                )
                await self.record_movement(movement)
                item_data["adjustment_journal_id"] = str(movement.id)
                adjustments.append(
                    {
                        "item_id": str(item_id),
                        "difference": float(diff),
                        "movement_id": str(movement.id),
                    }
                )
        opname.status = StockOpnameStatus.COMPLETED
        opname.closed_at = datetime.now(UTC)
        opname.closed_by = closed_by
        await self._log_audit(
            "COMPLETE_OPNAME",
            "stock_opname",
            opname_id,
            closed_by,
            {"auto_adjust": auto_adjust, "adjustments": len(adjustments)},
        )
        return {"opname_id": str(opname_id), "adjustments": adjustments}

    # ==================== TRANSFER ====================

    async def transfer_stock(
        self,
        item_id: UUID,
        from_warehouse_id: UUID,
        to_warehouse_id: UUID,
        quantity: Decimal,
        user_id: UUID,
        reference_type: str,
        reference_id: UUID,
        unit_cost: Decimal | None = None,
    ) -> tuple[UUID, UUID]:
        """Transfer stok antar gudang. Mengembalikan (movement_out_id, movement_in_id)."""
        if quantity <= 0:
            raise ValueError("Quantity must be positive")
        item = await self.get_item_by_id(item_id)
        if not item:
            raise ValueError(f"Item {item_id} not found")
        cost = unit_cost if unit_cost is not None else item.average_cost
        # Movement out
        mov_out = InventoryMovement(
            id=uuid4(),
            item_id=item_id,
            warehouse_id=from_warehouse_id,
            movement_type=InventoryMovementType.TRANSFER_OUT,
            quantity=quantity,
            unit_cost=cost,
            total_cost=quantity * cost,
            reference_type=reference_type,
            reference_id=reference_id,
            movement_date=datetime.now(UTC).date(),
            created_at=datetime.now(UTC),
            created_by=user_id,
            notes=f"Transfer out to {to_warehouse_id}",
        )
        await self.record_movement(mov_out)
        # Movement in
        mov_in = InventoryMovement(
            id=uuid4(),
            item_id=item_id,
            warehouse_id=to_warehouse_id,
            movement_type=InventoryMovementType.TRANSFER_IN,
            quantity=quantity,
            unit_cost=cost,
            total_cost=quantity * cost,
            reference_type=reference_type,
            reference_id=reference_id,
            movement_date=datetime.now(UTC).date(),
            created_at=datetime.now(UTC),
            created_by=user_id,
            notes=f"Transfer in from {from_warehouse_id}",
        )
        await self.record_movement(mov_in)
        return mov_out.id, mov_in.id

    # ==================== IMPOR / EKSPOR ====================

    async def export_items_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        items = await self.get_all_items(legal_entity_id)
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "item_code",
                "item_name",
                "item_type",
                "unit_of_measure",
                "reorder_point",
                "safety_stock",
                "current_stock",
                "average_cost",
                "sales_price",
            ]
        )
        for i in items:
            writer.writerow(
                [
                    i.item_code,
                    i.item_name,
                    i.item_type.value,
                    i.unit_of_measure,
                    float(i.reorder_point),
                    float(i.safety_stock),
                    float(i.current_stock),
                    float(i.average_cost),
                    float(i.sales_price),
                ]
            )
        return output.getvalue()

    async def import_items_from_csv(
        self, csv_content: str, legal_entity_id: UUID, user_id: UUID
    ) -> int:
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                item = InventoryItem(
                    id=uuid4(),
                    item_code=row["item_code"],
                    item_name=row["item_name"],
                    item_type=InventoryItemType(row["item_type"]),
                    legal_entity_id=legal_entity_id,
                    unit_of_measure=row["unit_of_measure"],
                    reorder_point=Decimal(row.get("reorder_point", "0")),
                    reorder_quantity=Decimal(row.get("reorder_quantity", "0")),
                    safety_stock=Decimal(row.get("safety_stock", "0")),
                    current_stock=Decimal(0),
                    average_cost=Decimal(row.get("average_cost", "0")),
                    last_purchase_cost=Decimal(row.get("average_cost", "0")),
                    standard_cost=Decimal(row.get("average_cost", "0")),
                    cost_method="AVERAGE",
                    sales_price=Decimal(row.get("sales_price", "0")),
                    currency_code="IDR",
                    is_active=True,
                    is_track_lot=False,
                    is_track_serial=False,
                    is_track_expiry=False,
                    default_warehouse_id=None,
                    category_id=None,
                    tax_rate_id=None,
                    weight_kg=None,
                    volume_m3=None,
                    dimensions=None,
                    notes=None,
                    created_at=datetime.now(UTC),
                    created_by=user_id,
                    updated_at=datetime.now(UTC),
                    updated_by=user_id,
                    version=1,
                )
                await self.add_item(item)
                count += 1
            except Exception as e:
                logger.warning(f"Import item failed: {e}")
        return count

    # ==================== STATISTICS & AUDIT ====================

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        items = list(self._items.values())
        if legal_entity_id:
            items = [i for i in items if i.legal_entity_id == legal_entity_id]
        total_stock_value = sum(i.current_stock * i.average_cost for i in items)
        total_items = len(items)
        low_stock_items = sum(1 for i in items if i.current_stock <= i.reorder_point)
        zero_stock = sum(1 for i in items if i.current_stock == 0)
        return {
            "total_items": total_items,
            "total_stock_value": float(total_stock_value),
            "low_stock_items": low_stock_items,
            "zero_stock_items": zero_stock,
            "total_movements": len(self._movements),
            "total_fifo_layers": sum(len(l) for l in self._fifo_layers.values()),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "items_count": len(self._items),
            "movements_count": len(self._movements),
            "fifo_layers_count": sum(len(l) for l in self._fifo_layers.values()),
            "stock_opnames_count": len(self._stock_opname),
        }
