# service_inventory.py - Complete rewrite with full event publishing

#!/usr/bin/env python3

"""
Module: service_inventory.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Inventory Management.
    Mempublikasikan semua domain events yang sesuai.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.inventory.aggregate_root import InventoryAggregate
from domain.inventory.domain_events import (
    COGSCalculated,
    InterWarehouseTransferCreated,
    InventoryValuationUpdated,
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockAdjusted,
    StockLevelAlert,
    StockMovementCreated,
    StockOpnameApproved,
    StockOpnameCreated,
    TransferCompleted,
)
from domain.inventory.inter_warehouse_transfer_entity import InterWarehouseTransfer, TransferStatus
from domain.inventory.invariants import InventoryInvariantsValidator
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure
from domain.inventory.movement_entity import MovementType, StockMovement
from domain.inventory.stock_opname_entity import OpnameStatus, StockOpname
from domain.inventory.valuation_method import (
    FIFOValuation,
    ValuationMethod,
    WeightedAverageValuation,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class InventoryValuationMethod(str, Enum):
    """Inventory valuation method."""

    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"
    MOVING_AVERAGE = "MOVING_AVERAGE"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateItemRequest:
    """Request to create an inventory item."""

    legal_entity_id: UUID
    sku: str
    name: str
    description: str | None = None
    item_type: str = "finished_good"
    uom: str = "pcs"
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal = Decimal("0")
    safety_stock: Decimal = Decimal("0")
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal = Decimal("0")
    selling_price: Decimal = Decimal("0")
    warehouse_code: str | None = None
    is_active: bool = True


@dataclass(kw_only=True)
class UpdateItemRequest:
    """Request to update an inventory item."""

    id: UUID
    name: str | None = None
    description: str | None = None
    item_type: str | None = None
    uom: str | None = None
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal | None = None
    selling_price: Decimal | None = None
    warehouse_code: str | None = None


@dataclass(kw_only=True)
class ItemResponse:
    """Response for inventory item."""

    id: UUID
    sku: str
    name: str
    description: str | None
    item_type: str
    uom: str
    current_stock: Decimal
    current_stock_value: Decimal
    average_cost: Decimal
    last_cost: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    standard_cost: Decimal
    selling_price: Decimal
    category: str | None
    warehouse_code: str | None
    status: str
    created_at: datetime


@dataclass(kw_only=True)
class StockMovementRequest:
    """Request to record stock movement."""

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


@dataclass(kw_only=True)
class StockMovementResponse:
    """Response for stock movement."""

    id: UUID
    item_id: UUID
    sku: str
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    movement_date: date
    reference_document_type: str | None
    reference_document_number: str | None
    warehouse_code: str | None
    notes: str | None
    created_at: datetime


@dataclass(kw_only=True)
class StockOpnameRequest:
    """Request to create stock opname."""

    legal_entity_id: UUID
    item_id: UUID
    physical_quantity: Decimal
    opname_date: date | None = None
    notes: str | None = None


@dataclass(kw_only=True)
class StockOpnameResponse:
    """Response for stock opname."""

    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    opname_date: date
    system_quantity: Decimal
    physical_quantity: Decimal
    discrepancy: Decimal
    discrepancy_value: Decimal
    status: str
    notes: str | None
    counted_by: UUID
    counted_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None


@dataclass(kw_only=True)
class TransferRequest:
    """Request for inter-warehouse transfer."""

    legal_entity_id: UUID
    item_id: UUID
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    transfer_date: date | None = None
    notes: str | None = None


@dataclass(kw_only=True)
class TransferResponse:
    """Response for inter-warehouse transfer."""

    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    transfer_date: date
    status: str
    notes: str | None
    requested_by: UUID
    requested_at: datetime
    completed_by: UUID | None
    completed_at: datetime | None


@dataclass(kw_only=True)
class COGSCalculationRequest:
    """Request for COGS calculation."""

    legal_entity_id: UUID
    period_start: date
    period_end: date


@dataclass(kw_only=True)
class COGSCalculationResponse:
    """Response for COGS calculation."""

    period_start: date
    period_end: date
    total_cogs: Decimal
    items: list[dict[str, Any]]


@dataclass(kw_only=True)
class InventoryValuationRequest:
    """Request to update inventory valuation."""

    legal_entity_id: UUID
    valuation_date: date
    valuation_method: str


# ============================================================================
# Exceptions
# ============================================================================


class InventoryServiceError(Exception):
    pass


class ItemNotFoundError(InventoryServiceError):
    pass


class InsufficientStockError(InventoryServiceError):
    pass


class NegativeStockNotAllowedError(InventoryServiceError):
    pass


class TransferNotFoundError(InventoryServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class InventoryService:
    """
    Service layer untuk Inventory Management.
    """

    def __init__(
        self,
        inv_repo: InventoryRepositoryPort,
        uow: UnitOfWorkPort,
        event_publisher: EventPublisherPort | None = None,
        ledger_repo: LedgerRepositoryPort | None = None,
        valuation_method: str = "FIFO",
    ):
        if inv_repo is None:
            raise ValueError("inv_repo is required")
        if uow is None:
            raise ValueError("uow is required")

        self._inv_repo = inv_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._ledger_repo = ledger_repo
        self._validator = InventoryInvariantsValidator()

        # Initialize valuation engine
        if valuation_method.upper() == "FIFO":
            self._valuation_method = ValuationMethod.FIFO
            self._valuation_engine = FIFOValuation()
        else:
            self._valuation_method = ValuationMethod.WEIGHTED_AVERAGE
            self._valuation_engine = WeightedAverageValuation()

        self._stats = {"items_created": 0, "movements": 0, "opnames": 0, "transfers": 0}

        logger.info(f"InventoryService initialized with valuation method {valuation_method}")

    # ==================== ITEM MASTER ====================

    async def create_item(
        self, request: CreateItemRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ItemResponse:
        """Create new inventory item."""
        # Check uniqueness of SKU
        existing = await self._inv_repo.find_item_by_sku(request.legal_entity_id, request.sku)
        if existing:
            raise InventoryServiceError(f"Item with SKU {request.sku} already exists")

        # Validate item type
        valid_types = [
            "raw_material",
            "work_in_progress",
            "finished_good",
            "packaging",
            "spare_part",
        ]
        if request.item_type not in valid_types:
            raise InventoryServiceError(f"Invalid item_type: {request.item_type}")

        item = Item(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            sku=request.sku,
            name=request.name,
            description=request.description,
            item_type=ItemType(request.item_type),
            unit_of_measure=UnitOfMeasure(request.uom),
            current_stock=Decimal("0"),
            current_stock_value=Decimal("0"),
            average_cost=Decimal("0"),
            last_cost=Decimal("0"),
            reorder_point=request.reorder_point,
            safety_stock=request.safety_stock,
            maximum_stock=request.maximum_stock,
            minimum_stock=request.minimum_stock,
            status=ItemStatus.ACTIVE,
            standard_cost=request.standard_cost,
            selling_price=request.selling_price,
            category=request.category,
            warehouse_code=request.warehouse_code,
            created_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=None,
            updated_by=None,
        )

        aggregate = InventoryAggregate(item=item, version=0)
        aggregate.create(user_id)

        await self._inv_repo.save_item(aggregate)
        await self._uow.commit()

        self._stats["items_created"] += 1

        if self._event_publisher:
            event = ItemCreated(
                aggregate_id=item.id,
                legal_entity_id=item.legal_entity_id,
                sku=item.sku,
                name=item.name,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Item created: {item.sku} - {item.name}")
        return self._to_item_response(item)

    async def update_item(
        self,
        request: UpdateItemRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> ItemResponse:
        """Update an existing inventory item."""
        agg = await self._inv_repo.get_item_by_id(request.id)
        if not agg:
            raise ItemNotFoundError(f"Item {request.id} not found")

        item = agg.item
        changes = {}

        # Track changes
        if request.name is not None and request.name != item.name:
            changes["name"] = {"old": item.name, "new": request.name}
            item.name = request.name
        if request.description is not None and request.description != item.description:
            changes["description"] = {"old": item.description, "new": request.description}
            item.description = request.description
        if request.item_type is not None:
            new_type = ItemType(request.item_type)
            if new_type != item.item_type:
                changes["item_type"] = {"old": item.item_type.value, "new": new_type.value}
                item.item_type = new_type
        if request.uom is not None:
            new_uom = UnitOfMeasure(request.uom)
            if new_uom != item.unit_of_measure:
                changes["uom"] = {"old": item.unit_of_measure.value, "new": new_uom.value}
                item.unit_of_measure = new_uom
        if request.category is not None and request.category != item.category:
            changes["category"] = {"old": item.category, "new": request.category}
            item.category = request.category
        if request.brand is not None and request.brand != item.brand:
            changes["brand"] = {"old": item.brand, "new": request.brand}
            item.brand = request.brand
        if request.reorder_point is not None and request.reorder_point != item.reorder_point:
            changes["reorder_point"] = {"old": item.reorder_point, "new": request.reorder_point}
            item.reorder_point = request.reorder_point
        if request.safety_stock is not None and request.safety_stock != item.safety_stock:
            changes["safety_stock"] = {"old": item.safety_stock, "new": request.safety_stock}
            item.safety_stock = request.safety_stock
        if request.maximum_stock is not None and request.maximum_stock != item.maximum_stock:
            changes["maximum_stock"] = {"old": item.maximum_stock, "new": request.maximum_stock}
            item.maximum_stock = request.maximum_stock
        if request.minimum_stock is not None and request.minimum_stock != item.minimum_stock:
            changes["minimum_stock"] = {"old": item.minimum_stock, "new": request.minimum_stock}
            item.minimum_stock = request.minimum_stock
        if request.standard_cost is not None and request.standard_cost != item.standard_cost:
            changes["standard_cost"] = {"old": item.standard_cost, "new": request.standard_cost}
            item.standard_cost = request.standard_cost
        if request.selling_price is not None and request.selling_price != item.selling_price:
            changes["selling_price"] = {"old": item.selling_price, "new": request.selling_price}
            item.selling_price = request.selling_price
        if request.warehouse_code is not None and request.warehouse_code != item.warehouse_code:
            changes["warehouse_code"] = {"old": item.warehouse_code, "new": request.warehouse_code}
            item.warehouse_code = request.warehouse_code

        if not changes:
            # No changes, return current state
            return self._to_item_response(item)

        item.updated_at = datetime.utcnow()
        item.updated_by = user_id

        await self._inv_repo.save_item(agg)
        await self._uow.commit()

        if self._event_publisher:
            event = ItemUpdated(
                legal_entity_id=item.legal_entity_id,
                sku=item.sku,
                changes=changes,
                user_id=user_id,
                aggregate_id=item.id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Item updated: {item.sku} (fields: {list(changes.keys())})")
        return self._to_item_response(item)

    async def deactivate_item(
        self,
        item_id: UUID,
        reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> bool:
        """Deactivate an inventory item."""
        agg = await self._inv_repo.get_item_by_id(item_id)
        if not agg:
            raise ItemNotFoundError(f"Item {item_id} not found")

        if agg.item.status == ItemStatus.INACTIVE:
            return True  # Already inactive

        # Check if stock is zero before deactivating
        if agg.item.current_stock > 0:
            raise InventoryServiceError(
                f"Cannot deactivate item with stock {agg.item.current_stock}. Please adjust stock first."
            )

        agg.item.status = ItemStatus.INACTIVE
        agg.item.updated_at = datetime.utcnow()
        agg.item.updated_by = user_id

        await self._inv_repo.save_item(agg)
        await self._uow.commit()

        if self._event_publisher:
            event = ItemDeactivated(
                sku=agg.item.sku,
                reason=reason,
                user_id=user_id,
                aggregate_id=item_id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        logger.info(f"Item deactivated: {agg.item.sku} (reason: {reason})")
        return True

    async def get_item(self, item_id: UUID) -> ItemResponse | None:
        """Get item by ID."""
        aggregate = await self._inv_repo.get_item_by_id(item_id)
        if not aggregate:
            return None
        return self._to_item_response(aggregate.item)

    async def list_items(
        self,
        legal_entity_id: UUID,
        item_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ItemResponse]:
        """List items with filters."""
        items = await self._inv_repo.list_items(
            legal_entity_id=legal_entity_id,
            item_type=item_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        return [self._to_item_response(agg.item) for agg in items]

    # ==================== STOCK MOVEMENTS ====================

    async def record_movement(
        self, request: StockMovementRequest, user_id: UUID, correlation_id: str | None = None
    ) -> StockMovementResponse:
        """Record stock movement."""
        item_agg = await self._inv_repo.get_item_by_id(request.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {request.item_id} not found")

        # Validate movement type
        movement_type = MovementType(request.movement_type)
        movement_date = request.movement_date or date.today()

        # Check stock for outbound movements
        if movement_type in (
            MovementType.SALES_ISSUE,
            MovementType.TRANSFER_OUT,
            MovementType.ADJUSTMENT_OUT,
        ):
            if item_agg.item.current_stock < request.quantity:
                raise InsufficientStockError(
                    f"Insufficient stock for item {item_agg.item.sku}. "
                    f"Available: {item_agg.item.current_stock}, requested: {request.quantity}"
                )

        # Calculate cost for movement
        if movement_type.is_inbound():
            unit_cost = request.unit_cost or item_agg.item.last_cost
            total_value = request.quantity * unit_cost
            # Update average cost for inbound
            if self._valuation_method == ValuationMethod.WEIGHTED_AVERAGE:
                total_qty = item_agg.item.current_stock + request.quantity
                total_value_all = item_agg.item.current_stock_value + total_value
                new_avg_cost = (
                    total_value_all / total_qty if total_qty > 0 else item_agg.item.average_cost
                )
            else:
                new_avg_cost = item_agg.item.average_cost
        else:
            # For outbound, use valuation method to determine cost
            unit_cost = await self._get_movement_cost(item_agg.item, request.quantity)
            total_value = request.quantity * unit_cost
            new_avg_cost = item_agg.item.average_cost

        # Create movement
        movement = StockMovement(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            movement_type=movement_type,
            quantity=request.quantity,
            unit_cost=unit_cost,
            total_value=total_value,
            movement_date=movement_date,
            reference_document_type=request.reference_document_type,
            reference_document_number=request.reference_document_number,
            warehouse_code=request.warehouse_code,
            notes=request.notes,
            created_by=user_id,
            created_at=datetime.utcnow(),
        )

        # Update item stock
        if movement_type.is_inbound():
            new_stock = item_agg.item.current_stock + request.quantity
            new_value = item_agg.item.current_stock_value + total_value
        else:
            new_stock = item_agg.item.current_stock - request.quantity
            new_value = item_agg.item.current_stock_value - total_value

        if new_stock < 0 and not self._validator.allow_negative_stock(item_agg.item):
            raise NegativeStockNotAllowedError(
                f"Negative stock not allowed for item {item_agg.item.sku}"
            )

        item_agg.update_stock(new_stock, new_value, new_avg_cost, user_id)

        await self._inv_repo.save_item(item_agg)
        await self._inv_repo.save_movement(movement)
        await self._uow.commit()

        self._stats["movements"] += 1

        # ---- PUBLISH EVENTS ----

        # 1. StockMovementCreated
        if self._event_publisher:
            event = StockMovementCreated(
                aggregate_id=movement.id,
                item_id=request.item_id,
                sku=item_agg.item.sku,
                movement_type=movement_type.value,
                quantity=request.quantity,
                unit_cost=unit_cost,
                total_value=total_value,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

            # 2. StockAdjustedEvent if adjustment
            if movement_type in (MovementType.ADJUSTMENT_IN, MovementType.ADJUSTMENT_OUT):
                # Construct StockAdjustmentEntity (simplified for event)
                from domain.inventory.stock_adjustment_entity import StockAdjustmentEntity

                adj = StockAdjustmentEntity(
                    adjustment_id=movement.id,
                    adjustment_number=movement.reference_document_number or movement.id.hex[:8],
                    adjustment_type=(
                        "INCREASE" if movement_type == MovementType.ADJUSTMENT_IN else "DECREASE"
                    ),
                    item_id=movement.item_id,
                    item_sku=item_agg.item.sku,
                    warehouse_id=UUID(int=0),  # placeholder
                    warehouse_code=movement.warehouse_code,
                    quantity=movement.quantity,
                    unit_cost=movement.unit_cost,
                    total_value=movement.total_value,
                    reason=movement.notes or "Manual adjustment",
                    adjustment_date=movement.movement_date,
                )
                adj_event = StockAdjustedEvent(
                    adjustment=adj,
                    adjusted_by=str(user_id),
                    aggregate_id=movement.id,
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(adj_event, correlation_id=correlation_id)

            # 3. StockLevelAlert if stock <= reorder point
            if item_agg.item.reorder_point > 0 and new_stock <= item_agg.item.reorder_point:
                alert_event = StockLevelAlert(
                    item_id=item_agg.item.id,
                    sku=item_agg.item.sku,
                    item_name=item_agg.item.name,
                    current_stock=new_stock,
                    reorder_point=item_agg.item.reorder_point,
                    safety_stock=item_agg.item.safety_stock,
                    alert_type="LOW_STOCK",
                    aggregate_id=item_agg.item.id,
                    occurred_at=datetime.utcnow(),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(alert_event, correlation_id=correlation_id)

        logger.info(
            f"Stock movement recorded: {movement_type.value} {request.quantity} of {item_agg.item.sku}"
        )
        return self._to_movement_response(movement, item_agg.item.sku)

    async def _get_movement_cost(self, item: Item, quantity: Decimal) -> Decimal:
        """Determine unit cost for outbound movement."""
        if self._valuation_method == ValuationMethod.FIFO:
            layers = await self._inv_repo.get_fifo_layers(item.id)
            remaining_qty = quantity
            total_cost = Decimal("0")
            for layer in layers:
                if remaining_qty <= 0:
                    break
                take_qty = min(layer.quantity, remaining_qty)
                total_cost += take_qty * layer.unit_cost
                remaining_qty -= take_qty
            return total_cost / quantity if quantity > 0 else item.average_cost
        else:
            return item.average_cost

    # ==================== STOCK OPNAME ====================

    async def create_stock_opname(
        self, request: StockOpnameRequest, user_id: UUID, correlation_id: str | None = None
    ) -> StockOpnameResponse:
        """Create stock opname."""
        item_agg = await self._inv_repo.get_item_by_id(request.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {request.item_id} not found")

        discrepancy = request.physical_quantity - item_agg.item.current_stock

        opname = StockOpname(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            opname_date=request.opname_date or date.today(),
            system_quantity=item_agg.item.current_stock,
            physical_quantity=request.physical_quantity,
            discrepancy=discrepancy,
            unit_cost=item_agg.item.average_cost,
            discrepancy_value=discrepancy * item_agg.item.average_cost,
            status=OpnameStatus.PENDING,
            notes=request.notes,
            counted_by=user_id,
            counted_at=datetime.utcnow(),
            approved_by=None,
            approved_at=None,
        )

        await self._inv_repo.save_opname(opname)
        await self._uow.commit()

        self._stats["opnames"] += 1

        if self._event_publisher:
            event = StockOpnameCreated(
                aggregate_id=opname.id,
                item_id=request.item_id,
                sku=item_agg.item.sku,
                discrepancy=discrepancy,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        # Auto-approve if discrepancy is zero
        if discrepancy == 0:
            await self.approve_stock_opname(opname.id, user_id, correlation_id)

        return self._to_opname_response(opname, item_agg.item)

    async def approve_stock_opname(
        self, opname_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> StockOpnameResponse:
        """Approve stock opname and create adjustment."""
        opname = await self._inv_repo.get_opname_by_id(opname_id)
        if not opname:
            raise InventoryServiceError(f"Opname {opname_id} not found")

        if opname.status != OpnameStatus.PENDING:
            raise InventoryServiceError(f"Opname already {opname.status.value}")

        item_agg = await self._inv_repo.get_item_by_id(opname.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {opname.item_id} not found")

        # Create adjustment movement if needed
        if opname.discrepancy != 0:
            adjustment_type = (
                MovementType.ADJUSTMENT_IN
                if opname.discrepancy > 0
                else MovementType.ADJUSTMENT_OUT
            )
            movement = StockMovement(
                id=uuid4(),
                legal_entity_id=opname.legal_entity_id,
                item_id=opname.item_id,
                movement_type=adjustment_type,
                quantity=abs(opname.discrepancy),
                unit_cost=item_agg.item.average_cost,
                total_value=abs(opname.discrepancy_value),
                movement_date=date.today(),
                reference_document_type="STOCK_OPNAME",
                reference_document_number=opname.id.hex[:8],
                notes=f"Adjustment from opname {opname.id}",
                created_by=approver_id,
                created_at=datetime.utcnow(),
            )
            await self._inv_repo.save_movement(movement)

            # Update item stock
            new_stock = item_agg.item.current_stock + opname.discrepancy
            new_value = item_agg.item.current_stock_value + opname.discrepancy_value
            item_agg.update_stock(new_stock, new_value, item_agg.item.average_cost, approver_id)
            await self._inv_repo.save_item(item_agg)

        # Mark opname as approved
        opname.status = OpnameStatus.APPROVED
        opname.approved_by = approver_id
        opname.approved_at = datetime.utcnow()
        await self._inv_repo.save_opname(opname)

        await self._uow.commit()

        if self._event_publisher:
            event = StockOpnameApproved(
                aggregate_id=opname_id,
                item_id=opname.item_id,
                discrepancy=opname.discrepancy,
                user_id=approver_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_opname_response(opname, item_agg.item)

    # ==================== INTER-WAREHOUSE TRANSFER ====================

    async def create_transfer(
        self, request: TransferRequest, user_id: UUID, correlation_id: str | None = None
    ) -> TransferResponse:
        """Create inter-warehouse transfer."""
        item_agg = await self._inv_repo.get_item_by_id(request.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {request.item_id} not found")

        if item_agg.item.current_stock < request.quantity:
            raise InsufficientStockError("Insufficient stock for transfer")

        transfer = InterWarehouseTransfer(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            from_warehouse=request.from_warehouse,
            to_warehouse=request.to_warehouse,
            quantity=request.quantity,
            unit_cost=item_agg.item.average_cost,
            total_value=request.quantity * item_agg.item.average_cost,
            transfer_date=request.transfer_date or date.today(),
            status=TransferStatus.PENDING,
            notes=request.notes,
            requested_by=user_id,
            requested_at=datetime.utcnow(),
            completed_by=None,
            completed_at=None,
        )

        await self._inv_repo.save_transfer(transfer)

        # Reduce stock in from_warehouse
        movement = StockMovement(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            item_id=request.item_id,
            movement_type=MovementType.TRANSFER_OUT,
            quantity=request.quantity,
            unit_cost=item_agg.item.average_cost,
            total_value=transfer.total_value,
            movement_date=request.transfer_date or date.today(),
            reference_document_type="TRANSFER",
            reference_document_number=transfer.id.hex[:8],
            warehouse_code=request.from_warehouse,
            notes=f"Transfer to {request.to_warehouse}",
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._inv_repo.save_movement(movement)

        # Update item stock
        new_stock = item_agg.item.current_stock - request.quantity
        new_value = item_agg.item.current_stock_value - transfer.total_value
        item_agg.update_stock(new_stock, new_value, item_agg.item.average_cost, user_id)
        await self._inv_repo.save_item(item_agg)

        await self._uow.commit()

        self._stats["transfers"] += 1

        if self._event_publisher:
            event = InterWarehouseTransferCreated(
                aggregate_id=transfer.id,
                item_id=request.item_id,
                sku=item_agg.item.sku,
                quantity=request.quantity,
                from_warehouse=request.from_warehouse,
                to_warehouse=request.to_warehouse,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_transfer_response(transfer, item_agg.item)

    async def complete_transfer(
        self, transfer_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> TransferResponse:
        """Complete a transfer."""
        transfer = await self._inv_repo.get_transfer_by_id(transfer_id)
        if not transfer:
            raise TransferNotFoundError(f"Transfer {transfer_id} not found")

        if transfer.status != TransferStatus.PENDING:
            raise InventoryServiceError(f"Transfer already {transfer.status.value}")

        item_agg = await self._inv_repo.get_item_by_id(transfer.item_id)
        if not item_agg:
            raise ItemNotFoundError(f"Item {transfer.item_id} not found")

        # Receive goods in to_warehouse
        movement = StockMovement(
            id=uuid4(),
            legal_entity_id=transfer.legal_entity_id,
            item_id=transfer.item_id,
            movement_type=MovementType.TRANSFER_IN,
            quantity=transfer.quantity,
            unit_cost=transfer.unit_cost,
            total_value=transfer.total_value,
            movement_date=date.today(),
            reference_document_type="TRANSFER",
            reference_document_number=transfer.id.hex[:8],
            warehouse_code=transfer.to_warehouse,
            notes=f"Transfer from {transfer.from_warehouse} completed",
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        await self._inv_repo.save_movement(movement)

        # Update item stock
        new_stock = item_agg.item.current_stock + transfer.quantity
        new_value = item_agg.item.current_stock_value + transfer.total_value
        new_avg_cost = new_value / new_stock if new_stock > 0 else item_agg.item.average_cost
        item_agg.update_stock(new_stock, new_value, new_avg_cost, user_id)
        await self._inv_repo.save_item(item_agg)

        transfer.status = TransferStatus.COMPLETED
        transfer.completed_by = user_id
        transfer.completed_at = datetime.utcnow()
        await self._inv_repo.save_transfer(transfer)

        await self._uow.commit()

        if self._event_publisher:
            event = TransferCompleted(
                aggregate_id=transfer_id,
                item_id=transfer.item_id,
                quantity=transfer.quantity,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return self._to_transfer_response(transfer, item_agg.item)

    # ==================== COGS CALCULATION ====================

    async def calculate_cogs(
        self, request: COGSCalculationRequest, user_id: UUID, correlation_id: str | None = None
    ) -> COGSCalculationResponse:
        """Calculate COGS for a period."""
        movements = await self._inv_repo.get_outbound_movements(
            legal_entity_id=request.legal_entity_id,
            from_date=request.period_start,
            to_date=request.period_end,
        )

        # Group by item
        cogs_by_item = {}
        for mv in movements:
            item_id = str(mv.item_id)
            if item_id not in cogs_by_item:
                item_agg = await self._inv_repo.get_item_by_id(mv.item_id)
                cogs_by_item[item_id] = {
                    "sku": item_agg.item.sku if item_agg else "unknown",
                    "name": item_agg.item.name if item_agg else "unknown",
                    "quantity": Decimal("0"),
                    "cogs": Decimal("0"),
                }
            cogs_by_item[item_id]["quantity"] += mv.quantity
            cogs_by_item[item_id]["cogs"] += mv.total_value

        total_cogs = sum(v["cogs"] for v in cogs_by_item.values())

        if self._event_publisher:
            event = COGSCalculated(
                legal_entity_id=request.legal_entity_id,
                period_start=request.period_start,
                period_end=request.period_end,
                total_cogs=total_cogs,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return COGSCalculationResponse(
            period_start=request.period_start,
            period_end=request.period_end,
            total_cogs=total_cogs,
            items=[
                {
                    "sku": v["sku"],
                    "name": v["name"],
                    "quantity": float(v["quantity"]),
                    "cogs": float(v["cogs"]),
                }
                for v in cogs_by_item.values()
            ],
        )

    # ==================== INVENTORY VALUATION ====================

    async def update_inventory_valuation(
        self,
        request: InventoryValuationRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Update inventory valuation (e.g., for financial reporting)."""
        items = await self._inv_repo.list_items(request.legal_entity_id, limit=10000)
        total_value = Decimal("0")
        for agg in items:
            # In a real implementation, you'd recalculate valuation based on method
            # For simplicity, we just sum current stock value
            total_value += agg.item.current_stock_value

        if self._event_publisher:
            event = InventoryValuationUpdated(
                legal_entity_id=request.legal_entity_id,
                valuation_date=request.valuation_date,
                total_value=total_value,
                valuation_method=request.valuation_method,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "legal_entity_id": str(request.legal_entity_id),
            "valuation_date": request.valuation_date.isoformat(),
            "valuation_method": request.valuation_method,
            "total_value": total_value,
            "items_count": len(items),
        }

    # ==================== REPORTS ====================

    async def get_stock_card(
        self, item_id: UUID, from_date: date | None = None, to_date: date | None = None
    ) -> list[dict[str, Any]]:
        """Get stock card for an item."""
        movements = await self._inv_repo.get_movements_by_item(item_id, from_date, to_date)
        return [
            {
                "date": m.movement_date.isoformat(),
                "movement_type": m.movement_type.value,
                "quantity_in": float(m.quantity) if m.movement_type.is_inbound() else 0,
                "quantity_out": float(m.quantity) if not m.movement_type.is_inbound() else 0,
                "unit_cost": float(m.unit_cost),
                "total_value": float(m.total_value),
                "reference": m.reference_document_number,
                "warehouse": m.warehouse_code,
            }
            for m in movements
        ]

    async def get_low_stock_items(
        self, legal_entity_id: UUID, threshold_percentage: Decimal = Decimal("20")
    ) -> list[ItemResponse]:
        """Get items below reorder point."""
        items = await self._inv_repo.list_items(legal_entity_id, status="ACTIVE", limit=10000)
        low_stock = []
        for agg in items:
            if agg.item.current_stock <= agg.item.reorder_point and agg.item.reorder_point > 0:
                low_stock.append(agg.item)
        return [self._to_item_response(item) for item in low_stock]

    # ==================== PRIVATE HELPERS ====================

    def _to_item_response(self, item: Item) -> ItemResponse:
        return ItemResponse(
            id=item.id,
            sku=item.sku,
            name=item.name,
            description=item.description,
            item_type=item.item_type.value,
            uom=item.unit_of_measure.value,
            current_stock=item.current_stock,
            current_stock_value=item.current_stock_value,
            average_cost=item.average_cost,
            last_cost=item.last_cost,
            reorder_point=item.reorder_point,
            safety_stock=item.safety_stock,
            standard_cost=item.standard_cost,
            selling_price=item.selling_price,
            category=item.category,
            warehouse_code=item.warehouse_code,
            status=item.status.value,
            created_at=item.created_at,
        )

    def _to_movement_response(self, movement: StockMovement, sku: str) -> StockMovementResponse:
        return StockMovementResponse(
            id=movement.id,
            item_id=movement.item_id,
            sku=sku,
            movement_type=movement.movement_type.value,
            quantity=movement.quantity,
            unit_cost=movement.unit_cost,
            total_value=movement.total_value,
            movement_date=movement.movement_date,
            reference_document_type=movement.reference_document_type,
            reference_document_number=movement.reference_document_number,
            warehouse_code=movement.warehouse_code,
            notes=movement.notes,
            created_at=movement.created_at,
        )

    def _to_opname_response(self, opname: StockOpname, item: Item) -> StockOpnameResponse:
        return StockOpnameResponse(
            id=opname.id,
            item_id=opname.item_id,
            item_name=item.name,
            sku=item.sku,
            opname_date=opname.opname_date,
            system_quantity=opname.system_quantity,
            physical_quantity=opname.physical_quantity,
            discrepancy=opname.discrepancy,
            discrepancy_value=opname.discrepancy_value,
            status=opname.status.value,
            notes=opname.notes,
            counted_by=opname.counted_by,
            counted_at=opname.counted_at,
            approved_by=opname.approved_by,
            approved_at=opname.approved_at,
        )

    def _to_transfer_response(
        self, transfer: InterWarehouseTransfer, item: Item
    ) -> TransferResponse:
        return TransferResponse(
            id=transfer.id,
            item_id=transfer.item_id,
            item_name=item.name,
            sku=item.sku,
            from_warehouse=transfer.from_warehouse,
            to_warehouse=transfer.to_warehouse,
            quantity=transfer.quantity,
            unit_cost=transfer.unit_cost,
            total_value=transfer.total_value,
            transfer_date=transfer.transfer_date,
            status=transfer.status.value,
            notes=transfer.notes,
            requested_by=transfer.requested_by,
            requested_at=transfer.requested_at,
            completed_by=transfer.completed_by,
            completed_at=transfer.completed_at,
        )

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_inventory_service(
    inv_repo: InventoryRepositoryPort,
    uow: UnitOfWorkPort,
    event_publisher: EventPublisherPort | None = None,
    ledger_repo: LedgerRepositoryPort | None = None,
    valuation_method: str = "FIFO",
) -> InventoryService:
    return InventoryService(inv_repo, uow, event_publisher, ledger_repo, valuation_method)


__all__ = [
    "COGSCalculationRequest",
    "COGSCalculationResponse",
    "CreateItemRequest",
    "InsufficientStockError",
    "InventoryService",
    "InventoryServiceError",
    "InventoryValuationMethod",
    "InventoryValuationRequest",
    "ItemNotFoundError",
    "ItemResponse",
    "NegativeStockNotAllowedError",
    "StockMovementRequest",
    "StockMovementResponse",
    "StockOpnameRequest",
    "StockOpnameResponse",
    "TransferNotFoundError",
    "TransferRequest",
    "TransferResponse",
    "UpdateItemRequest",
    "create_inventory_service",
]