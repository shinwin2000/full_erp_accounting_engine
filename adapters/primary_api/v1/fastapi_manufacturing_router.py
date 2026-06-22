
#!/usr/bin/env python3
"""
Module: fastapi_manufacturing_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Manufacturing:
               work order, bill of materials (BOM), routing, work in process (WIP),
               cost card, variance analysis, overhead allocation, HPP calculation.

Method Standards (ERP):
- create_bom() / update_bom() / delete_bom() / get_bom()
- create_routing() / update_routing() / delete_routing() / get_routing()
- create_work_order() / update_work_order() / delete_work_order() / get_work_order()
- release_work_order() / complete_work_order() / cancel_work_order()
- issue_material() / receive_finished_goods() / record_labor() / record_overhead()
- calculate_wip() / calculate_variance() / calculate_standard_cost()
- close_work_order() / reopen_work_order()
- create_cost_card() / update_cost_card() / delete_cost_card()
- allocate_overhead() / calculate_hpp()
- get_work_order_status() / get_work_order_history()
- audit_trail_work_order() / can_transition_work_order()
- register_work_order_event() / get_work_order_events()
- version_work_order()
"""


from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class BOMStatus(str, Enum):
    """Status Bill of Materials."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    OBSOLETE = "obsolete"
    ARCHIVED = "archived"
    LOCKED = "locked"


class RoutingStatus(str, Enum):
    """Status Routing."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"
    OBSOLETE = "obsolete"
    ARCHIVED = "archived"


class WorkOrderStatus(str, Enum):
    """Status Work Order."""

    DRAFT = "draft"
    PLANNED = "planned"
    RELEASED = "released"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class CostElement(str, Enum):
    """Elemen biaya."""

    MATERIAL = "material"
    LABOR = "labor"
    OVERHEAD = "overhead"
    SUBCONTRACT = "subcontract"
    OTHER = "other"


class VarianceType(str, Enum):
    """Jenis variance."""

    MATERIAL_PRICE = "material_price"
    MATERIAL_USAGE = "material_usage"
    LABOR_RATE = "labor_rate"
    LABOR_EFFICIENCY = "labor_efficiency"
    OVERHEAD_VOLUME = "overhead_volume"
    OVERHEAD_SPENDING = "overhead_spending"
    MIX = "mix"
    YIELD = "yield"


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class BOMLineSchema(BaseModel):
    """Line dalam Bill of Materials."""

    model_config = ConfigDict(from_attributes=True)

    component_item_id: UUID = Field(..., description="ID komponen")
    quantity: Decimal = Field(..., gt=0, decimal_places=4, description="Kuantitas")
    scrap_percent: Decimal = Field(
        0, ge=0, le=100, decimal_places=2, description="Persentase scrap"
    )
    unit_of_measure: str = Field("pcs", max_length=10, description="Satuan")
    cost_allocated: Decimal = Field(
        0, ge=0, decimal_places=2, description="Biaya yang dialokasikan"
    )
    notes: str | None = Field(None, max_length=500)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Quantity must be greater than 0")
        return v


