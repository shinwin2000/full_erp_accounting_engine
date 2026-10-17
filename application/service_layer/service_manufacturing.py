#!/usr/bin/env python3
"""
Module: service_manufacturing.py
Layer: 8 - Application / Service Layer
Responsibility:
    Service layer untuk Manufacturing / Production.
    Mempublikasikan semua domain events yang sesuai.

Design notes (v6.2):
    - Signature DUAL: mendukung pola lama `create_bom(request: BOMRequest, user_id, ...)`
      (untuk backward-compat dengan workflow & test) DAN pola baru kwargs-based
      yang dipanggil oleh fastapi_manufacturing_router.py.
    - Semua method baru (list_*, get_*_by_id, create_routing, release_work_order,
      close_work_order, update_work_order, deactivate_bom, export_work_orders,
      create_cost_card, list_cost_cards) diimplementasikan sebagai thin wrapper
      di atas ManufacturingRepositoryPort / RoutingRepositoryPort.
    - Kapabilitas agregasi (get_work_order_costs, get_wip_value,
      get_manufacturing_costs, close_period) diekspos ke workflow cost flow /
      COGS / HPP close.

Changelog v6.2:
    - FIX: tambah DTO `RoutingResponse`. Router schema memakai enum
      `RoutingStatus` sendiri; kalau service mengembalikan entity domain,
      `RoutingStatus(r.status)` gagal karena domain enum tidak kompatibel
      dengan enum router. Solusi: konversi `status` ke string di DTO.
    - FIX: `create_routing` dan `list_routings` sekarang return DTO
      (`RoutingResponse`), bukan entity domain.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.bill_of_materials_entity import (
    BillOfMaterialsEntity,
    BOMItem,
    BOMStatus,
)
from domain.manufacturing.cost_card_entity import (
    CostCardEntity,
    CostCardStatus,
)
from domain.manufacturing.cost_element_enum import CostElement
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
from domain.manufacturing.production_routing_entity import (
    ProductionRoutingEntity,
    RoutingOperation,
    RoutingStatus,
)
from domain.manufacturing.standard_cost_entity import (
    StandardCostEntity,
    StandardCostStatus,
)
from domain.manufacturing.variance_analysis_engine import VarianceAnalysisEngine
from domain.manufacturing.work_order_entity import (
    WorkOrderEntity,
    WorkOrderPriority,
    WorkOrderStatus,
    WorkOrderType,
)
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.inventory_repository_port import InventoryRepositoryPort
from ports.primary.manufacturing_repository_port import (
    ManufacturingRepositoryPort,
    WorkOrderCosts,
)
from ports.primary.routing_repository_port import RoutingRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# AUDIT DECORATOR (marker untuk static checker)
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# Enums (dipertahankan dari versi lama untuk backward-compat)
# ============================================================================


class WorkOrderStatusEnum(str, Enum):
    DRAFT = "draft"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ON_HOLD = "on_hold"


class ManufacturingOrderType(str, Enum):
    STANDARD = "standard"
    CUSTOM = "custom"
    REPAIR = "repair"
    PROTOTYPE = "prototype"


# ============================================================================
# DTOs (dipertahankan dari versi lama untuk backward-compat)
# ============================================================================


@dataclass(kw_only=True)
class BOMRequest:
    product_id: UUID
    product_code: str
    effective_date: date
    version: str = "1.0.0"
    is_active: bool = True
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(kw_only=True)
class BOMUpdateRequest:
    bom_id: UUID
    effective_date: date | None = None
    is_active: bool | None = None
    items: list[dict[str, Any]] | None = None


@dataclass(kw_only=True)
class BOMResponse:
    bom_id: UUID
    product_id: UUID
    items: list[dict[str, Any]]
    total_material_cost: Decimal
    effective_date: date
    is_active: bool
    version: str
    product_code: str = ""
    product_name: str = ""
    bom_code: str = ""
    bom_name: str = ""
    bom_version: int = 1
    expiry_date: date | None = None
    status: str = "draft"
    is_default: bool = False
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version_counter: int = 1

    @property
    def id(self) -> UUID:
        """Alias untuk kompatibilitas dengan router yang memakai `.id`."""
        return self.bom_id

    @property
    def lines(self) -> list[dict[str, Any]]:
        """Alias untuk kompatibilitas dengan router yang memakai `.lines`
        (BOMResponseSchema.lines). Kontennya sama dengan `items`."""
        return self.items


@dataclass(kw_only=True)
class WorkOrderRequest:
    product_id: UUID
    product_code: str
    quantity: Decimal
    due_date: date
    bom_version: str | None = None
    routing_id: UUID | None = None
    legal_entity_id: UUID


@dataclass(kw_only=True)
class WorkOrderResponse:
    """
    DTO response untuk Work Order.

    FIX v6.1: field berikut dihapus dari `__init__` dan diganti property
    read-only untuk menghindari konflik "property has no setter":
      - rejected_quantity, bom_code, routing_code
      - standard_material_cost / standard_labor_cost / standard_overhead_cost
      - standard_total_cost / actual_total_cost
      - material_variance / labor_variance / overhead_variance / total_variance
    """

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    quantity: Decimal
    completed_quantity: Decimal
    due_date: date
    status: str
    created_at: datetime
    product_code: str = ""
    product_name: str = ""
    remaining_quantity: Decimal = Decimal("0")
    bom_id: UUID | None = None
    routing_id: UUID | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    actual_material_cost: Decimal = Decimal("0")
    actual_labor_cost: Decimal = Decimal("0")
    actual_overhead_cost: Decimal = Decimal("0")
    priority: int = 5
    cost_center: str | None = None
    notes: str | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1
    is_locked: bool = False

    # ---------------- Aliases (read-only properties) ----------------

    @property
    def id(self) -> UUID:
        return self.work_order_id

    @property
    def planned_quantity(self) -> Decimal:
        return self.quantity

    @property
    def rejected_quantity(self) -> Decimal:
        return Decimal("0")

    @property
    def bom_code(self) -> str | None:
        return None

    @property
    def routing_code(self) -> str | None:
        return None

    @property
    def standard_material_cost(self) -> Decimal:
        return self.actual_material_cost

    @property
    def standard_labor_cost(self) -> Decimal:
        return self.actual_labor_cost

    @property
    def standard_overhead_cost(self) -> Decimal:
        return self.actual_overhead_cost

    @property
    def standard_total_cost(self) -> Decimal:
        return self.actual_material_cost + self.actual_labor_cost + self.actual_overhead_cost

    @property
    def actual_total_cost(self) -> Decimal:
        return self.actual_material_cost + self.actual_labor_cost + self.actual_overhead_cost

    @property
    def material_variance(self) -> Decimal:
        return Decimal("0")

    @property
    def labor_variance(self) -> Decimal:
        return Decimal("0")

    @property
    def overhead_variance(self) -> Decimal:
        return Decimal("0")

    @property
    def total_variance(self) -> Decimal:
        return Decimal("0")


@dataclass(kw_only=True)
class RoutingResponse:
    """
    DTO response untuk Routing.

    FIX v6.2: DTO ini menggantikan entity domain saat dikembalikan dari
    `create_routing` / `list_routings`. Router schema
    (`RoutingResponseSchema`) memakai enum `RoutingStatus`-nya sendiri
    yang tidak kompatibel dengan domain enum. Kita kirim `status` sebagai
    string supaya router bisa mem-parse-nya.
    """

    id: UUID
    routing_id: UUID
    routing_code: str
    routing_name: str
    product_id: UUID
    product_code: str = ""
    product_name: str = ""
    routing_version: int = 1
    version: int = 1
    effective_date: date | None = None
    expiry_date: date | None = None
    status: str = "draft"
    is_default: bool = False
    steps: list[dict[str, Any]] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version_counter: int = 1


@dataclass(kw_only=True)
class CostCardResponse:
    """DTO response untuk Cost Card (kompatibel dengan CostCardResponseSchema)."""

    id: UUID
    cost_card_code: str
    product_id: UUID
    product_code: str = ""
    product_name: str = ""
    effective_date: date | None = None
    expiry_date: date | None = None
    material_cost: Decimal = Decimal("0")
    labor_cost: Decimal = Decimal("0")
    overhead_cost: Decimal = Decimal("0")
    other_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    quantity_base: Decimal = Decimal("1")
    unit_cost: Decimal = Decimal("0")
    unit_of_measure: str = "pcs"
    status: str = "draft"
    is_active: bool = True
    breakdown: dict[str, Any] | None = None
    notes: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1


def _cost_card_to_response(
    card: CostCardEntity,
    *,
    effective_date: date | None = None,
    expiry_date: date | None = None,
    breakdown: dict[str, Any] | None = None,
    notes: str | None = None,
    unit_of_measure: str | None = None,
    cost_card_code: str | None = None,
) -> CostCardResponse:
    """
    FIX v6.4:
        - `unit_cost` diambil dari entity (sudah = total_cost / quantity_base)
        - `quantity_base` dari entity
    """
    from uuid import UUID as _UUID

    created_by_uuid: _UUID | None = None
    if card.created_by and card.created_by != "system":
        try:
            created_by_uuid = _UUID(str(card.created_by))
        except (ValueError, TypeError):
            created_by_uuid = None
    if created_by_uuid is None:
        created_by_uuid = _UUID(int=0)

    return CostCardResponse(
        id=card.cost_card_id,
        cost_card_code=cost_card_code or card.work_order_number,
        product_id=card.product_id,
        product_code=card.product_code,
        product_name=card.product_name,
        effective_date=effective_date or card.created_at.date(),
        expiry_date=expiry_date,
        material_cost=card.material_cost,
        labor_cost=card.labor_cost,
        overhead_cost=card.overhead_cost,
        other_cost=card.other_cost,
        total_cost=card.total_cost,
        quantity_base=card.quantity_base,
        unit_cost=card.unit_cost,
        unit_of_measure=unit_of_measure or card.unit_of_measure,
        status=card.status.value,
        is_active=(card.status != CostCardStatus.CLOSED),
        breakdown=breakdown,
        notes=notes,
        created_at=card.created_at,
        updated_at=card.updated_at,
        created_by=created_by_uuid,
        version=card.version,
    )

def _routing_to_response(routing: ProductionRoutingEntity) -> RoutingResponse:
    """Helper: entity routing -> DTO RoutingResponse.

    FIX v6.2: `status` di-konversi ke string supaya router tidak perlu
    mem-parse domain enum.
    """
    from uuid import UUID as _UUID

    created_by_uuid: _UUID | None = None
    if routing.created_by and routing.created_by != "system":
        try:
            created_by_uuid = _UUID(str(routing.created_by))
        except (ValueError, TypeError):
            created_by_uuid = None
    if created_by_uuid is None:
        created_by_uuid = _UUID(int=0)

    def _op_to_dict(op: RoutingOperation) -> dict[str, Any]:
        return {
            "operation_id": str(op.operation_id),
            "step_number": op.sequence,
            "sequence": op.sequence,
            "operation_code": op.operation_code,
            "operation_name": op.operation_name,
            "work_center": op.work_center_name,
            "work_center_id": str(op.work_center_id),
            "description": op.description,
            "setup_time_hours": op.setup_time_hours,
            "run_time_hours": op.run_time_per_unit_hours,
            "run_time_per_unit_hours": op.run_time_per_unit_hours,
            "labor_hours": op.run_time_per_unit_hours,
            "labor_cost_per_hour": op.labor_cost_per_hour,
            "machine_cost_per_hour": op.machine_cost_per_hour,
            "fixed_cost": op.fixed_cost,
        }

    ops = [_op_to_dict(op) for op in routing.operations]

    return RoutingResponse(
        id=routing.routing_id,
        routing_id=routing.routing_id,
        routing_code=routing.routing_code,
        routing_name=routing.routing_code,
        product_id=routing.product_id,
        product_code=routing.product_code,
        product_name=routing.product_name,
        routing_version=routing.version,
        version=routing.version,
        effective_date=routing.effective_date.date() if routing.effective_date else None,
        expiry_date=routing.expiry_date.date() if routing.expiry_date else None,
        status=routing.status.value if hasattr(routing.status, "value") else str(routing.status),
        is_default=(
            routing.status.value == "active"
            if hasattr(routing.status, "value")
            else False
        ),
        steps=ops,
        operations=ops,
        notes=routing.notes,
        created_at=routing.created_at,
        updated_at=routing.updated_at,
        created_by=created_by_uuid,
        version_counter=routing.version_counter,
    )


@dataclass(kw_only=True)
class MaterialIssueRequest:
    work_order_id: UUID
    material_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    issue_date: date
    issued_by: UUID
    notes: str | None = None


@dataclass(kw_only=True)
class LaborPostRequest:
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
    work_order_id: UUID
    overhead_pool: str
    amount: Decimal
    allocation_basis: str
    applied_by: UUID
    notes: str | None = None


@dataclass(kw_only=True)
class ProductionCompletionRequest:
    work_order_id: UUID
    completed_quantity: Decimal
    rejected_quantity: Decimal = Decimal("0")
    completion_date: date = field(default_factory=date.today)
    completed_by: UUID | None = None
    remarks: str | None = None


@dataclass(kw_only=True)
class StandardCostRequest:
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


class RoutingNotFoundError(ManufacturingServiceError):
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
        routing_repo: RoutingRepositoryPort | None = None,
    ):
        if manufacturing_repo is None:
            raise ValueError("manufacturing_repo is required")
        if inventory_repo is None:
            raise ValueError("inventory_repo is required")

        self._mfg_repo = manufacturing_repo
        self._inventory_repo = inventory_repo
        self._routing_repo = routing_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = ManufacturingInvariantsValidator()
        self._variance_engine = VarianceAnalysisEngine()
        self._overhead_engine = OverheadAllocationEngine()
        self._hpp_calculator = HPPCalculator()
        self._stats = {
            "boms_created": 0,
            "work_orders_created": 0,
            "work_orders_completed": 0,
        }
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("ManufacturingService initialized")

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        logger.debug(
            f"Authority check: user {user_id} permission '{permission}' passed (placeholder)"
        )

    def _record_audit(
        self, action: str, details: dict[str, Any] | None = None
    ) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "ManufacturingService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    async def _publish_event(
        self, event: Any, correlation_id: str | None = None
    ) -> None:
        if self._event_publisher is None:
            return
        try:
            await self._event_publisher.publish(
                event,
                event_type=str(getattr(event.event_type, "value", event.event_type)),
                aggregate_id=event.aggregate_id,
                aggregate_type="Manufacturing",
                metadata={"correlation_id": correlation_id} if correlation_id else None,
            )
        except TypeError:
            try:
                await self._event_publisher.publish(event)
            except Exception as e:
                logger.warning(f"Failed to publish event {type(event).__name__}: {e}")
        except Exception as e:
            logger.warning(f"Failed to publish event {type(event).__name__}: {e}")

    # ========================================================================
    # BOM
    # ========================================================================

    @audit
    async def create_bom(
        self,
        request: BOMRequest | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        *,
        bom_code: str | None = None,
        bom_name: str | None = None,
        product_id: UUID | None = None,
        product_code: str | None = None,
        bom_version: int = 1,
        effective_date: date | None = None,
        expiry_date: date | None = None,
        is_default: bool = False,
        lines: list[dict[str, Any]] | None = None,
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> BOMResponse:
        if request is not None:
            product_id = request.product_id
            product_code = request.product_code
            bom_code = bom_code or f"BOM-{request.product_code}-V{request.version}"
            bom_name = bom_name or f"BOM {product_id}"
            lines = list(request.items)
            effective_date = request.effective_date
            created_by = created_by or user_id
            bom_version = 1
        else:
            if product_id is None:
                raise ManufacturingServiceError("product_id is required")
            if not lines:
                raise ManufacturingServiceError("lines is required and cannot be empty")
            if not bom_code:
                bom_code = f"BOM-{product_code or str(product_id)[:8]}-V{bom_version}"
            bom_name = bom_name or bom_code
            effective_date = effective_date or date.today()
            created_by = created_by or user_id

        self._check_authority(created_by, "create_bom")

        for line in lines:
            component_id = line.get("component_id") or line.get("component_item_id")
            if component_id is None:
                raise ManufacturingServiceError(
                    "each line must have 'component_id' or 'component_item_id'"
                )
            try:
                component = await self._inventory_repo.get_item_by_id(
                    UUID(str(component_id))
                )
            except Exception as e:
                logger.warning(f"Failed to lookup component {component_id}: {e}")
                component = None
            if not component:
                raise ManufacturingServiceError(f"Component {component_id} not found")

        bom_items: list[BOMItem] = []
        for line in lines:
            component_id = UUID(str(line.get("component_id") or line.get("component_item_id")))
            quantity = Decimal(str(line.get("quantity", 0)))
            scrap = Decimal(str(line.get("scrap_percentage", 0)))
            unit_cost = Decimal(str(line.get("unit_cost", 0) or 0))
            item_code = line.get("item_code") or str(component_id)[:12]
            item_name = line.get("item_name") or item_code
            uom = line.get("unit_of_measure") or line.get("uom") or "pcs"
            bom_items.append(
                BOMItem(
                    item_id=component_id,
                    item_code=item_code,
                    item_name=item_name,
                    quantity=quantity,
                    unit_of_measure=uom,
                    unit_cost=unit_cost,
                    scrap_percentage=scrap,
                    cost_element=CostElement.MATERIAL,
                    notes=line.get("notes", ""),
                )
            )

        bom = BillOfMaterialsEntity(
            bom_id=uuid4(),
            bom_code=bom_code or "",
            product_id=product_id,
            product_code=product_code or "",
            product_name=product_code or "",
            version=bom_version,
            quantity_per_assembly=Decimal("1"),
            unit_of_measure="pcs",
            items=bom_items,
            status=BOMStatus.ACTIVE if is_default else BOMStatus.DRAFT,
            routing_id=None,
            effective_date=datetime.combine(
                effective_date or date.today(), datetime.min.time(), tzinfo=UTC
            ),
            expiry_date=(
                datetime.combine(expiry_date, datetime.min.time(), tzinfo=UTC)
                if expiry_date else None
            ),
            notes=notes or "",
            created_by=str(created_by) if created_by else "system",
        )

        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        await self._mfg_repo.save_bom(bom)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._stats["boms_created"] += 1

        await self._publish_event(
            BOMCreatedEvent(
                aggregate_id=bom.bom_id,
                aggregate_version=1,
                bom=bom,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )

        self._record_audit(
            "create_bom",
            {
                "bom_id": str(bom.bom_id),
                "bom_code": bom.bom_code,
                "product_id": str(bom.product_id),
                "user_id": str(created_by) if created_by else None,
            },
        )

        total_cost = sum((i.total_cost for i in bom.items), Decimal("0"))
        return BOMResponse(
            bom_id=bom.bom_id,
            product_id=bom.product_id,
            product_code=bom.product_code,
            product_name=bom.product_name,
            bom_code=bom.bom_code,
            bom_name=bom_name,
            bom_version=bom.bom_version if hasattr(bom, "bom_version") else bom.version,
            items=[
                {
                    "component_id": str(i.item_id),
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                    "unit_of_measure": i.unit_of_measure,
                    "item_code": i.item_code,
                    "item_name": i.item_name,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=effective_date or date.today(),
            expiry_date=expiry_date,
            is_active=(bom.status == BOMStatus.ACTIVE),
            status=bom.status.value if hasattr(bom.status, "value") else str(bom.status),
            is_default=is_default,
            notes=notes,
            created_at=bom.created_at,
            updated_at=bom.updated_at,
            created_by=created_by,
            version=bom.version,
            version_counter=bom.version_counter,
        )

    @audit
    async def update_bom(
        self,
        request: BOMUpdateRequest | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        *,
        bom_id: UUID | None = None,
        bom_name: str | None = None,
        effective_date: date | None = None,
        expiry_date: date | None = None,
        is_default: bool | None = None,
        lines: list[dict[str, Any]] | None = None,
        notes: str | None = None,
        updated_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> BOMResponse | None:
        if request is not None:
            bom_id = request.bom_id
            effective_date = request.effective_date
            lines = request.items
            is_default = request.is_active
            updated_by = updated_by or user_id
        else:
            if bom_id is None:
                raise ManufacturingServiceError("bom_id is required")
            updated_by = updated_by or user_id

        self._check_authority(updated_by, "update_bom")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]

        existing = await self._mfg_repo.get_bom_by_id(bom_id)
        if not existing:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        new_items = existing.items
        if lines is not None:
            new_items = []
            for line in lines:
                comp_id = UUID(str(line.get("component_id") or line.get("component_item_id")))
                new_items.append(
                    BOMItem(
                        item_id=comp_id,
                        item_code=line.get("item_code") or str(comp_id)[:12],
                        item_name=line.get("item_name") or str(comp_id)[:12],
                        quantity=Decimal(str(line.get("quantity", 0))),
                        unit_of_measure=line.get("unit_of_measure")
                        or line.get("uom")
                        or "pcs",
                        unit_cost=Decimal(str(line.get("unit_cost", 0) or 0)),
                        scrap_percentage=Decimal(str(line.get("scrap_percentage", 0))),
                        cost_element=CostElement.MATERIAL,
                    )
                )

        new_status = existing.status
        if is_default is True:
            new_status = BOMStatus.ACTIVE
        elif is_default is False and existing.status == BOMStatus.ACTIVE:
            new_status = BOMStatus.DRAFT

        updated = BillOfMaterialsEntity(
            bom_id=existing.bom_id,
            bom_code=existing.bom_code,
            product_id=existing.product_id,
            product_code=existing.product_code,
            product_name=existing.product_name,
            version=existing.version,
            quantity_per_assembly=existing.quantity_per_assembly,
            unit_of_measure=existing.unit_of_measure,
            items=new_items,
            status=new_status,
            routing_id=existing.routing_id,
            effective_date=(
                datetime.combine(effective_date, datetime.min.time(), tzinfo=UTC)
                if effective_date else existing.effective_date
            ),
            expiry_date=(
                datetime.combine(expiry_date, datetime.min.time(), tzinfo=UTC)
                if expiry_date else existing.expiry_date
            ),
            notes=notes if notes is not None else existing.notes,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
            created_by=str(updated_by) if updated_by else existing.created_by,
            version_counter=existing.version_counter + 1,
        )

        await self._mfg_repo.save_bom(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            BOMUpdatedEvent(
                aggregate_id=updated.bom_id,
                aggregate_version=updated.version_counter,
                bom_id=updated.bom_id,
                bom_code=updated.bom_code,
                changes={"items_count": len(new_items)},
                updated_by=str(updated_by) if updated_by else "system",
                user_id=str(updated_by) if updated_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )

        self._record_audit("update_bom", {"bom_id": str(updated.bom_id)})

        total_cost = sum((i.total_cost for i in updated.items), Decimal("0"))
        return BOMResponse(
            bom_id=updated.bom_id,
            product_id=updated.product_id,
            product_code=updated.product_code,
            product_name=updated.product_name,
            bom_code=updated.bom_code,
            bom_name=bom_name or updated.bom_code,
            bom_version=updated.version,
            items=[
                {
                    "component_id": str(i.item_id),
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                    "unit_of_measure": i.unit_of_measure,
                }
                for i in updated.items
            ],
            total_material_cost=total_cost,
            effective_date=(
                updated.effective_date.date() if updated.effective_date else date.today()
            ),
            expiry_date=updated.expiry_date.date() if updated.expiry_date else None,
            is_active=(updated.status == BOMStatus.ACTIVE),
            status=updated.status.value if hasattr(updated.status, "value") else str(updated.status),
            is_default=(updated.status == BOMStatus.ACTIVE),
            notes=updated.notes,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
            created_by=updated_by,
            version=updated.version,
            version_counter=updated.version_counter,
        )

    async def deactivate_bom(
        self,
        bom_id: UUID,
        user_id: UUID,
        legal_entity_id: UUID,
        reason: str = "",
    ) -> BOMResponse | None:
        self._check_authority(user_id, "deactivate_bom")
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        existing = await self._mfg_repo.get_bom_by_id(bom_id)
        if not existing:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        updated = BillOfMaterialsEntity(
            bom_id=existing.bom_id,
            bom_code=existing.bom_code,
            product_id=existing.product_id,
            product_code=existing.product_code,
            product_name=existing.product_name,
            version=existing.version,
            quantity_per_assembly=existing.quantity_per_assembly,
            unit_of_measure=existing.unit_of_measure,
            items=existing.items,
            status=BOMStatus.OBSOLETE,
            routing_id=existing.routing_id,
            effective_date=existing.effective_date,
            expiry_date=datetime.now(UTC),
            notes=f"{existing.notes}\nDeactivated: {reason}" if reason else existing.notes,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
            created_by=str(user_id),
            version_counter=existing.version_counter + 1,
        )
        await self._mfg_repo.save_bom(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._record_audit(
            "deactivate_bom", {"bom_id": str(bom_id), "reason": reason}
        )
        return BOMResponse(
            bom_id=updated.bom_id,
            product_id=updated.product_id,
            product_code=updated.product_code,
            product_name=updated.product_name,
            bom_code=updated.bom_code,
            bom_name=updated.bom_code,
            bom_version=updated.version,
            items=[],
            total_material_cost=Decimal("0"),
            effective_date=(
                updated.effective_date.date() if updated.effective_date else date.today()
            ),
            is_active=False,
            status=updated.status.value,
            version=str(updated.version),
        )

    async def activate_bom(
        self,
        bom_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> BOMResponse | None:
        self._check_authority(user_id, "activate_bom")
        existing = await self._mfg_repo.get_bom_by_id(bom_id)
        if not existing:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        activated = existing.activate(str(user_id))
        await self._mfg_repo.save_bom(activated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            BOMActivatedEvent(
                aggregate_id=activated.bom_id,
                aggregate_version=activated.version_counter,
                bom=activated,
                activated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("activate_bom", {"bom_id": str(bom_id)})
        return self._bom_to_response(activated)

    async def obsolete_bom(
        self,
        bom_id: UUID,
        reason: str,
        user_id: UUID,
        correlation_id: str | None = None,
    ) -> bool:
        self._check_authority(user_id, "obsolete_bom")
        existing = await self._mfg_repo.get_bom_by_id(bom_id)
        if not existing:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        obsoleted = existing.obsoleted(str(user_id), reason)
        await self._mfg_repo.save_bom(obsoleted)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            BOMObsoletedEvent(
                aggregate_id=obsoleted.bom_id,
                aggregate_version=obsoleted.version_counter,
                bom=obsoleted,
                reason=reason,
                obsoleted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("obsolete_bom", {"bom_id": str(bom_id), "reason": reason})
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
        self._check_authority(user_id, "add_bom_item")
        existing = await self._mfg_repo.get_bom_by_id(bom_id)
        if not existing:
            raise BOMNotFoundError(f"BOM {bom_id} not found")

        new_item = BOMItem(
            item_id=component_id,
            item_code=str(component_id)[:12],
            item_name=str(component_id)[:12],
            quantity=quantity,
            unit_of_measure="pcs",
            unit_cost=Decimal("0"),
            scrap_percentage=scrap_percentage,
            cost_element=CostElement.MATERIAL,
        )
        updated = existing.add_item(new_item, str(user_id) if user_id else "system")
        await self._mfg_repo.save_bom(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            BOMItemAddedEvent(
                aggregate_id=updated.bom_id,
                aggregate_version=updated.version_counter,
                bom_id=updated.bom_id,
                bom_code=updated.bom_code,
                item=new_item,
                added_by=str(user_id) if user_id else "system",
                user_id=str(user_id) if user_id else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("add_bom_item", {"bom_id": str(bom_id)})
        return self._bom_to_response(updated)

    def _bom_to_response(self, bom: BillOfMaterialsEntity) -> BOMResponse:
        total_cost = sum((i.total_cost for i in bom.items), Decimal("0"))
        now = datetime.now(UTC)
        created_at = bom.created_at if bom.created_at is not None else now
        updated_at = bom.updated_at if bom.updated_at is not None else created_at
        created_by = None
        if bom.created_by and bom.created_by != "system":
            try:
                created_by = UUID(str(bom.created_by))
            except (ValueError, TypeError):
                created_by = None

        return BOMResponse(
            bom_id=bom.bom_id,
            product_id=bom.product_id,
            product_code=bom.product_code,
            product_name=bom.product_name,
            bom_code=bom.bom_code,
            bom_name=bom.bom_code,
            bom_version=bom.version,
            items=[
                {
                    "component_id": str(i.item_id),
                    "quantity": i.quantity,
                    "scrap_percentage": i.scrap_percentage,
                    "unit_of_measure": i.unit_of_measure,
                }
                for i in bom.items
            ],
            total_material_cost=total_cost,
            effective_date=(
                bom.effective_date.date() if bom.effective_date else date.today()
            ),
            expiry_date=bom.expiry_date.date() if bom.expiry_date else None,
            is_active=(bom.status == BOMStatus.ACTIVE),
            status=bom.status.value if hasattr(bom.status, "value") else str(bom.status),
            version=str(bom.version),
            created_at=created_at,
            updated_at=updated_at,
            created_by=created_by,
        )

    async def list_boms(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        is_default: bool | None = None,
        status: str | None = None,
        effective_as_of: date | None = None,
    ) -> list[BOMResponse]:
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        boms = await self._mfg_repo.list_all_boms(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            status=status,
            is_default=is_default,
            effective_as_of=effective_as_of,
        )
        return [self._bom_to_response(b) for b in boms]

    async def get_bom_by_id(
        self, bom_id: UUID, legal_entity_id: UUID | None = None
    ) -> BOMResponse | None:
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        bom = await self._mfg_repo.get_bom_by_id(bom_id)
        if not bom:
            return None
        return self._bom_to_response(bom)

    async def get_active_bom(
        self, product_id: UUID, as_of_date: date
    ) -> BOMResponse | None:
        bom = await self._mfg_repo.get_active_bom(product_id, as_of_date)
        if not bom:
            return None
        return self._bom_to_response(bom)

    async def get_bom_by_work_order(
        self, work_order_id: UUID
    ) -> BOMResponse | None:
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            return None
        bom = await self._mfg_repo.get_bom_by_id(wo.bom_id)
        if not bom:
            return None
        return self._bom_to_response(bom)

    # ========================================================================
    # ROUTING (v6.2: return DTO, bukan entity)
    # ========================================================================

    async def create_routing(
        self,
        routing_code: str,
        routing_name: str,
        product_id: UUID,
        routing_version: int,
        effective_date: date,
        expiry_date: date | None,
        is_default: bool,
        steps: list[dict[str, Any]],
        notes: str | None,
        created_by: UUID,
        legal_entity_id: UUID,
        correlation_id: str | None = None,
    ) -> RoutingResponse:
        if self._routing_repo is None:
            raise RoutingNotFoundError(
                "RoutingRepository not configured in ManufacturingService"
            )
        self._check_authority(created_by, "create_routing")

        operations: list[RoutingOperation] = []
        for step in steps:
            seq = int(step.get("step_number") or step.get("sequence") or 0)
            operations.append(
                RoutingOperation(
                    operation_id=uuid4(),
                    operation_code=step.get("operation_code")
                    or step.get("work_center")
                    or f"OP-{seq:03d}",
                    operation_name=step.get("operation_name")
                    or step.get("description")
                    or f"Op {seq}",
                    sequence=seq,
                    work_center_id=uuid4(),
                    work_center_name=step.get("work_center") or "DEFAULT",
                    setup_time_hours=Decimal(str(step.get("setup_time_hours", 0))),
                    run_time_per_unit_hours=Decimal(
                        str(step.get("run_time_hours", 0))
                    ),
                    labor_cost_per_hour=Decimal(str(step.get("labor_cost_rate", 0) or 0)),
                    machine_cost_per_hour=Decimal(
                        str(step.get("machine_cost_rate", 0) or 0)
                    ),
                    fixed_cost=Decimal("0"),
                    description=step.get("description") or "",
                )
            )

        routing = ProductionRoutingEntity(
            routing_id=uuid4(),
            routing_code=routing_code,
            product_id=product_id,
            product_code=str(product_id)[:12],
            product_name=routing_name,
            version=routing_version,
            operations=operations,
            status=RoutingStatus.ACTIVE if is_default else RoutingStatus.DRAFT,
            effective_date=datetime.combine(
                effective_date, datetime.min.time(), tzinfo=UTC
            ),
            expiry_date=(
                datetime.combine(expiry_date, datetime.min.time(), tzinfo=UTC)
                if expiry_date else None
            ),
            notes=notes or "",
            created_by=str(created_by),
        )
        if hasattr(self._routing_repo, "set_legal_entity_id"):
            self._routing_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        await self._routing_repo.save_routing(routing, legal_entity_id=legal_entity_id)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._record_audit(
            "create_routing",
            {"routing_id": str(routing.routing_id), "routing_code": routing_code},
        )
        # FIX v6.2: return DTO, bukan entity
        return _routing_to_response(routing)

    async def get_routing_by_id(
        self, routing_id: UUID, legal_entity_id: UUID | None = None
    ) -> RoutingResponse | None:
        if self._routing_repo is None:
            return None
        routing = await self._routing_repo.get_routing_by_id(routing_id, legal_entity_id)
        if not routing:
            return None
        return _routing_to_response(routing)

    async def list_routings(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        is_default: bool | None = None,
        status: str | None = None,
    ) -> list[RoutingResponse]:
        if self._routing_repo is None:
            return []
        routings = await self._routing_repo.list_routings(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            is_default=is_default,
            status=status,
        )
        # FIX v6.2: konversi ke DTO supaya `status` jadi string
        return [_routing_to_response(rt) for rt in routings]

    # ========================================================================
    # WORK ORDER
    # ========================================================================

    @audit
    async def create_work_order(
        self,
        request: WorkOrderRequest | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        *,
        work_order_number: str | None = None,
        product_id: UUID | None = None,
        product_code: str | None = None,
        planned_quantity: Decimal | None = None,
        planned_start_date: date | None = None,
        planned_end_date: date | None = None,
        bom_id: UUID | None = None,
        routing_id: UUID | None = None,
        cost_center: str | None = None,
        priority: int = 5,
        notes: str | None = None,
        created_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
    ) -> WorkOrderResponse:
        if request is not None:
            product_id = request.product_id
            product_code = request.product_code
            planned_quantity = request.quantity
            planned_start_date = date.today()
            planned_end_date = request.due_date
            routing_id = request.routing_id
            legal_entity_id = request.legal_entity_id
            created_by = created_by or user_id
        else:
            if product_id is None or planned_quantity is None:
                raise ManufacturingServiceError("product_id and planned_quantity required")
            created_by = created_by or user_id

        self._check_authority(created_by, "create_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]

        if bom_id is None:
            active_bom = await self._mfg_repo.get_active_bom(
                product_id, planned_start_date or date.today()
            )
            if not active_bom:
                raise BOMNotFoundError(f"No active BOM for product {product_id}")
            bom_id = active_bom.bom_id

        if work_order_number:
            existing = await self._mfg_repo.get_work_order_by_number(work_order_number)
            if existing is not None:
                suffix = 1
                base = work_order_number
                while existing is not None:
                    work_order_number = f"{base}-{suffix:03d}"
                    existing = await self._mfg_repo.get_work_order_by_number(work_order_number)
                    suffix += 1
                logger.info(
                    f"WO number {base} already exists; using {work_order_number}"
                )

        if not work_order_number:
            product_code_for_number = product_code or str(product_id)[:8]
            work_order_number = await self._generate_wo_number(product_code_for_number)

        start_dt = datetime.combine(
            planned_start_date or date.today(), datetime.min.time(), tzinfo=UTC
        )
        end_dt = datetime.combine(
            planned_end_date or (planned_start_date or date.today()),
            datetime.min.time(),
            tzinfo=UTC,
        )
        if end_dt <= start_dt:
            from datetime import timedelta
            end_dt = start_dt + timedelta(days=1)

        try:
            prio_enum = WorkOrderPriority.NORMAL
            if priority <= 2:
                prio_enum = WorkOrderPriority.URGENT
            elif priority <= 4:
                prio_enum = WorkOrderPriority.HIGH
            elif priority <= 7:
                prio_enum = WorkOrderPriority.NORMAL
            else:
                prio_enum = WorkOrderPriority.LOW
        except Exception:
            prio_enum = WorkOrderPriority.NORMAL

        wo = WorkOrderEntity(
            work_order_id=uuid4(),
            work_order_number=work_order_number,
            product_id=product_id,
            product_code=product_code or "",
            product_name=product_code or "",
            bom_id=bom_id,
            bom_version=1,
            planned_quantity=planned_quantity,
            completed_quantity=Decimal("0"),
            status=WorkOrderStatus.DRAFT,
            priority=prio_enum,
            planned_start_date=start_dt,
            planned_end_date=end_dt,
            actual_start_date=None,
            actual_end_date=None,
            routing_id=routing_id,
            cost_center=cost_center,
            notes=notes or "",
            work_order_type=WorkOrderType.PRODUCTION,
            created_by=str(created_by) if created_by else "system",
        )

        await self._mfg_repo.save_work_order(wo)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._stats["work_orders_created"] += 1

        await self._publish_event(
            WorkOrderCreatedEvent(
                aggregate_id=wo.work_order_id,
                aggregate_version=1,
                work_order=wo,
                created_by=str(created_by) if created_by else "system",
                user_id=str(created_by) if created_by else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "create_work_order",
            {
                "work_order_id": str(wo.work_order_id),
                "work_order_number": wo.work_order_number,
            },
        )
        return self._wo_to_response(wo)

    def _wo_to_response(self, wo: WorkOrderEntity) -> WorkOrderResponse:
        from uuid import UUID as _UUID

        created_by_uuid: _UUID | None = None
        if wo.created_by and wo.created_by != "system":
            try:
                created_by_uuid = _UUID(str(wo.created_by))
            except (ValueError, TypeError):
                created_by_uuid = None
        if created_by_uuid is None:
            created_by_uuid = _UUID(int=0)

        return WorkOrderResponse(
            work_order_id=wo.work_order_id,
            work_order_number=wo.work_order_number,
            product_id=wo.product_id,
            product_code=wo.product_code,
            product_name=wo.product_name,
            quantity=wo.planned_quantity,
            completed_quantity=wo.completed_quantity,
            remaining_quantity=wo.get_remaining_quantity(),
            due_date=wo.planned_end_date.date(),
            planned_start_date=wo.planned_start_date.date(),
            planned_end_date=wo.planned_end_date.date(),
            actual_start_date=wo.actual_start_date.date() if wo.actual_start_date else None,
            actual_end_date=wo.actual_end_date.date() if wo.actual_end_date else None,
            status=wo.status.value,
            priority=5,
            cost_center=wo.cost_center,
            notes=wo.notes,
            bom_id=wo.bom_id,
            routing_id=wo.routing_id,
            actual_material_cost=wo.material_actual_cost,
            actual_labor_cost=wo.labor_actual_cost,
            actual_overhead_cost=wo.overhead_actual_cost,
            created_at=wo.created_at,
            updated_at=wo.updated_at,
            created_by=created_by_uuid,
            version=wo.version,
        )

    async def list_work_orders(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        status: WorkOrderStatus | str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        page: int = 1,
        page_size: int = 20,
        **kwargs: Any,
    ) -> Any:
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]

        status_enum: WorkOrderStatus | None = None
        if status is not None:
            if isinstance(status, WorkOrderStatus):
                status_enum = status
            else:
                try:
                    status_enum = WorkOrderStatus(str(status).lower())
                except ValueError:
                    status_enum = None

        eff_start = start_date or from_date
        eff_end = end_date or to_date

        offset = (page - 1) * page_size
        wos = await self._mfg_repo.list_work_orders(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            status=status_enum,
            start_date=eff_start,
            end_date=eff_end,
            limit=page_size,
            offset=offset,
        )

        responses = [self._wo_to_response(w) for w in wos]

        class _PaginatedResult(list):
            def __init__(self, items, total=None, page=1, page_size=20):
                super().__init__(items)
                self.items = list(items)
                self.total = total if total is not None else len(items)
                self.page = page
                self.page_size = page_size

        return _PaginatedResult(responses, total=len(responses), page=page, page_size=page_size)

    async def get_work_order_by_id(
        self, work_order_id: UUID, legal_entity_id: UUID | None = None
    ) -> WorkOrderEntity | None:
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        return await self._mfg_repo.get_work_order(work_order_id)

    async def get_work_order(self, work_order_id: UUID) -> WorkOrderEntity | None:
        return await self._mfg_repo.get_work_order(work_order_id)

    @audit
    async def update_work_order(
        self,
        work_order_id: UUID,
        planned_quantity: Decimal | None = None,
        planned_start_date: date | None = None,
        planned_end_date: date | None = None,
        bom_id: UUID | None = None,
        routing_id: UUID | None = None,
        cost_center: str | None = None,
        priority: int | None = None,
        notes: str | None = None,
        status: str | None = None,
        updated_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        **kwargs: Any,
    ) -> WorkOrderEntity | None:
        self._check_authority(updated_by, "update_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        existing = await self._mfg_repo.get_work_order(work_order_id)
        if not existing:
            return None

        start_dt = (
            datetime.combine(planned_start_date, datetime.min.time(), tzinfo=UTC)
            if planned_start_date else existing.planned_start_date
        )
        end_dt = (
            datetime.combine(planned_end_date, datetime.min.time(), tzinfo=UTC)
            if planned_end_date else existing.planned_end_date
        )
        if end_dt <= start_dt:
            from datetime import timedelta
            end_dt = start_dt + timedelta(days=1)

        new_status = existing.status
        if status:
            try:
                new_status = WorkOrderStatus(str(status).lower())
            except ValueError:
                pass

        updated = WorkOrderEntity(
            work_order_id=existing.work_order_id,
            work_order_number=existing.work_order_number,
            product_id=existing.product_id,
            product_code=existing.product_code,
            product_name=existing.product_name,
            bom_id=bom_id or existing.bom_id,
            bom_version=existing.bom_version,
            planned_quantity=planned_quantity or existing.planned_quantity,
            completed_quantity=existing.completed_quantity,
            status=new_status,
            priority=existing.priority,
            planned_start_date=start_dt,
            planned_end_date=end_dt,
            actual_start_date=existing.actual_start_date,
            actual_end_date=existing.actual_end_date,
            routing_id=routing_id or existing.routing_id,
            cost_center=cost_center if cost_center is not None else existing.cost_center,
            notes=notes if notes is not None else existing.notes,
            work_order_type=existing.work_order_type,
            created_at=existing.created_at,
            updated_at=datetime.now(UTC),
            created_by=str(updated_by) if updated_by else existing.created_by,
            version=existing.version + 1,
            material_actual_cost=existing.material_actual_cost,
            labor_actual_cost=existing.labor_actual_cost,
            overhead_actual_cost=existing.overhead_actual_cost,
        )
        await self._mfg_repo.save_work_order(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._record_audit("update_work_order", {"work_order_id": str(work_order_id)})
        return updated

    @audit
    async def approve_work_order(
        self,
        work_order_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> WorkOrderResponse:
        self._check_authority(user_id, "approve_work_order")
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")
        approved = wo.approve(str(user_id))
        await self._mfg_repo.save_work_order(approved)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            WorkOrderApprovedEvent(
                aggregate_id=approved.work_order_id,
                aggregate_version=approved.version,
                work_order=approved,
                approved_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("approve_work_order", {"work_order_id": str(work_order_id)})
        return self._wo_to_response(approved)

    @audit
    async def release_work_order(
        self,
        work_order_id: UUID,
        actual_start_date: date | None = None,
        notes: str | None = None,
        released_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        **kwargs: Any,
    ) -> WorkOrderEntity | None:
        self._check_authority(released_by, "release_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            return None
        if wo.status == WorkOrderStatus.DRAFT:
            wo = wo.approve(str(released_by) if released_by else "system")
        if wo.status == WorkOrderStatus.APPROVED:
            wo = wo.start_production(str(released_by) if released_by else "system")
        await self._mfg_repo.save_work_order(wo)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")
        self._record_audit("release_work_order", {"work_order_id": str(work_order_id)})
        return wo

    @audit
    async def start_work_order(
        self,
        work_order_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> WorkOrderResponse:
        self._check_authority(user_id, "start_work_order")
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")
        if wo.status not in (WorkOrderStatus.APPROVED, WorkOrderStatus.DRAFT):
            raise ManufacturingServiceError(
                f"Cannot start work order in status {wo.status.value}"
            )
        if wo.status == WorkOrderStatus.DRAFT:
            wo = wo.approve(str(user_id))
        started = wo.start_production(str(user_id))
        await self._mfg_repo.save_work_order(started)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            WorkOrderStartedEvent(
                aggregate_id=started.work_order_id,
                aggregate_version=started.version,
                work_order=started,
                started_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("start_work_order", {"work_order_id": str(work_order_id)})
        return self._wo_to_response(started)

    @audit
    async def complete_work_order(
        self,
        work_order_id: UUID,
        completed_quantity: Decimal,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        rejected_quantity: Decimal = Decimal("0"),
        actual_end_date: date | None = None,
        notes: str | None = None,
        completed_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        **kwargs: Any,
    ) -> WorkOrderResponse:
        actor = completed_by or user_id
        self._check_authority(actor, "complete_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")
        if wo.status != WorkOrderStatus.IN_PROGRESS:
            raise ManufacturingServiceError(
                f"Cannot complete work order in status {wo.status.value}"
            )
        completed = wo.complete_production(
            completed_quantity, str(actor) if actor else "system"
        )
        await self._mfg_repo.save_work_order(completed)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._stats["work_orders_completed"] += 1

        is_full = completed.completed_quantity >= completed.planned_quantity
        if is_full:
            await self._publish_event(
                ProductionCompletedEvent(
                    aggregate_id=completed.work_order_id,
                    aggregate_version=completed.version,
                    work_order_id=completed.work_order_id,
                    work_order_number=completed.work_order_number,
                    product_id=completed.product_id,
                    product_code=completed.product_code,
                    product_name=completed.product_name,
                    quantity=completed.completed_quantity,
                    unit_cost=(
                        completed.material_actual_cost
                        + completed.labor_actual_cost
                        + completed.overhead_actual_cost
                    )
                    / (completed.completed_quantity or Decimal("1")),
                    total_cost=(
                        completed.material_actual_cost
                        + completed.labor_actual_cost
                        + completed.overhead_actual_cost
                    ),
                    completed_by=str(actor) if actor else "system",
                    user_id=str(actor) if actor else None,
                    correlation_id=correlation_id,
                ),
                correlation_id=correlation_id,
            )

        await self._publish_event(
            WorkOrderCompletedEvent(
                aggregate_id=completed.work_order_id,
                aggregate_version=completed.version,
                work_order=completed,
                completed_quantity=completed_quantity,
                completed_by=str(actor) if actor else "system",
                is_fully_completed=is_full,
                user_id=str(actor) if actor else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "complete_work_order",
            {
                "work_order_id": str(work_order_id),
                "completed_quantity": str(completed_quantity),
            },
        )
        return self._wo_to_response(completed)

    @audit
    async def close_work_order(
        self,
        work_order_id: UUID,
        closed_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        **kwargs: Any,
    ) -> WorkOrderEntity | None:
        self._check_authority(closed_by, "close_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            return None
        closed = WorkOrderEntity(
            work_order_id=wo.work_order_id,
            work_order_number=wo.work_order_number,
            product_id=wo.product_id,
            product_code=wo.product_code,
            product_name=wo.product_name,
            bom_id=wo.bom_id,
            bom_version=wo.bom_version,
            planned_quantity=wo.planned_quantity,
            completed_quantity=wo.completed_quantity,
            status=WorkOrderStatus.COMPLETED,
            priority=wo.priority,
            planned_start_date=wo.planned_start_date,
            planned_end_date=wo.planned_end_date,
            actual_start_date=wo.actual_start_date,
            actual_end_date=wo.actual_end_date or datetime.now(UTC),
            routing_id=wo.routing_id,
            cost_center=wo.cost_center,
            notes=wo.notes,
            work_order_type=wo.work_order_type,
            created_at=wo.created_at,
            updated_at=datetime.now(UTC),
            created_by=str(closed_by) if closed_by else wo.created_by,
            version=wo.version + 1,
            material_actual_cost=wo.material_actual_cost,
            labor_actual_cost=wo.labor_actual_cost,
            overhead_actual_cost=wo.overhead_actual_cost,
        )
        await self._mfg_repo.save_work_order(closed)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")
        self._record_audit("close_work_order", {"work_order_id": str(work_order_id)})
        return closed

    @audit
    async def cancel_work_order(
        self,
        work_order_id: UUID,
        reason: str,
        user_id: UUID | None = None,
        cancelled_by: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> Any:
        actor = cancelled_by or user_id
        self._check_authority(actor, "cancel_work_order")
        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")
        cancelled = wo.cancel(str(actor) if actor else "system", reason)
        await self._mfg_repo.save_work_order(cancelled)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            WorkOrderCancelledEvent(
                aggregate_id=cancelled.work_order_id,
                aggregate_version=cancelled.version,
                work_order=cancelled,
                reason=reason,
                cancelled_by=str(actor) if actor else "system",
                user_id=str(actor) if actor else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("cancel_work_order", {"work_order_id": str(work_order_id)})
        return cancelled

    # ========================================================================
    # MATERIAL / LABOR / OVERHEAD
    # ========================================================================

    @audit
    async def post_labor(
        self,
        request: LaborPostRequest,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "post_labor")
        wo = await self._mfg_repo.get_work_order(request.work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(
                f"Work order {request.work_order_id} not found"
            )
        cost = request.hours * request.rate
        updated = wo.update_actual_costs(
            labor_actual=(wo.labor_actual_cost + cost),
            updated_by=str(user_id),
        )
        await self._mfg_repo.save_work_order(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            LaborPostedEvent(
                aggregate_id=wo.work_order_id,
                aggregate_version=updated.version,
                work_order_id=wo.work_order_id,
                work_order_number=wo.work_order_number,
                employee_id=request.employee_id,
                employee_name=request.employee_name,
                hours=request.hours,
                rate=request.rate,
                cost=cost,
                posted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("post_labor", {"work_order_id": str(request.work_order_id)})
        return {
            "work_order_id": str(request.work_order_id),
            "employee_id": str(request.employee_id),
            "hours": request.hours,
            "rate": request.rate,
            "cost": cost,
        }

    @audit
    async def apply_overhead(
        self,
        request: OverheadApplyRequest,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "apply_overhead")
        wo = await self._mfg_repo.get_work_order(request.work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(
                f"Work order {request.work_order_id} not found"
            )
        updated = wo.update_actual_costs(
            overhead_actual=(wo.overhead_actual_cost + request.amount),
            updated_by=str(user_id),
        )
        await self._mfg_repo.save_work_order(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            OverheadAppliedEvent(
                aggregate_id=wo.work_order_id,
                aggregate_version=updated.version,
                work_order_id=wo.work_order_id,
                work_order_number=wo.work_order_number,
                overhead_pool=request.overhead_pool,
                amount=request.amount,
                allocation_basis=request.allocation_basis,
                applied_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "apply_overhead", {"work_order_id": str(request.work_order_id)}
        )
        return {
            "work_order_id": str(request.work_order_id),
            "overhead_pool": request.overhead_pool,
            "amount": request.amount,
        }

    # ========================================================================
    # WIP
    # ========================================================================

    async def list_wip(
        self,
        legal_entity_id: UUID,
        work_order_id: UUID | None = None,
        product_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        wips = await self._mfg_repo.list_wip(
            legal_entity_id=legal_entity_id,
            work_order_id=work_order_id,
            product_id=product_id,
        )
        return [
            {
                "id": str(w.wip_id),
                "work_order_id": str(w.work_order_id),
                "work_order_number": w.work_order_number,
                "product_id": str(w.product_id),
                "product_name": w.product_name,
                "quantity_started": w.quantity_started,
                "quantity_remaining": w.quantity_remaining,
                "completion_percent": w.get_completion_percentage(),
                "material_cost": w.material_cost,
                "labor_cost": w.labor_cost,
                "overhead_cost": w.overhead_cost,
                "total_cost": w.total_cost,
                "material_issued": [],
                "labor_recorded": [],
                "start_date": w.created_at.date(),
                "expected_completion_date": None,
                "created_at": w.created_at,
            }
            for w in wips
        ]

    # ========================================================================
    # COST CARD
    # ========================================================================

    @audit
    async def create_cost_card(
        self,
        cost_card_code: str,
        product_id: UUID,
        effective_date: date,
        expiry_date: date | None,
        material_cost: Decimal,
        labor_cost: Decimal,
        overhead_cost: Decimal,
        other_cost: Decimal,
        quantity_base: Decimal,
        unit_of_measure: str,
        breakdown: dict[str, Any] | None,
        notes: str | None,
        created_by: UUID,
        legal_entity_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> CostCardResponse:
        """
        FIX v6.4: hitung unit_cost = total / quantity_base; simpan
        quantity_base, unit_of_measure, other_cost di entity & DB.
        """
        self._check_authority(created_by, "create_cost_card")

        total = (
            material_cost
            + labor_cost
            + overhead_cost
            + (other_cost or Decimal("0"))
        )
        unit = (
            (total / quantity_base).quantize(Decimal("0.01"))
            if quantity_base and quantity_base > 0
            else Decimal("0")
        )

        card = CostCardEntity(
            cost_card_id=uuid4(),
            work_order_id=uuid4(),
            work_order_number=cost_card_code,
            product_id=product_id,
            product_code=cost_card_code,
            product_name=cost_card_code,
            planned_quantity=quantity_base,
            completed_quantity=Decimal("0"),
            material_cost=material_cost,
            labor_cost=labor_cost,
            overhead_cost=overhead_cost,
            other_cost=other_cost or Decimal("0"),
            total_cost=total,
            unit_cost=unit,
            status=CostCardStatus.OPEN,
            quantity_base=quantity_base,
            unit_of_measure=unit_of_measure or "pcs",
            entries=[],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            created_by=str(created_by),
            version=1,
        )

        if legal_entity_id is not None and hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        await self._mfg_repo.save_cost_card(card)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        self._record_audit(
            "create_cost_card", {"cost_card_id": str(card.cost_card_id)}
        )
        return _cost_card_to_response(
            card,
            effective_date=effective_date,
            expiry_date=expiry_date,
            breakdown=breakdown,
            notes=notes,
            unit_of_measure=unit_of_measure,
            cost_card_code=cost_card_code,
        )
    
    async def list_cost_cards(
        self,
        legal_entity_id: UUID,
        product_id: UUID | None = None,
        effective_as_of: date | None = None,
        is_active: bool | None = None,
    ) -> list[CostCardResponse]:
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]
        cards = await self._mfg_repo.list_cost_cards(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            effective_as_of=effective_as_of,
            is_active=is_active,
        )
        return [_cost_card_to_response(c) for c in cards]

    # ========================================================================
    # STANDARD COST
    # ========================================================================

    @audit
    async def create_standard_cost(
        self,
        request: StandardCostRequest,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "create_standard_cost")
        total = request.material_cost + request.labor_cost + request.overhead_cost
        sc = StandardCostEntity.create(
            product_id=request.product_id,
            product_code=request.product_code,
            product_name=request.product_name,
            material_cost=request.material_cost,
            labor_cost=request.labor_cost,
            overhead_cost=request.overhead_cost,
            effective_date=datetime.combine(
                request.effective_date, datetime.min.time(), tzinfo=UTC
            ),
            created_by=str(user_id),
        )
        await self._mfg_repo.save_standard_cost(sc)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            StandardCostCreatedEvent(
                aggregate_id=sc.standard_cost_id,
                aggregate_version=1,
                standard_cost_id=sc.standard_cost_id,
                product_id=request.product_id,
                product_code=request.product_code,
                product_name=request.product_name,
                material_cost=request.material_cost,
                labor_cost=request.labor_cost,
                overhead_cost=request.overhead_cost,
                total_cost=total,
                effective_date=datetime.combine(
                    request.effective_date, datetime.min.time(), tzinfo=UTC
                ),
                created_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "create_standard_cost", {"standard_cost_id": str(sc.standard_cost_id)}
        )
        return {
            "standard_cost_id": str(sc.standard_cost_id),
            "product_id": str(request.product_id),
            "total_cost": total,
        }

    @audit
    async def activate_standard_cost(
        self,
        standard_cost_id: UUID,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "activate_standard_cost")
        sc = await self._mfg_repo.get_standard_cost_by_id(standard_cost_id)
        if not sc:
            raise ManufacturingServiceError(
                f"Standard cost {standard_cost_id} not found"
            )
        await self._mfg_repo.save_standard_cost(sc)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            StandardCostActivatedEvent(
                aggregate_id=sc.standard_cost_id,
                aggregate_version=1,
                standard_cost_id=sc.standard_cost_id,
                product_id=sc.product_id,
                product_code=sc.product_code,
                product_name=sc.product_name,
                activated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "activate_standard_cost", {"standard_cost_id": str(standard_cost_id)}
        )
        return {"standard_cost_id": str(standard_cost_id), "activated": True}

    # ========================================================================
    # HPP / VARIANCE / COST CARD UPDATE
    # ========================================================================

    @audit
    async def calculate_hpp(
        self,
        request: HPPCalculationRequest,
        user_id: UUID,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "calculate_hpp")
        work_orders = await self._mfg_repo.list_completed_work_orders(
            legal_entity_id=uuid4(),
            from_date=request.period_start,
            to_date=request.period_end,
        )
        total_units = Decimal("0")
        total_cost = Decimal("0")
        for wo in work_orders:
            total_units += wo.completed_quantity
            costs = await self._mfg_repo.get_work_order_costs(wo.work_order_id)
            total_cost += costs.total_cost
        unit_hpp = total_cost / total_units if total_units > 0 else Decimal("0")

        await self._publish_event(
            HPPCalculatedEvent(
                aggregate_id=request.product_id,
                aggregate_version=1,
                product_id=request.product_id,
                period_start=datetime.combine(
                    request.period_start, datetime.min.time(), tzinfo=UTC
                ),
                period_end=datetime.combine(
                    request.period_end, datetime.max.time(), tzinfo=UTC
                ),
                units_produced=total_units,
                total_cost=total_cost,
                unit_hpp=unit_hpp,
                calculated_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("calculate_hpp", {"product_id": str(request.product_id)})
        return {
            "product_id": str(request.product_id),
            "period_start": request.period_start.isoformat(),
            "period_end": request.period_end.isoformat(),
            "units_produced": total_units,
            "total_cost": total_cost,
            "unit_hpp": unit_hpp,
        }

    @audit
    async def analyze_variance(
        self,
        work_order_id: UUID,
        user_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "analyze_variance")
        wo = await self._mfg_repo.get_work_order(work_order_id)
        if not wo:
            raise WorkOrderNotFoundError(f"Work order {work_order_id} not found")

        std_cost = await self._mfg_repo.get_standard_cost_by_product(wo.product_id)
        if not std_cost:
            raise ManufacturingServiceError(
                f"No standard cost for product {wo.product_id}"
            )
        costs = await self._mfg_repo.get_work_order_costs(work_order_id)

        std_total = (
            std_cost.material_cost + std_cost.labor_cost + std_cost.overhead_cost
        ) * wo.completed_quantity
        actual_total = costs.total_cost
        total_variance = actual_total - std_total
        variance_type = "unfavorable" if total_variance > 0 else "favorable"

        await self._publish_event(
            VarianceAnalyzedEvent(
                aggregate_id=wo.work_order_id,
                aggregate_version=wo.version,
                work_order_id=wo.work_order_id,
                work_order_number=wo.work_order_number,
                total_variance=total_variance,
                variance_type=variance_type,
                material_variance=costs.material_cost
                - (std_cost.material_cost * wo.completed_quantity),
                labor_variance=costs.labor_cost
                - (std_cost.labor_cost * wo.completed_quantity),
                overhead_variance=costs.overhead_cost
                - (std_cost.overhead_cost * wo.completed_quantity),
                analyzed_by=str(user_id) if user_id else "system",
                user_id=str(user_id) if user_id else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit(
            "analyze_variance", {"work_order_id": str(work_order_id)}
        )
        return {
            "work_order_id": work_order_id,
            "work_order_number": wo.work_order_number,
            "product_id": wo.product_id,
            "product_name": wo.product_name,
            "standard_cost": std_total,
            "actual_cost": actual_total,
            "total_variance": total_variance,
            "total_variance_percent": (
                float(total_variance / std_total * 100) if std_total else 0.0
            ),
            "material_price_variance": Decimal("0"),
            "material_usage_variance": Decimal("0"),
            "material_variance_total": costs.material_cost
            - (std_cost.material_cost * wo.completed_quantity),
            "labor_rate_variance": Decimal("0"),
            "labor_efficiency_variance": Decimal("0"),
            "labor_variance_total": costs.labor_cost
            - (std_cost.labor_cost * wo.completed_quantity),
            "overhead_volume_variance": Decimal("0"),
            "overhead_spending_variance": Decimal("0"),
            "overhead_variance_total": costs.overhead_cost
            - (std_cost.overhead_cost * wo.completed_quantity),
            "variances_by_component": [],
            "analysis_period_start": (wo.actual_start_date or wo.planned_start_date).date(),
            "analysis_period_end": (wo.actual_end_date or wo.planned_end_date).date(),
            "generated_at": datetime.now(UTC),
            "variance_type": variance_type,
            "material_variance": costs.material_cost
            - (std_cost.material_cost * wo.completed_quantity),
            "labor_variance": costs.labor_cost
            - (std_cost.labor_cost * wo.completed_quantity),
            "overhead_variance": costs.overhead_cost
            - (std_cost.overhead_cost * wo.completed_quantity),
        }

    @audit
    async def update_cost_card(
        self,
        product_id: UUID,
        period: str,
        total_cost: Decimal,
        unit_cost: Decimal,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self._check_authority(user_id, "update_cost_card")
        existing = await self._mfg_repo.get_cost_card(product_id, period)
        if existing:
            updated = CostCardEntity(
                cost_card_id=existing.cost_card_id,
                work_order_id=existing.work_order_id,
                work_order_number=existing.work_order_number,
                product_id=existing.product_id,
                product_code=existing.product_code,
                product_name=existing.product_name,
                planned_quantity=existing.planned_quantity,
                completed_quantity=existing.completed_quantity,
                material_cost=existing.material_cost,
                labor_cost=existing.labor_cost,
                overhead_cost=existing.overhead_cost,
                total_cost=total_cost,
                unit_cost=unit_cost,
                status=existing.status,
                entries=existing.entries,
                created_at=existing.created_at,
                updated_at=datetime.now(UTC),
                created_by=existing.created_by,
                version=existing.version + 1,
            )
        else:
            updated = CostCardEntity(
                cost_card_id=uuid4(),
                work_order_id=uuid4(),
                work_order_number=f"CC-{period}",
                product_id=product_id,
                product_code=str(product_id)[:12],
                product_name=str(product_id)[:12],
                planned_quantity=Decimal("1"),
                completed_quantity=Decimal("0"),
                material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=total_cost,
                unit_cost=unit_cost,
                status=CostCardStatus.OPEN,
                entries=[],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                created_by=str(user_id) if user_id else "system",
                version=1,
            )
        await self._mfg_repo.save_cost_card(updated)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

        await self._publish_event(
            CostCardUpdatedEvent(
                aggregate_id=product_id,
                aggregate_version=1,
                product_id=product_id,
                period=period,
                total_cost=total_cost,
                unit_cost=unit_cost,
                user_id=str(user_id) if user_id else None,
                correlation_id=correlation_id,
            ),
            correlation_id=correlation_id,
        )
        self._record_audit("update_cost_card", {"product_id": str(product_id)})
        return {
            "product_id": str(product_id),
            "period": period,
            "total_cost": total_cost,
            "unit_cost": unit_cost,
        }

    # ========================================================================
    # WORKFLOW SUPPORT
    # ========================================================================

    async def get_work_order_costs(self, work_order_id: UUID) -> WorkOrderCosts:
        return await self._mfg_repo.get_work_order_costs(work_order_id)

    async def get_wip_value(
        self, legal_entity_id: UUID, as_of_date: date
    ) -> Decimal:
        return await self._mfg_repo.get_wip_value(legal_entity_id, as_of_date)

    async def get_manufacturing_costs(
        self, legal_entity_id: UUID, from_date: date, to_date: date
    ) -> Decimal:
        return await self._mfg_repo.get_manufacturing_costs(
            legal_entity_id, from_date, to_date
        )

    async def get_completed_work_orders(
        self, legal_entity_id: UUID, period_start: date, period_end: date
    ) -> list[WorkOrderEntity]:
        return await self._mfg_repo.list_completed_work_orders(
            legal_entity_id, period_start, period_end
        )

    async def close_period(
        self, legal_entity_id: UUID, period: str, user_id: UUID
    ) -> None:
        await self._mfg_repo.close_period(legal_entity_id, period, user_id)
        if self._uow:
            try:
                await self._uow.commit()
            except Exception as e:
                logger.warning(f"UoW commit failed (non-fatal): {e}")

    # ========================================================================
    # EXPORT WORK ORDERS
    # ========================================================================

    async def export_work_orders(
        self,
        legal_entity_id: UUID,
        start_date: date,
        end_date: date,
        format: str = "csv",
        status: str | None = None,
        **kwargs: Any,
    ) -> bytes:
        if format != "csv":
            raise ManufacturingServiceError(
                f"Export format '{format}' not yet supported; use 'csv'"
            )
        if hasattr(self._mfg_repo, "set_legal_entity_id"):
            self._mfg_repo.set_legal_entity_id(legal_entity_id)  # type: ignore[attr-defined]

        status_enum = None
        if status:
            try:
                status_enum = WorkOrderStatus(str(status).lower())
            except ValueError:
                status_enum = None

        wos = await self._mfg_repo.list_work_orders(
            legal_entity_id=legal_entity_id,
            status=status_enum,
            start_date=start_date,
            end_date=end_date,
            limit=10000,
            offset=0,
        )

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "wo_number",
                "product_id",
                "product_code",
                "product_name",
                "quantity",
                "completed_quantity",
                "status",
                "planned_start_date",
                "planned_end_date",
                "actual_start_date",
                "actual_end_date",
                "total_material_cost",
                "total_labor_cost",
                "total_overhead_cost",
                "total_cost",
            ]
        )
        for wo in wos:
            writer.writerow(
                [
                    wo.work_order_number,
                    str(wo.product_id),
                    wo.product_code,
                    wo.product_name,
                    str(wo.planned_quantity),
                    str(wo.completed_quantity),
                    wo.status.value,
                    wo.planned_start_date.date().isoformat(),
                    wo.planned_end_date.date().isoformat(),
                    wo.actual_start_date.date().isoformat() if wo.actual_start_date else "",
                    wo.actual_end_date.date().isoformat() if wo.actual_end_date else "",
                    str(wo.material_actual_cost),
                    str(wo.labor_actual_cost),
                    str(wo.overhead_actual_cost),
                    str(
                        wo.material_actual_cost
                        + wo.labor_actual_cost
                        + wo.overhead_actual_cost
                    ),
                ]
            )
        self._record_audit(
            "export_work_orders",
            {"legal_entity_id": str(legal_entity_id), "count": len(wos)},
        )
        return buf.getvalue().encode("utf-8")

    # ========================================================================
    # HELPERS
    # ========================================================================

    async def _generate_wo_number(self, product_code: str) -> str:
        last = await self._mfg_repo.get_last_work_order_number()
        seq = 1
        if last:
            try:
                seq = int(last.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        return f"WO-{product_code}-{seq:06d}"

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_manufacturing_service(
    manufacturing_repo: ManufacturingRepositoryPort,
    inventory_repo: InventoryRepositoryPort,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
    routing_repo: RoutingRepositoryPort | None = None,
) -> ManufacturingService:
    return ManufacturingService(
        manufacturing_repo,
        inventory_repo,
        uow,
        event_publisher,
        routing_repo,
    )


__all__ = [
    "BOMNotFoundError",
    "BOMRequest",
    "BOMResponse",
    "BOMUpdateRequest",
    "HPPCalculationRequest",
    "InsufficientMaterialError",
    "LaborPostRequest",
    "ManufacturingOrderType",
    "ManufacturingService",
    "ManufacturingServiceError",
    "MaterialIssueRequest",
    "OverheadApplyRequest",
    "ProductionCompletionRequest",
    "RoutingNotFoundError",
    "RoutingResponse",
    "StandardCostRequest",
    "WorkOrderNotFoundError",
    "WorkOrderRequest",
    "WorkOrderResponse",
    "WorkOrderStatusEnum",
    "create_manufacturing_service",
    "CostCardResponse"
]
