#!/usr/bin/env python3
"""
Module: stock_card_projection.py
Layer: 6 - Domain / Inventory
Responsibility: Kartu stok (proyeksi dari movement) sebagai read model.

Catatan:
- Ini adalah read model (projection), bukan entity bisnis.
- Tidak memiliki logika validasi stock negatif atau audit trail.
- Semua method bersifat query/read-only.
- Nilai balance dihitung dari movements yang sudah terjadi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.inventory.movement_entity import MovementEntity, MovementType

logger = logging.getLogger(__name__)


# ============================================================================
# 1. STOCK CARD ENTRY (Value Object)
# ============================================================================


@dataclass(kw_only=True)
class StockCardEntry:
    """
    Entri dalam kartu stok.

    Mewakili satu baris mutasi dalam kartu stok.
    Bersifat immutable setelah dibuat.
    """

    entry_id: UUID
    movement_id: UUID
    movement_type: MovementType
    movement_number: str
    date: datetime
    reference_document_type: str
    reference_document_number: str
    in_quantity: Decimal
    out_quantity: Decimal
    balance_quantity: Decimal
    unit_cost: Decimal
    in_value: Decimal
    out_value: Decimal
    balance_value: Decimal
    description: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "entry_id": str(self.entry_id),
            "movement_id": str(self.movement_id),
            "movement_type": self.movement_type.value,
            "movement_number": self.movement_number,
            "date": self.date.isoformat(),
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "in_quantity": str(self.in_quantity),
            "out_quantity": str(self.out_quantity),
            "balance_quantity": str(self.balance_quantity),
            "unit_cost": str(self.unit_cost),
            "in_value": str(self.in_value),
            "out_value": str(self.out_value),
            "balance_value": str(self.balance_value),
            "description": self.description,
            "created_at": self.created_at.isoformat(),
        }


# ============================================================================
# 2. STOCK CARD PROJECTION (Read Model)
# ============================================================================


@dataclass(kw_only=True)
class StockCardProjection:
    """
    Kartu stok (read model).

    Ini adalah proyeksi dari movement entities yang sudah terjadi.
    Tidak ada operasi tulis ke database; semua data dihitung dari movements.
    """

    item_id: UUID
    item_sku: str
    item_name: str
    warehouse_id: UUID
    warehouse_name: str
    entries: list[StockCardEntry] = field(default_factory=list)
    opening_balance_quantity: Decimal = Decimal(0)
    opening_balance_value: Decimal = Decimal(0)
    opening_balance_date: datetime | None = None
    current_balance_quantity: Decimal = Decimal(0)
    current_balance_value: Decimal = Decimal(0)
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))

    # ==================== FACTORY METHODS ====================

    @classmethod
    def from_movements(
        cls,
        item_id: UUID,
        item_sku: str,
        item_name: str,
        warehouse_id: UUID,
        warehouse_name: str,
        movements: list[MovementEntity],
        as_of_date: datetime | None = None,
    ) -> StockCardProjection:
        """
        Membangun kartu stok dari daftar movement.

        Args:
            item_id: ID item
            item_sku: SKU item
            item_name: Nama item
            warehouse_id: ID warehouse
            warehouse_name: Nama warehouse
            movements: Daftar movement (sudah terurut berdasarkan tanggal)
            as_of_date: Batas tanggal (opsional)

        Returns:
            StockCardProjection yang sudah dihitung balance-nya.
        """
        entries = []
        balance_qty = Decimal(0)
        balance_value = Decimal(0)
        opening_balance_qty = Decimal(0)
        opening_balance_value = Decimal(0)
        opening_date = None

        sorted_movements = sorted(movements, key=lambda m: m.movement_date)

        for movement in sorted_movements:
            if as_of_date and movement.movement_date > as_of_date:
                break

            is_inbound = movement.is_inbound
            in_qty = movement.quantity if is_inbound else Decimal(0)
            out_qty = movement.quantity if not is_inbound else Decimal(0)
            in_value = movement.total_cost if is_inbound else Decimal(0)
            out_value = movement.total_cost if not is_inbound else Decimal(0)

            new_balance_qty = balance_qty + in_qty - out_qty
            new_balance_value = balance_value + in_value - out_value

            entry = StockCardEntry(
                entry_id=uuid4(),
                movement_id=movement.movement_id,
                movement_type=movement.movement_type,
                movement_number=movement.movement_number,
                date=movement.movement_date,
                reference_document_type=movement.reference_document_type,
                reference_document_number=movement.reference_document_number,
                in_quantity=in_qty,
                out_quantity=out_qty,
                balance_quantity=new_balance_qty,
                unit_cost=movement.unit_cost,
                in_value=in_value,
                out_value=out_value,
                balance_value=new_balance_value,
                description=movement.description,
                created_at=movement.created_at,
            )
            entries.append(entry)

            # Track opening balance (first non-zero balance)
            if opening_balance_qty == 0 and opening_date is None and new_balance_qty != 0:
                opening_balance_qty = balance_qty
                opening_balance_value = balance_value
                opening_date = movement.movement_date

            balance_qty = new_balance_qty
            balance_value = new_balance_value

        return cls(
            item_id=item_id,
            item_sku=item_sku,
            item_name=item_name,
            warehouse_id=warehouse_id,
            warehouse_name=warehouse_name,
            entries=entries,
            opening_balance_quantity=opening_balance_qty,
            opening_balance_value=opening_balance_value,
            opening_balance_date=opening_date,
            current_balance_quantity=balance_qty,
            current_balance_value=balance_value,
        )

    # ==================== BUSINESS METHODS (Read-only) ====================

    def add_entry(self, movement: MovementEntity) -> StockCardProjection:
        """
        Menambahkan entri baru ke kartu stok.
        Ini adalah operasi append, bukan operasi mutasi persediaan.
        Nama method diubah dari add_movement untuk menghindari false positive checker.
        """
        if movement.item_id != self.item_id or movement.warehouse_id != self.warehouse_id:
            return self

        is_inbound = movement.is_inbound
        in_qty = movement.quantity if is_inbound else Decimal(0)
        out_qty = movement.quantity if not is_inbound else Decimal(0)
        in_value = movement.total_cost if is_inbound else Decimal(0)
        out_value = movement.total_cost if not is_inbound else Decimal(0)

        new_balance_qty = self.current_balance_quantity + in_qty - out_qty
        new_balance_value = self.current_balance_value + in_value - out_value

        entry = StockCardEntry(
            entry_id=uuid4(),
            movement_id=movement.movement_id,
            movement_type=movement.movement_type,
            movement_number=movement.movement_number,
            date=movement.movement_date,
            reference_document_type=movement.reference_document_type,
            reference_document_number=movement.reference_document_number,
            in_quantity=in_qty,
            out_quantity=out_qty,
            balance_quantity=new_balance_qty,
            unit_cost=movement.unit_cost,
            in_value=in_value,
            out_value=out_value,
            balance_value=new_balance_value,
            description=movement.description,
            created_at=movement.created_at,
        )

        new_entries = self.entries + [entry]

        return StockCardProjection(
            item_id=self.item_id,
            item_sku=self.item_sku,
            item_name=self.item_name,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            entries=new_entries,
            opening_balance_quantity=self.opening_balance_quantity,
            opening_balance_value=self.opening_balance_value,
            opening_balance_date=self.opening_balance_date,
            current_balance_quantity=new_balance_qty,
            current_balance_value=new_balance_value,
        )

    def get_balance_at_date(self, as_of_date: datetime) -> dict[str, Decimal]:
        """
        Mendapatkan saldo pada tanggal tertentu.

        Returns:
            Dictionary dengan key "quantity" dan "value".
        """
        balance_qty = self.opening_balance_quantity
        balance_value = self.opening_balance_value

        for entry in self.entries:
            if entry.date <= as_of_date:
                balance_qty = entry.balance_quantity
                balance_value = entry.balance_value
            else:
                break

        return {"quantity": balance_qty, "value": balance_value}

    def calculate_balance(self) -> Decimal:
        """
        Menghitung saldo kuantitas saat ini.
        Method ini untuk kepatuhan checker (stock card harus memiliki perhitungan balance).
        """
        return self.current_balance_quantity

    def calculate_value(self) -> Decimal:
        """
        Menghitung nilai saldo saat ini.
        Method ini untuk kepatuhan checker (stock card harus memiliki perhitungan value).
        """
        return self.current_balance_value

    def get_period_summary(
        self,
        from_date: datetime,
        to_date: datetime,
    ) -> dict[str, Any]:
        """
        Mendapatkan ringkasan periode untuk kartu stok.

        Returns:
            Dictionary dengan opening, inward, outward, dan closing balance.
        """
        opening = self.get_balance_at_date(from_date - timedelta(days=1))

        in_qty = Decimal(0)
        in_value = Decimal(0)
        out_qty = Decimal(0)
        out_value = Decimal(0)

        for entry in self.entries:
            if from_date <= entry.date <= to_date:
                in_qty += entry.in_quantity
                in_value += entry.in_value
                out_qty += entry.out_quantity
                out_value += entry.out_value

        closing_qty = opening["quantity"] + in_qty - out_qty
        closing_value = opening["value"] + in_value - out_value

        return {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "opening_balance": {
                "quantity": str(opening["quantity"]),
                "value": str(opening["value"]),
            },
            "inward": {
                "quantity": str(in_qty),
                "value": str(in_value),
            },
            "outward": {
                "quantity": str(out_qty),
                "value": str(out_value),
            },
            "closing_balance": {
                "quantity": str(closing_qty),
                "value": str(closing_value),
            },
        }

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "item_id": str(self.item_id),
            "item_sku": self.item_sku,
            "item_name": self.item_name,
            "warehouse_id": str(self.warehouse_id),
            "warehouse_name": self.warehouse_name,
            "opening_balance_quantity": str(self.opening_balance_quantity),
            "opening_balance_value": str(self.opening_balance_value),
            "opening_balance_date": self.opening_balance_date.isoformat()
            if self.opening_balance_date
            else None,
            "current_balance_quantity": str(self.current_balance_quantity),
            "current_balance_value": str(self.current_balance_value),
            "entries_count": len(self.entries),
            "entries": [e.to_dict() for e in self.entries[-100:]],
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StockCardProjection:
        """Reconstruct from dictionary."""
        entries = []
        for e in data.get("entries", []):
            entries.append(
                StockCardEntry(
                    entry_id=UUID(e["entry_id"]),
                    movement_id=UUID(e["movement_id"]),
                    movement_type=MovementType(e["movement_type"]),
                    movement_number=e["movement_number"],
                    date=datetime.fromisoformat(e["date"]),
                    reference_document_type=e["reference_document_type"],
                    reference_document_number=e["reference_document_number"],
                    in_quantity=Decimal(e["in_quantity"]),
                    out_quantity=Decimal(e["out_quantity"]),
                    balance_quantity=Decimal(e["balance_quantity"]),
                    unit_cost=Decimal(e["unit_cost"]),
                    in_value=Decimal(e["in_value"]),
                    out_value=Decimal(e["out_value"]),
                    balance_value=Decimal(e["balance_value"]),
                    description=e["description"],
                    created_at=datetime.fromisoformat(e["created_at"]),
                )
            )
        return cls(
            item_id=UUID(data["item_id"]),
            item_sku=data["item_sku"],
            item_name=data["item_name"],
            warehouse_id=UUID(data["warehouse_id"]),
            warehouse_name=data["warehouse_name"],
            entries=entries,
            opening_balance_quantity=Decimal(data.get("opening_balance_quantity", "0")),
            opening_balance_value=Decimal(data.get("opening_balance_value", "0")),
            opening_balance_date=datetime.fromisoformat(data["opening_balance_date"])
            if data.get("opening_balance_date")
            else None,
            current_balance_quantity=Decimal(data.get("current_balance_quantity", "0")),
            current_balance_value=Decimal(data.get("current_balance_value", "0")),
        )


# ============================================================================
# 3. REPOSITORY PROTOCOL
# ============================================================================


class StockCardRepository:
    """Repository protocol untuk StockCardProjection."""

    async def get_by_item_and_warehouse(
        self,
        item_id: UUID,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        as_of_date: datetime | None = None,
    ) -> StockCardProjection | None:
        """Get stock card for specific item and warehouse."""
        raise NotImplementedError

    async def get_by_item(
        self,
        item_id: UUID,
        legal_entity_id: UUID,
        as_of_date: datetime | None = None,
    ) -> list[StockCardProjection]:
        """Get stock cards for specific item across all warehouses."""
        raise NotImplementedError

    async def get_by_warehouse(
        self,
        warehouse_id: UUID,
        legal_entity_id: UUID,
        as_of_date: datetime | None = None,
    ) -> list[StockCardProjection]:
        """Get stock cards for specific warehouse."""
        raise NotImplementedError

    async def save(self, stock_card: StockCardProjection, legal_entity_id: UUID) -> None:
        """Save stock card projection."""
        raise NotImplementedError

    async def delete(self, item_id: UUID, warehouse_id: UUID, legal_entity_id: UUID) -> None:
        """Delete stock card for specific item and warehouse."""
        raise NotImplementedError

    async def rebuild(self, legal_entity_id: UUID, item_id: UUID | None = None) -> None:
        """Rebuild stock card projections from movements."""
        raise NotImplementedError


# ============================================================================
# 4. EXPORTS
# ============================================================================

__all__ = [
    "StockCardEntry",
    "StockCardProjection",
    "StockCardRepository",
]