class BOMCreateSchema(BaseModel):
    """Schema untuk membuat BOM baru."""

    model_config = ConfigDict(from_attributes=True)

    bom_code: str = Field(..., min_length=3, max_length=50, description="Kode BOM")
    bom_name: str = Field(..., min_length=3, max_length=200, description="Nama BOM")
    product_id: UUID = Field(..., description="Produk jadi")
    bom_version: int = Field(1, ge=1, description="Versi BOM")
    effective_date: date = Field(default_factory=date.today, description="Tanggal berlaku")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")
    is_default: bool = Field(False, description="BOM default")
    lines: list[BOMLineSchema] = Field(..., min_length=1, description="Komponen")
    notes: str | None = Field(None, max_length=500)

    @field_validator("bom_code")
    @classmethod
    def validate_bom_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("BOM code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_dates(self) -> BOMCreateSchema:
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("Expiry date must be after effective date")
        return self


class BOMResponseSchema(BaseModel):
    """Response BOM."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    bom_code: str
    bom_name: str
    product_id: UUID
    product_code: str | None = None
    product_name: str | None = None
    bom_version: int
    effective_date: date
    expiry_date: date | None
    status: BOMStatus
    is_default: bool
    lines: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class RoutingStepSchema(BaseModel):
    """Step dalam routing."""

    model_config = ConfigDict(from_attributes=True)

    step_number: int = Field(..., ge=1, description="Nomor urut step")
    work_center: str = Field(..., max_length=100, description="Work center")
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    setup_time_hours: Decimal = Field(0, ge=0, decimal_places=2, description="Waktu setup (jam)")
    run_time_hours: Decimal = Field(..., ge=0, decimal_places=2, description="Waktu proses (jam)")
    machine_hours: Decimal = Field(0, ge=0, decimal_places=2, description="Jam mesin")
    labor_hours: Decimal = Field(..., ge=0, decimal_places=2, description="Jam tenaga kerja")
    queue_time_hours: Decimal = Field(0, ge=0, decimal_places=2, description="Waktu antri")
    move_time_hours: Decimal = Field(0, ge=0, decimal_places=2, description="Waktu pindah")

    @field_validator("step_number")
    @classmethod
    def validate_step_number(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Step number must be greater than 0")
        return v


class RoutingCreateSchema(BaseModel):
    """Schema untuk membuat routing baru."""

    model_config = ConfigDict(from_attributes=True)

    routing_code: str = Field(..., min_length=3, max_length=50, description="Kode routing")
    routing_name: str = Field(..., min_length=3, max_length=200, description="Nama routing")
    product_id: UUID = Field(..., description="Produk")
    routing_version: int = Field(1, ge=1, description="Versi routing")
    effective_date: date = Field(default_factory=date.today, description="Tanggal berlaku")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")
    is_default: bool = Field(False, description="Routing default")
    steps: list[RoutingStepSchema] = Field(..., min_length=1, description="Step-step produksi")
    notes: str | None = Field(None, max_length=500)

    @field_validator("routing_code")
    @classmethod
    def validate_routing_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Routing code is required")
        return v.upper()


class RoutingResponseSchema(BaseModel):
    """Response routing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    routing_code: str
    routing_name: str
    product_id: UUID
    product_code: str | None = None
    product_name: str | None = None
    routing_version: int
    effective_date: date
    expiry_date: date | None
    status: RoutingStatus
    is_default: bool
    steps: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class WorkOrderCreateSchema(BaseModel):
    """Schema untuk membuat work order."""

    model_config = ConfigDict(from_attributes=True)

    work_order_number: str = Field(..., max_length=50, description="Nomor WO")
    product_id: UUID = Field(..., description="Produk yang diproduksi")
    planned_quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas rencana")
    planned_start_date: date = Field(..., description="Tanggal mulai rencana")
    planned_end_date: date = Field(..., description="Tanggal selesai rencana")
    bom_id: UUID | None = Field(None, description="BOM yang digunakan")
    routing_id: UUID | None = Field(None, description="Routing yang digunakan")
    cost_center: str | None = Field(None, max_length=50, description="Cost center")
    priority: int = Field(5, ge=1, le=10, description="Prioritas (1-10, 1 tertinggi)")
    notes: str | None = Field(None, max_length=500)

    @field_validator("work_order_number")
    @classmethod
    def validate_wo_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Work order number is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> WorkOrderCreateSchema:
        if self.planned_end_date < self.planned_start_date:
            raise ValueError("Planned end date must be after planned start date")
        return self


class WorkOrderUpdateSchema(BaseModel):
    """Schema untuk update work order."""

    model_config = ConfigDict(from_attributes=True)

    planned_quantity: Decimal | None = Field(None, gt=0, decimal_places=2)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    bom_id: UUID | None = None
    routing_id: UUID | None = None
    cost_center: str | None = None
    priority: int | None = Field(None, ge=1, le=10)
    notes: str | None = None
    status: WorkOrderStatus | None = None


class WorkOrderReleaseSchema(BaseModel):
    """Schema untuk release work order."""

    model_config = ConfigDict(from_attributes=True)

    actual_start_date: date = Field(default_factory=date.today, description="Tanggal mulai aktual")
    notes: str | None = None


class WorkOrderCompletionSchema(BaseModel):
    """Schema untuk complete work order."""

    model_config = ConfigDict(from_attributes=True)

    completed_quantity: Decimal = Field(
        ..., gt=0, decimal_places=2, description="Kuantitas selesai"
    )
    rejected_quantity: Decimal = Field(0, ge=0, decimal_places=2, description="Kuantitas reject")
    actual_end_date: date = Field(default_factory=date.today, description="Tanggal selesai aktual")
    notes: str | None = None

    @model_validator(mode="after")
    def validate_quantities(self) -> WorkOrderCompletionSchema:
        if self.completed_quantity + self.rejected_quantity <= 0:
            raise ValueError("Total completed and rejected must be greater than 0")
        return self


class WorkOrderResponseSchema(BaseModel):
    """Response work order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str | None = None
    product_name: str | None = None
    planned_quantity: Decimal
    completed_quantity: Decimal
    rejected_quantity: Decimal
    remaining_quantity: Decimal
    bom_id: UUID | None
    bom_code: str | None = None
    routing_id: UUID | None
    routing_code: str | None = None
    planned_start_date: date
    planned_end_date: date
    actual_start_date: date | None
    actual_end_date: date | None
    standard_material_cost: Decimal
    standard_labor_cost: Decimal
    standard_overhead_cost: Decimal
    standard_total_cost: Decimal
    actual_material_cost: Decimal
    actual_labor_cost: Decimal
    actual_overhead_cost: Decimal
    actual_total_cost: Decimal
    material_variance: Decimal
    labor_variance: Decimal
    overhead_variance: Decimal
    total_variance: Decimal
    status: WorkOrderStatus
    priority: int
    cost_center: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1
    is_locked: bool = False


class MaterialIssueSchema(BaseModel):
    """Schema untuk issue material ke work order."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID = Field(..., description="Item ID")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas")
    batch_number: str | None = Field(None, max_length=50, description="Batch number")
    warehouse_id: UUID = Field(..., description="Gudang asal")
    notes: str | None = Field(None, max_length=500)


class LaborRecordSchema(BaseModel):
    """Schema untuk record tenaga kerja."""

    model_config = ConfigDict(from_attributes=True)

    employee_id: UUID = Field(..., description="Karyawan")
    hours: Decimal = Field(..., gt=0, decimal_places=2, description="Jam kerja")
    hourly_rate: Decimal = Field(..., gt=0, decimal_places=2, description="Tarif per jam")
    work_center: str | None = Field(None, max_length=100, description="Work center")
    notes: str | None = Field(None, max_length=500)


class FinishedGoodsReceiptSchema(BaseModel):
    """Schema untuk receipt finished goods."""

    model_config = ConfigDict(from_attributes=True)

    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas")
    warehouse_id: UUID = Field(..., description="Gudang tujuan")
    batch_number: str | None = Field(None, max_length=50, description="Batch number")
    notes: str | None = Field(None, max_length=500)


