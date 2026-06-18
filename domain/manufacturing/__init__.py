#!/usr/bin/env python3
"""
Package: domain.manufacturing
Layer: 6 - Domain / Manufacturing
Responsibility: Manufacturing domain - production management, BOM, work orders, WIP, cost analysis.

Exports all public components from the manufacturing domain layer.
"""

from domain.manufacturing.aggregate_root import ManufacturingAggregate, ManufacturingRepository
from domain.manufacturing.bill_of_materials_entity import (
    BillOfMaterialsEntity,
    BillOfMaterialsRepository,
    BOMItem,
    BOMStatus,
    BOMType,
)
from domain.manufacturing.cost_card_entity import (
    CostCardEntity,
    CostCardRepository,
    CostCardStatus,
    CostEntry,
)
from domain.manufacturing.cost_card_projection import (
    CostCardProjection,
    CostCardProjectionRepository,
    CostCardSummary,
)
from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.domain_events import (
    BOMActivatedEvent,
    BOMCreatedEvent,
    BOMItemAddedEvent,
    BOMObsoletedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    LaborPostedEvent,
    MaterialIssuedEvent,
    OverheadAppliedEvent,
    ProductionCompletedEvent,
    StandardCostActivatedEvent,
    StandardCostCreatedEvent,
    VarianceAnalyzedEvent,
    WorkOrderApprovedEvent,
    WorkOrderCancelledEvent,
    WorkOrderCompletedEvent,
    WorkOrderCreatedEvent,
    WorkOrderStartedEvent,
    deserialize_domain_event,
    event_to_audit_log,
    serialize_domain_event,
)
from domain.manufacturing.hpp_per_product_calculator import (
    HPPCalculationMethod,
    HPPCalculationResult,
    HPPComponent,
    HPPPerProductCalculator,
)
from domain.manufacturing.invariants import (
    InvariantResult,
    ManufacturingInvariantEnforcer,
    ManufacturingInvariants,
)
from domain.manufacturing.overhead_allocation_engine import (
    AllocationBasis,
    AllocationRate,
    AllocationResult,
    OverheadAllocationEngine,
    OverheadPool,
)
from domain.manufacturing.production_routing_entity import (
    ProductionRoutingEntity,
    ProductionRoutingRepository,
    RoutingOperation,
    RoutingStatus,
)
from domain.manufacturing.standard_cost_entity import (
    StandardCostComponent,
    StandardCostEntity,
    StandardCostRepository,
    StandardCostStatus,
)
from domain.manufacturing.variance_analysis_engine import (
    VarianceAnalysisEngine,
    VarianceAnalysisResult,
    VarianceComponent,
    VarianceType,
)
from domain.manufacturing.work_in_process_entity import (
    WIPCostComponent,
    WIPStatus,
    WorkInProcessEntity,
    WorkInProcessRepository,
)
from domain.manufacturing.work_order_entity import (
    WorkOrderEntity,
    WorkOrderPriority,
    WorkOrderRepository,
    WorkOrderStatus,
    WorkOrderType,
)

__all__ = [
    # Aggregate
    "ManufacturingAggregate",
    "ManufacturingRepository",
    # Work Order
    "WorkOrderEntity",
    "WorkOrderStatus",
    "WorkOrderPriority",
    "WorkOrderType",
    "WorkOrderRepository",
    # BOM
    "BillOfMaterialsEntity",
    "BOMType",
    "BOMStatus",
    "BOMItem",
    "BillOfMaterialsRepository",
    # Routing
    "ProductionRoutingEntity",
    "RoutingStatus",
    "RoutingOperation",
    "ProductionRoutingRepository",
    # WIP
    "WorkInProcessEntity",
    "WIPStatus",
    "WIPCostComponent",
    "WorkInProcessRepository",
    # Cost Element
    "CostElement",
    # Standard Cost
    "StandardCostEntity",
    "StandardCostStatus",
    "StandardCostComponent",
    "StandardCostRepository",
    # Variance Analysis
    "VarianceAnalysisEngine",
    "VarianceType",
    "VarianceComponent",
    "VarianceAnalysisResult",
    # Overhead Allocation
    "OverheadAllocationEngine",
    "AllocationBasis",
    "OverheadPool",
    "AllocationRate",
    "AllocationResult",
    # HPP Calculator
    "HPPPerProductCalculator",
    "HPPCalculationMethod",
    "HPPComponent",
    "HPPCalculationResult",
    # Cost Card
    "CostCardEntity",
    "CostCardStatus",
    "CostEntry",
    "CostCardRepository",
    # Cost Card Projection
    "CostCardProjection",
    "CostCardProjectionRepository",
    "CostCardSummary",
    # Domain Events
    "DomainEventType",
    "DomainEvent",
    "BOMCreatedEvent",
    "BOMActivatedEvent",
    "BOMObsoletedEvent",
    "BOMItemAddedEvent",
    "WorkOrderCreatedEvent",
    "WorkOrderApprovedEvent",
    "WorkOrderStartedEvent",
    "WorkOrderCompletedEvent",
    "WorkOrderCancelledEvent",
    "MaterialIssuedEvent",
    "LaborPostedEvent",
    "OverheadAppliedEvent",
    "ProductionCompletedEvent",
    "StandardCostCreatedEvent",
    "StandardCostActivatedEvent",
    "VarianceAnalyzedEvent",
    "DomainEventPublisher",
    "deserialize_domain_event",
    "serialize_domain_event",
    "event_to_audit_log",
    # Invariants
    "ManufacturingInvariants",
    "ManufacturingInvariantEnforcer",
    "InvariantResult",
]
