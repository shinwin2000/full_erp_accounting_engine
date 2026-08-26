#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Manufacturing
Responsibility: Domain events for Manufacturing aggregate.

Defines all domain events emitted by Manufacturing aggregates:
- Work order lifecycle (created, approved, started, completed, cancelled)
- BOM lifecycle (created, updated, activated, obsoleted)
- Production completion
- Material issues, labor posting, overhead application
- WIP updates
- Standard cost updates
- Cost card updates
- HPP calculation

Events are immutable value objects used for event sourcing,
integration with other bounded contexts (inventory, accounting),
and building read models (projections).

Business rules:
- Events are immutable value objects.
- Each event contains aggregate_id, aggregate_version, timestamp, event data.
- Events can be serialized to/from JSON for persistence and messaging.
- Correlation_id and causation_id support event tracing.

Dependencies:
- Python standard library (uuid, datetime, dataclass, json, enum)
- domain.manufacturing.work_order_entity (WorkOrderEntity, WorkOrderStatus)
- domain.manufacturing.bill_of_materials_entity (BillOfMaterialsEntity, BOMStatus)
- domain.manufacturing.work_in_process_entity (WorkInProcessEntity, WIPStatus)

Audit:
All events are part of the immutable audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.work_order_entity import (
    WorkOrderEntity,
    WorkOrderStatus,
)

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    """Types of domain events in Manufacturing context."""

    # BOM Events
    BOM_CREATED = "bom_created"
    BOM_UPDATED = "bom_updated"
    BOM_ACTIVATED = "bom_activated"
    BOM_OBSOLETED = "bom_obsoleted"
    BOM_ITEM_ADDED = "bom_item_added"
    BOM_ITEM_REMOVED = "bom_item_removed"
    BOM_ITEM_UPDATED = "bom_item_updated"
    BOM_VERSION_INCREMENTED = "bom_version_incremented"

    # Work Order Events
    WORK_ORDER_CREATED = "work_order_created"
    WORK_ORDER_APPROVED = "work_order_approved"
    WORK_ORDER_STARTED = "work_order_started"
    WORK_ORDER_COMPLETED = "work_order_completed"
    WORK_ORDER_CANCELLED = "work_order_cancelled"
    WORK_ORDER_UPDATED = "work_order_updated"

    # Production Events
    MATERIAL_ISSUED = "material_issued"
    LABOR_POSTED = "labor_posted"
    OVERHEAD_APPLIED = "overhead_applied"
    PRODUCTION_COMPLETED = "production_completed"

    # WIP Events
    WIP_CREATED = "wip_created"
    WIP_UPDATED = "wip_updated"
    WIP_COMPLETED = "wip_completed"
    WIP_ADJUSTED = "wip_adjusted"

    # Cost Events
    STANDARD_COST_CREATED = "standard_cost_created"
    STANDARD_COST_UPDATED = "standard_cost_updated"
    STANDARD_COST_ACTIVATED = "standard_cost_activated"
    STANDARD_COST_OBSOLETED = "standard_cost_obsoleted"

    # Cost Card Events
    COST_CARD_CREATED = "cost_card_created"
    COST_CARD_UPDATED = "cost_card_updated"
    COST_CARD_CLOSED = "cost_card_closed"

    # HPP Events
    HPP_CALCULATED = "hpp_calculated"

    # Variance Events
    VARIANCE_ANALYZED = "variance_analyzed"

    # Routing Events
    ROUTING_CREATED = "routing_created"
    ROUTING_ACTIVATED = "routing_activated"
    ROUTING_OBSOLETED = "routing_obsoleted"

    def is_work_order_event(self) -> bool:
        """Return True if event relates to work order lifecycle."""
        work_order_events = {
            DomainEventType.WORK_ORDER_CREATED,
            DomainEventType.WORK_ORDER_APPROVED,
            DomainEventType.WORK_ORDER_STARTED,
            DomainEventType.WORK_ORDER_COMPLETED,
            DomainEventType.WORK_ORDER_CANCELLED,
            DomainEventType.WORK_ORDER_UPDATED,
        }
        return self in work_order_events

    def is_production_event(self) -> bool:
        """Return True if event relates to production execution."""
        production_events = {
            DomainEventType.MATERIAL_ISSUED,
            DomainEventType.LABOR_POSTED,
            DomainEventType.OVERHEAD_APPLIED,
            DomainEventType.PRODUCTION_COMPLETED,
        }
        return self in production_events

    def is_cost_event(self) -> bool:
        """Return True if event relates to costs."""
        cost_events = {
            DomainEventType.STANDARD_COST_CREATED,
            DomainEventType.STANDARD_COST_UPDATED,
            DomainEventType.STANDARD_COST_ACTIVATED,
            DomainEventType.STANDARD_COST_OBSOLETED,
            DomainEventType.COST_CARD_CREATED,
            DomainEventType.COST_CARD_UPDATED,
            DomainEventType.COST_CARD_CLOSED,
            DomainEventType.HPP_CALCULATED,
            DomainEventType.VARIANCE_ANALYZED,
        }
        return self in cost_events


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass
class DomainEvent:
    """
    Base class for all domain events in Manufacturing context.

    Attributes:
        event_id: Unique identifier for this event instance.
        event_type: Type of event (from DomainEventType enum).
        aggregate_id: ID of the aggregate that generated the event.
        aggregate_version: Version of the aggregate after applying this event.
        occurred_at: UTC timestamp when the event occurred.
        event_data: Dictionary of event-specific data.
        user_id: Optional user ID who triggered the event.
        correlation_id: Optional correlation ID for tracing.
        causation_id: Optional ID of the event that caused this event.
    """

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        """Serialize event to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Deserialize from dictionary."""
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


