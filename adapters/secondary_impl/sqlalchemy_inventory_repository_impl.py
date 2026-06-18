#!/usr/bin/env python3
"""
Module: sqlalchemy_inventory_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository untuk Inventory Management menggunakan
               SQLAlchemy ORM. Menyediakan operasi CRUD untuk item, stock movement,
               stock opname, inter-warehouse transfer, FIFO valuation, stock card,
               dan low stock alerts. Mendukung optimistic locking untuk item master
               dan batch update untuk stock levels.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- sqlalchemy import select, update, func, and_, or_
- ports.primary.inventory_repository_port (InventoryRepositoryPort)
- domain.inventory.aggregate_root (InventoryItemAggregate, StockMovement)
- infrastructure.persistence_orm.inventory_item_table, inventory_movement_table
- infrastructure.persistence_orm.warehouse_table
- domain.shared_value_objects.money_vo (Money)
- domain.shared_value_objects.quantity_vo (Quantity)
Audit: Setiap pergerakan stock (IN, OUT, ADJUSTMENT) dicatat di event store.
       FIFO layers juga dilacak untuk valuation accuracy.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Domain
from domain.inventory.aggregate_root import InventoryItemAggregate, StockMovement, StockMovementType
from domain.inventory.item_entity import ItemType, ValuationMethod
from domain.inventory.stock_opname_entity import StockOpname
from domain.inventory.valuation_method import FIFOLayer

# Value objects
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable

# Infrastructure ORM
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable
from infrastructure.persistence_orm.warehouse_table import WarehouseTable

# Ports
from ports.primary.inventory_repository_port import InventoryRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class InventoryRepositoryError(Exception):
    """Base exception untuk repository inventory."""

    pass


class DuplicateItemCodeError(InventoryRepositoryError):
    """Kode item sudah ada."""

    pass


class ItemNotFoundError(InventoryRepositoryError):
    """Item tidak ditemukan."""

    pass


class InsufficientStockError(InventoryRepositoryError):
    """Stok tidak mencukupi untuk pengeluaran."""

    pass


class FIFOLayerNotFoundError(InventoryRepositoryError):
    """Lapisan FIFO tidak ditemukan."""

    pass


class OptimisticLockError(InventoryRepositoryError):
    """Version mismatch saat update."""

    pass


class NegativeStockNotAllowedError(InventoryRepositoryError):
    """Stok negatif tidak diizinkan."""

    pass


# ============================================================================
# REPOSITORY IMPLEMENTATION
# ============================================================================


class SQLAlchemyInventoryRepository(InventoryRepositoryPort):
    """
    Implementasi repository Inventory dengan SQLAlchemy.
    """

    def __init__(self, session: AsyncSession | None = None):
        self._session = session

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise InventoryRepositoryError("Session not set")
        return self._session

    @session.setter
    def session(self, value: AsyncSession) -> None:
        self._session = value

    # ========================================================================
    # HELPER MAPPING METHODS
    # ========================================================================

    def _to_domain_item(self, table: InventoryItemTable) -> InventoryItemAggregate:
        """
        Mapping dari ORM model ke domain aggregate Item.
        """
        # Map enums
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

        aggregate = InventoryItemAggregate(
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
            min_stock=Quantity(value=table.min_stock, uom=table.unit_of_measure)
            if table.min_stock
            else None,
            max_stock=Quantity(value=table.max_stock, uom=table.unit_of_measure)
            if table.max_stock
            else None,
            description=table.description,
            tax_rate_purchase=table.tax_rate_purchase,
            tax_rate_sales=table.tax_rate_sales,
            created_at=table.created_at,
            updated_at=table.updated_at,
            created_by=table.created_by,
            version=table.version,
            legal_entity_id=table.legal_entity_id,
        )
        return aggregate

    async def _to_orm_item(self, aggregate: InventoryItemAggregate) -> InventoryItemTable:
        """Mapping dari domain ke ORM item."""
        table = InventoryItemTable(
            id=aggregate.id,
            item_code=aggregate.item_code,
            item_name=aggregate.item_name,
            item_type=aggregate.item_type.value
            if hasattr(aggregate.item_type, "value")
            else str(aggregate.item_type),
            unit_of_measure=aggregate.unit_of_measure,
            category=aggregate.category,
            brand=aggregate.brand,
            reorder_point=aggregate.reorder_point.value if aggregate.reorder_point else 0,
            reorder_quantity=aggregate.reorder_quantity.value if aggregate.reorder_quantity else 0,
            standard_cost=aggregate.standard_cost.amount,
            selling_price=aggregate.selling_price.amount,
            valuation_method=aggregate.valuation_method.value
            if hasattr(aggregate.valuation_method, "value")
            else str(aggregate.valuation_method),
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
        return table

    def _to_domain_movement(self, table: InventoryMovementTable) -> StockMovement:
        """Mapping movement ORM ke domain."""
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
        """Mapping domain movement ke ORM."""
        movement_type_str = (
            movement.movement_type.value
            if hasattr(movement.movement_type, "value")
            else str(movement.movement_type)
        )

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

    # ========================================================================
    # ITEM METHODS
    # ========================================================================

    async def add_item(self, item: InventoryItemAggregate) -> None:
        """
        Menambahkan item baru.
        """
        try:
            # Cek duplikasi item code
            exists = await self.exists_by_item_code(item.item_code, item.legal_entity_id)
            if exists:
                raise DuplicateItemCodeError(
                    f"Item code {item.item_code} already exists"
                )

            table = await self._to_orm_item(item)
            self.session.add(table)
            await self.session.flush()
            logger.info("Item added: %s (id=%s)", item.item_code, item.id)

        except DuplicateItemCodeError:
            raise
        except IntegrityError as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Integrity error: {e}") from e
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add item: %s", e)
            raise InventoryRepositoryError(f"Failed to add item: {e}") from e

    async def get_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        """Mengambil item berdasarkan ID."""
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.id == item_id, InventoryItemTable.deleted_at.is_(None)
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain_item(table)

        except Exception as e:
            logger.error("Failed to get item by id %s: %s", item_id, e)
            raise InventoryRepositoryError(f"Failed to get item: {e}") from e

    async def get_item_by_code(
        self, item_code: str, legal_entity_id: UUID
    ) -> InventoryItemAggregate | None:
        """Mengambil item berdasarkan kode item."""
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.item_code == item_code,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()

            if not table:
                return None
            return self._to_domain_item(table)

        except Exception as e:
            logger.error("Failed to get item by code %s: %s", item_code, e)
            raise InventoryRepositoryError(f"Failed to get item: {e}") from e

    async def update_item(self, item: InventoryItemAggregate) -> None:
        """Memperbarui data item."""
        try:
            # Get current version
            stmt = select(InventoryItemTable.version).where(InventoryItemTable.id == item.id)
            result = await self.session.execute(stmt)
            current_version = result.scalar_one_or_none()

            if current_version is None:
                raise ItemNotFoundError(f"Item {item.id} not found")

            if current_version != item.version:
                raise OptimisticLockError(
                    f"Version mismatch: expected {item.version}, got {current_version}"
                )

            table = await self._to_orm_item(item)
            table.version = item.version + 1
            table.updated_at = datetime.utcnow()

            await self.session.merge(table)
            await self.session.flush()
            logger.info("Item updated: %s", item.item_code)

        except OptimisticLockError:
            raise
        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to update item %s: %s", item.id, e)
            raise InventoryRepositoryError(f"Failed to update item: {e}") from e

    async def delete_item(self, item_id: UUID) -> bool:
        """Soft delete item."""
        try:
            stmt = (
                update(InventoryItemTable)
                .where(InventoryItemTable.id == item_id)
                .values(deleted_at=datetime.utcnow(), is_active=False)
            )
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount > 0

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to delete item %s: %s", item_id, e)
            raise InventoryRepositoryError(f"Failed to delete item: {e}") from e

    async def list_items(
        self,
        legal_entity_id: UUID,
        item_type: str | None = None,
        category: str | None = None,
        is_active: bool | None = True,
        low_stock_only: bool = False,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[InventoryItemAggregate], int]:
        """List items dengan filter dan pagination."""
        try:
            conditions = [
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            ]

            if item_type:
                conditions.append(InventoryItemTable.item_type == item_type)
            if category:
                conditions.append(InventoryItemTable.category == category)
            if is_active is not None:
                conditions.append(InventoryItemTable.is_active == is_active)
            if low_stock_only:
                conditions.append(
                    InventoryItemTable.current_stock <= InventoryItemTable.reorder_point
                )
            if search:
                # Menggunakan func.concat untuk menghindari f-string dalam SQL
                conditions.append(
                    or_(
                        InventoryItemTable.item_code.ilike(func.concat('%', search, '%')),
                        InventoryItemTable.item_name.ilike(func.concat('%', search, '%')),
                    )
                )

            # Get total count
            count_stmt = (
                select(func.count()).select_from(InventoryItemTable).where(and_(*conditions))
            )
            count_result = await self.session.execute(count_stmt)
            total = count_result.scalar()

            # Get items
            offset = (page - 1) * page_size
            stmt = (
                select(InventoryItemTable)
                .where(and_(*conditions))
                .order_by(InventoryItemTable.item_code)
                .limit(page_size)
                .offset(offset)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            items = [self._to_domain_item(table) for table in tables]
            return items, total

        except Exception as e:
            logger.error("Failed to list items: %s", e)
            raise InventoryRepositoryError(f"Failed to list items: {e}") from e

    async def update_stock(
        self, item_id: UUID, quantity_delta: Decimal, new_quantity: Decimal, average_cost: Decimal
    ) -> None:
        """Update current stock dan average cost."""
        try:
            stmt = (
                update(InventoryItemTable)
                .where(InventoryItemTable.id == item_id)
                .values(
                    current_stock=new_quantity,
                    average_cost=average_cost,
                    updated_at=datetime.utcnow(),
                )
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            logger.error("Failed to update stock for item %s: %s", item_id, e)
            raise InventoryRepositoryError(f"Failed to update stock: {e}") from e

    async def exists_by_item_code(self, item_code: str, legal_entity_id: UUID) -> bool:
        """Check apakah item code sudah ada."""
        try:
            stmt = (
                select(func.count())
                .select_from(InventoryItemTable)
                .where(
                    InventoryItemTable.item_code == item_code,
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.deleted_at.is_(None),
                )
            )
            result = await self.session.execute(stmt)
            count = result.scalar()
            return count > 0

        except Exception as e:
            logger.error("Failed to check item code %s: %s", item_code, e)
            raise InventoryRepositoryError(f"Failed to check item code: {e}") from e

    # ========================================================================
    # STOCK MOVEMENT METHODS
    # ========================================================================

    async def add_movement(self, movement: StockMovement) -> None:
        """Menambahkan pergerakan stock."""
        try:
            table = await self._to_orm_movement(movement)
            self.session.add(table)
            await self.session.flush()
            logger.info(
                "Movement added: %s for item %s",
                movement.movement_number,
                movement.item_id
            )

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add movement: %s", e)
            raise InventoryRepositoryError(f"Failed to add movement: {e}") from e

    async def get_movements_by_item(
        self,
        item_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 100,
    ) -> list[StockMovement]:
        """Mendapatkan semua pergerakan stock untuk item."""
        try:
            conditions = [InventoryMovementTable.item_id == item_id]
            if start_date:
                conditions.append(InventoryMovementTable.movement_date >= start_date)
            if end_date:
                conditions.append(InventoryMovementTable.movement_date <= end_date)

            stmt = (
                select(InventoryMovementTable)
                .where(and_(*conditions))
                .order_by(InventoryMovementTable.movement_date)
                .limit(limit)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            return [self._to_domain_movement(table) for table in tables]

        except Exception as e:
            logger.error("Failed to get movements for item %s: %s", item_id, e)
            raise InventoryRepositoryError(f"Failed to get movements: {e}") from e

    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID) -> Decimal:
        """Mendapatkan current stock untuk item di warehouse tertentu."""
        try:
            stmt = select(InventoryItemTable.current_stock).where(
                InventoryItemTable.id == item_id, InventoryItemTable.warehouse_id == warehouse_id
            )
            result = await self.session.execute(stmt)
            stock = result.scalar_one_or_none()
            return Decimal(str(stock)) if stock else Decimal(0)

        except Exception as e:
            logger.error("Failed to get current stock: %s", e)
            raise InventoryRepositoryError(f"Failed to get stock: {e}") from e

    # ========================================================================
    # FIFO LAYER METHODS
    # ========================================================================

    async def get_fifo_layers(self, item_id: UUID) -> list[FIFOLayer]:
        """Mendapatkan FIFO layers untuk suatu item."""
        try:
            stmt = (
                select(InventoryFIFOLayerTable)
                .where(
                    InventoryFIFOLayerTable.item_id == item_id,
                    InventoryFIFOLayerTable.remaining_quantity > 0,
                )
                .order_by(InventoryFIFOLayerTable.created_at)
            )

            result = await self.session.execute(stmt)
            tables = result.scalars().all()

            layers = []
            for table in tables:
                layers.append(
                    FIFOLayer(
                        id=table.id,
                        item_id=table.item_id,
                        quantity=Quantity(value=table.quantity, uom=table.uom),
                        remaining_quantity=Quantity(value=table.remaining_quantity, uom=table.uom),
                        unit_cost=Money(amount=table.unit_cost, currency=table.currency or "IDR"),
                        purchase_date=table.purchase_date,
                        movement_id=table.movement_id,
                    )
                )
            return layers

        except Exception as e:
            logger.error("Failed to get FIFO layers for item %s: %s", item_id, e)
            raise InventoryRepositoryError(f"Failed to get FIFO layers: {e}") from e

    async def add_fifo_layer(self, layer: FIFOLayer) -> None:
        """Menambahkan FIFO layer baru."""
        try:
            table = InventoryFIFOLayerTable(
                id=layer.id,
                item_id=layer.item_id,
                quantity=layer.quantity.value,
                remaining_quantity=layer.remaining_quantity.value,
                uom=layer.quantity.uom,
                unit_cost=layer.unit_cost.amount,
                currency=layer.unit_cost.currency,
                purchase_date=layer.purchase_date,
                movement_id=layer.movement_id,
                created_at=datetime.utcnow(),
            )
            self.session.add(table)
            await self.session.flush()

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to add FIFO layer: %s", e)
            raise InventoryRepositoryError(f"Failed to add FIFO layer: {e}") from e

    async def update_fifo_layer(self, layer_id: UUID, remaining_quantity: Decimal) -> None:
        """Update remaining quantity dari FIFO layer."""
        try:
            stmt = (
                update(InventoryFIFOLayerTable)
                .where(InventoryFIFOLayerTable.id == layer_id)
                .values(remaining_quantity=remaining_quantity, updated_at=datetime.utcnow())
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            logger.error("Failed to update FIFO layer %s: %s", layer_id, e)
            raise InventoryRepositoryError(f"Failed to update FIFO layer: {e}") from e

    # ========================================================================
    # STOCK OPNAME METHODS
    # ========================================================================

    async def create_stock_opname(self, opname: StockOpname) -> UUID:
        """Membuat record stock opname."""
        try:
            table = StockOpnameTable(
                id=opname.id,
                opname_number=opname.opname_number,
                warehouse_id=opname.warehouse_id,
                opname_date=opname.opname_date,
                status=opname.status,
                lines=opname.lines,
                total_adjustments=opname.total_adjustments,
                adjustment_value=opname.adjustment_value.amount if opname.adjustment_value else 0,
                created_at=datetime.utcnow(),
                created_by=opname.created_by,
            )
            self.session.add(table)
            await self.session.flush()
            return opname.id

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to create stock opname: %s", e)
            raise InventoryRepositoryError(f"Failed to create stock opname: {e}") from e

    async def approve_stock_opname(self, opname_id: UUID, approved_by: UUID) -> None:
        """Approve stock opname dan apply adjustments."""
        try:
            stmt = (
                update(StockOpnameTable)
                .where(StockOpnameTable.id == opname_id)
                .values(status="approved", approved_by=approved_by, approved_at=datetime.utcnow())
            )
            await self.session.execute(stmt)
            await self.session.flush()

        except Exception as e:
            await self.session.rollback()
            logger.error("Failed to approve stock opname %s: %s", opname_id, e)
            raise InventoryRepositoryError(f"Failed to approve opname: {e}") from e

    # ========================================================================
    # WAREHOUSE METHODS
    # ========================================================================

    async def get_warehouses(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        """Mendapatkan daftar warehouse."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.legal_entity_id == legal_entity_id, WarehouseTable.is_active == True
            )
            result = await self.session.execute(stmt)
            warehouses = result.scalars().all()

            return [
                {"id": w.id, "code": w.code, "name": w.name, "location": w.location}
                for w in warehouses
            ]

        except Exception as e:
            logger.error("Failed to get warehouses: %s", e)
            raise InventoryRepositoryError(f"Failed to get warehouses: {e}") from e

    # ========================================================================
    # LOW STOCK ALERTS
    # ========================================================================

    async def get_low_stock_items(
        self, legal_entity_id: UUID, warehouse_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        """Mendapatkan item dengan stok di bawah reorder point."""
        try:
            conditions = [
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.is_active == True,
                InventoryItemTable.current_stock <= InventoryItemTable.reorder_point,
            ]
            if warehouse_id:
                conditions.append(InventoryItemTable.warehouse_id == warehouse_id)

            stmt = select(
                InventoryItemTable.id,
                InventoryItemTable.item_code,
                InventoryItemTable.item_name,
                InventoryItemTable.current_stock,
                InventoryItemTable.reorder_point,
                InventoryItemTable.warehouse_id,
            ).where(and_(*conditions))

            result = await self.session.execute(stmt)
            rows = result.all()

            return [
                {
                    "item_id": row.id,
                    "item_code": row.item_code,
                    "item_name": row.item_name,
                    "current_stock": float(row.current_stock),
                    "reorder_point": float(row.reorder_point),
                    "shortage": float(row.reorder_point - row.current_stock)
                    if row.current_stock < row.reorder_point
                    else 0,
                    "warehouse_id": row.warehouse_id,
                }
                for row in rows
            ]

        except Exception as e:
            logger.error("Failed to get low stock items: %s", e)
            raise InventoryRepositoryError(f"Failed to get low stock items: {e}") from e

    # ========================================================================
    # GENERATE MOVEMENT NUMBER
    # ========================================================================

    async def get_next_movement_number(self, prefix: str = "MOV", year: int = None) -> str:
        """Generate movement number berikutnya."""
        if year is None:
            year = date.today().year

        try:
            # Gunakan func.concat untuk menghindari f-string dalam SQL
            pattern = func.concat(prefix, '-', year, '-%')
            stmt = (
                select(InventoryMovementTable.movement_number)
                .where(InventoryMovementTable.movement_number.like(pattern))
                .order_by(InventoryMovementTable.movement_number.desc())
                .limit(1)
            )

            result = await self.session.execute(stmt)
            last_number = result.scalar_one_or_none()

            if last_number:
                seq = int(last_number.split("-")[-1]) + 1
            else:
                seq = 1

            return f"{prefix}-{year}-{seq:06d}"

        except Exception as e:
            logger.error("Failed to generate movement number: %s", e)
            raise InventoryRepositoryError(f"Failed to generate number: {e}") from e


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DuplicateItemCodeError",
    "FIFOLayerNotFoundError",
    "InsufficientStockError",
    "InventoryRepositoryError",
    "ItemNotFoundError",
    "NegativeStockNotAllowedError",
    "OptimisticLockError",
    "SQLAlchemyInventoryRepository",
]