class WIPResponseSchema(BaseModel):
    """Response Work In Process."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_name: str
    quantity_started: Decimal
    quantity_remaining: Decimal
    completion_percent: float
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    material_issued: list[dict[str, Any]]
    labor_recorded: list[dict[str, Any]]
    start_date: date
    expected_completion_date: date | None
    created_at: datetime


class CostCardCreateSchema(BaseModel):
    """Schema untuk membuat cost card."""

    model_config = ConfigDict(from_attributes=True)

    cost_card_code: str = Field(..., min_length=3, max_length=50, description="Kode cost card")
    product_id: UUID = Field(..., description="Produk")
    effective_date: date = Field(default_factory=date.today, description="Tanggal berlaku")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")
    material_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya material")
    labor_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya tenaga kerja")
    overhead_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya overhead")
    other_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya lain")
    quantity_base: Decimal = Field(1, gt=0, decimal_places=2, description="Kuantitas dasar")
    unit_of_measure: str = Field("pcs", max_length=10, description="Satuan")
    breakdown: dict[str, Any] | None = Field(None, description="Rincian biaya")
    notes: str | None = Field(None, max_length=500)

    @field_validator("cost_card_code")
    @classmethod
    def validate_cost_card_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Cost card code is required")
        return v.upper()

    @property
    def total_cost(self) -> Decimal:
        return self.material_cost + self.labor_cost + self.overhead_cost + self.other_cost

    @property
    def unit_cost(self) -> Decimal:
        if self.quantity_base > 0:
            return (self.total_cost / self.quantity_base).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        return Decimal(0)


class CostCardResponseSchema(BaseModel):
    """Response cost card."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cost_card_code: str
    product_id: UUID
    product_code: str | None = None
    product_name: str | None = None
    effective_date: date
    expiry_date: date | None
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    other_cost: Decimal
    total_cost: Decimal
    quantity_base: Decimal
    unit_cost: Decimal
    unit_of_measure: str
    status: str
    is_active: bool
    breakdown: dict[str, Any] | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class VarianceAnalysisResponseSchema(BaseModel):
    """Response variance analysis."""

    model_config = ConfigDict(from_attributes=True)

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_name: str
    standard_cost: Decimal
    actual_cost: Decimal
    total_variance: Decimal
    total_variance_percent: float
    material_price_variance: Decimal
    material_usage_variance: Decimal
    material_variance_total: Decimal
    labor_rate_variance: Decimal
    labor_efficiency_variance: Decimal
    labor_variance_total: Decimal
    overhead_volume_variance: Decimal
    overhead_spending_variance: Decimal
    overhead_variance_total: Decimal
    variances_by_component: list[dict[str, Any]]
    analysis_period_start: date
    analysis_period_end: date
    generated_at: datetime


class OverheadAllocationSchema(BaseModel):
    """Schema untuk alokasi overhead."""

    model_config = ConfigDict(from_attributes=True)

    allocation_date: date = Field(default_factory=date.today, description="Tanggal alokasi")
    allocation_base: str = Field(
        ..., description="Dasar alokasi: machine_hours, labor_hours, material_cost"
    )
    total_overhead: Decimal = Field(..., gt=0, decimal_places=2, description="Total overhead")
    work_order_ids: list[UUID] | None = Field(
        None, description="Work order yang dialokasi (kosong = semua aktif)"
    )


class OverheadAllocationResponseSchema(BaseModel):
    """Response alokasi overhead."""

    model_config = ConfigDict(from_attributes=True)

    allocation_id: UUID
    allocation_number: str
    allocation_date: date
    allocation_base: str
    total_overhead: Decimal
    allocated_overhead: Decimal
    work_orders_affected: int
    journal_id: UUID | None
    details: list[dict[str, Any]]
    status: str
    created_at: datetime
    created_by: UUID


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_manufacturing_service(request: Request, ) -> Any:
    """Get Manufacturing Service instance."""

    from application.service_layer.service_manufacturing import ManufacturingService

    container = request.app.state.container
    return container.resolve(ManufacturingService)


