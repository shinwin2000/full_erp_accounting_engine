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
    "AllocationBasis",
    "AllocationRate",
    "AllocationResult",
    "BOMActivatedEvent",
    "BOMCreatedEvent",
    "BOMItem",
    "BOMItemAddedEvent",
    "BOMObsoletedEvent",
    "BOMStatus",
    "BOMType",
    # BOM
    "BillOfMaterialsEntity",
    "BillOfMaterialsRepository",
    # Cost Card
    "CostCardEntity",
    # Cost Card Projection
    "CostCardProjection",
    "CostCardProjectionRepository",
    "CostCardRepository",
    "CostCardStatus",
    "CostCardSummary",
    # Cost Element
    "CostElement",
    "CostEntry",
    "DomainEvent",
    "DomainEventPublisher",
    # Domain Events
    "DomainEventType",
    "HPPCalculationMethod",
    "HPPCalculationResult",
    "HPPComponent",
    # HPP Calculator
    "HPPPerProductCalculator",
    "InvariantResult",
    "LaborPostedEvent",
    # Aggregate
    "ManufacturingAggregate",
    "ManufacturingInvariantEnforcer",
    # Invariants
    "ManufacturingInvariants",
    "ManufacturingRepository",
    "MaterialIssuedEvent",
    # Overhead Allocation
    "OverheadAllocationEngine",
    "OverheadAppliedEvent",
    "OverheadPool",
    "ProductionCompletedEvent",
    # Routing
    "ProductionRoutingEntity",
    "ProductionRoutingRepository",
    "RoutingOperation",
    "RoutingStatus",
    "StandardCostActivatedEvent",
    "StandardCostComponent",
    "StandardCostCreatedEvent",
    # Standard Cost
    "StandardCostEntity",
    "StandardCostRepository",
    "StandardCostStatus",
    # Variance Analysis
    "VarianceAnalysisEngine",
    "VarianceAnalysisResult",
    "VarianceAnalyzedEvent",
    "VarianceComponent",
    "VarianceType",
    "WIPCostComponent",
    "WIPStatus",
    # WIP
    "WorkInProcessEntity",
    "WorkInProcessRepository",
    "WorkOrderApprovedEvent",
    "WorkOrderCancelledEvent",
    "WorkOrderCompletedEvent",
    "WorkOrderCreatedEvent",
    # Work Order
    "WorkOrderEntity",
    "WorkOrderPriority",
    "WorkOrderRepository",
    "WorkOrderStartedEvent",
    "WorkOrderStatus",
    "WorkOrderType",
    "deserialize_domain_event",
    "event_to_audit_log",
    "serialize_domain_event",
]