# ============================================================================
# BOM Events
# ============================================================================


@dataclass
class BOMCreatedEvent(DomainEvent):
    """Emitted when a new Bill of Materials is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bom: BillOfMaterialsEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "bom_id": str(bom.bom_id),
            "bom_code": bom.bom_code,
            "product_id": str(bom.product_id),
            "product_code": bom.product_code,
            "product_name": bom.product_name,
            "version": bom.version,
            "quantity_per_assembly": str(bom.quantity_per_assembly),
            "unit_of_measure": bom.unit_of_measure,
            "total_cost": str(bom.get_total_cost()),
            "item_count": len(bom.items),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BOM_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BOMUpdatedEvent(DomainEvent):
    """Emitted when a BOM is updated (general update)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bom_id: UUID,
        bom_code: str,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "bom_id": str(bom_id),
            "bom_code": bom_code,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BOM_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BOMActivatedEvent(DomainEvent):
    """Emitted when a BOM is activated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bom: BillOfMaterialsEntity,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "bom_id": str(bom.bom_id),
            "bom_code": bom.bom_code,
            "product_id": str(bom.product_id),
            "product_code": bom.product_code,
            "product_name": bom.product_name,
            "previous_status": BOMStatus.DRAFT.value,
            "new_status": BOMStatus.ACTIVE.value,
            "effective_date": bom.effective_date.isoformat() if bom.effective_date else None,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BOM_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BOMObsoletedEvent(DomainEvent):
    """Emitted when a BOM is marked obsolete."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bom: BillOfMaterialsEntity,
        reason: str,
        obsoleted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "bom_id": str(bom.bom_id),
            "bom_code": bom.bom_code,
            "product_id": str(bom.product_id),
            "product_code": bom.product_code,
            "product_name": bom.product_name,
            "previous_status": bom.status.value,
            "new_status": BOMStatus.OBSOLETE.value,
            "reason": reason,
            "obsoleted_by": obsoleted_by,
            "expiry_date": bom.expiry_date.isoformat() if bom.expiry_date else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BOM_OBSOLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BOMItemAddedEvent(DomainEvent):
    """Emitted when an item is added to a BOM."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bom_id: UUID,
        bom_code: str,
        item: Any,  # BOMItem
        added_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "bom_id": str(bom_id),
            "bom_code": bom_code,
            "item_id": str(item.item_id),
            "item_code": item.item_code,
            "item_name": item.item_name,
            "quantity": str(item.quantity),
            "unit_cost": str(item.unit_cost),
            "cost_element": item.cost_element.value,
            "added_by": added_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BOM_ITEM_ADDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Work Order Events
# ============================================================================


@dataclass
class WorkOrderCreatedEvent(DomainEvent):
    """Emitted when a new work order is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order: WorkOrderEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order.work_order_id),
            "work_order_number": work_order.work_order_number,
            "product_id": str(work_order.product_id),
            "product_code": work_order.product_code,
            "product_name": work_order.product_name,
            "planned_quantity": str(work_order.planned_quantity),
            "planned_start_date": work_order.planned_start_date.isoformat(),
            "planned_end_date": work_order.planned_end_date.isoformat(),
            "priority": work_order.priority.value,
            "bom_id": str(work_order.bom_id),
            "bom_version": work_order.bom_version,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class WorkOrderApprovedEvent(DomainEvent):
    """Emitted when a work order is approved."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order: WorkOrderEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order.work_order_id),
            "work_order_number": work_order.work_order_number,
            "previous_status": WorkOrderStatus.DRAFT.value,
            "new_status": WorkOrderStatus.APPROVED.value,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class WorkOrderStartedEvent(DomainEvent):
    """Emitted when production on a work order starts."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order: WorkOrderEntity,
        started_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order.work_order_id),
            "work_order_number": work_order.work_order_number,
            "previous_status": WorkOrderStatus.APPROVED.value,
            "new_status": WorkOrderStatus.IN_PROGRESS.value,
            "actual_start_date": work_order.actual_start_date.isoformat()
            if work_order.actual_start_date
            else None,
            "started_by": started_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_STARTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class WorkOrderCompletedEvent(DomainEvent):
    """Emitted when a work order is completed (fully or partially)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order: WorkOrderEntity,
        completed_quantity: Decimal,
        completed_by: str,
        is_fully_completed: bool,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order.work_order_id),
            "work_order_number": work_order.work_order_number,
            "completed_quantity": str(completed_quantity),
            "total_completed": str(work_order.completed_quantity),
            "planned_quantity": str(work_order.planned_quantity),
            "previous_status": work_order.status.value,
            "new_status": WorkOrderStatus.COMPLETED.value
            if is_fully_completed
            else WorkOrderStatus.PARTIALLY_COMPLETED.value,
            "is_fully_completed": is_fully_completed,
            "actual_end_date": work_order.actual_end_date.isoformat()
            if work_order.actual_end_date
            else None,
            "completed_by": completed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_COMPLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class WorkOrderCancelledEvent(DomainEvent):
    """Emitted when a work order is cancelled."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order: WorkOrderEntity,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order.work_order_id),
            "work_order_number": work_order.work_order_number,
            "previous_status": work_order.status.value,
            "new_status": WorkOrderStatus.CANCELLED.value,
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.WORK_ORDER_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Production Execution Events
# ============================================================================