async def get_hpp_close_use_case() -> Any:
    """Get HPP Manufacturing Close Use Case instance."""

    from application.use_cases.hpp_manufacturing_close import HPPManufacturingCloseUseCase

    container = request.app.state.container
    return container.resolve(HPPManufacturingCloseUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/manufacturing", tags=["Manufacturing"])


# ----------------------------------------------------------------------------
# BILL OF MATERIALS (BOM)
# ----------------------------------------------------------------------------


@router.post(
    "/bom",
    response_model=BOMResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Bill of Materials",
    operation_id="create_bom",
)
async def create_bom(
    request: BOMCreateSchema,
    _permission: None = Depends(require_permission("manufacturing:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> BOMResponseSchema:
    """Create a new Bill of Materials."""
    try:
        result = await service.create_bom(
            bom_code=request.bom_code,
            bom_name=request.bom_name,
            product_id=request.product_id,
            bom_version=request.bom_version,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            is_default=request.is_default,
            lines=[line.dict() for line in request.lines],
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return BOMResponseSchema(
            id=result.id,
            bom_code=result.bom_code,
            bom_name=result.bom_name,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            bom_version=result.bom_version,
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            status=BOMStatus(result.status),
            is_default=result.is_default,
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create BOM: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/bom",
    response_model=list[BOMResponseSchema],
    summary="List Bill of Materials",
    operation_id="list_bom",
)
async def list_bom(
    product_id: UUID | None = Query(None, description="Filter by product"),
    is_default: bool | None = Query(None, description="Filter by default"),
    status: BOMStatus | None = Query(None, description="Filter by status"),
    effective_as_of: date | None = Query(None, description="Effective as of date"),
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> list[BOMResponseSchema]:
    """List Bill of Materials with filters."""
    try:
        boms = await service.list_boms(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            is_default=is_default,
            status=status.value if status else None,
            effective_as_of=effective_as_of,
        )

        return [
            BOMResponseSchema(
                id=b.id,
                bom_code=b.bom_code,
                bom_name=b.bom_name,
                product_id=b.product_id,
                product_code=b.product_code,
                product_name=b.product_name,
                bom_version=b.bom_version,
                effective_date=b.effective_date,
                expiry_date=b.expiry_date,
                status=BOMStatus(b.status),
                is_default=b.is_default,
                lines=b.lines,
                notes=b.notes,
                created_at=b.created_at,
                updated_at=b.updated_at,
                created_by=b.created_by,
                created_by_name=b.created_by_name,
                version=b.version,
            )
            for b in boms
        ]
    except Exception as e:
        logger.exception("Failed to list BOM: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/bom/{bom_id}",
    response_model=BOMResponseSchema,
    summary="Get BOM by ID",
    operation_id="get_bom",
)
async def get_bom(
    bom_id: UUID,
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> BOMResponseSchema:
    """Get Bill of Materials by ID."""
    try:
        bom = await service.get_bom_by_id(bom_id, legal_entity_id)

        if not bom:
            raise HTTPException(status_code=404, detail="BOM not found")

        return BOMResponseSchema(
            id=bom.id,
            bom_code=bom.bom_code,
            bom_name=bom.bom_name,
            product_id=bom.product_id,
            product_code=bom.product_code,
            product_name=bom.product_name,
            bom_version=bom.bom_version,
            effective_date=bom.effective_date,
            expiry_date=bom.expiry_date,
            status=BOMStatus(bom.status),
            is_default=bom.is_default,
            lines=bom.lines,
            notes=bom.notes,
            created_at=bom.created_at,
            updated_at=bom.updated_at,
            created_by=bom.created_by,
            created_by_name=bom.created_by_name,
            version=bom.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get BOM: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/bom/{bom_id}",
    response_model=BOMResponseSchema,
    summary="Update BOM",
    operation_id="update_bom",
)
async def update_bom(
    bom_id: UUID,
    request: BOMCreateSchema,
    _permission: None = Depends(require_permission("manufacturing:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> BOMResponseSchema:
    """Update Bill of Materials."""
    try:
        result = await service.update_bom(
            bom_id=bom_id,
            bom_name=request.bom_name,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            is_default=request.is_default,
            lines=[line.dict() for line in request.lines],
            notes=request.notes,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="BOM not found or cannot be updated")

        return BOMResponseSchema(
            id=result.id,
            bom_code=result.bom_code,
            bom_name=result.bom_name,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            bom_version=result.bom_version,
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            status=BOMStatus(result.status),
            is_default=result.is_default,
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update BOM: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/bom/{bom_id}",
    response_model=dict[str, Any],
    summary="Deactivate BOM",
    operation_id="deactivate_bom",
)
async def deactivate_bom(
    bom_id: UUID,
    reason: str = Query("", description="Reason for deactivation"),
    _permission: None = Depends(require_permission("manufacturing:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> dict[str, Any]:
    """Deactivate a Bill of Materials."""
    try:
        result = await service.deactivate_bom(bom_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="BOM not found")

        return {
            "bom_id": str(bom_id),
            "bom_code": result.bom_code,
            "status": result.status,
            "message": "BOM deactivated",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate BOM: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ROUTING
# ----------------------------------------------------------------------------


@router.post(
    "/routing",
    response_model=RoutingResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Routing",
    operation_id="create_routing",
)
async def create_routing(
    request: RoutingCreateSchema,
    _permission: None = Depends(require_permission("manufacturing:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> RoutingResponseSchema:
    """Create a new Routing."""
    try:
        result = await service.create_routing(
            routing_code=request.routing_code,
            routing_name=request.routing_name,
            product_id=request.product_id,
            routing_version=request.routing_version,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            is_default=request.is_default,
            steps=[step.dict() for step in request.steps],
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return RoutingResponseSchema(
            id=result.id,
            routing_code=result.routing_code,
            routing_name=result.routing_name,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            routing_version=result.routing_version,
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            status=RoutingStatus(result.status),
            is_default=result.is_default,
            steps=result.steps,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create routing: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/routing",
    response_model=list[RoutingResponseSchema],
    summary="List Routings",
    operation_id="list_routing",
)
async def list_routing(
    product_id: UUID | None = Query(None, description="Filter by product"),
    is_default: bool | None = Query(None, description="Filter by default"),
    status: RoutingStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> list[RoutingResponseSchema]:
    """List Routings with filters."""
    try:
        routings = await service.list_routings(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            is_default=is_default,
            status=status.value if status else None,
        )

        return [
            RoutingResponseSchema(
                id=r.id,
                routing_code=r.routing_code,
                routing_name=r.routing_name,
                product_id=r.product_id,
                product_code=r.product_code,
                product_name=r.product_name,
                routing_version=r.routing_version,
                effective_date=r.effective_date,
                expiry_date=r.expiry_date,
                status=RoutingStatus(r.status),
                is_default=r.is_default,
                steps=r.steps,
                notes=r.notes,
                created_at=r.created_at,
                updated_at=r.updated_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                version=r.version,
            )
            for r in routings
        ]
    except Exception as e:
        logger.exception("Failed to list routing: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/routing/{routing_id}",
    response_model=RoutingResponseSchema,
    summary="Get Routing by ID",
    operation_id="get_routing",
)
async def get_routing(
    routing_id: UUID,
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> RoutingResponseSchema:
    """Get Routing by ID."""
    try:
        routing = await service.get_routing_by_id(routing_id, legal_entity_id)

        if not routing:
            raise HTTPException(status_code=404, detail="Routing not found")

        return RoutingResponseSchema(
            id=routing.id,
            routing_code=routing.routing_code,
            routing_name=routing.routing_name,
            product_id=routing.product_id,
            product_code=routing.product_code,
            product_name=routing.product_name,
            routing_version=routing.routing_version,
            effective_date=routing.effective_date,
            expiry_date=routing.expiry_date,
            status=RoutingStatus(routing.status),
            is_default=routing.is_default,
            steps=routing.steps,
            notes=routing.notes,
            created_at=routing.created_at,
            updated_at=routing.updated_at,
            created_by=routing.created_by,
            created_by_name=routing.created_by_name,
            version=routing.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get routing: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WORK ORDER
# ----------------------------------------------------------------------------


@router.post(
    "/work-orders",
    response_model=WorkOrderResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Work Order",
    operation_id="create_work_order",
)
async def create_work_order(
    request: WorkOrderCreateSchema,
    _permission: None = Depends(require_permission("manufacturing:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Create a new Work Order."""
    try:
        result = await service.create_work_order(
            work_order_number=request.work_order_number,
            product_id=request.product_id,
            planned_quantity=request.planned_quantity,
            planned_start_date=request.planned_start_date,
            planned_end_date=request.planned_end_date,
            bom_id=request.bom_id,
            routing_id=request.routing_id,
            cost_center=request.cost_center,
            priority=request.priority,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return WorkOrderResponseSchema(
            id=result.id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            planned_quantity=result.planned_quantity,
            completed_quantity=result.completed_quantity,
            rejected_quantity=result.rejected_quantity,
            remaining_quantity=result.remaining_quantity,
            bom_id=result.bom_id,
            bom_code=result.bom_code,
            routing_id=result.routing_id,
            routing_code=result.routing_code,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            standard_material_cost=result.standard_material_cost,
            standard_labor_cost=result.standard_labor_cost,
            standard_overhead_cost=result.standard_overhead_cost,
            standard_total_cost=result.standard_total_cost,
            actual_material_cost=result.actual_material_cost,
            actual_labor_cost=result.actual_labor_cost,
            actual_overhead_cost=result.actual_overhead_cost,
            actual_total_cost=result.actual_total_cost,
            material_variance=result.material_variance,
            labor_variance=result.labor_variance,
            overhead_variance=result.overhead_variance,
            total_variance=result.total_variance,
            status=WorkOrderStatus(result.status),
            priority=result.priority,
            cost_center=result.cost_center,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_locked=result.is_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/work-orders",
    response_model=list[WorkOrderResponseSchema],
    summary="List Work Orders",
    operation_id="list_work_orders",
)
async def list_work_orders(
    product_id: UUID | None = Query(None, description="Filter by product"),
    status: WorkOrderStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> list[WorkOrderResponseSchema]:
    """List Work Orders with pagination and filters."""
    try:
        result = await service.list_work_orders(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            WorkOrderResponseSchema(
                id=wo.id,
                work_order_number=wo.work_order_number,
                product_id=wo.product_id,
                product_code=wo.product_code,
                product_name=wo.product_name,
                planned_quantity=wo.planned_quantity,
                completed_quantity=wo.completed_quantity,
                rejected_quantity=wo.rejected_quantity,
                remaining_quantity=wo.remaining_quantity,
                bom_id=wo.bom_id,
                bom_code=wo.bom_code,
                routing_id=wo.routing_id,
                routing_code=wo.routing_code,
                planned_start_date=wo.planned_start_date,
                planned_end_date=wo.planned_end_date,
                actual_start_date=wo.actual_start_date,
                actual_end_date=wo.actual_end_date,
                standard_material_cost=wo.standard_material_cost,
                standard_labor_cost=wo.standard_labor_cost,
                standard_overhead_cost=wo.standard_overhead_cost,
                standard_total_cost=wo.standard_total_cost,
                actual_material_cost=wo.actual_material_cost,
                actual_labor_cost=wo.actual_labor_cost,
                actual_overhead_cost=wo.actual_overhead_cost,
                actual_total_cost=wo.actual_total_cost,
                material_variance=wo.material_variance,
                labor_variance=wo.labor_variance,
                overhead_variance=wo.overhead_variance,
                total_variance=wo.total_variance,
                status=WorkOrderStatus(wo.status),
                priority=wo.priority,
                cost_center=wo.cost_center,
                notes=wo.notes,
                created_at=wo.created_at,
                updated_at=wo.updated_at,
                created_by=wo.created_by,
                created_by_name=wo.created_by_name,
                version=wo.version,
                is_locked=wo.is_locked,
            )
            for wo in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list work orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderResponseSchema,
    summary="Get Work Order by ID",
    operation_id="get_work_order",
)
async def get_work_order(
    work_order_id: UUID,
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Get Work Order by ID."""
    try:
        wo = await service.get_work_order_by_id(work_order_id, legal_entity_id)

        if not wo:
            raise HTTPException(status_code=404, detail="Work order not found")

        return WorkOrderResponseSchema(
            id=wo.id,
            work_order_number=wo.work_order_number,
            product_id=wo.product_id,
            product_code=wo.product_code,
            product_name=wo.product_name,
            planned_quantity=wo.planned_quantity,
            completed_quantity=wo.completed_quantity,
            rejected_quantity=wo.rejected_quantity,
            remaining_quantity=wo.remaining_quantity,
            bom_id=wo.bom_id,
            bom_code=wo.bom_code,
            routing_id=wo.routing_id,
            routing_code=wo.routing_code,
            planned_start_date=wo.planned_start_date,
            planned_end_date=wo.planned_end_date,
            actual_start_date=wo.actual_start_date,
            actual_end_date=wo.actual_end_date,
            standard_material_cost=wo.standard_material_cost,
            standard_labor_cost=wo.standard_labor_cost,
            standard_overhead_cost=wo.standard_overhead_cost,
            standard_total_cost=wo.standard_total_cost,
            actual_material_cost=wo.actual_material_cost,
            actual_labor_cost=wo.actual_labor_cost,
            actual_overhead_cost=wo.actual_overhead_cost,
            actual_total_cost=wo.actual_total_cost,
            material_variance=wo.material_variance,
            labor_variance=wo.labor_variance,
            overhead_variance=wo.overhead_variance,
            total_variance=wo.total_variance,
            status=WorkOrderStatus(wo.status),
            priority=wo.priority,
            cost_center=wo.cost_center,
            notes=wo.notes,
            created_at=wo.created_at,
            updated_at=wo.updated_at,
            created_by=wo.created_by,
            created_by_name=wo.created_by_name,
            version=wo.version,
            is_locked=wo.is_locked,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderResponseSchema,
    summary="Update Work Order",
    operation_id="update_work_order",
)
async def update_work_order(
    work_order_id: UUID,
    request: WorkOrderUpdateSchema,
    _permission: None = Depends(require_permission("manufacturing:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Update Work Order (only PLANNED or DRAFT status)."""
    try:
        result = await service.update_work_order(
            work_order_id=work_order_id,
            planned_quantity=request.planned_quantity,
            planned_start_date=request.planned_start_date,
            planned_end_date=request.planned_end_date,
            bom_id=request.bom_id,
            routing_id=request.routing_id,
            cost_center=request.cost_center,
            priority=request.priority,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Work order not found or cannot be updated")

        return WorkOrderResponseSchema(
            id=result.id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            planned_quantity=result.planned_quantity,
            completed_quantity=result.completed_quantity,
            rejected_quantity=result.rejected_quantity,
            remaining_quantity=result.remaining_quantity,
            bom_id=result.bom_id,
            bom_code=result.bom_code,
            routing_id=result.routing_id,
            routing_code=result.routing_code,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            standard_material_cost=result.standard_material_cost,
            standard_labor_cost=result.standard_labor_cost,
            standard_overhead_cost=result.standard_overhead_cost,
            standard_total_cost=result.standard_total_cost,
            actual_material_cost=result.actual_material_cost,
            actual_labor_cost=result.actual_labor_cost,
            actual_overhead_cost=result.actual_overhead_cost,
            actual_total_cost=result.actual_total_cost,
            material_variance=result.material_variance,
            labor_variance=result.labor_variance,
            overhead_variance=result.overhead_variance,
            total_variance=result.total_variance,
            status=WorkOrderStatus(result.status),
            priority=result.priority,
            cost_center=result.cost_center,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_locked=result.is_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/work-orders/{work_order_id}/release",
    response_model=WorkOrderResponseSchema,
    summary="Release Work Order",
    operation_id="release_work_order",
)
async def release_work_order(
    work_order_id: UUID,
    request: WorkOrderReleaseSchema,
    _permission: None = Depends(require_permission("manufacturing:release")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Release a planned work order to production."""
    try:
        result = await service.release_work_order(
            work_order_id=work_order_id,
            actual_start_date=request.actual_start_date,
            notes=request.notes,
            released_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Work order not found or cannot be released"
            )

        return WorkOrderResponseSchema(
            id=result.id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            planned_quantity=result.planned_quantity,
            completed_quantity=result.completed_quantity,
            rejected_quantity=result.rejected_quantity,
            remaining_quantity=result.remaining_quantity,
            bom_id=result.bom_id,
            bom_code=result.bom_code,
            routing_id=result.routing_id,
            routing_code=result.routing_code,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            standard_material_cost=result.standard_material_cost,
            standard_labor_cost=result.standard_labor_cost,
            standard_overhead_cost=result.standard_overhead_cost,
            standard_total_cost=result.standard_total_cost,
            actual_material_cost=result.actual_material_cost,
            actual_labor_cost=result.actual_labor_cost,
            actual_overhead_cost=result.actual_overhead_cost,
            actual_total_cost=result.actual_total_cost,
            material_variance=result.material_variance,
            labor_variance=result.labor_variance,
            overhead_variance=result.overhead_variance,
            total_variance=result.total_variance,
            status=WorkOrderStatus(result.status),
            priority=result.priority,
            cost_center=result.cost_center,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_locked=result.is_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to release work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/work-orders/{work_order_id}/complete",
    response_model=WorkOrderResponseSchema,
    summary="Complete Work Order",
    operation_id="complete_work_order",
)
async def complete_work_order(
    work_order_id: UUID,
    request: WorkOrderCompletionSchema,
    _permission: None = Depends(require_permission("manufacturing:complete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Complete a work order (record finished goods)."""
    try:
        result = await service.complete_work_order(
            work_order_id=work_order_id,
            completed_quantity=request.completed_quantity,
            rejected_quantity=request.rejected_quantity,
            actual_end_date=request.actual_end_date,
            notes=request.notes,
            completed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Work order not found or cannot be completed"
            )

        return WorkOrderResponseSchema(
            id=result.id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            planned_quantity=result.planned_quantity,
            completed_quantity=result.completed_quantity,
            rejected_quantity=result.rejected_quantity,
            remaining_quantity=result.remaining_quantity,
            bom_id=result.bom_id,
            bom_code=result.bom_code,
            routing_id=result.routing_id,
            routing_code=result.routing_code,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            standard_material_cost=result.standard_material_cost,
            standard_labor_cost=result.standard_labor_cost,
            standard_overhead_cost=result.standard_overhead_cost,
            standard_total_cost=result.standard_total_cost,
            actual_material_cost=result.actual_material_cost,
            actual_labor_cost=result.actual_labor_cost,
            actual_overhead_cost=result.actual_overhead_cost,
            actual_total_cost=result.actual_total_cost,
            material_variance=result.material_variance,
            labor_variance=result.labor_variance,
            overhead_variance=result.overhead_variance,
            total_variance=result.total_variance,
            status=WorkOrderStatus(result.status),
            priority=result.priority,
            cost_center=result.cost_center,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_locked=result.is_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to complete work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/work-orders/{work_order_id}",
    response_model=dict[str, Any],
    summary="Cancel Work Order",
    operation_id="cancel_work_order",
)
async def cancel_work_order(
    work_order_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("manufacturing:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> dict[str, Any]:
    """Cancel a work order (only PLANNED or RELEASED)."""
    try:
        result = await service.cancel_work_order(
            work_order_id=work_order_id,
            reason=reason,
            cancelled_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Work order not found or cannot be cancelled"
            )

        return {
            "work_order_id": str(work_order_id),
            "work_order_number": result.work_order_number,
            "status": result.status,
            "message": "Work order cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/work-orders/{work_order_id}/close",
    response_model=WorkOrderResponseSchema,
    summary="Close Work Order",
    operation_id="close_work_order",
)
async def close_work_order(
    work_order_id: UUID,
    _permission: None = Depends(require_permission("manufacturing:close")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> WorkOrderResponseSchema:
    """Close a completed work order (prevent further changes)."""
    try:
        result = await service.close_work_order(
            work_order_id=work_order_id,
            closed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Work order not found or cannot be closed")

        return WorkOrderResponseSchema(
            id=result.id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            planned_quantity=result.planned_quantity,
            completed_quantity=result.completed_quantity,
            rejected_quantity=result.rejected_quantity,
            remaining_quantity=result.remaining_quantity,
            bom_id=result.bom_id,
            bom_code=result.bom_code,
            routing_id=result.routing_id,
            routing_code=result.routing_code,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            standard_material_cost=result.standard_material_cost,
            standard_labor_cost=result.standard_labor_cost,
            standard_overhead_cost=result.standard_overhead_cost,
            standard_total_cost=result.standard_total_cost,
            actual_material_cost=result.actual_material_cost,
            actual_labor_cost=result.actual_labor_cost,
            actual_overhead_cost=result.actual_overhead_cost,
            actual_total_cost=result.actual_total_cost,
            material_variance=result.material_variance,
            labor_variance=result.labor_variance,
            overhead_variance=result.overhead_variance,
            total_variance=result.total_variance,
            status=WorkOrderStatus(result.status),
            priority=result.priority,
            cost_center=result.cost_center,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_locked=result.is_locked,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WORK IN PROCESS (WIP)
# ----------------------------------------------------------------------------


@router.get(
    "/wip",
    response_model=list[dict[str, Any]],
    summary="List Work in Process (WIP)",
    operation_id="list_wip",
)
async def list_wip(
    work_order_id: UUID | None = Query(None, description="Filter by work order"),
    product_id: UUID | None = Query(None, description="Filter by product"),
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> list[dict[str, Any]]:
    """List Work in Process (WIP) for active work orders."""
    try:
        wip_items = await service.list_wip(
            legal_entity_id=legal_entity_id,
            work_order_id=work_order_id,
            product_id=product_id,
        )

        return [
            {
                "id": str(w.id),
                "work_order_id": str(w.work_order_id),
                "work_order_number": w.work_order_number,
                "product_id": str(w.product_id),
                "product_name": w.product_name,
                "quantity_started": float(w.quantity_started),
                "quantity_remaining": float(w.quantity_remaining),
                "completion_percent": w.completion_percent,
                "material_cost": float(w.material_cost),
                "labor_cost": float(w.labor_cost),
                "overhead_cost": float(w.overhead_cost),
                "total_cost": float(w.total_cost),
                "material_issued": w.material_issued,
                "labor_recorded": w.labor_recorded,
                "start_date": w.start_date.isoformat(),
                "expected_completion_date": w.expected_completion_date.isoformat()
                if w.expected_completion_date
                else None,
                "created_at": w.created_at.isoformat(),
            }
            for w in wip_items
        ]
    except Exception as e:
        logger.exception("Failed to list WIP: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# COST CARD
# ----------------------------------------------------------------------------


@router.post(
    "/cost-cards",
    response_model=CostCardResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Cost Card",
    operation_id="create_cost_card",
)
async def create_cost_card(
    request: CostCardCreateSchema,
    _permission: None = Depends(require_permission("manufacturing:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> CostCardResponseSchema:
    """Create a new Cost Card for standard costing."""
    try:
        result = await service.create_cost_card(
            cost_card_code=request.cost_card_code,
            product_id=request.product_id,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            material_cost=request.material_cost,
            labor_cost=request.labor_cost,
            overhead_cost=request.overhead_cost,
            other_cost=request.other_cost,
            quantity_base=request.quantity_base,
            unit_of_measure=request.unit_of_measure,
            breakdown=request.breakdown,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return CostCardResponseSchema(
            id=result.id,
            cost_card_code=result.cost_card_code,
            product_id=result.product_id,
            product_code=result.product_code,
            product_name=result.product_name,
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            material_cost=result.material_cost,
            labor_cost=result.labor_cost,
            overhead_cost=result.overhead_cost,
            other_cost=result.other_cost,
            total_cost=result.total_cost,
            quantity_base=result.quantity_base,
            unit_cost=result.unit_cost,
            unit_of_measure=result.unit_of_measure,
            status=result.status,
            is_active=result.is_active,
            breakdown=result.breakdown,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create cost card: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/cost-cards",
    response_model=list[CostCardResponseSchema],
    summary="List Cost Cards",
    operation_id="list_cost_cards",
)
async def list_cost_cards(
    product_id: UUID | None = Query(None, description="Filter by product"),
    effective_as_of: date | None = Query(None, description="Effective as of date"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> list[CostCardResponseSchema]:
    """List Cost Cards with filters."""
    try:
        cards = await service.list_cost_cards(
            legal_entity_id=legal_entity_id,
            product_id=product_id,
            effective_as_of=effective_as_of,
            is_active=is_active,
        )

        return [
            CostCardResponseSchema(
                id=c.id,
                cost_card_code=c.cost_card_code,
                product_id=c.product_id,
                product_code=c.product_code,
                product_name=c.product_name,
                effective_date=c.effective_date,
                expiry_date=c.expiry_date,
                material_cost=c.material_cost,
                labor_cost=c.labor_cost,
                overhead_cost=c.overhead_cost,
                other_cost=c.other_cost,
                total_cost=c.total_cost,
                quantity_base=c.quantity_base,
                unit_cost=c.unit_cost,
                unit_of_measure=c.unit_of_measure,
                status=c.status,
                is_active=c.is_active,
                breakdown=c.breakdown,
                notes=c.notes,
                created_at=c.created_at,
                updated_at=c.updated_at,
                created_by=c.created_by,
                created_by_name=c.created_by_name,
                version=c.version,
            )
            for c in cards
        ]
    except Exception as e:
        logger.exception("Failed to list cost cards: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# VARIANCE ANALYSIS
# ----------------------------------------------------------------------------


@router.get(
    "/variance-analysis/{work_order_id}",
    response_model=VarianceAnalysisResponseSchema,
    summary="Get variance analysis for work order",
    operation_id="get_variance_analysis",
)
async def get_variance_analysis(
    work_order_id: UUID,
    _permission: None = Depends(require_permission("manufacturing:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> VarianceAnalysisResponseSchema:
    """Get variance analysis comparing standard vs actual costs."""
    try:
        result = await service.analyze_variance(work_order_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Work order not found")

        return VarianceAnalysisResponseSchema(
            work_order_id=result.work_order_id,
            work_order_number=result.work_order_number,
            product_id=result.product_id,
            product_name=result.product_name,
            standard_cost=result.standard_cost,
            actual_cost=result.actual_cost,
            total_variance=result.total_variance,
            total_variance_percent=result.total_variance_percent,
            material_price_variance=result.material_price_variance,
            material_usage_variance=result.material_usage_variance,
            material_variance_total=result.material_variance_total,
            labor_rate_variance=result.labor_rate_variance,
            labor_efficiency_variance=result.labor_efficiency_variance,
            labor_variance_total=result.labor_variance_total,
            overhead_volume_variance=result.overhead_volume_variance,
            overhead_spending_variance=result.overhead_spending_variance,
            overhead_variance_total=result.overhead_variance_total,
            variances_by_component=result.variances_by_component,
            analysis_period_start=result.analysis_period_start,
            analysis_period_end=result.analysis_period_end,
            generated_at=result.generated_at,
        )
    except Exception as e:
        logger.exception("Failed to get variance analysis: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HPP CLOSE (Monthly COGS calculation)
# ----------------------------------------------------------------------------


@router.post(
    "/close-hpp",
    response_model=dict[str, Any],
    summary="Close HPP for period",
    operation_id="close_hpp",
)
async def close_hpp_period(
    fiscal_year: int = Query(..., description="Fiscal year"),
    period: int = Query(..., ge=1, le=12, description="Period (month)"),
    _permission: None = Depends(require_permission("manufacturing:close")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    hpp_close_use_case: Any = Depends(get_hpp_close_use_case),
) -> dict[str, Any]:
    """Close HPP for period (calculate COGS from manufacturing)."""
    try:
        result = await hpp_close_use_case.execute(
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            period=period,
            closed_by=current_user.user_id,
        )

        return {
            "status": result.status,
            "journal_id": str(result.journal_id) if result.journal_id else None,
            "cogs_amount": float(result.cogs_amount),
            "work_orders_processed": result.work_orders_processed,
            "message": result.message,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close HPP: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------


@router.get(
    "/export/work-orders",
    summary="Export work orders",
    operation_id="export_work_orders",
)
async def export_work_orders(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: WorkOrderStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("manufacturing:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_manufacturing_service),
) -> Response:
    """Export work orders to CSV or Excel."""
    try:
        data = await service.export_work_orders(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            status=status.value if status else None,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"work_orders_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export work orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
