#!/usr/bin/env python3
"""
Module: sqlalchemy_inventory_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Inventory Management menggunakan
               SQLAlchemy ORM. LENGKAP dengan semua method yang dibutuhkan oleh port.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domain.inventory.aggregate_root import InventoryItemAggregate, StockMovement, StockMovementType
from domain.inventory.item_entity import ItemType, ValuationMethod
from domain.inventory.stock_opname_entity import StockOpname
from domain.inventory.valuation_method import FIFOLayer
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable
from infrastructure.persistence_orm.warehouse_table import WarehouseTable
from ports.primary.inventory_repository_port import InventoryMovement as PortInventoryMovement
from ports.primary.inventory_repository_port import InventoryRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================

class InventoryRepositoryError(Exception):
    pass


class DuplicateItemCodeError(InventoryRepositoryError):
    pass


class ItemNotFoundError(InventoryRepositoryError):
    pass


class InsufficientStockError(InventoryRepositoryError):
    pass


class FIFOLayerNotFoundError(InventoryRepositoryError):
    pass


class OptimisticLockError(InventoryRepositoryError):
    pass


class NegativeStockNotAllowedError(InventoryRepositoryError):
    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================

class SQLAlchemyInventoryRepository(InventoryRepositoryPort):
    """
    Implementasi repository Inventory dengan SQLAlchemy - LENGKAP.
    """

    def __init__(self, session: AsyncSession | None = None, legal_entity_id: UUID | None = None):
        self._session = session
        self._legal_entity_id = legal_entity_id
        self._audit_log: list[dict[str, Any]] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise InventoryRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    def _get_legal_entity_id(self, provided: UUID | None = None) -> UUID:
        """Get legal_entity_id from provided or fallback to instance attribute."""
        if provided is not None:
            return provided
        if self._legal_entity_id is not None:
            return self._legal_entity_id
        raise ValueError("legal_entity_id is required but not provided and not set in repository")

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain_item(self, table: InventoryItemTable) -> InventoryItemAggregate:
        item_type_map = {
            "raw_material": ItemType.RAW_MATERIAL,
            "work_in_process": ItemType.WORK_IN_PROCESS,
            "finished_good": ItemType.FINISHED_GOOD,
            "trading": ItemType.TRADING,
        }
        valuation_map = {
            "FIFO": ValuationMethod.FIFO,
            "LIFO": ValuationMethod.LIFO,
            "AVERAGE": ValuationMethod.AVERAGE,
            "STANDARD": ValuationMethod.STANDARD,
        }
        return InventoryItemAggregate(
            id=table.id,
            item_code=table.item_code,
            item_name=table.item_name,
            item_type=item_type_map.get(table.item_type, ItemType.TRADING),
            unit_of_measure=table.unit_of_measure,
            category=table.category,
            brand=table.brand,
            reorder_point=Quantity(value=table.reorder_point, uom=table.unit_of_measure),
            reorder_quantity=Quantity(value=table.reorder_quantity, uom=table.unit_of_measure),
            standard_cost=Money(amount=table.standard_cost, currency=table.currency_code or "IDR"),
            selling_price=Money(amount=table.selling_price, currency=table.currency_code or "IDR"),
            valuation_method=valuation_map.get(table.valuation_method, ValuationMethod.FIFO),
            is_active=table.is_active,
            current_stock=Quantity(value=table.current_stock, uom=table.unit_of_measure),
            average_cost=Money(amount=table.average_cost, currency=table.currency_code or "IDR"),
            last_cost=Money(amount=table.last_cost, currency=table.currency_code or "IDR"),
            warehouse_id=table.warehouse_id,
            min_stock=Quantity(value=table.min_stock, uom=table.unit_of_measure) if table.min_stock else None,
            max_stock=Quantity(value=table.max_stock, uom=table.unit_of_measure) if table.max_stock else None,
            description=table.description,
            tax_rate_purchase=table.tax_rate_purchase,
            tax_rate_sales=table.tax_rate_sales,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )

    async def _to_orm_item(self, aggregate: InventoryItemAggregate) -> InventoryItemTable:
        return InventoryItemTable(
            id=aggregate.id,
            item_code=aggregate.item_code,
            item_name=aggregate.item_name,
            item_type=aggregate.item_type.value if hasattr(aggregate.item_type, "value") else str(aggregate.item_type),
            unit_of_measure=aggregate.unit_of_measure,
            category=aggregate.category,
            brand=aggregate.brand,
            reorder_point=aggregate.reorder_point.value if aggregate.reorder_point else 0,
            reorder_quantity=aggregate.reorder_quantity.value if aggregate.reorder_quantity else 0,
            standard_cost=aggregate.standard_cost.amount,
            selling_price=aggregate.selling_price.amount,
            valuation_method=aggregate.valuation_method.value if hasattr(aggregate.valuation_method, "value") else str(aggregate.valuation_method),
            is_active=aggregate.is_active,
            current_stock=aggregate.current_stock.value,
            average_cost=aggregate.average_cost.amount,
            last_cost=aggregate.last_cost.amount,
            warehouse_id=aggregate.warehouse_id,
            min_stock=aggregate.min_stock.value if aggregate.min_stock else None,
            max_stock=aggregate.max_stock.value if aggregate.max_stock else None,
            description=aggregate.description,
            tax_rate_purchase=aggregate.tax_rate_purchase,
            tax_rate_sales=aggregate.tax_rate_sales,
            currency_code=aggregate.standard_cost.currency,
            created_at=aggregate.created_at,
            updated_at=datetime.utcnow(),
            created_by=aggregate.created_by,
            version=aggregate.version,
            legal_entity_id=aggregate.legal_entity_id,
        )

    def _to_domain_movement(self, table: InventoryMovementTable) -> StockMovement:
        movement_type_map = {
            "IN": StockMovementType.IN,
            "OUT": StockMovementType.OUT,
            "ADJUSTMENT": StockMovementType.ADJUSTMENT,
            "TRANSFER_IN": StockMovementType.TRANSFER_IN,
            "TRANSFER_OUT": StockMovementType.TRANSFER_OUT,
        }
        return StockMovement(
            id=table.id,
            movement_number=table.movement_number,
            item_id=table.item_id,
            movement_type=movement_type_map.get(table.movement_type, StockMovementType.IN),
            quantity=Quantity(value=table.quantity, uom=table.uom),
            unit_cost=Money(amount=table.unit_cost, currency=table.currency or "IDR"),
            total_cost=Money(amount=table.total_cost, currency=table.currency or "IDR"),
            movement_date=table.movement_date,
            reference_type=table.reference_type,
            reference_id=table.reference_id,
            warehouse_id=table.warehouse_id,
            to_warehouse_id=table.to_warehouse_id,
            batch_number=table.batch_number,
            expiry_date=table.expiry_date,
            notes=table.notes,
            created_at=table.created_at,
            created_by=table.created_by,
        )

    async def _to_orm_movement(self, movement: StockMovement) -> InventoryMovementTable:
        movement_type_str = movement.movement_type.value if hasattr(movement.movement_type, "value") else str(movement.movement_type)
        return InventoryMovementTable(
            id=movement.id,
            movement_number=movement.movement_number,
            item_id=movement.item_id,
            movement_type=movement_type_str,
            quantity=movement.quantity.value,
            uom=movement.quantity.uom,
            unit_cost=movement.unit_cost.amount,
            total_cost=movement.total_cost.amount,
            currency=movement.unit_cost.currency,
            movement_date=movement.movement_date,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            warehouse_id=movement.warehouse_id,
            to_warehouse_id=movement.to_warehouse_id,
            batch_number=movement.batch_number,
            expiry_date=movement.expiry_date,
            notes=movement.notes,
            created_at=movement.created_at,
            created_by=movement.created_by,
        )

    def _to_domain_fifo_layer(self, table: InventoryFIFOLayerTable) -> FIFOLayer:
        """Map ORM FIFO layer to domain FIFOLayer."""
        return FIFOLayer(
            id=table.id,
            item_id=table.item_id,
            quantity=Quantity(value=table.quantity, uom=table.uom),
            cost_per_unit=Money(amount=table.cost_per_unit, currency=table.currency or "IDR"),
            layer_date=table.layer_date,
            remaining_quantity=Quantity(value=table.remaining_quantity, uom=table.uom),
            created_at=table.created_at,
        )

    def _port_movement_to_domain(self, movement: PortInventoryMovement) -> StockMovement:
        """Convert port InventoryMovement to domain StockMovement."""
        # Map movement_type from port enum to domain enum
        from ports.primary.inventory_repository_port import (
            InventoryMovementType as PortMovementType,
        )
        type_map = {
            PortMovementType.PURCHASE_IN: StockMovementType.IN,
            PortMovementType.SALES_OUT: StockMovementType.OUT,
            PortMovementType.PRODUCTION_IN: StockMovementType.IN,
            PortMovementType.PRODUCTION_OUT: StockMovementType.OUT,
            PortMovementType.ADJUSTMENT_IN: StockMovementType.ADJUSTMENT,
            PortMovementType.ADJUSTMENT_OUT: StockMovementType.ADJUSTMENT,
            PortMovementType.TRANSFER_IN: StockMovementType.TRANSFER_IN,
            PortMovementType.TRANSFER_OUT: StockMovementType.TRANSFER_OUT,
            PortMovementType.RETURN_IN: StockMovementType.IN,
            PortMovementType.RETURN_OUT: StockMovementType.OUT,
            PortMovementType.SCRAP: StockMovementType.OUT,
            PortMovementType.SAMPLE: StockMovementType.OUT,
        }
        domain_type = type_map.get(movement.movement_type, StockMovementType.IN)
        return StockMovement(
            id=movement.id,
            movement_number=None,  # akan digenerate saat save
            item_id=movement.item_id,
            movement_type=domain_type,
            quantity=Quantity(value=movement.quantity, uom="PCS"),  # uom from item later
            unit_cost=Money(amount=movement.unit_cost, currency="IDR"),
            total_cost=Money(amount=movement.total_cost, currency="IDR"),
            movement_date=movement.movement_date,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            warehouse_id=movement.warehouse_id,
            to_warehouse_id=None,
            batch_number=movement.lot_number,
            expiry_date=movement.expiry_date,
            notes=movement.notes,
            created_at=movement.created_at,
            created_by=movement.created_by,
        )

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def _log_audit(self, action: str, item_id: UUID, details: dict[str, Any]) -> None:
        self._audit_log.append({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "item_id": str(item_id),
            "details": details,
        })
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ========================================================================
    # ITEM METHODS (EXISTING, renamed to match port)
    # ========================================================================

    async def add_item(self, item: InventoryItemAggregate) -> None:
        try:
            exists = await self.exists_by_item_code(item.item_code, item.legal_entity_id)
            if exists:
                raise DuplicateItemCodeError(f"Item code {item.item_code} already exists")
            table = await self._to_orm_item(item)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("ADD", item.id, {"item_code": item.item_code})
            logger.info("Item added: %s", item.item_code)
        except DuplicateItemCodeError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to add item: {e}") from e

    async def get_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        try:
            stmt = select(InventoryItemTable).where(InventoryItemTable.id == item_id, InventoryItemTable.deleted_at.is_(None))
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_item(table) if table else None
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get item: {e}") from e

    async def get_item_by_code(self, item_code: str, legal_entity_id: UUID) -> InventoryItemAggregate | None:
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.item_code == item_code,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_item(table) if table else None
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get item by code: {e}") from e

    async def get_item_by_sku(self, sku: str, legal_entity_id: UUID) -> InventoryItemAggregate | None:
        """Get item by SKU (alias for item_code)."""
        return await self.get_item_by_code(sku, legal_entity_id)

    async def update_item(self, item: InventoryItemAggregate) -> None:
        try:
            stmt = select(InventoryItemTable.version).where(InventoryItemTable.id == item.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()
            if current_version is None:
                raise ItemNotFoundError(f"Item {item.id} not found")
            if current_version != item.version:
                raise OptimisticLockError(f"Version mismatch: expected {item.version}, got {current_version}")
            table = await self._to_orm_item(item)
            table.version = item.version + 1
            table.updated_at = datetime.utcnow()
            await self.session.merge(table)
            await self.session.flush()
            await self._log_audit("UPDATE", item.id, {"item_code": item.item_code})
            logger.info("Item updated: %s", item.item_code)
        except (ItemNotFoundError, OptimisticLockError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to update item: {e}") from e

    async def delete_item(self, item_id: UUID) -> bool:
        try:
            stmt = update(InventoryItemTable).where(InventoryItemTable.id == item_id).values(deleted_at=datetime.utcnow(), is_active=False)
            result = await self.session.execute(stmt)
            await self.session.flush()
            if result.rowcount > 0:
                await self._log_audit("DELETE", item_id, {})
                logger.info("Item %s soft deleted", item_id)
            return result.rowcount > 0
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to delete item: {e}") from e

    async def exists_by_item_code(self, item_code: str, legal_entity_id: UUID) -> bool:
        try:
            stmt = select(func.count()).select_from(InventoryItemTable).where(
                InventoryItemTable.item_code == item_code,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar() > 0
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to check item code: {e}") from e

    # ========================================================================
    # QUERY METHODS (with signatures matching port)
    # ========================================================================

    async def get_all_items(
        self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[InventoryItemAggregate]:
        """Get all items for a legal entity with pagination."""
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            ).order_by(InventoryItemTable.item_code).limit(limit).offset(offset)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get all items: {e}") from e

    async def find_items_by_category(self, category: str, legal_entity_id: UUID | None = None) -> list[InventoryItemAggregate]:
        """Find items by category. legal_entity_id optional with fallback."""
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.category == category,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            ).order_by(InventoryItemTable.item_code)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to find items by category: {e}") from e

    # ===== FIX 1: get_items_below_reorder_point dengan legal_entity_id wajib =====
    async def get_items_below_reorder_point(self, legal_entity_id: UUID) -> list[InventoryItemAggregate]:
        """Get items with stock below reorder point for a legal entity."""
        conditions = [
            InventoryItemTable.legal_entity_id == legal_entity_id,
            InventoryItemTable.deleted_at.is_(None),
            InventoryItemTable.current_stock <= InventoryItemTable.reorder_point,
        ]
        try:
            stmt = select(InventoryItemTable).where(and_(*conditions)).order_by(InventoryItemTable.current_stock)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_item(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get items below reorder point: {e}") from e

    # ===== FIX 2: get_recommended_po_items dengan legal_entity_id wajib =====
    async def get_recommended_po_items(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Get items recommended for purchase order."""
        items = await self.get_items_below_reorder_point(legal_entity_id)
        result = []
        for item in items:
            shortage = item.reorder_point.value - item.current_stock.value
            if shortage > 0:
                result.append({
                    "item_id": str(item.id),
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "current_stock": float(item.current_stock.value),
                    "reorder_point": float(item.reorder_point.value),
                    "reorder_quantity": float(item.reorder_quantity.value) if item.reorder_quantity else 0,
                    "shortage": float(shortage),
                    "recommended_po": float(max(shortage, item.reorder_quantity.value or 0)),
                    "unit_cost": float(item.standard_cost.amount),
                })
        return result

    # ========================================================================
    # STOCK MOVEMENT METHODS (matching port signatures)
    # ========================================================================

    async def add_movement(self, movement: StockMovement) -> None:
        """Internal: save movement to DB."""
        try:
            table = await self._to_orm_movement(movement)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("MOVEMENT", movement.item_id, {"movement_number": movement.movement_number})
            logger.info("Movement added: %s", movement.movement_number)
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to add movement: {e}") from e

    async def record_movement(self, movement: PortInventoryMovement) -> None:
        """
        Record a stock movement from port DTO.
        Signature matches InventoryRepositoryPort.record_movement.
        """
        # Convert port movement to domain StockMovement
        domain_movement = self._port_movement_to_domain(movement)
        # Ensure movement_number is generated
        domain_movement.movement_number = await self.get_next_movement_number()
        # Update item stock
        item = await self.get_item_by_id(domain_movement.item_id)
        if not item:
            raise ItemNotFoundError(f"Item {domain_movement.item_id} not found")
        # Determine sign
        if domain_movement.movement_type in (StockMovementType.IN, StockMovementType.TRANSFER_IN):
            delta = domain_movement.quantity.value
        else:
            delta = -domain_movement.quantity.value
        # Compute unit cost if not set (for OUT movements, use FIFO or avg)
        if delta < 0:
            # For out movements, we might need to calculate cost from FIFO layers
            # Use average cost as fallback
            domain_movement.unit_cost = Money(amount=item.average_cost.amount, currency=item.average_cost.currency)
            domain_movement.total_cost = Money(
                amount=domain_movement.unit_cost.amount * domain_movement.quantity.value,
                currency=domain_movement.unit_cost.currency
            )
        # Update stock
        new_stock = item.current_stock.value + delta
        if new_stock < 0:
            raise InsufficientStockError(f"Insufficient stock: {item.current_stock.value} < {-delta}")
        # Update average cost for IN movements
        if delta > 0:
            total_value = item.average_cost.amount * item.current_stock.value + domain_movement.total_cost.amount
            new_avg = total_value / new_stock if new_stock > 0 else domain_movement.unit_cost.amount
            item.average_cost = Money(amount=new_avg, currency=item.average_cost.currency)
        item.current_stock = Quantity(value=new_stock, uom=item.unit_of_measure)
        item.version += 1
        await self.update_item(item)
        # Save movement
        await self.add_movement(domain_movement)

    async def get_movements_by_item(
        self, item_id: UUID, start_date: date, end_date: date, limit: int = 100
    ) -> list[StockMovement]:
        """Get movements for an item within date range. Signature matches port."""
        conditions = [InventoryMovementTable.item_id == item_id]
        if start_date:
            conditions.append(InventoryMovementTable.movement_date >= start_date)
        if end_date:
            conditions.append(InventoryMovementTable.movement_date <= end_date)
        try:
            stmt = select(InventoryMovementTable).where(and_(*conditions)).order_by(
                InventoryMovementTable.movement_date.desc()
            ).limit(limit)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_movement(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get movements: {e}") from e

    async def get_movements_by_reference(self, reference_type: str, reference_id: UUID) -> list[StockMovement]:
        try:
            stmt = select(InventoryMovementTable).where(
                InventoryMovementTable.reference_type == reference_type,
                InventoryMovementTable.reference_id == reference_id,
            ).order_by(InventoryMovementTable.movement_date)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_movement(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get movements by reference: {e}") from e

    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID | None = None) -> Decimal:
        """Get current stock for item, optionally per warehouse."""
        try:
            if warehouse_id is None:
                stmt = select(InventoryItemTable.current_stock).where(InventoryItemTable.id == item_id)
                result = await self.session.execute(stmt)
                stock = result.scalar_one_or_none()
                return Decimal(str(stock)) if stock else Decimal(0)
            else:
                # For specific warehouse, sum movements
                stmt = select(
                    func.coalesce(
                        func.sum(
                            case(
                                (InventoryMovementTable.movement_type.in_(['IN', 'TRANSFER_IN']), InventoryMovementTable.quantity),
                                else_=-InventoryMovementTable.quantity
                            )
                        ), 0
                    )
                ).where(
                    InventoryMovementTable.item_id == item_id,
                    InventoryMovementTable.warehouse_id == warehouse_id,
                )
                result = await self.session.execute(stmt)
                return Decimal(str(result.scalar() or 0))
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get current stock: {e}") from e

    # ========================================================================
    # FIFO LAYERS (matching port signature)
    # ========================================================================

    async def get_fifo_layers(self, item_id: UUID, warehouse_id: UUID) -> list[FIFOLayer]:
        """Get FIFO layers for item and warehouse."""
        try:
            stmt = select(InventoryFIFOLayerTable).where(
                InventoryFIFOLayerTable.item_id == item_id,
                InventoryFIFOLayerTable.warehouse_id == warehouse_id,
                InventoryFIFOLayerTable.remaining_quantity > 0,
            ).order_by(InventoryFIFOLayerTable.layer_date)
            result = await self.session.execute(stmt)
            tables = result.scalars().all()
            return [self._to_domain_fifo_layer(t) for t in tables]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get FIFO layers: {e}") from e

    # ========================================================================
    # STOCK UPDATE
    # ========================================================================

    async def update_stock(self, item_id: UUID, quantity_delta: Decimal, new_quantity: Decimal, average_cost: Decimal) -> None:
        try:
            stmt = update(InventoryItemTable).where(InventoryItemTable.id == item_id).values(
                current_stock=new_quantity,
                average_cost=average_cost,
                updated_at=datetime.utcnow(),
            )
            await self.session.execute(stmt)
            await self.session.flush()
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to update stock: {e}") from e

    async def adjust_stock(self, item_id: UUID, quantity: Decimal) -> bool:
        item = await self.get_item_by_id(item_id)
        if not item:
            return False
        new_quantity = item.current_stock.value + quantity
        if new_quantity < 0:
            raise NegativeStockNotAllowedError(f"Stock would be negative: {new_quantity}")
        await self.update_stock(item_id, quantity, new_quantity, item.average_cost.amount)
        return True

    # ========================================================================
    # STOCK OPNAME (matching port signature)
    # ========================================================================

    async def create_stock_opname(self, warehouse_id: UUID, created_by: UUID, notes: str | None = None) -> UUID:
        """Create a new stock opname."""
        try:
            opname = StockOpname(
                id=uuid4(),
                warehouse_id=warehouse_id,
                opname_date=datetime.utcnow().date(),
                status="draft",
                lines=[],
                total_adjustments=Decimal(0),
                adjustment_value=Money(amount=Decimal(0), currency="IDR"),
                created_at=datetime.utcnow(),
                created_by=created_by,
            )
            table = StockOpnameTable(
                id=opname.id,
                opname_number=f"OPN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                warehouse_id=opname.warehouse_id,
                opname_date=opname.opname_date,
                status=opname.status,
                lines=opname.lines,
                total_adjustments=opname.total_adjustments,
                adjustment_value=opname.adjustment_value.amount,
                created_at=opname.created_at,
                created_by=opname.created_by,
            )
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("CREATE_OPNAME", opname.id, {"warehouse_id": str(warehouse_id)})
            return opname.id
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to create stock opname: {e}") from e

    async def record_opname_item(self, opname_id: UUID, item_id: UUID, physical_count: Decimal, system_count: Decimal, notes: str | None = None) -> None:
        """Record an item in stock opname."""
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id)
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            lines = opname_table.lines or []
            lines.append({
                "item_id": str(item_id),
                "physical_count": float(physical_count),
                "system_count": float(system_count),
                "difference": float(physical_count - system_count),
                "notes": notes,
                "recorded_at": datetime.utcnow().isoformat(),
            })
            total_adj = sum(Decimal(str(l["difference"])) for l in lines)
            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                lines=lines,
                total_adjustments=float(total_adj),
                updated_at=datetime.utcnow(),
            )
            await self.session.execute(stmt_update)
            await self.session.flush()
            await self._log_audit("RECORD_OPNAME_ITEM", item_id, {"opname_id": str(opname_id), "difference": float(physical_count - system_count)})
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to record opname item: {e}") from e

    async def complete_stock_opname(self, opname_id: UUID, closed_by: UUID, auto_adjust: bool = True) -> dict[str, Any]:
        """Complete stock opname, optionally apply adjustments."""
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id)
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            if opname_table.status != "draft":
                raise InventoryRepositoryError("Opname already completed")
            adjustments = []
            for line in opname_table.lines or []:
                diff = Decimal(str(line["difference"]))
                if diff != 0 and auto_adjust:
                    item_id = UUID(line["item_id"])
                    if diff > 0:
                        await self.adjust_stock(item_id, diff)
                    else:
                        await self.adjust_stock(item_id, diff)
                    adjustments.append({
                        "item_id": line["item_id"],
                        "difference": float(diff),
                    })
            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                status="completed",
                approved_by=closed_by,
                approved_at=datetime.utcnow(),
                adjustments_applied=auto_adjust,
            )
            await self.session.execute(stmt_update)
            await self.session.flush()
            await self._log_audit("COMPLETE_OPNAME", opname_id, {"auto_adjust": auto_adjust, "adjustments": len(adjustments)})
            return {"opname_id": str(opname_id), "adjustments": adjustments}
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to complete stock opname: {e}") from e

    # ========================================================================
    # TRANSFER STOCK (matching port signature)
    # ========================================================================

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
        """Transfer stock between warehouses."""
        if from_warehouse_id == to_warehouse_id:
            raise ValueError("Source and destination warehouses are the same")
        item = await self.get_item_by_id(item_id)
        if not item:
            raise ItemNotFoundError(f"Item {item_id} not found")
        cost = unit_cost if unit_cost is not None else item.average_cost.amount
        # Create transfer out movement
        mov_out = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("TRF_OUT"),
            item_id=item_id,
            movement_type=StockMovementType.TRANSFER_OUT,
            quantity=Quantity(value=quantity, uom=item.unit_of_measure),
            unit_cost=Money(amount=cost, currency=item.average_cost.currency),
            total_cost=Money(amount=cost * quantity, currency=item.average_cost.currency),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=from_warehouse_id,
            to_warehouse_id=to_warehouse_id,
            notes=f"Transfer out to {to_warehouse_id}",
            created_by=user_id,
        )
        await self.add_movement(mov_out)
        # Create transfer in movement
        mov_in = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("TRF_IN"),
            item_id=item_id,
            movement_type=StockMovementType.TRANSFER_IN,
            quantity=Quantity(value=quantity, uom=item.unit_of_measure),
            unit_cost=Money(amount=cost, currency=item.average_cost.currency),
            total_cost=Money(amount=cost * quantity, currency=item.average_cost.currency),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=to_warehouse_id,
            to_warehouse_id=from_warehouse_id,
            notes=f"Transfer in from {from_warehouse_id}",
            created_by=user_id,
        )
        await self.add_movement(mov_in)
        # Update item stock (decrease then increase)
        # Use record_movement via port? Better to manually update.
        new_stock = item.current_stock.value  # no change if both in and out same warehouse? Actually warehouse-specific, but for simplicity we keep item current_stock unchanged.
        # But we need to log audit
        await self._log_audit("TRANSFER", item_id, {"from": str(from_warehouse_id), "to": str(to_warehouse_id), "qty": float(quantity)})
        return mov_out.id, mov_in.id

    # ========================================================================
    # INVENTORY VALUE (matching port signature)
    # ========================================================================

    async def get_inventory_value(
        self, legal_entity_id: UUID, as_of_date: date, valuation_method: str = "AVERAGE"
    ) -> Decimal:
        """Get total inventory value as of date."""
        # For simplicity, we ignore as_of_date and use current stock
        # because we don't have historical stock snapshots.
        try:
            stmt = select(
                func.coalesce(func.sum(InventoryItemTable.current_stock * InventoryItemTable.average_cost), 0)
            ).where(
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
                InventoryItemTable.is_active == True,
            )
            result = await self.session.execute(stmt)
            value = result.scalar()
            return Decimal(str(value)) if value else Decimal(0)
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get inventory value: {e}") from e

    # ========================================================================
    # STATISTICS (matching port signature)
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        """Get inventory statistics."""
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            total_items = await self.session.execute(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.deleted_at.is_(None),
                )
            )
            total = total_items.scalar() or 0
            active = await self.session.execute(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.is_active == True,
                    InventoryItemTable.deleted_at.is_(None),
                )
            )
            active_count = active.scalar() or 0
            total_value = await self.get_inventory_value(legal_entity_id, date.today())
            low_stock = len(await self.get_items_below_reorder_point(legal_entity_id))
            total_movements = await self.session.execute(
                select(func.count()).select_from(InventoryMovementTable).where(
                    InventoryMovementTable.item_id.in_(
                        select(InventoryItemTable.id).where(
                            InventoryItemTable.legal_entity_id == legal_entity_id,
                            InventoryItemTable.deleted_at.is_(None),
                        )
                    )
                )
            )
            movements_count = total_movements.scalar() or 0
            return {
                "total_items": total,
                "active_items": active_count,
                "inactive_items": total - active_count,
                "total_inventory_value": float(total_value),
                "low_stock_items": low_stock,
                "total_movements": movements_count,
            }
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get statistics: {e}") from e

    # ========================================================================
    # EXPORT / IMPORT (matching port signature)
    # ========================================================================

    async def export_items_to_csv(self, legal_entity_id: UUID | None = None) -> str:
        """Export items to CSV."""
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        items = await self.get_all_items(legal_entity_id, limit=10000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "item_code", "item_name", "category", "item_type", "unit_of_measure",
            "current_stock", "reorder_point", "reorder_quantity", "standard_cost",
            "selling_price", "valuation_method", "warehouse_id", "is_active"
        ])
        for item in items:
            writer.writerow([
                item.item_code,
                item.item_name,
                item.category or "",
                item.item_type.value,
                item.unit_of_measure,
                float(item.current_stock.value),
                float(item.reorder_point.value) if item.reorder_point else 0,
                float(item.reorder_quantity.value) if item.reorder_quantity else 0,
                float(item.standard_cost.amount),
                float(item.selling_price.amount),
                item.valuation_method.value,
                str(item.warehouse_id) if item.warehouse_id else "",
                "1" if item.is_active else "0",
            ])
        return output.getvalue()

    async def import_items_from_csv(self, csv_content: str, legal_entity_id: UUID, created_by: UUID) -> int:
        reader = csv.DictReader(io.StringIO(csv_content))
        count = 0
        for row in reader:
            try:
                item = InventoryItemAggregate(
                    id=uuid4(),
                    item_code=row["item_code"],
                    item_name=row["item_name"],
                    category=row.get("category"),
                    item_type=ItemType(row.get("item_type", "trading")),
                    unit_of_measure=row.get("unit_of_measure", "PCS"),
                    current_stock=Quantity(value=Decimal(row.get("current_stock", "0")), uom=row.get("unit_of_measure", "PCS")),
                    reorder_point=Quantity(value=Decimal(row.get("reorder_point", "0")), uom=row.get("unit_of_measure", "PCS")),
                    reorder_quantity=Quantity(value=Decimal(row.get("reorder_quantity", "0")), uom=row.get("unit_of_measure", "PCS")),
                    standard_cost=Money(amount=Decimal(row.get("standard_cost", "0")), currency="IDR"),
                    selling_price=Money(amount=Decimal(row.get("selling_price", "0")), currency="IDR"),
                    valuation_method=ValuationMethod(row.get("valuation_method", "FIFO")),
                    warehouse_id=UUID(row["warehouse_id"]) if row.get("warehouse_id") else None,
                    is_active=row.get("is_active", "1") == "1",
                    legal_entity_id=legal_entity_id,
                    created_by=created_by,
                )
                await self.add_item(item)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to import row: {e}")
        return count

    # ========================================================================
    # AUDIT LOG
    # ========================================================================

    async def get_audit_log(self, item_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if item_id:
            logs = [l for l in logs if l.get("item_id") == str(item_id)]
        return logs[-limit:]

    # ========================================================================
    # HEALTH CHECK
    # ========================================================================

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "InventoryRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "InventoryRepository", "error": str(e)}

    # ========================================================================
    # GENERATE MOVEMENT NUMBER
    # ========================================================================

    async def get_next_movement_number(self, prefix: str = "MOV", year: int = None) -> str:
        if year is None:
            year = date.today().year
        try:
            pattern = f"{prefix}-{year}-%"
            stmt = select(InventoryMovementTable.movement_number).where(
                InventoryMovementTable.movement_number.like(pattern)
            ).order_by(InventoryMovementTable.movement_number.desc()).limit(1)
            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()
            seq = int(last_number.split("-")[-1]) + 1 if last_number else 1
            return f"{prefix}-{year}-{seq:06d}"
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to generate movement number: {e}") from e

    # ========================================================================
    # ALIAS UNTUK KONTRAK PORT
    # ========================================================================

    async def find_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        return await self.get_item_by_id(item_id)

    async def save_item(self, item: InventoryItemAggregate) -> None:
        existing = await self.get_item_by_id(item.id)
        if existing:
            await self.update_item(item)
        else:
            await self.add_item(item)

    async def get_warehouses(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        try:
            stmt = select(WarehouseTable).where(WarehouseTable.legal_entity_id == legal_entity_id, WarehouseTable.is_active == True)
            result = await self.session.execute(stmt)
            warehouses = result.scalars().all()
            return [
                {"id": w.id, "code": w.code, "name": w.name, "location": w.location}
                for w in warehouses
            ]
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get warehouses: {e}") from e

    # ========================================================================
    # INVENTORY VALUATION (dari InventoryValuationRepositoryPort) - FIX 3
    # ========================================================================

    # ===== FIX 3: get_inventory_valuation dengan as_of_date wajib =====
    async def get_inventory_valuation(self, legal_entity_id: UUID, as_of_date: date) -> dict[str, Any]:
        """
        Get inventory valuation summary as of given date.
        Returns total value, breakdown by category, and details.
        """
        try:
            conditions = [
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
                InventoryItemTable.is_active == True,
            ]
            # For now, we ignore as_of_date and use current stock.
            # In future, we can implement historical valuation.
            total_value = await self.get_inventory_value(legal_entity_id, as_of_date)

            # Breakdown by category
            stmt = select(
                InventoryItemTable.category,
                func.sum(InventoryItemTable.current_stock * InventoryItemTable.average_cost).label('value')
            ).where(and_(*conditions)).group_by(InventoryItemTable.category)
            result = await self.session.execute(stmt)
            rows = result.all()
            by_category = {row.category or "Uncategorized": float(row.value) for row in rows}

            # Breakdown by warehouse
            stmt_wh = select(
                InventoryItemTable.warehouse_id,
                func.sum(InventoryItemTable.current_stock * InventoryItemTable.average_cost).label('value')
            ).where(and_(*conditions)).group_by(InventoryItemTable.warehouse_id)
            result_wh = await self.session.execute(stmt_wh)
            rows_wh = result_wh.all()
            by_warehouse = {str(row.warehouse_id): float(row.value) for row in rows_wh if row.warehouse_id}

            # Count items with stock > 0
            stmt_count = select(func.count()).where(
                and_(*conditions, InventoryItemTable.current_stock > 0)
            )
            count = await self.session.scalar(stmt_count) or 0

            return {
                "total_value": float(total_value),
                "item_count": count,
                "by_category": by_category,
                "by_warehouse": by_warehouse,
                "as_of_date": as_of_date.isoformat(),
                "currency": "IDR",
            }
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get inventory valuation: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

SQLAlchemyInventoryRepositoryImpl = SQLAlchemyInventoryRepository

__all__ = [
    "DuplicateItemCodeError",
    "FIFOLayerNotFoundError",
    "InsufficientStockError",
    "InventoryRepositoryError",
    "ItemNotFoundError",
    "NegativeStockNotAllowedError",
    "OptimisticLockError",
    "SQLAlchemyInventoryRepository",
    "SQLAlchemyInventoryRepositoryImpl",
]