@dataclass
class MaterialIssuedEvent(DomainEvent):
    """Emitted when materials are issued to production."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order_id: UUID,
        work_order_number: str,
        material_id: UUID,
        material_code: str,
        material_name: str,
        quantity: Decimal,
        cost: Decimal,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order_id),
            "work_order_number": work_order_number,
            "material_id": str(material_id),
            "material_code": material_code,
            "material_name": material_name,
            "quantity": str(quantity),
            "cost": str(cost),
            "issued_by": issued_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.MATERIAL_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class LaborPostedEvent(DomainEvent):
    """Emitted when labor costs are posted to a work order."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order_id: UUID,
        work_order_number: str,
        employee_id: UUID,
        employee_name: str,
        hours: Decimal,
        rate: Decimal,
        cost: Decimal,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order_id),
            "work_order_number": work_order_number,
            "employee_id": str(employee_id),
            "employee_name": employee_name,
            "hours": str(hours),
            "rate": str(rate),
            "cost": str(cost),
            "posted_by": posted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.LABOR_POSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class OverheadAppliedEvent(DomainEvent):
    """Emitted when overhead costs are applied to a work order."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order_id: UUID,
        work_order_number: str,
        overhead_pool: str,
        amount: Decimal,
        allocation_basis: str,
        applied_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order_id),
            "work_order_number": work_order_number,
            "overhead_pool": overhead_pool,
            "amount": str(amount),
            "allocation_basis": allocation_basis,
            "applied_by": applied_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.OVERHEAD_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class ProductionCompletedEvent(DomainEvent):
    """Emitted when finished goods are transferred to inventory."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order_id: UUID,
        work_order_number: str,
        product_id: UUID,
        product_code: str,
        product_name: str,
        quantity: Decimal,
        unit_cost: Decimal,
        total_cost: Decimal,
        completed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order_id),
            "work_order_number": work_order_number,
            "product_id": str(product_id),
            "product_code": product_code,
            "product_name": product_name,
            "quantity": str(quantity),
            "unit_cost": str(unit_cost),
            "total_cost": str(total_cost),
            "completed_by": completed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PRODUCTION_COMPLETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Cost Card Events
