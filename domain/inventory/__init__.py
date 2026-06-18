from __future__ import annotations

"""
Package: domain.inventory
Inventory management domain layer.
"""

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

__all__ = [
    # Aggregate
    "InventoryAggregate",
    "InventoryItemAggregate",
    # Events
    "COGSCalculated",
    "DomainEvent",
    "DomainEventType",
    "InterWarehouseTransferCreated",
    "ItemCreated",
    "ItemDeactivated",
    "ItemUpdated",
    "StockAdjusted",
    "StockMovementCreated",
    "StockOpnameApproved",
    "StockOpnameCreated",
    "TransferCompleted",
    # FIFO Layer
    "FIFOLayer",
    # Inter Warehouse Transfer
    "InterWarehouseTransfer",
    "InterWarehouseTransferEntity",
    "TransferItem",
    "TransferPriority",
    "TransferStatus",
    # Invariants
    "InvariantResult",
    "InventoryInvariants",
    "InventoryInvariantEnforcer",
    "InventoryInvariantsValidator",
    # Item
    "Item",
    "ItemEntity",
    "ItemStatus",
    "ItemType",
    "UnitOfMeasure",
    "ValuationMethod",
    "ItemTypeEnum",
    # Movement
    "MovementEntity",
    "MovementStatus",
    "MovementType",
    "StockMovement",
    # NRV
    "NRVTester",
    "NRVTestResult",
    "NRVTestResultSummary",
    "WriteDownMethod",
    # Stock Adjustment
    "AdjustmentReason",
    "AdjustmentStatus",
    "AdjustmentType",
    "StockAdjustment",
    "StockAdjustmentEntity",
    # Stock Card
    "StockCardEntry",
    "StockCardProjection",
    # Stock Opname
    "DiscrepancyType",
    "OpnameItem",
    "OpnameStatus",
    "StockOpname",
    "StockOpnameEntity",
    "StockOpnameStatus",
    # Valuation
    "FIFOValuation",
    "ValuationMethodFactory",
    "ValuationMethodStrategy",
    "ValuationMethodType",
    "ValuationResult",
]
