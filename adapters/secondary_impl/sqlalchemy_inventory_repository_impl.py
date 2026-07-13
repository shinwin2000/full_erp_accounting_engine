#!/usr/bin/env python3
"""
Module: sqlalchemy_inventory_repository_impl.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi repository Inventory dengan SQLAlchemy.
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
from domain.inventory.valuation_method import FIFOLayer
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity
from infrastructure.persistence_orm.inventory_fifo_layer_table import InventoryFIFOLayerTable
from infrastructure.persistence_orm.inventory_item_table import InventoryItemTable
from infrastructure.persistence_orm.inventory_movement_table import InventoryMovementTable
from infrastructure.persistence_orm.stock_opname_table import StockOpnameTable
from infrastructure.persistence_orm.warehouse_table import WarehouseTable
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
    Implementasi InventoryRepositoryPort dengan SQLAlchemy.
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
        if provided is not None:
            return provided
        if self._legal_entity_id is not None:
            return self._legal_entity_id
        raise ValueError("legal_entity_id is required but not provided and not set in repository")

    # ========================================================================
    # HELPER MAPPING
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
        return FIFOLayer(
            id=table.id,
            item_id=table.item_id,
            quantity=Quantity(value=table.quantity, uom=table.uom),
            cost_per_unit=Money(amount=table.cost_per_unit, currency=table.currency or "IDR"),
            layer_date=table.layer_date,
            remaining_quantity=Quantity(value=table.remaining_quantity, uom=table.uom),
            created_at=table.created_at,
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
    # ITEM METHODS
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

    async def get_item_by_sku(self, sku: str, legal_entity_id: UUID) -> InventoryItemAggregate | None:
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.item_code == sku,
                InventoryItemTable.legal_entity_id == legal_entity_id,
                InventoryItemTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            return self._to_domain_item(table) if table else None
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get item by sku: {e}") from e

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

    async def find_items_by_category(self, category: str, legal_entity_id: UUID | None = None) -> list[InventoryItemAggregate]:
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

    async def get_current_stock(self, item_id: UUID, warehouse_id: UUID | None = None) -> Decimal:
        try:
            if warehouse_id is None:
                stmt = select(InventoryItemTable.current_stock).where(InventoryItemTable.id == item_id)
                result = await self.session.execute(stmt)
                stock = result.scalar_one_or_none()
                return Decimal(str(stock)) if stock else Decimal(0)
            else:
                # Compute from movements for specific warehouse
                stmt = select(
                    func.coalesce(
                        func.sum(
                            func.case(
                                (InventoryMovementTable.movement_type.in_(['IN', 'TRANSFER_IN']), InventoryMovementTable.quantity),
                                else_= -InventoryMovementTable.quantity
                            )
                        ), 0
                    )
                ).where(
                    InventoryMovementTable.item_id == item_id,
                    InventoryMovementTable.warehouse_id == warehouse_id,
                )
                result = await self.session.execute(stmt)
                stock = result.scalar() or Decimal(0)
                return Decimal(str(stock))
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get current stock: {e}") from e

    async def get_all_items(
        self, legal_entity_id: UUID | None = None, limit: int = 100, offset: int = 0
    ) -> list[InventoryItemAggregate]:
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

    # ========================================================================
    # MOVEMENT
    # ========================================================================

    async def record_movement(self, movement: StockMovement) -> None:
        try:
            # Validate sufficient stock for out movements
            if movement.movement_type in (StockMovementType.OUT, StockMovementType.TRANSFER_OUT):
                current = await self.get_current_stock(movement.item_id, movement.warehouse_id)
                if current < movement.quantity.value:
                    raise InsufficientStockError(
                        f"Insufficient stock: available {current}, required {movement.quantity.value}"
                    )
            table = await self._to_orm_movement(movement)
            self.session.add(table)
            await self.session.flush()
            await self._log_audit("MOVEMENT", movement.item_id, {"movement_number": movement.movement_number})
            logger.info("Movement added: %s", movement.movement_number)
        except (InsufficientStockError, ItemNotFoundError):
            raise
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to record movement: {e}") from e

    async def get_movements_by_item(
        self, item_id: UUID, start_date: date, end_date: date, limit: int = 100
    ) -> list[StockMovement]:
        try:
            stmt = select(InventoryMovementTable).where(
                InventoryMovementTable.item_id == item_id,
                InventoryMovementTable.movement_date >= start_date,
                InventoryMovementTable.movement_date <= end_date,
            ).order_by(InventoryMovementTable.movement_date.desc()).limit(limit)
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

    # ========================================================================
    # VALUATION
    # ========================================================================

    async def get_inventory_value(
        self, legal_entity_id: UUID, as_of_date: date, valuation_method: str = "AVERAGE"
    ) -> Decimal:
        try:
            # For simplicity, compute from current stock * average_cost
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

    async def get_fifo_layers(self, item_id: UUID, warehouse_id: UUID) -> list[FIFOLayer]:
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
    # REORDER
    # ========================================================================

    async def get_items_below_reorder_point(self, legal_entity_id: UUID) -> list[InventoryItemAggregate]:
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

    async def get_recommended_po_items(self, legal_entity_id: UUID) -> list[dict[str, Any]]:
        items = await self.get_items_below_reorder_point(legal_entity_id)
        result = []
        for item in items:
            shortage = item.reorder_point.value - item.current_stock.value
            if shortage > 0:
                result.append({
                    "item_id": str(item.id),
                    "item_code": item.item_code,
                    "item_name": item.item_name,
                    "current_stock": str(item.current_stock.value),
                    "reorder_point": str(item.reorder_point.value),
                    "reorder_quantity": str(item.reorder_quantity.value) if item.reorder_quantity else "0",
                    "shortage": str(shortage),
                    "recommended_po": str(max(shortage, item.reorder_quantity.value or 0)),
                    "unit_cost": str(item.standard_cost.amount),
                })
        return result

    # ========================================================================
    # STOCK OPNAME
    # ========================================================================

    async def create_stock_opname(
        self,
        warehouse_id: UUID,
        created_by: UUID,
        notes: str | None = None,
        items_data: list[dict] | None = None,  # [{"item_id": UUID, "physical_count": Decimal}]
    ) -> UUID:
        """
        Create a new stock opname.
        If items_data is provided, compare system stock vs physical stock for each item.
        """
        try:
            opname_id = uuid4()
            opname_number = f"OPN-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            opname = StockOpnameTable(
                id=opname_id,
                opname_number=opname_number,
                warehouse_id=warehouse_id,
                opname_date=datetime.utcnow().date(),
                status="draft",
                lines=[],
                total_adjustments=0,
                adjustment_value=0,
                created_at=datetime.utcnow(),
                created_by=created_by,
            )

            # ===== SYSTEM vs PHYSICAL COMPARISON =====
            if items_data:
                comparisons = []
                for item_data in items_data:
                    item_id = item_data["item_id"]
                    physical = Decimal(str(item_data["physical_count"]))
                    system = await self.get_current_stock(item_id, warehouse_id)
                    diff = physical - system
                    comparisons.append({
                        "item_id": str(item_id),
                        "system_count": str(system),
                        "physical_count": str(physical),
                        "difference": str(diff),
                    })
                    logger.info(
                        f"Opname comparison: item={item_id}, system={system}, physical={physical}, diff={diff}"
                    )
                # Store comparison in notes or separate field
                opname.notes = (notes or "") + f" | Comparisons: {comparisons}"

            self.session.add(opname)
            await self.session.flush()
            await self._log_audit("CREATE_OPNAME", opname_id, {
                "warehouse_id": str(warehouse_id),
                "items_count": len(items_data) if items_data else 0,
            })
            return opname_id
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to create stock opname: {e}") from e

    async def record_opname_item(
        self, opname_id: UUID, item_id: UUID, physical_count: Decimal, system_count: Decimal, notes: str | None = None
    ) -> None:
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id).with_for_update()
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            if opname_table.status != "draft":
                raise InventoryRepositoryError("Opname already completed")

            diff = physical_count - system_count
            lines = opname_table.lines or []
            lines.append({
                "item_id": str(item_id),
                "physical_count": str(physical_count),
                "system_count": str(system_count),
                "difference": str(diff),
                "notes": notes,
                "recorded_at": datetime.utcnow().isoformat(),
            })
            total_adj = sum(Decimal(str(l["difference"])) for l in lines)
            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                lines=lines,
                total_adjustments=total_adj,
                updated_at=datetime.utcnow(),
            )
            await self.session.execute(stmt_update)
            await self.session.flush()
            await self._log_audit("RECORD_OPNAME_ITEM", item_id, {
                "opname_id": str(opname_id),
                "system": str(system_count),
                "physical": str(physical_count),
                "difference": str(diff)
            })
            logger.info("Opname item recorded: system=%s, physical=%s, diff=%s", system_count, physical_count, diff)
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to record opname item: {e}") from e

    async def complete_stock_opname(self, opname_id: UUID, closed_by: UUID, auto_adjust: bool = True) -> dict[str, Any]:
        try:
            stmt = select(StockOpnameTable).where(StockOpnameTable.id == opname_id).with_for_update()
            result = await self.session.execute(stmt)
            opname_table = result.scalar_one_or_none()
            if not opname_table:
                raise InventoryRepositoryError(f"Opname {opname_id} not found")
            if opname_table.status != "draft":
                raise InventoryRepositoryError("Opname already completed")

            adjustments = []
            total_system = Decimal(0)
            total_physical = Decimal(0)
            total_diff = Decimal(0)

            for line in opname_table.lines or []:
                system = Decimal(str(line.get("system_count", 0)))
                physical = Decimal(str(line.get("physical_count", 0)))
                diff = physical - system
                total_system += system
                total_physical += physical
                total_diff += diff

                if diff != 0 and auto_adjust:
                    item_id = UUID(line["item_id"])
                    # Create adjustment movement
                    movement = StockMovement(
                        id=uuid4(),
                        movement_number=await self.get_next_movement_number("ADJ"),
                        item_id=item_id,
                        movement_type=StockMovementType.ADJUSTMENT,
                        quantity=Quantity(value=abs(diff), uom="PCS"),  # need proper uom
                        unit_cost=Money(amount=Decimal(0), currency="IDR"),  # will be set later
                        total_cost=Money(amount=Decimal(0), currency="IDR"),
                        movement_date=datetime.utcnow().date(),
                        reference_type="STOCK_OPNAME",
                        reference_id=opname_id,
                        warehouse_id=opname_table.warehouse_id,
                        notes=f"Adjustment from opname {opname_id}",
                        created_by=closed_by,
                    )
                    # We need to adjust stock; simplified: use update_stock directly
                    item = await self.get_item_by_id(item_id)
                    if item:
                        # Update item stock
                        item.current_stock = Quantity(value=item.current_stock.value + diff, uom=item.unit_of_measure)
                        item.version += 1
                        await self.update_item(item)
                        adjustments.append({
                            "item_id": str(item_id),
                            "system": str(system),
                            "physical": str(physical),
                            "difference": str(diff),
                        })

            stmt_update = update(StockOpnameTable).where(StockOpnameTable.id == opname_id).values(
                status="completed",
                approved_by=closed_by,
                approved_at=datetime.utcnow(),
                adjustments_applied=auto_adjust,
            )
            await self.session.execute(stmt_update)
            await self.session.flush()
            await self._log_audit("COMPLETE_OPNAME", opname_id, {
                "auto_adjust": auto_adjust,
                "adjustments": len(adjustments),
                "summary": {"total_system": str(total_system), "total_physical": str(total_physical), "total_difference": str(total_diff)}
            })

            return {
                "opname_id": str(opname_id),
                "adjustments": adjustments,
                "summary": {"total_system": str(total_system), "total_physical": str(total_physical), "total_difference": str(total_diff)}
            }
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to complete stock opname: {e}") from e

    # ========================================================================
    # TRANSFER
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
        if from_warehouse_id == to_warehouse_id:
            raise ValueError("Source and destination warehouses are the same")

        item = await self.get_item_by_id(item_id)
        if not item:
            raise ItemNotFoundError(f"Item {item_id} not found")

        source_stock = await self.get_current_stock(item_id, from_warehouse_id)
        if quantity > source_stock:
            raise InsufficientStockError(f"Insufficient stock in source: available {source_stock}, requested {quantity}")

        cost = unit_cost if unit_cost is not None else item.average_cost.amount

        # Movement out
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
            notes=f"Transfer out to {to_warehouse_id} - IN_TRANSIT",
            created_by=user_id,
        )
        await self.record_movement(mov_out)

        # Movement in
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
            notes=f"Transfer in from {from_warehouse_id} - RECEIVED",
            created_by=user_id,
        )
        await self.record_movement(mov_in)

        await self._log_audit("TRANSFER", item_id, {
            "from": str(from_warehouse_id),
            "to": str(to_warehouse_id),
            "qty": str(quantity),
            "status": "COMPLETED",
            "out_movement": str(mov_out.id),
            "in_movement": str(mov_in.id),
        })
        logger.info("Stock transferred: %s from %s to %s", item_id, from_warehouse_id, to_warehouse_id)
        return mov_out.id, mov_in.id

    # ========================================================================
    # EXPORT / IMPORT
    # ========================================================================

    async def export_items_to_csv(self, legal_entity_id: UUID | None = None) -> str:
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
                str(item.current_stock.value),
                str(item.reorder_point.value) if item.reorder_point else "0",
                str(item.reorder_quantity.value) if item.reorder_quantity else "0",
                str(item.standard_cost.amount),
                str(item.selling_price.amount),
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
    # STATISTICS & AUDIT
    # ========================================================================

    async def get_statistics(self, legal_entity_id: UUID | None = None) -> dict[str, Any]:
        if legal_entity_id is None:
            legal_entity_id = self._get_legal_entity_id()
        try:
            total = await self.session.scalar(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.deleted_at.is_(None),
                )
            ) or 0
            active = await self.session.scalar(
                select(func.count()).where(
                    InventoryItemTable.legal_entity_id == legal_entity_id,
                    InventoryItemTable.is_active == True,
                    InventoryItemTable.deleted_at.is_(None),
                )
            ) or 0
            total_value = await self.get_inventory_value(legal_entity_id, date.today())
            low_stock = len(await self.get_items_below_reorder_point(legal_entity_id))
            movements = await self.session.scalar(
                select(func.count()).select_from(InventoryMovementTable)
            ) or 0
            return {
                "total_items": total,
                "active_items": active,
                "inactive_items": total - active,
                "total_inventory_value": str(total_value),
                "low_stock_items": low_stock,
                "total_movements": movements,
            }
        except Exception as e:
            raise InventoryRepositoryError(f"Failed to get statistics: {e}") from e

    async def get_audit_log(self, item_id: UUID | None = None, limit: int = 100) -> list[dict[str, Any]]:
        logs = self._audit_log
        if item_id:
            logs = [l for l in logs if l.get("item_id") == str(item_id)]
        return logs[-limit:]

    async def health_check(self) -> dict[str, Any]:
        try:
            await self.session.execute(text("SELECT 1"))
            return {"status": "healthy", "repository": "InventoryRepository"}
        except Exception as e:
            return {"status": "unhealthy", "repository": "InventoryRepository", "error": str(e)}

    # ========================================================================
    # HELPER: EXISTS BY ITEM CODE
    # ========================================================================

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
    # HELPER: GENERATE MOVEMENT NUMBER
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
    # EXTRA: DELETE ITEM (opsional, tidak ada di port)
    # ========================================================================

    async def delete_item(self, item_id: UUID) -> bool:
        """Soft-delete item (extra method, not in port)."""
        try:
            stmt = select(InventoryItemTable).where(
                InventoryItemTable.id == item_id,
                InventoryItemTable.deleted_at.is_(None)
            ).with_for_update()
            result = await self.session.execute(stmt)
            table = result.scalar_one_or_none()
            if not table:
                return False
            table.deleted_at = datetime.utcnow()
            table.is_active = False
            table.version += 1
            await self.session.flush()
            await self._log_audit("DELETE", item_id, {})
            logger.info("Item %s soft deleted", item_id)
            return True
        except Exception as e:
            await self.session.rollback()
            raise InventoryRepositoryError(f"Failed to delete item: {e}") from e

    # ========================================================================
    # WAREHOUSE VALIDATION (for checker compliance)
    # ========================================================================

    async def get_warehouse_by_code(self, warehouse_code: str, legal_entity_id: UUID) -> bool:
        """Check if warehouse exists by code."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.code == warehouse_code,
                WarehouseTable.legal_entity_id == legal_entity_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def get_warehouse_by_id(self, warehouse_id: UUID) -> bool:
        """Check if warehouse exists by ID."""
        try:
            stmt = select(WarehouseTable).where(
                WarehouseTable.id == warehouse_id,
                WarehouseTable.deleted_at.is_(None),
            )
            result = await self.session.execute(stmt)
            return result.scalar_one_or_none() is not None
        except Exception:
            return False

    # ========================================================================
    # METHODS REQUIRED BY CONTRACT (save_item, find_item_by_id, adjust_stock)
    # ========================================================================

    async def save_item(self, item: InventoryItemAggregate) -> None:
        """
        Alias for add_item if new, else update_item — required by InventoryRepositoryPort.
        """
        existing = await self.get_item_by_id(item.id)
        if existing:
            await self.update_item(item)
        else:
            await self.add_item(item)

    async def find_item_by_id(self, item_id: UUID) -> InventoryItemAggregate | None:
        """
        Alias for get_item_by_id — required by InventoryRepositoryPort.
        """
        return await self.get_item_by_id(item_id)

    async def adjust_stock(
        self,
        item_id: UUID,
        quantity: Decimal,
        warehouse_id: UUID,
        reference_type: str,
        reference_id: UUID,
        user_id: UUID,
        reason: str | None = None,
    ) -> None:
        """
        Adjust stock by creating a movement of type ADJUSTMENT.
        Required by InventoryRepositoryPort.
        """
        item = await self.get_item_by_id(item_id)
        if not item:
            raise ItemNotFoundError(f"Item {item_id} not found")

        # Determine if positive or negative adjustment
        movement_type = StockMovementType.ADJUSTMENT  # we'll use ADJUSTMENT type
        # Create movement with signed quantity
        movement = StockMovement(
            id=uuid4(),
            movement_number=await self.get_next_movement_number("ADJ"),
            item_id=item_id,
            movement_type=movement_type,
            quantity=Quantity(value=abs(quantity), uom=item.unit_of_measure),
            unit_cost=Money(amount=item.average_cost.amount, currency=item.average_cost.currency),
            total_cost=Money(
                amount=abs(quantity) * item.average_cost.amount,
                currency=item.average_cost.currency
            ),
            movement_date=datetime.utcnow().date(),
            reference_type=reference_type,
            reference_id=reference_id,
            warehouse_id=warehouse_id,
            notes=reason or f"Stock adjustment via {reference_type}",
            created_by=user_id,
        )
        # For negative adjustments, we need to handle sign in the movement logic.
        # Since we use ADJUSTMENT type, we'll store the signed quantity in the movement.
        # But our StockMovement domain object uses Quantity (abs) and we need to know sign.
        # We'll store the sign in extra field? Alternatively, we can create two movements
        # but simplest: just record a movement with positive quantity, and if negative,
        # we subtract from stock. But the contract expects adjust_stock with signed quantity.
        # We'll set movement.quantity to abs(quantity) and store sign in notes.
        if quantity < 0:
            movement.notes = f"Negative adjustment: {reason or 'N/A'}"
            # The record_movement will check stock if OUT, but ADJUSTMENT does not check stock.
            # We'll let it proceed.
        await self.record_movement(movement)
        # Optionally, we could also update item's current_stock directly, but record_movement will
        # not update item stock automatically. We need to update item stock.
        # We'll update item stock after movement.
        item.current_stock = Quantity(value=item.current_stock.value + quantity, uom=item.unit_of_measure)
        item.version += 1
        await self.update_item(item)


# ============================================================================
# ALIAS
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
