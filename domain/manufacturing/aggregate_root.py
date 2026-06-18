#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / Manufacturing
Responsibility: Root aggregate for production management.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.bill_of_materials_entity import BillOfMaterialsEntity, BOMStatus
from domain.manufacturing.domain_events import (
    BOMActivatedEvent,
    BOMCreatedEvent,
    BOMObsoletedEvent,
    ProductionCompletedEvent,
    StandardCostActivatedEvent,
    StandardCostCreatedEvent,
    VarianceAnalyzedEvent,
    WorkOrderApprovedEvent,
    WorkOrderCancelledEvent,
    WorkOrderCompletedEvent,
    WorkOrderCreatedEvent,
    WorkOrderStartedEvent,
)
from domain.manufacturing.standard_cost_entity import StandardCostEntity
from domain.manufacturing.variance_analysis_engine import (
    VarianceAnalysisEngine,
    VarianceAnalysisResult,
)
from domain.manufacturing.work_in_process_entity import WIPStatus, WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity, WorkOrderStatus

logger = logging.getLogger(__name__)


@dataclass
class ManufacturingAggregate:
    """
    Root aggregate for manufacturing.

    Business context:
    Manages the entire production process including planning, execution,
    and cost analysis. This aggregate ensures consistency across work orders,
    BOMs, WIP, and standard costs.
    """

    manufacturing_id: UUID
    legal_entity_id: UUID
    work_orders: dict[UUID, WorkOrderEntity] = field(default_factory=dict)
    bills_of_materials: dict[UUID, BillOfMaterialsEntity] = field(default_factory=dict)
    wip_entries: list[WorkInProcessEntity] = field(default_factory=list)
    standard_costs: dict[UUID, StandardCostEntity] = field(default_factory=dict)
    variance_engine: VarianceAnalysisEngine = field(default_factory=VarianceAnalysisEngine)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.manufacturing_id, UUID):
            raise TypeError("manufacturing_id must be a UUID")
        if not isinstance(self.legal_entity_id, UUID):
            raise TypeError("legal_entity_id must be a UUID")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1, got {self.version}")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware (UTC)")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware (UTC)")

    # ==================== PROPERTIES ====================

    @property
    def id(self) -> UUID:
        return self.manufacturing_id

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== EVENT METHODS ====================

    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)
        self._record_audit_trail("event_added", {"event_type": event.event_type.value})

    def clear_events(self) -> None:
        self._events.clear()
        self._record_audit_trail("events_cleared", {})

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pop_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def register_event(self, event: DomainEvent) -> None:
        self._add_event(event)

    # ==================== AUDIT TRAIL ====================

    def _record_audit_trail(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def clear_audit_trail(self) -> None:
        self._audit_trail.clear()

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        snapshot_data = {
            "aggregate_id": str(self.manufacturing_id),
            "aggregate_type": "ManufacturingAggregate",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "work_orders_count": len(self.work_orders),
                "boms_count": len(self.bills_of_materials),
                "wip_count": len(self.wip_entries),
                "standard_costs_count": len(self.standard_costs),
                "total_wip_value": str(self.calculate_total_wip_value()),
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit_trail("snapshot_created", {"version": self.version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        if snapshot.get("aggregate_id") != str(self.manufacturing_id):
            raise ValueError("Snapshot belongs to different aggregate")
        self._record_audit_trail(
            "restored_from_snapshot", {"snapshot_version": snapshot.get("version")}
        )

    def _compute_hash(self) -> str:
        state_str = json.dumps(
            {
                "id": str(self.manufacturing_id),
                "version": self.version,
                "work_orders_count": len(self.work_orders),
                "boms_count": len(self.bills_of_materials),
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: str, reason: str | None = None) -> ManufacturingAggregate:
        if self._is_locked:
            raise ValueError(f"Manufacturing aggregate is already locked by {self._locked_by}")
        self._record_audit_trail("locked", {"user_id": user_id, "reason": reason})
        self._is_locked = True
        self._locked_by = user_id
        self._locked_at = datetime.now(UTC)
        return self

    def unlock(self, user_id: str) -> ManufacturingAggregate:
        if not self._is_locked:
            raise ValueError("Manufacturing aggregate is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Aggregate locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit_trail("unlocked", {"user_id": user_id})
        self._is_locked = False
        self._locked_by = None
        self._locked_at = None
        return self

    # ==================== VALIDATE ====================

    def validate(self) -> list[str]:
        errors = []
        for bom in self.bills_of_materials.values():
            if not bom.items:
                errors.append(f"BOM {bom.bom_code} has no items")
        for wo in self.work_orders.values():
            if wo.completed_quantity > wo.planned_quantity:
                errors.append(
                    f"Work order {wo.work_order_number} completed quantity exceeds planned"
                )
            if wo.bom_id not in self.bills_of_materials:
                errors.append(
                    f"Work order {wo.work_order_number} references missing BOM {wo.bom_id}"
                )
        for wip in self.wip_entries:
            if wip.quantity_remaining < 0:
                errors.append(f"WIP for {wip.work_order_number} has negative remaining quantity")
        return errors

    # ==================== VERSION ====================

    def get_version(self) -> int:
        return self.version

    def increment_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(UTC)
        self._record_audit_trail("version_incremented", {"new_version": self.version})

    # ==================== TOUCH ====================

    def touch(self, user_id: str) -> None:
        self.updated_at = datetime.now(UTC)
        self._record_audit_trail("touched", {"user_id": user_id})

    # ==================== CLONE ====================

    def clone(self) -> ManufacturingAggregate:
        self._record_audit_trail("cloned", {"source_id": str(self.manufacturing_id)})
        return ManufacturingAggregate(
            manufacturing_id=uuid4(),
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders.copy(),
            bills_of_materials=self.bills_of_materials.copy(),
            wip_entries=self.wip_entries.copy(),
            standard_costs=self.standard_costs.copy(),
            variance_engine=self.variance_engine,
            version=1,
        )

    # ==================== BOM MANAGEMENT ====================

    def add_bill_of_materials(
        self, bom: BillOfMaterialsEntity, created_by: str
    ) -> ManufacturingAggregate:
        if bom.bom_id in self.bills_of_materials:
            raise ValueError(f"BOM {bom.bom_id} already exists")

        new_boms = dict(self.bills_of_materials)
        new_boms[bom.bom_id] = bom

        self._add_event(
            BOMCreatedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                bom=bom,
                created_by=created_by,
                user_id=created_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=new_boms,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def remove_bill_of_materials(self, bom_id: UUID, removed_by: str) -> ManufacturingAggregate:
        if bom_id not in self.bills_of_materials:
            raise ValueError(f"BOM {bom_id} not found")

        new_boms = dict(self.bills_of_materials)
        del new_boms[bom_id]

        self._record_audit_trail("bom_removed", {"bom_id": str(bom_id), "removed_by": removed_by})
        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=new_boms,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_bom(self, bom_id: UUID) -> BillOfMaterialsEntity | None:
        return self.bills_of_materials.get(bom_id)

    def get_active_bom_for_product(
        self, product_id: UUID, as_of_date: datetime
    ) -> BillOfMaterialsEntity | None:
        for bom in self.bills_of_materials.values():
            if (
                bom.product_id == product_id
                and bom.status == BOMStatus.ACTIVE
                and bom.effective_date
                and bom.effective_date <= as_of_date
                and (bom.expiry_date is None or bom.expiry_date >= as_of_date)
            ):
                return bom
        return None

    def activate_bom(self, bom_id: UUID, activated_by: str) -> ManufacturingAggregate:
        bom = self.bills_of_materials.get(bom_id)
        if not bom:
            raise ValueError(f"BOM {bom_id} not found")
        if bom.status != BOMStatus.DRAFT:
            raise ValueError(
                f"Only DRAFT BOMs can be activated, current status: {bom.status.value}"
            )

        activated_bom = bom.activate(activated_by)
        new_boms = dict(self.bills_of_materials)
        new_boms[bom_id] = activated_bom

        self._add_event(
            BOMActivatedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                bom=activated_bom,
                activated_by=activated_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=new_boms,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def obsoleted_bom(self, bom_id: UUID, reason: str, obsoleted_by: str) -> ManufacturingAggregate:
        bom = self.bills_of_materials.get(bom_id)
        if not bom:
            raise ValueError(f"BOM {bom_id} not found")

        obsoleted_bom = bom.obsoleted(obsoleted_by, reason)
        new_boms = dict(self.bills_of_materials)
        new_boms[bom_id] = obsoleted_bom

        self._add_event(
            BOMObsoletedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                bom=obsoleted_bom,
                reason=reason,
                obsoleted_by=obsoleted_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=new_boms,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    # ==================== WORK ORDER MANAGEMENT ====================

    def add_work_order(
        self, work_order: WorkOrderEntity, created_by: str
    ) -> ManufacturingAggregate:
        if work_order.work_order_id in self.work_orders:
            raise ValueError(f"Work order {work_order.work_order_id} already exists")
        if work_order.bom_id not in self.bills_of_materials:
            raise ValueError(f"BOM {work_order.bom_id} not found")

        new_work_orders = dict(self.work_orders)
        new_work_orders[work_order.work_order_id] = work_order

        self._add_event(
            WorkOrderCreatedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order=work_order,
                created_by=created_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def remove_work_order(self, work_order_id: UUID, removed_by: str) -> ManufacturingAggregate:
        if work_order_id not in self.work_orders:
            raise ValueError(f"Work order {work_order_id} not found")

        new_work_orders = dict(self.work_orders)
        del new_work_orders[work_order_id]

        self._record_audit_trail(
            "work_order_removed", {"work_order_id": str(work_order_id), "removed_by": removed_by}
        )
        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None:
        return self.work_orders.get(work_order_id)

    def get_work_order_by_number(self, work_order_number: str) -> WorkOrderEntity | None:
        for wo in self.work_orders.values():
            if wo.work_order_number == work_order_number:
                return wo
        return None

    def get_work_orders_by_status(self, status: WorkOrderStatus) -> list[WorkOrderEntity]:
        return [wo for wo in self.work_orders.values() if wo.status == status]

    def get_active_work_orders(self) -> list[WorkOrderEntity]:
        return [
            wo
            for wo in self.work_orders.values()
            if wo.status in (WorkOrderStatus.APPROVED, WorkOrderStatus.IN_PROGRESS)
        ]

    def approve_work_order(self, work_order_id: UUID, approved_by: str) -> ManufacturingAggregate:
        work_order = self.work_orders.get(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        if work_order.status != WorkOrderStatus.DRAFT:
            raise ValueError(f"Cannot approve work order in status {work_order.status.value}")

        updated_wo = work_order.approve(approved_by)
        new_work_orders = dict(self.work_orders)
        new_work_orders[work_order_id] = updated_wo

        self._add_event(
            WorkOrderApprovedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order=updated_wo,
                approved_by=approved_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def start_production(self, work_order_id: UUID, started_by: str) -> ManufacturingAggregate:
        work_order = self.work_orders.get(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        if work_order.status != WorkOrderStatus.APPROVED:
            raise ValueError(f"Cannot start work order in status {work_order.status.value}")

        updated_wo = work_order.start_production(started_by)
        new_work_orders = dict(self.work_orders)
        new_work_orders[work_order_id] = updated_wo

        # Create WIP entry
        wip = WorkInProcessEntity.create(
            work_order_id=work_order_id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            product_code=work_order.product_code,
            product_name=work_order.product_name,
            quantity_started=work_order.planned_quantity,
            created_by=started_by,
        )
        new_wip_entries = self.wip_entries + [wip]

        self._add_event(
            WorkOrderStartedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order=updated_wo,
                started_by=started_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=new_wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def complete_production(
        self, work_order_id: UUID, completed_quantity: Decimal, completed_by: str
    ) -> ManufacturingAggregate:
        work_order = self.work_orders.get(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        if work_order.status != WorkOrderStatus.IN_PROGRESS:
            raise ValueError(f"Cannot complete work order in status {work_order.status.value}")

        updated_wo = work_order.complete_production(completed_quantity, completed_by)
        new_work_orders = dict(self.work_orders)
        new_work_orders[work_order_id] = updated_wo

        # Update WIP
        wip = self.get_wip_for_work_order(work_order_id)
        if wip:
            updated_wip = wip.complete_units(completed_quantity)
            new_wip_entries = [w for w in self.wip_entries if w.work_order_id != work_order_id] + [
                updated_wip
            ]
        else:
            new_wip_entries = self.wip_entries

        is_fully_completed = updated_wo.completed_quantity >= updated_wo.planned_quantity
        self._add_event(
            WorkOrderCompletedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order=updated_wo,
                completed_quantity=completed_quantity,
                completed_by=completed_by,
                is_fully_completed=is_fully_completed,
            )
        )

        if is_fully_completed:
            self._add_event(
                ProductionCompletedEvent(
                    aggregate_id=self.manufacturing_id,
                    aggregate_version=self.version + 1,
                    work_order_id=work_order_id,
                    work_order_number=work_order.work_order_number,
                    product_id=work_order.product_id,
                    product_code=work_order.product_code,
                    product_name=work_order.product_name,
                    quantity=updated_wo.completed_quantity,
                    unit_cost=updated_wo.material_actual_cost
                    + updated_wo.labor_actual_cost
                    + updated_wo.overhead_actual_cost,
                    total_cost=work_order.material_actual_cost
                    + work_order.labor_actual_cost
                    + work_order.overhead_actual_cost,
                    completed_by=completed_by,
                )
            )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=new_wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def cancel_work_order(
        self, work_order_id: UUID, reason: str, cancelled_by: str
    ) -> ManufacturingAggregate:
        work_order = self.work_orders.get(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        if work_order.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            raise ValueError(f"Cannot cancel work order in status {work_order.status.value}")

        updated_wo = work_order.cancel(cancelled_by, reason)
        new_work_orders = dict(self.work_orders)
        new_work_orders[work_order_id] = updated_wo

        self._add_event(
            WorkOrderCancelledEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order=updated_wo,
                reason=reason,
                cancelled_by=cancelled_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=new_work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    # ==================== WIP MANAGEMENT ====================

    def add_wip_entry(self, wip: WorkInProcessEntity) -> ManufacturingAggregate:
        new_wip_entries = self.wip_entries + [wip]
        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=new_wip_entries,
            standard_costs=self.standard_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_wip_for_work_order(self, work_order_id: UUID) -> WorkInProcessEntity | None:
        for wip in self.wip_entries:
            if wip.work_order_id == work_order_id:
                return wip
        return None

    def get_open_wip_entries(self) -> list[WorkInProcessEntity]:
        return [wip for wip in self.wip_entries if wip.status == WIPStatus.OPEN]

    def calculate_total_wip_value(self) -> Decimal:
        total = Decimal(0)
        for wip in self.wip_entries:
            if wip.status == WIPStatus.OPEN:
                total += wip.get_remaining_value()
        return total

    # ==================== STANDARD COST MANAGEMENT ====================

    def add_standard_cost(
        self, standard_cost: StandardCostEntity, created_by: str
    ) -> ManufacturingAggregate:
        new_std_costs = dict(self.standard_costs)
        new_std_costs[standard_cost.product_id] = standard_cost

        self._add_event(
            StandardCostCreatedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                standard_cost_id=standard_cost.standard_cost_id,
                product_id=standard_cost.product_id,
                product_code=standard_cost.product_code,
                product_name=standard_cost.product_name,
                material_cost=standard_cost.material_cost,
                labor_cost=standard_cost.labor_cost,
                overhead_cost=standard_cost.overhead_cost,
                total_cost=standard_cost.total_cost,
                effective_date=standard_cost.effective_date,
                created_by=created_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=new_std_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def activate_standard_cost(self, product_id: UUID, activated_by: str) -> ManufacturingAggregate:
        std_cost = self.standard_costs.get(product_id)
        if not std_cost:
            raise ValueError(f"Standard cost for product {product_id} not found")
        if std_cost.status != StandardCostStatus.DRAFT:
            raise ValueError(f"Cannot activate standard cost in status {std_cost.status.value}")

        activated = std_cost.activate(activated_by)
        new_std_costs = dict(self.standard_costs)
        new_std_costs[product_id] = activated

        self._add_event(
            StandardCostActivatedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                standard_cost_id=activated.standard_cost_id,
                product_id=activated.product_id,
                product_code=activated.product_code,
                product_name=activated.product_name,
                activated_by=activated_by,
            )
        )

        self.increment_version()
        return ManufacturingAggregate(
            manufacturing_id=self.manufacturing_id,
            legal_entity_id=self.legal_entity_id,
            work_orders=self.work_orders,
            bills_of_materials=self.bills_of_materials,
            wip_entries=self.wip_entries,
            standard_costs=new_std_costs,
            variance_engine=self.variance_engine,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_standard_cost(
        self, product_id: UUID, as_of_date: datetime | None = None
    ) -> StandardCostEntity | None:
        std = self.standard_costs.get(product_id)
        if not std:
            return None
        check_date = as_of_date or datetime.now(UTC)
        if std.is_active_at_date(check_date):
            return std
        return None

    # ==================== VARIANCE ANALYSIS ====================

    def calculate_variance(
        self,
        work_order_id: UUID,
        actual_material_cost: Decimal,
        actual_labor_cost: Decimal,
        actual_overhead_cost: Decimal,
    ) -> VarianceAnalysisResult:
        work_order = self.work_orders.get(work_order_id)
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")

        std_cost = self.get_standard_cost(work_order.product_id)
        result = self.variance_engine.analyze_variance(
            work_order=work_order,
            actual_material_cost=actual_material_cost,
            actual_labor_cost=actual_labor_cost,
            actual_overhead_cost=actual_overhead_cost,
            standard_cost=std_cost,
        )

        self._add_event(
            VarianceAnalyzedEvent(
                aggregate_id=self.manufacturing_id,
                aggregate_version=self.version + 1,
                work_order_id=work_order_id,
                work_order_number=work_order.work_order_number,
                total_variance=result.total_variance,
                variance_type=result.total_variance_type.value,
                material_variance=result.components[0].variance_amount
                if len(result.components) > 0
                else Decimal(0),
                labor_variance=result.components[1].variance_amount
                if len(result.components) > 1
                else Decimal(0),
                overhead_variance=result.components[2].variance_amount
                if len(result.components) > 2
                else Decimal(0),
                analyzed_by="system",
            )
        )

        self.increment_version()
        return result

    # ==================== UTILITY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "manufacturing_id": str(self.manufacturing_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_work_orders": len(self.work_orders),
            "active_work_orders": len(self.get_active_work_orders()),
            "total_boms": len(self.bills_of_materials),
            "total_wip_value": str(self.calculate_total_wip_value()),
            "total_standard_costs": len(self.standard_costs),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    def __repr__(self) -> str:
        return (
            f"ManufacturingAggregate(manufacturing_id={self.manufacturing_id}, "
            f"legal_entity_id={self.legal_entity_id}, version={self.version})"
        )


class ManufacturingRepository:
    async def get_by_legal_entity(self, legal_entity_id: UUID) -> ManufacturingAggregate | None:
        raise NotImplementedError

    async def save(self, manufacturing: ManufacturingAggregate) -> None:
        raise NotImplementedError

    async def delete(self, manufacturing_id: UUID) -> None:
        raise NotImplementedError


__all__ = ["ManufacturingAggregate", "ManufacturingRepository", "WorkOrder"]
WorkOrder = WorkOrderEntity
