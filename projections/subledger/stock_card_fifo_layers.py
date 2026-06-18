#!/usr/bin/env python3
"""
Module: stock_card_fifo_layers.py
Layer: Projections (Subledger)
Responsibility: Membangun read model stock card (kartu stok) dengan tracking FIFO
               layers untuk inventory valuation. Mencatat setiap pergerakan stok
               (inbound/outbound) beserta cost layer-nya untuk perhitungan COGS
               dan ending inventory valuation. Mendukung query per item, warehouse,
               dan periode tertentu.
Dependencies:
- asyncio, logging, datetime, decimal
- sqlalchemy.ext.asyncio
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.persistence_orm.inventory_movement_table
- infrastructure.persistence_orm.inventory_item_table
- infrastructure.persistence_orm.warehouse_table
Audit: Stock card di-build dari event sourcing, digunakan untuk inventory valuation.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

PROJECTION_NAME = "stock_card_fifo_layers"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class StockCardFIFOError(Exception):
    """Base exception untuk stock card FIFO layers projection."""

    pass


# ============================================================================
# STOCK CARD FIFO LAYERS PROJECTION
# ============================================================================


class StockCardFIFOLayers:
    """
    Read model stock card dengan FIFO layers.

    Fitur:
    - Mencatat semua pergerakan stok per item
    - Menyimpan FIFO layers untuk valuation
    - Query stock card untuk periode tertentu
    - Menghitung ending inventory value
    - Mendukung multiple warehouse
    """

    def __init__(self):
        self._session_factory = None
        self._item_cache: dict[str, dict] = {}
        self._warehouse_cache: dict[str, str] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def rebuild_fifo_layers(self, item_id: UUID, legal_entity_id: UUID) -> None:
        """
        Membangun ulang FIFO layers untuk suatu item berdasarkan semua movement.
        """
        async with await self._get_session() as session:
            # Get all inbound movements for this item (IN, TRANSFER_IN)
            inbound_stmt = (
                select(InventoryMovementTable)
                .where(
                    InventoryMovementTable.item_id == item_id,
                    InventoryMovementTable.legal_entity_id == legal_entity_id,
                    InventoryMovementTable.movement_type.in_(["IN", "TRANSFER_IN"]),
                    InventoryMovementTable.deleted_at.is_(None),
                )
                .order_by(InventoryMovementTable.movement_date, InventoryMovementTable.created_at)
            )
            inbound_result = await session.execute(inbound_stmt)
            inbound_movements = inbound_result.scalars().all()

            # Delete existing layers for this item
            await session.execute(
                delete(InventoryFIFOLayerTable).where(
                    InventoryFIFOLayerTable.item_id == item_id,
                    InventoryFIFOLayerTable.legal_entity_id == legal_entity_id,
                )
            )

            # Create new layers from inbound movements
            for movement in inbound_movements:
                if movement.quantity > 0 and movement.unit_cost > 0:
                    layer = InventoryFIFOLayerTable(
                        id=uuid4(),
                        item_id=item_id,
                        quantity=movement.quantity,
                        remaining_quantity=movement.quantity,
                        uom=movement.uom,
                        unit_cost=movement.unit_cost,
                        currency=movement.currency,
                        purchase_date=movement.movement_date,
                        movement_id=movement.id,
                        legal_entity_id=legal_entity_id,
                        created_at=datetime.now(UTC),
                    )
                    session.add(layer)

            # Now process outbound movements to consume layers
            outbound_stmt = (
                select(InventoryMovementTable)
                .where(
                    InventoryMovementTable.item_id == item_id,
                    InventoryMovementTable.legal_entity_id == legal_entity_id,
                    InventoryMovementTable.movement_type.in_(["OUT", "TRANSFER_OUT"]),
                    InventoryMovementTable.deleted_at.is_(None),
                )
                .order_by(InventoryMovementTable.movement_date, InventoryMovementTable.created_at)
            )
            outbound_result = await session.execute(outbound_stmt)
            outbound_movements = outbound_result.scalars().all()

            for outbound in outbound_movements:
                quantity_to_consume = outbound.quantity
                # Get layers in FIFO order (oldest first) with remaining > 0
                layer_stmt = (
                    select(InventoryFIFOLayerTable)
                    .where(
                        InventoryFIFOLayerTable.item_id == item_id,
                        InventoryFIFOLayerTable.remaining_quantity > 0,
                        InventoryFIFOLayerTable.legal_entity_id == legal_entity_id,
                    )
                    .order_by(
                        InventoryFIFOLayerTable.purchase_date, InventoryFIFOLayerTable.created_at
                    )
                )
                layer_result = await session.execute(layer_stmt)
                layers = layer_result.scalars().all()

                for layer in layers:
                    if quantity_to_consume <= 0:
                        break
                    consume = min(quantity_to_consume, layer.remaining_quantity)
                    layer.remaining_quantity -= consume
                    quantity_to_consume -= consume
                    session.add(layer)

            await session.commit()
            logger.info(f"FIFO layers rebuilt for item {item_id}")

    async def rebuild_all_items(self, legal_entity_id: UUID) -> dict[str, Any]:
        """
        Membangun ulang FIFO layers untuk semua item dalam legal entity.
        """
        async with await self._get_session() as session:
            item_stmt = select(InventoryItemTable.id).where(
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            item_result = await session.execute(item_stmt)
            item_ids = item_result.scalars().all()

        success = 0
        errors = 0
        for item_id in item_ids:
            try:
                await self.rebuild_fifo_layers(item_id, legal_entity_id)
                success += 1
            except Exception as e:
                logger.error(f"Failed to rebuild FIFO layers for item {item_id}: {e}")
                errors += 1

        logger.info(f"FIFO layers rebuild completed: {success} items succeeded, {errors} failed")
        return {"success": success, "errors": errors}

    async def get_stock_card(
        self,
        item_id: UUID,
        warehouse_id: UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Mendapatkan stock card (mutasi stok) untuk item.
        """
        async with await self._get_session() as session:
            conditions = [
                InventoryMovementTable.item_id == item_id,
                InventoryMovementTable.deleted_at.is_(None),
            ]
            if warehouse_id:
                conditions.append(InventoryMovementTable.warehouse_id == warehouse_id)
            if start_date:
                conditions.append(InventoryMovementTable.movement_date >= start_date)
            if end_date:
                conditions.append(InventoryMovementTable.movement_date <= end_date)

            stmt = (
                select(InventoryMovementTable)
                .where(and_(*conditions))
                .order_by(InventoryMovementTable.movement_date, InventoryMovementTable.created_at)
                .limit(limit)
            )
            result = await session.execute(stmt)
            movements = result.scalars().all()

            # Get item name
            item_stmt = select(InventoryItemTable.item_code, InventoryItemTable.item_name).where(
                InventoryItemTable.id == item_id
            )
            item_result = await session.execute(item_stmt)
            item_row = item_result.first()
            item_code = item_row[0] if item_row else "N/A"
            item_name = item_row[1] if item_row else "N/A"

            # Calculate running balance
            balance = Decimal(0)
            entries = []
            for mv in movements:
                if mv.movement_type in ("IN", "TRANSFER_IN"):
                    balance += mv.quantity
                    in_qty = mv.quantity
                    out_qty = Decimal(0)
                else:
                    balance -= mv.quantity
                    in_qty = Decimal(0)
                    out_qty = mv.quantity

                entries.append(
                    {
                        "date": mv.movement_date.isoformat(),
                        "reference": mv.reference_number or mv.movement_number,
                        "movement_type": mv.movement_type,
                        "in_quantity": float(in_qty),
                        "out_quantity": float(out_qty),
                        "balance_quantity": float(balance),
                        "unit_cost": float(mv.unit_cost),
                        "total_cost": float(mv.total_cost),
                        "balance_value": float(balance * mv.unit_cost) if balance > 0 else 0,
                        "warehouse_id": str(mv.warehouse_id) if mv.warehouse_id else None,
                        "batch_number": mv.batch_number,
                    }
                )

            return {
                "item_id": str(item_id),
                "item_code": item_code,
                "item_name": item_name,
                "entries": entries,
                "total_in": float(
                    sum(m.quantity for m in movements if m.movement_type in ("IN", "TRANSFER_IN"))
                ),
                "total_out": float(
                    sum(m.quantity for m in movements if m.movement_type in ("OUT", "TRANSFER_OUT"))
                ),
                "closing_balance": float(balance),
            }

    async def get_fifo_layers(self, item_id: UUID, legal_entity_id: UUID) -> list[dict]:
        """
        Mendapatkan FIFO layers untuk suatu item (untuk inventory valuation).
        """
        async with await self._get_session() as session:
            stmt = (
                select(InventoryFIFOLayerTable)
                .where(
                    InventoryFIFOLayerTable.item_id == item_id,
                    InventoryFIFOLayerTable.legal_entity_id == legal_entity_id,
                    InventoryFIFOLayerTable.remaining_quantity > 0,
                )
                .order_by(InventoryFIFOLayerTable.purchase_date, InventoryFIFOLayerTable.created_at)
            )
            result = await session.execute(stmt)
            layers = result.scalars().all()

            total_value = Decimal(0)
            layer_list = []
            for layer in layers:
                value = layer.remaining_quantity * layer.unit_cost
                total_value += value
                layer_list.append(
                    {
                        "layer_id": str(layer.id),
                        "purchase_date": layer.purchase_date.isoformat(),
                        "quantity": float(layer.remaining_quantity),
                        "unit_cost": float(layer.unit_cost),
                        "total_value": float(value),
                        "uom": layer.uom,
                    }
                )

            return {
                "item_id": str(item_id),
                "total_quantity": float(sum(l.remaining_quantity for l in layers)),
                "total_value": float(total_value),
                "weighted_average_cost": float(
                    total_value / sum(l.remaining_quantity for l in layers)
                )
                if layers
                else 0,
                "layers": layer_list,
            }

    async def get_ending_inventory_value(self, legal_entity_id: UUID, as_of_date: date) -> Decimal:
        """
        Mendapatkan total nilai ending inventory pada tanggal tertentu.
        """
        # Get all items with active FIFO layers
        async with await self._get_session() as session:
            stmt = (
                select(
                    InventoryFIFOLayerTable.item_id,
                    func.sum(
                        InventoryFIFOLayerTable.remaining_quantity
                        * InventoryFIFOLayerTable.unit_cost
                    ).label("total_value"),
                )
                .where(
                    InventoryFIFOLayerTable.legal_entity_id == legal_entity_id,
                    InventoryFIFOLayerTable.purchase_date <= as_of_date,
                    InventoryFIFOLayerTable.remaining_quantity > 0,
                )
                .group_by(InventoryFIFOLayerTable.item_id)
            )
            result = await session.execute(stmt)
            rows = result.all()

            total_value = Decimal(0)
            for row in rows:
                total_value += Decimal(str(row[1]))
            return total_value

    async def get_item_valuation_detail(
        self, item_id: UUID, legal_entity_id: UUID, as_of_date: date
    ) -> dict:
        """
        Mendapatkan detail valuation untuk satu item.
        """
        stock_card = await self.get_stock_card(item_id, start_date=None, end_date=as_of_date)
        fifo_layers = await self.get_fifo_layers(item_id, legal_entity_id)

        return {
            "item_id": str(item_id),
            "item_code": stock_card["item_code"],
            "item_name": stock_card["item_name"],
            "as_of_date": as_of_date.isoformat(),
            "current_stock": stock_card["closing_balance"],
            "valuation_method": "FIFO",
            "total_value": fifo_layers["total_value"],
            "weighted_average_cost": fifo_layers["weighted_average_cost"],
            "fifo_layers": fifo_layers["layers"],
        }

    async def rebuild_for_movement(self, movement_id: UUID) -> None:
        """
        Incremental update ketika ada movement baru (dipanggil oleh event listener).
        """
        async with await self._get_session() as session:
            movement_stmt = select(InventoryMovementTable).where(
                InventoryMovementTable.id == movement_id,
                InventoryMovementTable.deleted_at.is_(None),
            )
            movement_result = await session.execute(movement_stmt)
            movement = movement_result.scalar_one_or_none()
            if not movement:
                return

            # Rebuild layers for the item
            await self.rebuild_fifo_layers(movement.item_id, movement.legal_entity_id)
            logger.info(f"FIFO layers updated due to movement {movement_id}")


# ============================================================================
# ORM MODEL (tambahan - sudah ada di persistence_orm, tapi referensi)
# ============================================================================

# InventoryFIFOLayerTable sudah didefinisikan di infrastructure.persistence_orm.inventory_fifo_layer_table
# Kita gunakan dari sana

# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_stock_card_fifo: StockCardFIFOLayers | None = None


async def get_stock_card_fifo() -> StockCardFIFOLayers:
    """Get singleton instance of StockCardFIFOLayers."""
    global _stock_card_fifo
    if _stock_card_fifo is None:
        _stock_card_fifo = StockCardFIFOLayers()
    return _stock_card_fifo


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["StockCardFIFOError", "StockCardFIFOLayers", "get_stock_card_fifo"]
