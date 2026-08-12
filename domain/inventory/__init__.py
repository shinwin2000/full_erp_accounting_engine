from __future__ import annotations

from domain.inventory.aggregate_root import InventoryAggregate, InventoryItemAggregate
from domain.inventory.domain_events import (
    COGSCalculated,
    DomainEvent,
    DomainEventType,
    InterWarehouseTransferCreated,
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockAdjusted,
    StockMovementCreated,
    StockOpnameApproved,
    StockOpnameCreated,
    TransferCompleted,
)
from domain.inventory.fifo_layer_entity import FIFOLayer
from domain.inventory.inter_warehouse_transfer_entity import (
    InterWarehouseTransfer,
    InterWarehouseTransferEntity,
    TransferItem,
    TransferPriority,
    TransferStatus,
)
from domain.inventory.invariants import (
    InvariantResult,
    InventoryInvariantEnforcer,
    InventoryInvariants,
    InventoryInvariantsValidator,
)
from domain.inventory.item_entity import (
    Item,
    ItemEntity,
    ItemStatus,
    ItemType,
    UnitOfMeasure,
    ValuationMethod,
)
from domain.inventory.item_type_enum import ItemType as ItemTypeEnum
from domain.inventory.movement_entity import (
    MovementEntity,
    MovementStatus,
    MovementType,
    StockMovement,
)
from domain.inventory.nrv_tester import (
    NRVTester,
    NRVTestResult,
    NRVTestResultSummary,
    WriteDownMethod,
)
from domain.inventory.stock_adjustment_entity import (
    AdjustmentReason,
    AdjustmentStatus,
    AdjustmentType,
    StockAdjustment,
    StockAdjustmentEntity,
)
from domain.inventory.stock_card_projection import StockCardEntry, StockCardProjection
from domain.inventory.stock_opname_entity import (
    DiscrepancyType,
    OpnameItem,
    OpnameStatus,
    StockOpname,
    StockOpnameEntity,
    StockOpnameStatus,
)
from domain.inventory.valuation_method import (
    FIFOValuation,
    ValuationMethodFactory,
    ValuationMethodStrategy,
    ValuationMethodType,
    ValuationResult,
)

"""
Package: domain.inventory
Inventory management domain layer.
"""

__all__ = [
    # Stock Adjustment
    "AdjustmentReason",
    "AdjustmentStatus",
    "AdjustmentType",
    # Events
    "COGSCalculated",
    # Stock Opname
    "DiscrepancyType",
    "DomainEvent",
    "DomainEventType",
    # FIFO Layer
    "FIFOLayer",
    # Valuation
    "FIFOValuation",
    # Inter Warehouse Transfer
    "InterWarehouseTransfer",
    "InterWarehouseTransferCreated",
    "InterWarehouseTransferEntity",
    # Invariants
    "InvariantResult",
    # Aggregate
    "InventoryAggregate",
    "InventoryInvariantEnforcer",
    "InventoryInvariants",
    "InventoryInvariantsValidator",
    "InventoryItemAggregate",
    # Item
    "Item",
    "ItemCreated",
    "ItemDeactivated",
    "ItemEntity",
    "ItemStatus",
    "ItemType",
    "ItemTypeEnum",
    "ItemUpdated",
    # Movement
    "MovementEntity",
    "MovementStatus",
    "MovementType",
    "NRVTestResult",
    "NRVTestResultSummary",
    # NRV
    "NRVTester",
    "OpnameItem",
    "OpnameStatus",
    "StockAdjusted",
    "StockAdjustment",
    "StockAdjustmentEntity",
    # Stock Card
    "StockCardEntry",
    "StockCardProjection",
    "StockMovement",
    "StockMovementCreated",
    "StockOpname",
    "StockOpnameApproved",
    "StockOpnameCreated",
    "StockOpnameEntity",
    "StockOpnameStatus",
    "TransferCompleted",
    "TransferItem",
    "TransferPriority",
    "TransferStatus",
    "UnitOfMeasure",
    "ValuationMethod",
    "ValuationMethodFactory",
    "ValuationMethodStrategy",
    "ValuationMethodType",
    "ValuationResult",
    "WriteDownMethod",
]
