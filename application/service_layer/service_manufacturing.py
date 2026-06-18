# service_manufacturing.py - Complete rewrite with full implementation

#!/usr/bin/env python3

"""
Module: service_manufacturing.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer for Manufacturing / Production.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.bill_of_materials_entity import BillOfMaterials, BOMItem
from domain.manufacturing.domain_events import (
    BOMCreated,
    WorkOrderCompleted,
    WorkOrderCreated,
    WorkOrderStarted,
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
class ProductionCompletionRequest:
    """Request to complete production."""

    work_order_id: UUID
    completed_quantity: Decimal
    rejected_quantity: Decimal
    completion_date: date
    completed_by: UUID
    remarks: str | None = None


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
            event = BOMCreated(
                bom_id=bom.id,
                product_id=request.product_id,
                version=request.version,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
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
            event = WorkOrderCreated(
                work_order_id=work_order.id,
                work_order_number=wo_number,
                product_id=request.product_id,
                quantity=request.quantity,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
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

        if work_order.status != WorkOrderStatus.DRAFT:
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

        # Issue materials
        for item in bom.items:
            issue_qty = item.quantity * work_order.quantity * (1 + item.scrap_percentage / 100)
            await self._inventory_repo.issue_material(
                item.component_id, issue_qty, f"WO {work_order.work_order_number}", user_id
            )

        work_order.status = WorkOrderStatus.IN_PROGRESS
        work_order.started_at = datetime.utcnow()
        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = WorkOrderStarted(
                work_order_id=work_order_id,
                work_order_number=work_order.work_order_number,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
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

    async def complete_work_order(
        self,
        work_order_id: UUID,
        completed_quantity: Decimal,
        user_id: UUID,
        correlation_id: str | None = None,
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
        if work_order.completed_quantity >= work_order.quantity:
            work_order.status = WorkOrderStatus.COMPLETED
            work_order.completed_at = datetime.utcnow()

        # Receive finished goods into inventory
        await self._inventory_repo.receive_finished_goods(
            work_order.product_id, completed_quantity, f"WO {work_order.work_order_number}", user_id
        )

        await self._mfg_repo.save_work_order(work_order)
        if self._uow:
            await self._uow.commit()

        self._stats["work_orders_completed"] += 1

        if self._event_publisher:
            event = WorkOrderCompleted(
                work_order_id=work_order_id,
                work_order_number=work_order.work_order_number,
                completed_quantity=completed_quantity,
                user_id=user_id,
                occurred_at=datetime.utcnow(),
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
    "InsufficientMaterialError",
    "ManufacturingOrderType",
    "ManufacturingService",
    "ManufacturingServiceError",
    "MaterialIssueRequest",
    "ProductionCompletionRequest",
    "WorkOrderNotFoundError",
    "WorkOrderRequest",
    "WorkOrderResponse",
    "WorkOrderStatusEnum",
    "create_manufacturing_service",
]