# ============================================================================


@dataclass
class CostCardUpdatedEvent(DomainEvent):
    """Emitted when a cost card is updated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        product_id: UUID,
        period: str,
        total_cost: Decimal,
        unit_cost: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "product_id": str(product_id),
            "period": period,
            "total_cost": str(total_cost),
            "unit_cost": str(unit_cost),
            "updated_by": user_id,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COST_CARD_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# HPP Calculated Event
# ============================================================================


@dataclass
class HPPCalculatedEvent(DomainEvent):
    """Emitted when HPP (Cost of Goods Manufactured) is calculated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        product_id: UUID,
        period_start: datetime,
        period_end: datetime,
        units_produced: Decimal,
        total_cost: Decimal,
        unit_hpp: Decimal,
        calculated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "product_id": str(product_id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "units_produced": str(units_produced),
            "total_cost": str(total_cost),
            "unit_hpp": str(unit_hpp),
            "calculated_by": calculated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HPP_CALCULATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Standard Cost Events
# ============================================================================


@dataclass
class StandardCostCreatedEvent(DomainEvent):
    """Emitted when a standard cost is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        standard_cost_id: UUID,
        product_id: UUID,
        product_code: str,
        product_name: str,
        material_cost: Decimal,
        labor_cost: Decimal,
        overhead_cost: Decimal,
        total_cost: Decimal,
        effective_date: datetime,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "standard_cost_id": str(standard_cost_id),
            "product_id": str(product_id),
            "product_code": product_code,
            "product_name": product_name,
            "material_cost": str(material_cost),
            "labor_cost": str(labor_cost),
            "overhead_cost": str(overhead_cost),
            "total_cost": str(total_cost),
            "effective_date": effective_date.isoformat(),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.STANDARD_COST_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class StandardCostActivatedEvent(DomainEvent):
    """Emitted when a standard cost is activated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        standard_cost_id: UUID,
        product_id: UUID,
        product_code: str,
        product_name: str,
        activated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "standard_cost_id": str(standard_cost_id),
            "product_id": str(product_id),
            "product_code": product_code,
            "product_name": product_name,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.STANDARD_COST_ACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Variance Analysis Event
# ============================================================================


@dataclass
class VarianceAnalyzedEvent(DomainEvent):
    """Emitted when variance analysis is performed."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        work_order_id: UUID,
        work_order_number: str,
        total_variance: Decimal,
        variance_type: str,  # favorable/unfavorable
        material_variance: Decimal,
        labor_variance: Decimal,
        overhead_variance: Decimal,
        analyzed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "work_order_id": str(work_order_id),
            "work_order_number": work_order_number,
            "total_variance": str(total_variance),
            "variance_type": variance_type,
            "material_variance": str(material_variance),
            "labor_variance": str(labor_variance),
            "overhead_variance": str(overhead_variance),
            "analyzed_by": analyzed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.VARIANCE_ANALYZED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Domain Event Publisher Protocol
# ============================================================================


class DomainEventPublisher:
    """Protocol for publishing domain events to message bus / event store."""

    async def publish(self, event: DomainEvent) -> None:
        """Publish a single domain event."""
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await self.publish(event)


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    """Deserialize JSON string to DomainEvent."""
    data = json.loads(json_str)
    return DomainEvent.from_dict(data)


def serialize_domain_event(event: DomainEvent) -> str:
    """Serialize domain event to JSON string."""
    return event.to_json()


def event_to_audit_log(event: DomainEvent) -> dict[str, Any]:
    """Convert domain event to audit log entry."""
    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type.value,
        "aggregate_id": str(event.aggregate_id),
        "aggregate_version": event.aggregate_version,
        "occurred_at": event.occurred_at.isoformat(),
        "user_id": event.user_id,
        "correlation_id": event.correlation_id,
        "summary": event.event_data.get(
            "work_order_number", event.event_data.get("bom_code", str(event.aggregate_id))
        ),
    }


# ============================================================================
# Aliases for Backward Compatibility with service_manufacturing.py
# ============================================================================

# BOM events
BOMCreated = BOMCreatedEvent
BOMUpdated = BOMUpdatedEvent
BOMActivated = BOMActivatedEvent
BOMObsoleted = BOMObsoletedEvent
BOMItemAdded = BOMItemAddedEvent

# Work order events
WorkOrderCreated = WorkOrderCreatedEvent
WorkOrderApproved = WorkOrderApprovedEvent
WorkOrderStarted = WorkOrderStartedEvent
WorkOrderCompleted = WorkOrderCompletedEvent
WorkOrderCancelled = WorkOrderCancelledEvent

# Production events
MaterialIssued = MaterialIssuedEvent
LaborPosted = LaborPostedEvent
OverheadApplied = OverheadAppliedEvent
ProductionCompleted = ProductionCompletedEvent

# Cost card events
CostCardUpdated = CostCardUpdatedEvent

# HPP events
HPPCalculated = HPPCalculatedEvent

# Standard cost events
StandardCostCreated = StandardCostCreatedEvent
StandardCostActivated = StandardCostActivatedEvent

# Variance event
VarianceAnalyzed = VarianceAnalyzedEvent

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "BOMActivated",
    "BOMActivatedEvent",
    "BOMCreated",
    # BOM events
    "BOMCreatedEvent",
    "BOMItemAdded",
    "BOMItemAddedEvent",
    "BOMObsoleted",
    "BOMObsoletedEvent",
    "BOMUpdated",
    "BOMUpdatedEvent",
    "CostCardUpdated",
    # Cost Card events
    "CostCardUpdatedEvent",
    "DomainEvent",
    # Protocol
    "DomainEventPublisher",
    "DomainEventType",
    "HPPCalculated",
    # HPP events
    "HPPCalculatedEvent",
    "LaborPosted",
    "LaborPostedEvent",
    "MaterialIssued",
    # Production events
    "MaterialIssuedEvent",
    "OverheadApplied",
    "OverheadAppliedEvent",
    "ProductionCompleted",
    "ProductionCompletedEvent",
    "StandardCostActivated",
    "StandardCostActivatedEvent",
    "StandardCostCreated",
    # Standard Cost events
    "StandardCostCreatedEvent",
    "VarianceAnalyzed",
    # Variance event
    "VarianceAnalyzedEvent",
    "WorkOrderApproved",
    "WorkOrderApprovedEvent",
    "WorkOrderCancelled",
    "WorkOrderCancelledEvent",
    "WorkOrderCompleted",
    "WorkOrderCompletedEvent",
    "WorkOrderCreated",
    # Work Order events
    "WorkOrderCreatedEvent",
    "WorkOrderStarted",
    "WorkOrderStartedEvent",
    # Helpers
    "deserialize_domain_event",
    "event_to_audit_log",
    "serialize_domain_event",
]
