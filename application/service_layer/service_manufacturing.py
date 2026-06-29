# service_manufacturing.py - Complete rewrite with correct event names (with Event suffix)

#!/usr/bin/env python3

"""
Module: service_manufacturing.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Manufacturing / Production.
    Mempublikasikan semua domain events yang sesuai (dengan nama event yang benar di registry).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.bill_of_materials_entity import BillOfMaterials, BOMItem, BOMStatus
from domain.manufacturing.domain_events import (
    BOMActivatedEvent,
    BOMCreatedEvent,
    BOMItemAddedEvent,
    BOMObsoletedEvent,
    BOMUpdatedEvent,
    CostCardUpdatedEvent,
    HPPCalculatedEvent,
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
)
from domain.manufacturing.hpp_per_product_calculator import HPPCalculator
from domain.manufacturing.invariants import ManufacturingInvariantsValidator
from domain.manufacturing.overhead_allocation_engine import OverheadAllocationEngine
from domain.manufacturing.variance_analysis_engine import VarianceAnalysisEngine
from domain.manufacturing.work_order_entity import WorkOrder, WorkOrderStatus
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
from ports.primary.manufacturing_repository_port import ManufacturingRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class WorkOrderStatusEnum(str, Enum):
    """Status work order."""

    DRAFT = "draft"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class ManufacturingOrderType(str, Enum):
    """Type of manufacturing order."""

    STANDARD = "standard"
    CUSTOM = "custom"
    REPAIR = "repair"
    PROTOTYPE = "prototype"


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class BOMRequest:
    """Request to create Bill of Materials."""

    product_id: UUID
    product_code: str
    effective_date: date
    version: str = "1.0.0"
    is_active: bool = True
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(kw_only=True)
class BOMUpdateRequest:
    """Request to update Bill of Materials."""

    bom_id: UUID
    effective_date: date | None = None
    is_active: bool | None = None
    items: list[dict[str, Any]] | None = None


@dataclass(kw_only=True)
class BOMResponse:
    """Response for Bill of Materials."""

    bom_id: UUID
    product_id: UUID
    items: list[dict[str, Any]]
    total_material_cost: Decimal
    effective_date: date
    is_active: bool
    version: str


@dataclass(kw_only=True)
class WorkOrderRequest:
    """Request to create work order."""

    product_id: UUID
    product_code: str
    quantity: Decimal
    due_date: date
    bom_version: str | None = None
    routing_id: UUID | None = None
    legal_entity_id: UUID


@dataclass(kw_only=True)
class WorkOrderResponse:
    """Response for work order."""

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    quantity: Decimal
    completed_quantity: Decimal
    due_date: date
    status: str
    created_at: datetime


@dataclass(kw_only=True)
class MaterialIssueRequest:
    """Request to issue material to production."""

    work_order_id: UUID
    material_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    issue_date: date
    issued_by: UUID
    notes: str | None = None


@dataclass(kw_only=True)
class LaborPostRequest:
    """Request to post labor to a work order."""

    work_order_id: UUID
    employee_id: UUID
    employee_name: str
    hours: Decimal
    rate: Decimal
    work_date: date
    posted_by: UUID
    notes: str | None = None


@dataclass(kw_only=True)
class OverheadApplyRequest:
    """Request to apply overhead to a work order."""

    work_order_id: UUID
    overhead_pool: str
    amount: Decimal
    allocation_basis: str
    applied_by: UUID
    notes: str | None = None


@dataclass(kw_only=True)
class ProductionCompletionRequest:
    """Request to complete production."""

    work_order_id: UUID
    completed_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0")
    completion_date: date
    completed_by: UUID
    remarks: str | None = None


@dataclass(kw_only=True)
class StandardCostRequest:
    """Request to create standard cost."""

    product_id: UUID
    product_code: str
    product_name: str
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    effective_date: date
    created_by: UUID


@dataclass(kw_only=True)
class HPPCalculationRequest:
    """Request to calculate HPP."""

    product_id: UUID
    period_start: date
    period_end: date


# ============================================================================
# Exceptions
# ============================================================================


class ManufacturingServiceError(Exception):
    pass


class BOMNotFoundError(ManufacturingServiceError):
    pass


class WorkOrderNotFoundError(ManufacturingServiceError):
    pass


class InsufficientMaterialError(ManufacturingServiceError):
    pass


# ============================================================================
# Main Service
# ============================================================================


class ManufacturingService:
    """
    Service untuk manufaktur dan produksi.
    Mempublikasikan semua domain events dengan nama yang benar.
    """

    def __init__(
        self,
        manufacturing_repo: ManufacturingRepositoryPort,
        inventory_repo: InventoryRepositoryPort,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        if manufacturing_repo is None:
            raise ValueError("manufacturing_repo is required")
        if inventory_repo is None:
            raise ValueError("inventory_repo is required")

        self._mfg_repo = manufacturing_repo
        self._inventory_repo = inventory_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = ManufacturingInvariantsValidator()
        self._variance_engine = VarianceAnalysisEngine()
        self._overhead_engine = OverheadAllocationEngine()
        self._hpp_calculator = HPPCalculator()
        self._stats = {"boms_created": 0, "work_orders_created": 0, "work_orders_completed": 0}

        logger.info("ManufacturingService initialized")

    # ========================================================================
    # Bill of Materials (BOM)
    # ========================================================================

    async def create_bom(
        self, request: BOMRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BOMResponse:
        """Create a new Bill of Materials."""
        # Validate components exist in inventory
        for item in request.items:
            component = await self._inventory_repo.get_item_by_id(item["component_id"])
            if not component:
                raise ManufacturingServiceError(f"Component {item['component_id']} not found")

        bom = BillOfMaterials(
            id=uuid4(),
            product_id=request.product_id,
            product_code=request.product_code,
            version=request.version,
            effective_date=request.effective_date,
            is_active=request.is_active,
            items=[
                BOMItem(
                    component_id=item["component_id"],
                    quantity=Decimal(str(item["quantity"])),
                    scrap_percentage=Decimal(str(item.get("scrap_percentage", 0))),
                )
                for item in request.items
            ],
            created_by=user_id,
            created_at=datetime.utcnow(),
            updated_at=None,
        )

        # Calculate total material cost
        total_cost = Decimal("0")
        for bom_item in bom.items:
            component = await self._inventory_repo.get_item_by_id(bom_item.component_id)
            if component:
                total_cost += component.item.average_cost * bom_item.quantity

        await self._mfg_repo.save_bom(bom)
        if self._uow:
            await self._uow.commit()

        self._stats["boms_created"] += 1

        if self._event_publisher:
            event = BOMCreatedEvent(
                aggregate_id=bom.id,
                aggregate_version=1,
                bom=bom,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return BOMResponse(
            bom_id=bom.id,
            product_id=bom.product_id,
            version=bom.version,
            items=[
                {
                    "component_id": i.component_id,
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=bom.effective_date,
            is_active=bom.is_active,
        )

    async def update_bom(
        self,
        request: BOMUpdateRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BOMResponse:
        """Update an existing BOM."""
        bom = await self._mfg_repo.get_bom_by_id(request.bom_id)
        if not bom:
            raise BOMNotFoundError(f"BOM {request.bom_id} not found")

        changes = {}
        if request.effective_date is not None:
            changes["effective_date"] = request.effective_date
            bom.effective_date = request.effective_date
        if request.is_active is not None:
            changes["is_active"] = request.is_active
            bom.is_active = request.is_active
        if request.items is not None:
            old_items = [{"component_id": i.component_id, "quantity": i.quantity} for i in bom.items]
            bom.items = [
                BOMItem(
                    component_id=item["component_id"],
                    quantity=Decimal(str(item["quantity"])),
                    scrap_percentage=Decimal(str(item.get("scrap_percentage", 0))),
                )
                for item in request.items
            ]
            changes["items"] = {"old": old_items, "new": request.items}

        bom.updated_at = datetime.utcnow()
        bom.updated_by = user_id
        bom.version += 1

        await self._mfg_repo.save_bom(bom)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = BOMUpdatedEvent(
                aggregate_id=bom.id,
                aggregate_version=bom.version,
                bom_id=bom.id,
                bom_code=bom.product_code,
                changes=changes,
                updated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        # Recalculate total cost
        total_cost = Decimal("0")
        for bom_item in bom.items:
            component = await self._inventory_repo.get_item_by_id(bom_item.component_id)
            if component:
                total_cost += component.item.average_cost * bom_item.quantity

        return BOMResponse(
            bom_id=bom.id,
            product_id=bom.product_id,
            version=bom.version,
            items=[
                {
                    "component_id": i.component_id,
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=bom.effective_date,
            is_active=bom.is_active,
        )

    async def activate_bom(
        self,
        bom_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BOMResponse:
        """Activate a BOM."""
        bom = await self._mfg_repo.get_bom_by_id(bom_id)
        if not bom:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        # Deactivate other BOMs for same product
        await self._mfg_repo.deactivate_boms_for_product(bom.product_id, exclude_bom_id=bom_id)

        bom.is_active = True
        bom.updated_at = datetime.utcnow()
        bom.updated_by = user_id
        bom.version += 1

        await self._mfg_repo.save_bom(bom)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = BOMActivatedEvent(
                aggregate_id=bom.id,
                aggregate_version=bom.version,
                bom=bom,
                activated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return await self.get_active_bom(bom.product_id, date.today())

    async def obsolete_bom(
        self,
        bom_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Mark BOM as obsolete."""
        bom = await self._mfg_repo.get_bom_by_id(bom_id)
        if not bom:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        bom.is_active = False
        bom.updated_at = datetime.utcnow()
        bom.updated_by = user_id
        bom.version += 1

        await self._mfg_repo.save_bom(bom)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = BOMObsoletedEvent(
                aggregate_id=bom.id,
                aggregate_version=bom.version,
                bom=bom,
                reason=reason,
                obsoleted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return True

    async def add_bom_item(
        self,
        bom_id: UUID,
        component_id: UUID,
        quantity: Decimal,
        scrap_percentage: Decimal = Decimal("0"),
        user_id: UUID | None = None,
        correlation_id: str | None = None,
    ) -> BOMResponse:
        """Add an item to an existing BOM."""
        bom = await self._mfg_repo.get_bom_by_id(bom_id)
        if not bom:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        # Validate component exists
        component = await self._inventory_repo.get_item_by_id(component_id)
        if not component:
            raise ManufacturingServiceError(f"Component {component_id} not found")

        new_item = BOMItem(
            component_id=component_id,
            quantity=quantity,
            scrap_percentage=scrap_percentage,
        )
        bom.items.append(new_item)
        bom.updated_at = datetime.utcnow()
        bom.updated_by = user_id
        bom.version += 1

        await self._mfg_repo.save_bom(bom)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = BOMItemAddedEvent(
                aggregate_id=bom.id,
                aggregate_version=bom.version,
                bom_id=bom.id,
                bom_code=bom.product_code,
                item=new_item,
                added_by=str(user_id) if user_id else "system",
                user_id=str(user_id) if user_id else None,
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        # Recalculate total cost
        total_cost = Decimal("0")
        for bom_item in bom.items:
            comp = await self._inventory_repo.get_item_by_id(bom_item.component_id)
            if comp:
                total_cost += comp.item.average_cost * bom_item.quantity

        return BOMResponse(
            bom_id=bom.id,
            product_id=bom.product_id,
            version=bom.version,
            items=[
                {
                    "component_id": i.component_id,
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=bom.effective_date,
            is_active=bom.is_active,
        )

    async def get_active_bom(self, product_id: UUID, as_of_date: date) -> BOMResponse | None:
        """Get active BOM for a product."""
        bom = await self._mfg_repo.get_active_bom(product_id, as_of_date)
        if not bom:
            return None

        total_cost = Decimal("0")
        for item in bom.items:
            component = await self._inventory_repo.get_item_by_id(item.component_id)
            if component:
                total_cost += component.item.average_cost * item.quantity

        return BOMResponse(
            bom_id=bom.id,
            product_id=bom.product_id,
            version=bom.version,
            items=[
                {
                    "component_id": i.component_id,
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=bom.effective_date,
            is_active=bom.is_active,
        )

    # ========================================================================
    # Work Order
    # ========================================================================

    async def create_work_order(
        self, request: WorkOrderRequest, user_id: UUID, correlation_id: str | None = None
    ) -> WorkOrderResponse:
        """Create a production work order."""
        # Get active BOM
        bom = await self._mfg_repo.get_active_bom(request.product_id, date.today())
        if not bom:
            raise BOMNotFoundError(f"No active BOM for product {request.product_id}")

        # Generate work order number
        wo_number = await self._generate_wo_number(request.product_code)

        work_order = WorkOrder(
            id=uuid4(),
            work_order_number=wo_number,
            product_id=request.product_id,
            product_code=request.product_code,
            quantity=request.quantity,
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.DRAFT,
            due_date=request.due_date,
            bom_id=bom.id,
            routing_id=request.routing_id,
            legal_entity_id=request.legal_entity_id,
            created_by=user_id,
            created_at=datetime.utcnow(),
            started_at=None,
            completed_at=None,
        )

        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        self._stats["work_orders_created"] += 1

        if self._event_publisher:
            event = WorkOrderCreatedEvent(
                aggregate_id=work_order.id,
                aggregate_version=1,
                work_order=work_order,
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return WorkOrderResponse(
            work_order_id=work_order.id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            quantity=work_order.quantity,
            completed_quantity=work_order.completed_quantity,
            due_date=work_order.due_date,
            status=work_order.status.value,
            created_at=work_order.created_at,
        )

    async def approve_work_order(
        self,
        work_order_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> WorkOrderResponse:
        """Approve a work order."""
        work_order = await self._mfg_repo.get_work_order(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        if work_order.status != WorkOrderStatus.DRAFT:
            raise ManufacturingServiceError(
                f"Cannot approve work order in status {work_order.status.value}"
            )

        work_order.status = WorkOrderStatus.APPROVED
        work_order.updated_at = datetime.utcnow()
        work_order.version += 1
        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = WorkOrderApprovedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order=work_order,
                approved_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return WorkOrderResponse(
            work_order_id=work_order.id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            quantity=work_order.quantity,
            completed_quantity=work_order.completed_quantity,
            due_date=work_order.due_date,
            status=work_order.status.value,
            created_at=work_order.created_at,
        )

    async def start_work_order(
        self, work_order_id: UUID, user_id: UUID, correlation_id: str | None = None
    ) -> WorkOrderResponse:
        """Start production, issue raw materials."""
        work_order = await self._mfg_repo.get_work_order(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        if work_order.status not in (WorkOrderStatus.DRAFT, WorkOrderStatus.APPROVED):
            raise ManufacturingServiceError(
                f"Cannot start work order in status {work_order.status.value}"
            )

        # Get BOM components
        bom = await self._mfg_repo.get_bom_by_id(work_order.bom_id)
        if not bom:
            raise BOMNotFoundError(f"BOM {work_order.bom_id} not found")

        # Check material availability
        for item in bom.items:
            required_qty = item.quantity * work_order.quantity * (1 + item.scrap_percentage / 100)
            component = await self._inventory_repo.get_item_by_id(item.component_id)
            if not component or component.item.current_stock < required_qty:
                raise InsufficientMaterialError(
                    f"Insufficient stock for component {item.component_id}"
                )

        # Issue materials and publish MaterialIssued event
        for item in bom.items:
            issue_qty = item.quantity * work_order.quantity * (1 + item.scrap_percentage / 100)
            component = await self._inventory_repo.get_item_by_id(item.component_id)
            unit_cost = component.item.average_cost if component else Decimal("0")
            await self._inventory_repo.issue_material(
                item.component_id, issue_qty, f"WO {work_order.work_order_number}", user_id
            )

            # Publish MaterialIssued event per component
            if self._event_publisher and component:
                event = MaterialIssuedEvent(
                    aggregate_id=work_order.id,
                    aggregate_version=1,
                    work_order_id=work_order.id,
                    work_order_number=work_order.work_order_number,
                    material_id=item.component_id,
                    material_code=component.item.sku if component else "unknown",
                    material_name=component.item.name if component else "unknown",
                    quantity=issue_qty,
                    cost=issue_qty * unit_cost,
                    issued_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event, correlation_id=correlation_id)

        work_order.status = WorkOrderStatus.IN_PROGRESS
        work_order.started_at = datetime.utcnow()
        work_order.updated_at = datetime.utcnow()
        work_order.version += 1
        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = WorkOrderStartedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order=work_order,
                started_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return WorkOrderResponse(
            work_order_id=work_order.id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            quantity=work_order.quantity,
            completed_quantity=work_order.completed_quantity,
            due_date=work_order.due_date,
            status=work_order.status.value,
            created_at=work_order.created_at,
        )

    async def post_labor(
        self,
        request: LaborPostRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Post labor to a work order."""
        work_order = await self._mfg_repo.get_work_order(request.work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {request.work_order_id} not found")

        if work_order.status != WorkOrderStatus.IN_PROGRESS:
            raise ManufacturingServiceError("Labor can only be posted to work orders in progress")

        cost = request.hours * request.rate

        # Save labor record
        await self._mfg_repo.save_labor(
            work_order_id=request.work_order_id,
            employee_id=request.employee_id,
            hours=request.hours,
            rate=request.rate,
            cost=cost,
            work_date=request.work_date,
            posted_by=user_id,
        )
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = LaborPostedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                employee_id=request.employee_id,
                employee_name=request.employee_name,
                hours=request.hours,
                rate=request.rate,
                cost=cost,
                posted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "work_order_id": str(request.work_order_id),
            "employee_id": str(request.employee_id),
            "hours": request.hours,
            "rate": request.rate,
            "cost": cost,
        }

    async def apply_overhead(
        self,
        request: OverheadApplyRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply overhead to a work order."""
        work_order = await self._mfg_repo.get_work_order(request.work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {request.work_order_id} not found")

        if work_order.status != WorkOrderStatus.IN_PROGRESS:
            raise ManufacturingServiceError("Overhead can only be applied to work orders in progress")

        # Save overhead record
        await self._mfg_repo.save_overhead(
            work_order_id=request.work_order_id,
            overhead_pool=request.overhead_pool,
            amount=request.amount,
            allocation_basis=request.allocation_basis,
            applied_by=user_id,
            notes=request.notes,
        )
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = OverheadAppliedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                overhead_pool=request.overhead_pool,
                amount=request.amount,
                allocation_basis=request.allocation_basis,
                applied_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "work_order_id": str(request.work_order_id),
            "overhead_pool": request.overhead_pool,
            "amount": request.amount,
        }

    async def complete_work_order(
        self,
        work_order_id: UUID,
        completed_quantity: Decimal,
        user_id: UUID,
        correlation_id: str | None = None,
        rejected_quantity: Decimal = Decimal("0"),
    ) -> WorkOrderResponse:
        """Complete work order, receive finished goods."""
        work_order = await self._mfg_repo.get_work_order(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        if work_order.status != WorkOrderStatus.IN_PROGRESS:
            raise ManufacturingServiceError("Only work orders in progress can be completed")

        if completed_quantity > work_order.quantity:
            raise ManufacturingServiceError("Completed quantity exceeds planned quantity")

        work_order.completed_quantity += completed_quantity
        is_fully_completed = work_order.completed_quantity >= work_order.quantity
        if is_fully_completed:
            work_order.status = WorkOrderStatus.COMPLETED
            work_order.completed_at = datetime.utcnow()
        else:
            work_order.status = WorkOrderStatus.PARTIALLY_COMPLETED
        work_order.updated_at = datetime.utcnow()
        work_order.version += 1

        # Receive finished goods into inventory
        bom = await self._mfg_repo.get_bom_by_id(work_order.bom_id)
        unit_cost = Decimal("0")
        if bom:
            for item in bom.items:
                comp = await self._inventory_repo.get_item_by_id(item.component_id)
                if comp:
                    unit_cost += comp.item.average_cost * item.quantity
            # Add labor and overhead costs (simplified)
            labor_total = await self._mfg_repo.get_total_labor_for_work_order(work_order_id)
            overhead_total = await self._mfg_repo.get_total_overhead_for_work_order(work_order_id)
            unit_cost += (labor_total + overhead_total) / work_order.quantity

        await self._inventory_repo.receive_finished_goods(
            work_order.product_id,
            completed_quantity,
            f"WO {work_order.work_order_number}",
            user_id,
            unit_cost,
        )

        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        self._stats["work_orders_completed"] += 1

        if self._event_publisher:
            # Publish ProductionCompleted event
            prod_event = ProductionCompletedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                product_id=work_order.product_id,
                product_code=work_order.product_code,
                product_name=work_order.product_code,  # placeholder
                quantity=completed_quantity,
                unit_cost=unit_cost,
                total_cost=completed_quantity * unit_cost,
                completed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(prod_event, correlation_id=correlation_id)

            # Also publish WorkOrderCompleted
            wo_event = WorkOrderCompletedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order=work_order,
                completed_quantity=completed_quantity,
                completed_by=str(user_id),
                is_fully_completed=is_fully_completed,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(wo_event, correlation_id=correlation_id)

        return WorkOrderResponse(
            work_order_id=work_order.id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            quantity=work_order.quantity,
            completed_quantity=work_order.completed_quantity,
            due_date=work_order.due_date,
            status=work_order.status.value,
            created_at=work_order.created_at,
        )

    async def cancel_work_order(
        self,
        work_order_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        """Cancel a work order."""
        work_order = await self._mfg_repo.get_work_order(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        if work_order.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            raise ManufacturingServiceError(f"Cannot cancel work order in status {work_order.status.value}")

        work_order.status = WorkOrderStatus.CANCELLED
        work_order.updated_at = datetime.utcnow()
        work_order.version += 1
        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = WorkOrderCancelledEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order=work_order,
                reason=reason,
                cancelled_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return True

    # ========================================================================
    # Standard Cost
    # ========================================================================

    async def create_standard_cost(
        self,
        request: StandardCostRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a standard cost for a product."""
        standard_cost_id = uuid4()
        total_cost = request.material_cost + request.labor_cost + request.overhead_cost

        await self._mfg_repo.save_standard_cost(
            standard_cost_id=standard_cost_id,
            product_id=request.product_id,
            product_code=request.product_code,
            product_name=request.product_name,
            material_cost=request.material_cost,
            labor_cost=request.labor_cost,
            overhead_cost=request.overhead_cost,
            total_cost=total_cost,
            effective_date=request.effective_date,
            created_by=user_id,
        )
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = StandardCostCreatedEvent(
                aggregate_id=standard_cost_id,
                aggregate_version=1,
                standard_cost_id=standard_cost_id,
                product_id=request.product_id,
                product_code=request.product_code,
                product_name=request.product_name,
                material_cost=request.material_cost,
                labor_cost=request.labor_cost,
                overhead_cost=request.overhead_cost,
                total_cost=total_cost,
                effective_date=datetime.combine(request.effective_date, datetime.min.time()),
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "standard_cost_id": str(standard_cost_id),
            "product_id": str(request.product_id),
            "total_cost": total_cost,
        }

    async def activate_standard_cost(
        self,
        standard_cost_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Activate a standard cost."""
        sc = await self._mfg_repo.get_standard_cost(standard_cost_id)
        if not sc:
            raise ManufacturingServiceError(f"Standard cost {standard_cost_id} not found")

        # Deactivate other standard costs for same product
        await self._mfg_repo.deactivate_standard_costs_for_product(sc.product_id, exclude_id=standard_cost_id)

        await self._mfg_repo.activate_standard_cost(standard_cost_id, user_id)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = StandardCostActivatedEvent(
                aggregate_id=standard_cost_id,
                aggregate_version=1,
                standard_cost_id=standard_cost_id,
                product_id=sc.product_id,
                product_code=sc.product_code,
                product_name=sc.product_name,
                activated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {"standard_cost_id": str(standard_cost_id), "activated": True}

    # ========================================================================
    # HPP Calculation
    # ========================================================================

    async def calculate_hpp(
        self,
        request: HPPCalculationRequest,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Calculate HPP for a product over a period."""
        work_orders = await self._mfg_repo.get_completed_work_orders(
            request.product_id,
            request.period_start,
            request.period_end,
        )

        total_units = Decimal("0")
        total_cost = Decimal("0")

        for wo in work_orders:
            total_units += wo.completed_quantity
            bom = await self._mfg_repo.get_bom_by_id(wo.bom_id)
            if bom:
                for item in bom.items:
                    comp = await self._inventory_repo.get_item_by_id(item.component_id)
                    if comp:
                        total_cost += comp.item.average_cost * item.quantity * wo.completed_quantity
            labor_total = await self._mfg_repo.get_total_labor_for_work_order(wo.id)
            overhead_total = await self._mfg_repo.get_total_overhead_for_work_order(wo.id)
            total_cost += labor_total + overhead_total

        unit_hpp = total_cost / total_units if total_units > 0 else Decimal("0")

        if self._event_publisher:
            event = HPPCalculatedEvent(
                aggregate_id=request.product_id,
                aggregate_version=1,
                product_id=request.product_id,
                period_start=datetime.combine(request.period_start, datetime.min.time()),
                period_end=datetime.combine(request.period_end, datetime.max.time()),
                units_produced=total_units,
                total_cost=total_cost,
                unit_hpp=unit_hpp,
                calculated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "product_id": str(request.product_id),
            "period_start": request.period_start.isoformat(),
            "period_end": request.period_end.isoformat(),
            "units_produced": total_units,
            "total_cost": total_cost,
            "unit_hpp": unit_hpp,
        }

    # ========================================================================
    # Variance Analysis
    # ========================================================================

    async def analyze_variance(
        self,
        work_order_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Perform variance analysis for a completed work order."""
        work_order = await self._mfg_repo.get_work_order(work_order_id)
        if not work_order:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        if work_order.status != WorkOrderStatus.COMPLETED:
            raise ManufacturingServiceError("Variance analysis only for completed work orders")

        # Get standard cost
        std_cost = await self._mfg_repo.get_active_standard_cost(work_order.product_id)
        if not std_cost:
            raise ManufacturingServiceError(f"No standard cost for product {work_order.product_id}")

        # Get actual costs
        bom = await self._mfg_repo.get_bom_by_id(work_order.bom_id)
        actual_material = Decimal("0")
        if bom:
            for item in bom.items:
                comp = await self._inventory_repo.get_item_by_id(item.component_id)
                if comp:
                    actual_material += comp.item.average_cost * item.quantity * work_order.completed_quantity

        actual_labor = await self._mfg_repo.get_total_labor_for_work_order(work_order_id)
        actual_overhead = await self._mfg_repo.get_total_overhead_for_work_order(work_order_id)

        standard_total = (std_cost.material_cost + std_cost.labor_cost + std_cost.overhead_cost) * work_order.completed_quantity
        actual_total = actual_material + actual_labor + actual_overhead
        total_variance = actual_total - standard_total

        variance_type = "unfavorable" if total_variance > 0 else "favorable"

        if self._event_publisher:
            event = VarianceAnalyzedEvent(
                aggregate_id=work_order.id,
                aggregate_version=work_order.version,
                work_order_id=work_order.id,
                work_order_number=work_order.work_order_number,
                total_variance=total_variance,
                variance_type=variance_type,
                material_variance=actual_material - (std_cost.material_cost * work_order.completed_quantity),
                labor_variance=actual_labor - (std_cost.labor_cost * work_order.completed_quantity),
                overhead_variance=actual_overhead - (std_cost.overhead_cost * work_order.completed_quantity),
                analyzed_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "work_order_id": str(work_order_id),
            "total_variance": total_variance,
            "variance_type": variance_type,
            "material_variance": actual_material - (std_cost.material_cost * work_order.completed_quantity),
            "labor_variance": actual_labor - (std_cost.labor_cost * work_order.completed_quantity),
            "overhead_variance": actual_overhead - (std_cost.overhead_cost * work_order.completed_quantity),
        }

    # ========================================================================
    # Cost Card
    # ========================================================================

    async def update_cost_card(
        self,
        product_id: UUID,
        period: str,
        total_cost: Decimal,
        unit_cost: Decimal,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Update cost card for a product."""
        await self._mfg_repo.save_cost_card(
            product_id=product_id,
            period=period,
            total_cost=total_cost,
            unit_cost=unit_cost,
            updated_by=user_id,
        )
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = CostCardUpdatedEvent(
                aggregate_id=product_id,
                aggregate_version=1,
                product_id=product_id,
                period=period,
                total_cost=total_cost,
                unit_cost=unit_cost,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event, correlation_id=correlation_id)

        return {
            "product_id": str(product_id),
            "period": period,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
        }

    # ========================================================================
    # Helpers
    # ========================================================================

    async def _generate_wo_number(self, product_code: str) -> str:
        """Generate work order number."""
        last = await self._mfg_repo.get_last_work_order_number()
        seq = int(last.split("-")[-1]) + 1 if last else 1
        return f"WO-{product_code}-{seq:06d}"

    def get_stats(self) -> dict[str, int]:
        """Get service statistics."""
        return self._stats.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_manufacturing_service(
    manufacturing_repo: ManufacturingRepositoryPort,
    inventory_repo: InventoryRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> ManufacturingService:
    return ManufacturingService(manufacturing_repo, inventory_repo, uow, event_publisher)


__all__ = [
    "BOMNotFoundError",
    "BOMRequest",
    "BOMResponse",
    "BOMUpdateRequest",
    "InsufficientMaterialError",
    "ManufacturingOrderType",
    "ManufacturingService",
    "ManufacturingServiceError",
    "MaterialIssueRequest",
    "LaborPostRequest",
    "OverheadApplyRequest",
    "ProductionCompletionRequest",
    "StandardCostRequest",
    "HPPCalculationRequest",
    "WorkOrderNotFoundError",
    "WorkOrderRequest",
    "WorkOrderResponse",
    "WorkOrderStatusEnum",
    "create_manufacturing_service",
]