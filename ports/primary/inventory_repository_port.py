#!/usr/bin/env python3
"""
Module: inventory_repository_port.py
Layer: Ports (Primary)
Responsibility: Port interface untuk Inventory Management.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

# Import domain aggregates (sesuai dengan yang digunakan implementasi)
from domain.inventory.aggregate_root import InventoryItemAggregate, StockMovement
from domain.inventory.valuation_method import FIFOLayer


class InventoryRepositoryPort(ABC):
    """
    Port interface untuk repository Inventory.
    """

    # ==================== ITEM ====================

    @abstractmethod
    async def add_item(self, item: InventoryItemAggregate) -> None:
        """Tambah item baru."""
        pass

    @abstractmethod
    async def get_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        """Dapatkan item berdasarkan ID."""
        pass

    @abstractmethod
    async def get_item_by_sku(self, sku: str, legal_entity_id: UUID) -> InventoryItemAggregate | None:
        """Dapatkan item berdasarkan SKU/kode."""
        pass

    @abstractmethod
    async def update_item(self, item: InventoryItemAggregate) -> None:
        """Update item."""
        pass

    @abstractmethod
    async def find_items_by_category(self, category: str, legal_entity_id: UUID | None = None) -> list[InventoryItemAggregate]:
        """Cari item berdasarkan kategori."""
        pass

    @abstractmethod
    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID | None = None) -> Decimal:
        """Stok saat ini untuk item di warehouse tertentu atau total."""
        pass

    @abstractmethod
    async def get_all_items(
        self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[InventoryItemAggregate]:
        """Daftar semua item dengan paginasi."""
        pass

    # ==================== MOVEMENT ====================

    @abstractmethod
    async def record_movement(self, movement: StockMovement) -> None:
        """Catat pergerakan stok."""
        pass

    @abstractmethod
    async def get_movements_by_item(
        self, item_id: UUID, start_date: date, end_date: date, limit: int = 100
    ) -> list[StockMovement]:
        """Dapatkan pergerakan stok untuk item dalam rentang tanggal."""
        pass

    @abstractmethod
    async def get_movements_by_reference(self, reference_type: str, reference_id: UUID) -> list[StockMovement]:
        """Dapatkan pergerakan stok berdasarkan referensi."""
        pass

    # ==================== VALUATION ====================

    @abstractmethod
    async def get_inventory_value(
        self, legal_entity_id: UUID, as_of_date: date, valuation_method: str = "AVERAGE"
    ) -> Decimal:
        """Nilai total persediaan pada tanggal tertentu."""
        pass

    @abstractmethod
    async def get_fifo_layers(self, item_id: UUID, warehouse_id: UUID) -> list[FIFOLayer]:
        """Dapatkan layer FIFO untuk item di warehouse."""
        pass

    # ==================== REORDER ====================

    @abstractmethod
    async def get_items_below_reorder_point(self, legal_entity_id: UUID) -> list[InventoryItemAggregate]:
        """Item dengan stok di bawah reorder point."""
        pass

    @abstractmethod
    async def get_recommended_po_items(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Item yang perlu dipesan ulang dengan rekomendasi kuantitas."""
        pass

    # ==================== STOCK OPNAME ====================

    @abstractmethod
    async def create_stock_opname(self, warehouse_id: UUID, created_by: UUID, notes: str | None = None) -> UUID:
        """Buat stock opname baru. Mengembalikan opname_id."""
        pass

    @abstractmethod
    async def record_opname_item(
        self, opname_id: UUID, item_id: UUID, physical_count: Decimal, system_count: Decimal, notes: str | None = None
    ) -> None:
        """Catat hasil hitung fisik untuk satu item (system vs physical)."""
        pass

    @abstractmethod
    async def complete_stock_opname(self, opname_id: UUID, closed_by: UUID, auto_adjust: bool = True) -> dict[str, Any]:
        """Selesaikan stock opname, opsional auto adjustment."""
        pass

    # ==================== TRANSFER ====================

    @abstractmethod
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
        pass

    # ==================== EXPORT / IMPORT ====================

    @abstractmethod
    async def export_items_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        """Ekspor item ke CSV."""
        pass

    @abstractmethod
    async def import_items_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        """Impor item dari CSV."""
        pass

    # ==================== STATISTICS & AUDIT ====================

    @abstractmethod
    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        """Statistik inventory."""
        pass

    @abstractmethod
    async def get_audit_log(self, item_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Audit log untuk item tertentu (atau semua)."""
        pass

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Health check repository."""
        pass


__all__ = ["InventoryRepositoryPort"]
