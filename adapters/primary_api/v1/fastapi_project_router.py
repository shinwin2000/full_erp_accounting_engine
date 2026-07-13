#!/usr/bin/env python3
"""
Module: fastapi_project_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Project & Services:
               project CRUD, time entry, retainer contract, project costing,
               revenue recognition, billing schedule, project dashboard.

Method Standards (ERP):
- create_project() / update_project() / delete_project() / get_project()
- activate_project() / suspend_project() / close_project() / reopen_project()
- create_time_entry() / update_time_entry() / delete_time_entry()
- approve_time_entry() / reject_time_entry() / bill_time_entry()
- create_retainer_contract() / update_retainer_contract() / terminate_retainer()
- calculate_project_cost() / calculate_project_revenue() / calculate_project_profit()
- recognize_revenue() / generate_project_invoice()
- get_project_status() / get_project_history() / get_project_snapshot()
- get_project_dashboard() / get_project_summary()
- get_time_entry_report() / get_utilization_report()
- audit_trail_project() / can_transition_project()
- register_project_event() / get_project_events()
- version_project()
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
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
# IDEMPOTENCY MANAGER (for write operations)
# ============================================================================

class IdempotencyManager:
    """
    Simple in-memory idempotency manager untuk FastAPI endpoints.
    Menyimpan hasil operasi berdasarkan idempotency_key + method_name.
    TTL 24 jam.
    """

    def __init__(self):
        self._storage: dict[str, tuple[str, datetime]] = {}
        self._ttl_seconds = 86400

    def _get_key(self, idempotency_key: str, method_name: str) -> str:
        raw = f"{method_name}:{idempotency_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_cached_result(self, idempotency_key: str, method_name: str) -> dict[str, Any] | None:
        storage_key = self._get_key(idempotency_key, method_name)
        entry = self._storage.get(storage_key)
        if entry is None:
            return None
        result_json, timestamp = entry
        if (datetime.now() - timestamp).total_seconds() > self._ttl_seconds:
            del self._storage[storage_key]
            return None
        try:
            return json.loads(result_json)
        except json.JSONDecodeError:
            return None

    def cache_result(self, idempotency_key: str, method_name: str, result: dict[str, Any]) -> None:
        storage_key = self._get_key(idempotency_key, method_name)
        try:
            result_json = json.dumps(result, default=str)
        except TypeError:
            result_json = json.dumps({"result": str(result)}, default=str)
        self._storage[storage_key] = (result_json, datetime.now())


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ProjectStatus(str, Enum):
    """Status project."""

    DRAFT = "draft"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"


class ContractType(str, Enum):
    """Jenis kontrak."""

    FIXED_PRICE = "fixed_price"  # Harga tetap
    TIME_MATERIAL = "time_material"  # Time & Material
    RETAINER = "retainer"  # Retainer bulanan
    COST_PLUS = "cost_plus"  # Cost plus
    MILESTONE = "milestone"  # Berdasarkan milestone


class RevenueRecognitionMethod(str, Enum):
    """Metode pengakuan pendapatan."""

    PERCENTAGE_COMPLETION = "percentage_completion"  # Persentase penyelesaian
    COMPLETED_CONTRACT = "completed_contract"  # Kontrak selesai
    STRAIGHT_LINE = "straight_line"  # Garis lurus
    MILESTONE = "milestone"  # Berdasarkan milestone
    INPUT_METHOD = "input_method"  # Metode input (cost)
    OUTPUT_METHOD = "output_method"  # Metode output (units)


class TimeEntryStatus(str, Enum):
    """Status time entry."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    BILLED = "billed"
    CANCELLED = "cancelled"


class RetainerStatus(str, Enum):
    """Status retainer contract."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"
    EXPIRED = "expired"
    DRAFT = "draft"


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ProjectCreateSchema(BaseModel):
    """Schema untuk membuat project baru."""

    model_config = ConfigDict(from_attributes=True)

    project_code: str = Field(..., min_length=3, max_length=50, description="Kode project")
    project_name: str = Field(..., min_length=3, max_length=200, description="Nama project")
    customer_id: UUID = Field(..., description="Customer ID")
    start_date: date = Field(..., description="Tanggal mulai")
    end_date: date | None = Field(None, description="Tanggal selesai")
    contract_type: ContractType = Field(..., description="Jenis kontrak")
    contract_value: Decimal = Field(..., gt=0, decimal_places=2, description="Nilai kontrak")
    currency_code: str = Field("IDR", min_length=3, max_length=3, description="Mata uang")
    budget_total: Decimal = Field(0, ge=0, decimal_places=2, description="Total budget")
    manager_employee_id: UUID | None = Field(None, description="Project manager")
    revenue_recognition_method: RevenueRecognitionMethod = Field(
        RevenueRecognitionMethod.PERCENTAGE_COMPLETION, description="Metode pengakuan pendapatan"
    )
    billing_cycle_days: int = Field(30, ge=1, description="Siklus billing (hari)")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    tags: list[str] | None = Field(None, description="Tags")

    @field_validator("project_code")
    @classmethod
    def validate_project_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Project code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_dates(self) -> ProjectCreateSchema:
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be after start date")
        return self


class ProjectUpdateSchema(BaseModel):
    """Schema untuk update project."""

    model_config = ConfigDict(from_attributes=True)

    project_name: str | None = Field(None, min_length=3, max_length=200)
    end_date: date | None = None
    status: ProjectStatus | None = None
    budget_total: Decimal | None = Field(None, ge=0, decimal_places=2)
    manager_employee_id: UUID | None = None
    notes: str | None = Field(None, max_length=500)
    tags: list[str] | None = None


class ProjectResponseSchema(BaseModel):
    """Response project."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_code: str
    project_name: str
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    start_date: date
    end_date: date | None
    status: ProjectStatus
    contract_type: ContractType
    contract_value: Decimal
    currency_code: str
    budget_total: Decimal
    cost_to_date: Decimal
    revenue_to_date: Decimal
    recognized_revenue_to_date: Decimal
    unbilled_revenue: Decimal
    profit_to_date: Decimal
    profit_margin_percent: float
    completion_percent: float
    revenue_recognition_method: RevenueRecognitionMethod
    billing_cycle_days: int
    manager_employee_id: UUID | None
    manager_name: str | None = None
    notes: str | None
    tags: list[str] | None
    is_locked: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class ProjectCostResponseSchema(BaseModel):
    """Response project cost breakdown."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    project_code: str
    project_name: str
    as_of_date: date
    labor_cost: Decimal
    material_cost: Decimal
    equipment_cost: Decimal
    subcontractor_cost: Decimal
    overhead_cost: Decimal
    other_cost: Decimal
    total_cost: Decimal
    budget_variance: Decimal
    cost_by_category: dict[str, Decimal]
    cost_by_period: dict[str, Decimal]


class ProjectRevenueResponseSchema(BaseModel):
    """Response project revenue."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    project_code: str
    project_name: str
    period_start: date
    period_end: date
    contract_value: Decimal
    revenue_recognized: Decimal
    revenue_to_date: Decimal
    unbilled_revenue: Decimal
    invoiced_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    recognition_method: RevenueRecognitionMethod
    recognition_percentage: float
    notes: str | None = None


class TimeEntryCreateSchema(BaseModel):
    """Schema untuk membuat time entry."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID = Field(..., description="Project ID")
    work_date: date = Field(default_factory=date.today, description="Tanggal kerja")
    hours: Decimal = Field(..., gt=0, decimal_places=2, description="Jam kerja")
    hourly_rate: Decimal = Field(..., gt=0, decimal_places=2, description="Tarif per jam")
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    is_billable: bool = Field(True, description="Dapat ditagih?")
    task_code: str | None = Field(None, max_length=50, description="Kode task")

    @property
    def total_amount(self) -> Decimal:
        return (self.hours * self.hourly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TimeEntryUpdateSchema(BaseModel):
    """Schema untuk update time entry."""

    model_config = ConfigDict(from_attributes=True)

    hours: Decimal | None = Field(None, gt=0, decimal_places=2)
    hourly_rate: Decimal | None = Field(None, gt=0, decimal_places=2)
    description: str | None = Field(None, max_length=500)
    status: TimeEntryStatus | None = None


class TimeEntryResponseSchema(BaseModel):
    """Response time entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    time_entry_number: str
    employee_id: UUID
    employee_name: str | None = None
    project_id: UUID
    project_code: str | None = None
    project_name: str | None = None
    work_date: date
    hours: Decimal
    hourly_rate: Decimal
    total_amount: Decimal
    description: str | None
    is_billable: bool
    task_code: str | None
    status: TimeEntryStatus
    is_billed: bool
    billed_invoice_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    version: int = 1


class RetainerContractCreateSchema(BaseModel):
    """Schema untuk membuat retainer contract."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID = Field(..., description="Customer ID")
    contract_number: str = Field(..., max_length=50, description="Nomor kontrak")
    monthly_fee: Decimal = Field(..., gt=0, decimal_places=2, description="Fee bulanan")
    start_date: date = Field(..., description="Tanggal mulai")
    end_date: date | None = Field(None, description="Tanggal selesai")
    max_hours_per_month: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Max jam per bulan"
    )
    hourly_rate_overtime: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Rate overtime"
    )
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("contract_number")
    @classmethod
    def validate_contract_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Contract number is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> RetainerContractCreateSchema:
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be after start date")
        return self


class RetainerContractResponseSchema(BaseModel):
    """Response retainer contract."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    contract_number: str
    monthly_fee: Decimal
    start_date: date
    end_date: date | None
    status: RetainerStatus
    max_hours_per_month: Decimal | None
    hourly_rate_overtime: Decimal | None
    total_invoiced: Decimal
    total_hours_used: Decimal
    remaining_hours: Decimal | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class MilestoneCreateSchema(BaseModel):
    """Schema untuk membuat milestone project."""

    model_config = ConfigDict(from_attributes=True)

    milestone_name: str = Field(..., max_length=200)
    milestone_order: int = Field(..., ge=1)
    percentage: Decimal = Field(..., gt=0, le=100, decimal_places=2)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    due_date: date = Field(..., description="Target date")
    description: str | None = Field(None, max_length=500)


class MilestoneResponseSchema(BaseModel):
    """Response milestone."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    milestone_name: str
    milestone_order: int
    percentage: Decimal
    amount: Decimal
    due_date: date
    completed_date: date | None = None
    is_completed: bool
    description: str | None
    created_at: datetime
    updated_at: datetime


class RevenueRecognitionRequestSchema(BaseModel):
    """Schema untuk pengakuan pendapatan."""

    model_config = ConfigDict(from_attributes=True)

    period_end_date: date = Field(..., description="Tanggal akhir periode")
    project_ids: list[UUID] | None = Field(None, description="Project IDs (kosong = semua)")
    calculate_only: bool = Field(False, description="Hitung saja, tidak posting")


class RevenueRecognitionResponseSchema(BaseModel):
    """Response pengakuan pendapatan."""

    model_config = ConfigDict(from_attributes=True)

    recognition_id: UUID
    project_id: UUID
    project_name: str
    period_end_date: date
    previous_recognized: Decimal
    current_recognized: Decimal
    total_recognized: Decimal
    remaining_revenue: Decimal
    journal_id: UUID | None = None
    status: str
    created_at: datetime


class ProjectDashboardResponseSchema(BaseModel):
    """Response project dashboard."""

    model_config = ConfigDict(from_attributes=True)

    total_projects: int
    active_projects: int
    on_hold_projects: int
    completed_projects: int
    total_budget: Decimal
    total_cost_to_date: Decimal
    total_revenue_recognized: Decimal
    total_profit: Decimal
    overall_profit_margin: float
    average_completion_percent: float
    projects_by_status: dict[str, int]
    projects_by_customer: list[dict[str, Any]]
    top_projects_by_revenue: list[dict[str, Any]]
    top_projects_by_cost: list[dict[str, Any]]
    as_of_date: date


class UtilizationReportSchema(BaseModel):
    """Response utilization report."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    total_employees: int
    total_available_hours: Decimal
    total_billed_hours: Decimal
    total_non_billed_hours: Decimal
    total_utilization_rate: float
    by_employee: list[dict[str, Any]]
    by_project: list[dict[str, Any]]


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_project_service(request: Request) -> Any:
    """Get Project Service instance."""
    from application.service_layer.service_project import ProjectService

    container = request.app.state.container
    return container.resolve(ProjectService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/projects", tags=["Projects & Services"])


# ----------------------------------------------------------------------------
# PROJECT CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=ProjectResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
    operation_id="create_project",
)
async def create_project(
    request: ProjectCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Create a new project."""
    method_name = "create_project"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ProjectResponseSchema(**cached)

    try:
        result = await service.create_project(
            project_code=request.project_code,
            project_name=request.project_name,
            customer_id=request.customer_id,
            start_date=request.start_date,
            end_date=request.end_date,
            contract_type=request.contract_type.value,
            contract_value=request.contract_value,
            currency_code=request.currency_code,
            budget_total=request.budget_total,
            manager_employee_id=request.manager_employee_id,
            revenue_recognition_method=request.revenue_recognition_method.value,
            billing_cycle_days=request.billing_cycle_days,
            notes=request.notes,
            tags=request.tags,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = ProjectResponseSchema(
            id=result.id,
            project_code=result.project_code,
            project_name=result.project_name,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            start_date=result.start_date,
            end_date=result.end_date,
            status=ProjectStatus(result.status),
            contract_type=ContractType(result.contract_type),
            contract_value=result.contract_value,
            currency_code=result.currency_code,
            budget_total=result.budget_total,
            cost_to_date=result.cost_to_date,
            revenue_to_date=result.revenue_to_date,
            recognized_revenue_to_date=result.recognized_revenue_to_date,
            unbilled_revenue=result.unbilled_revenue,
            profit_to_date=result.profit_to_date,
            profit_margin_percent=result.profit_margin_percent,
            completion_percent=result.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(result.revenue_recognition_method),
            billing_cycle_days=result.billing_cycle_days,
            manager_employee_id=result.manager_employee_id,
            manager_name=result.manager_name,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{project_id}",
    response_model=ProjectResponseSchema,
    summary="Get project by ID",
    operation_id="get_project",
)
async def get_project(
    project_id: UUID,
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Get project by ID."""
    try:
        project = await service.get_project_by_id(project_id, legal_entity_id)

        if not project:
            raise HTTPException(status_code=404, detail="Project not found")

        return ProjectResponseSchema(
            id=project.id,
            project_code=project.project_code,
            project_name=project.project_name,
            customer_id=project.customer_id,
            customer_name=project.customer_name,
            customer_code=project.customer_code,
            start_date=project.start_date,
            end_date=project.end_date,
            status=ProjectStatus(project.status),
            contract_type=ContractType(project.contract_type),
            contract_value=project.contract_value,
            currency_code=project.currency_code,
            budget_total=project.budget_total,
            cost_to_date=project.cost_to_date,
            revenue_to_date=project.revenue_to_date,
            recognized_revenue_to_date=project.recognized_revenue_to_date,
            unbilled_revenue=project.unbilled_revenue,
            profit_to_date=project.profit_to_date,
            profit_margin_percent=project.profit_margin_percent,
            completion_percent=project.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(project.revenue_recognition_method),
            billing_cycle_days=project.billing_cycle_days,
            manager_employee_id=project.manager_employee_id,
            manager_name=project.manager_name,
            notes=project.notes,
            tags=project.tags,
            is_locked=project.is_locked,
            created_at=project.created_at,
            updated_at=project.updated_at,
            created_by=project.created_by,
            created_by_name=project.created_by_name,
            version=project.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-code/{project_code}",
    response_model=ProjectResponseSchema,
    summary="Get project by code",
    operation_id="get_project_by_code",
)
async def get_project_by_code(
    project_code: str,
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Get project by project code."""
    try:
        project = await service.get_project_by_code(project_code, legal_entity_id)

        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project {project_code} not found",
            )

        return ProjectResponseSchema(
            id=project.id,
            project_code=project.project_code,
            project_name=project.project_name,
            customer_id=project.customer_id,
            customer_name=project.customer_name,
            customer_code=project.customer_code,
            start_date=project.start_date,
            end_date=project.end_date,
            status=ProjectStatus(project.status),
            contract_type=ContractType(project.contract_type),
            contract_value=project.contract_value,
            currency_code=project.currency_code,
            budget_total=project.budget_total,
            cost_to_date=project.cost_to_date,
            revenue_to_date=project.revenue_to_date,
            recognized_revenue_to_date=project.recognized_revenue_to_date,
            unbilled_revenue=project.unbilled_revenue,
            profit_to_date=project.profit_to_date,
            profit_margin_percent=project.profit_margin_percent,
            completion_percent=project.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(project.revenue_recognition_method),
            billing_cycle_days=project.billing_cycle_days,
            manager_employee_id=project.manager_employee_id,
            manager_name=project.manager_name,
            notes=project.notes,
            tags=project.tags,
            is_locked=project.is_locked,
            created_at=project.created_at,
            updated_at=project.updated_at,
            created_by=project.created_by,
            created_by_name=project.created_by_name,
            version=project.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get project by code: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{project_id}",
    response_model=ProjectResponseSchema,
    summary="Update project",
    operation_id="update_project",
)
async def update_project(
    project_id: UUID,
    request: ProjectUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Update project information."""
    method_name = "update_project"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ProjectResponseSchema(**cached)

    try:
        result = await service.update_project(
            project_id=project_id,
            project_name=request.project_name,
            end_date=request.end_date,
            status=request.status.value if request.status else None,
            budget_total=request.budget_total,
            manager_employee_id=request.manager_employee_id,
            notes=request.notes,
            tags=request.tags,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Project not found or cannot be updated")

        response = ProjectResponseSchema(
            id=result.id,
            project_code=result.project_code,
            project_name=result.project_name,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            start_date=result.start_date,
            end_date=result.end_date,
            status=ProjectStatus(result.status),
            contract_type=ContractType(result.contract_type),
            contract_value=result.contract_value,
            currency_code=result.currency_code,
            budget_total=result.budget_total,
            cost_to_date=result.cost_to_date,
            revenue_to_date=result.revenue_to_date,
            recognized_revenue_to_date=result.recognized_revenue_to_date,
            unbilled_revenue=result.unbilled_revenue,
            profit_to_date=result.profit_to_date,
            profit_margin_percent=result.profit_margin_percent,
            completion_percent=result.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(result.revenue_recognition_method),
            billing_cycle_days=result.billing_cycle_days,
            manager_employee_id=result.manager_employee_id,
            manager_name=result.manager_name,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{project_id}",
    response_model=dict[str, Any],
    summary="Close/cancel project",
    operation_id="close_project",
)
async def close_project(
    project_id: UUID,
    permanent: bool = Query(False, description="Permanent closure"),
    reason: str = Query("", description="Reason for closure"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> dict[str, Any]:
    """Close or cancel a project."""
    method_name = "close_project"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        if permanent:
            result = await service.delete_project(
                project_id, current_user.user_id, legal_entity_id, reason
            )
            action = "deleted"
        else:
            result = await service.close_project(
                project_id, current_user.user_id, legal_entity_id, reason
            )
            action = "closed"

        if not result:
            raise HTTPException(status_code=404, detail="Project not found")

        response = {
            "project_id": str(project_id),
            "project_code": result.project_code,
            "action": action,
            "status": result.status,
            "message": f"Project {action} successfully",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{project_id}/activate",
    response_model=ProjectResponseSchema,
    summary="Activate project",
    operation_id="activate_project",
)
async def activate_project(
    project_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Activate a project (change status to ACTIVE)."""
    method_name = "activate_project"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ProjectResponseSchema(**cached)

    try:
        result = await service.activate_project(project_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Project not found or cannot be activated")

        response = ProjectResponseSchema(
            id=result.id,
            project_code=result.project_code,
            project_name=result.project_name,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            start_date=result.start_date,
            end_date=result.end_date,
            status=ProjectStatus(result.status),
            contract_type=ContractType(result.contract_type),
            contract_value=result.contract_value,
            currency_code=result.currency_code,
            budget_total=result.budget_total,
            cost_to_date=result.cost_to_date,
            revenue_to_date=result.revenue_to_date,
            recognized_revenue_to_date=result.recognized_revenue_to_date,
            unbilled_revenue=result.unbilled_revenue,
            profit_to_date=result.profit_to_date,
            profit_margin_percent=result.profit_margin_percent,
            completion_percent=result.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(result.revenue_recognition_method),
            billing_cycle_days=result.billing_cycle_days,
            manager_employee_id=result.manager_employee_id,
            manager_name=result.manager_name,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to activate project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{project_id}/suspend",
    response_model=ProjectResponseSchema,
    summary="Suspend project",
    operation_id="suspend_project",
)
async def suspend_project(
    project_id: UUID,
    reason: str = Query(..., description="Suspension reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectResponseSchema:
    """Suspend a project (change status to ON_HOLD)."""
    method_name = "suspend_project"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return ProjectResponseSchema(**cached)

    try:
        result = await service.suspend_project(
            project_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Project not found or cannot be suspended")

        response = ProjectResponseSchema(
            id=result.id,
            project_code=result.project_code,
            project_name=result.project_name,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            start_date=result.start_date,
            end_date=result.end_date,
            status=ProjectStatus(result.status),
            contract_type=ContractType(result.contract_type),
            contract_value=result.contract_value,
            currency_code=result.currency_code,
            budget_total=result.budget_total,
            cost_to_date=result.cost_to_date,
            revenue_to_date=result.revenue_to_date,
            recognized_revenue_to_date=result.recognized_revenue_to_date,
            unbilled_revenue=result.unbilled_revenue,
            profit_to_date=result.profit_to_date,
            profit_margin_percent=result.profit_margin_percent,
            completion_percent=result.completion_percent,
            revenue_recognition_method=RevenueRecognitionMethod(result.revenue_recognition_method),
            billing_cycle_days=result.billing_cycle_days,
            manager_employee_id=result.manager_employee_id,
            manager_name=result.manager_name,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to suspend project: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST PROJECTS
# ----------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[ProjectResponseSchema],
    summary="List projects",
    operation_id="list_projects",
)
async def list_projects(
    customer_id: UUID | None = Query(None, description="Filter by customer"),
    status: ProjectStatus | None = Query(None, description="Filter by status"),
    manager_id: UUID | None = Query(None, description="Filter by project manager"),
    start_date_from: date | None = Query(None, description="Start date from"),
    start_date_to: date | None = Query(None, description="Start date to"),
    search: str | None = Query(None, description="Search in code or name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> list[ProjectResponseSchema]:
    """List projects with pagination and filters."""
    try:
        result = await service.list_projects(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status.value if status else None,
            manager_id=manager_id,
            start_date_from=start_date_from,
            start_date_to=start_date_to,
            search=search,
            page=page,
            page_size=page_size,
        )

        return [
            ProjectResponseSchema(
                id=p.id,
                project_code=p.project_code,
                project_name=p.project_name,
                customer_id=p.customer_id,
                customer_name=p.customer_name,
                customer_code=p.customer_code,
                start_date=p.start_date,
                end_date=p.end_date,
                status=ProjectStatus(p.status),
                contract_type=ContractType(p.contract_type),
                contract_value=p.contract_value,
                currency_code=p.currency_code,
                budget_total=p.budget_total,
                cost_to_date=p.cost_to_date,
                revenue_to_date=p.revenue_to_date,
                recognized_revenue_to_date=p.recognized_revenue_to_date,
                unbilled_revenue=p.unbilled_revenue,
                profit_to_date=p.profit_to_date,
                profit_margin_percent=p.profit_margin_percent,
                completion_percent=p.completion_percent,
                revenue_recognition_method=RevenueRecognitionMethod(p.revenue_recognition_method),
                billing_cycle_days=p.billing_cycle_days,
                manager_employee_id=p.manager_employee_id,
                manager_name=p.manager_name,
                notes=p.notes,
                tags=p.tags,
                is_locked=p.is_locked,
                created_at=p.created_at,
                updated_at=p.updated_at,
                created_by=p.created_by,
                created_by_name=p.created_by_name,
                version=p.version,
            )
            for p in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list projects: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PROJECT COSTS & FINANCIALS
# ----------------------------------------------------------------------------


@router.get(
    "/{project_id}/cost",
    response_model=ProjectCostResponseSchema,
    summary="Get project cost breakdown",
    operation_id="get_project_cost",
)
async def get_project_cost(
    project_id: UUID,
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectCostResponseSchema:
    """Get project cost breakdown by category and period."""
    try:
        cost = await service.get_project_cost(project_id, legal_entity_id, as_of_date)

        if not cost:
            raise HTTPException(status_code=404, detail="Project not found")

        return ProjectCostResponseSchema(
            project_id=cost.project_id,
            project_code=cost.project_code,
            project_name=cost.project_name,
            as_of_date=as_of_date,
            labor_cost=cost.labor_cost,
            material_cost=cost.material_cost,
            equipment_cost=cost.equipment_cost,
            subcontractor_cost=cost.subcontractor_cost,
            overhead_cost=cost.overhead_cost,
            other_cost=cost.other_cost,
            total_cost=cost.total_cost,
            budget_variance=cost.budget_variance,
            cost_by_category=cost.cost_by_category,
            cost_by_period=cost.cost_by_period,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get project cost: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{project_id}/revenue",
    response_model=ProjectRevenueResponseSchema,
    summary="Get project revenue details",
    operation_id="get_project_revenue",
)
async def get_project_revenue(
    project_id: UUID,
    period_start: date = Query(..., description="Period start"),
    period_end: date = Query(..., description="Period end"),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectRevenueResponseSchema:
    """Get project revenue details for a period."""
    try:
        revenue = await service.get_project_revenue(
            project_id=project_id,
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )

        if not revenue:
            raise HTTPException(status_code=404, detail="Project not found")

        return ProjectRevenueResponseSchema(
            project_id=revenue.project_id,
            project_code=revenue.project_code,
            project_name=revenue.project_name,
            period_start=period_start,
            period_end=period_end,
            contract_value=revenue.contract_value,
            revenue_recognized=revenue.revenue_recognized,
            revenue_to_date=revenue.revenue_to_date,
            unbilled_revenue=revenue.unbilled_revenue,
            invoiced_amount=revenue.invoiced_amount,
            paid_amount=revenue.paid_amount,
            outstanding_amount=revenue.outstanding_amount,
            recognition_method=RevenueRecognitionMethod(revenue.recognition_method),
            recognition_percentage=revenue.recognition_percentage,
            notes=revenue.notes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get project revenue: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TIME ENTRIES
# ----------------------------------------------------------------------------


@router.post(
    "/time-entries",
    response_model=TimeEntryResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create time entry",
    operation_id="create_time_entry",
)
async def create_time_entry(
    request: TimeEntryCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:time_entry")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> TimeEntryResponseSchema:
    """Create a time entry for an employee."""
    method_name = "create_time_entry"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return TimeEntryResponseSchema(**cached)

    try:
        result = await service.create_time_entry(
            project_id=request.project_id,
            work_date=request.work_date,
            hours=request.hours,
            hourly_rate=request.hourly_rate,
            description=request.description,
            is_billable=request.is_billable,
            task_code=request.task_code,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = TimeEntryResponseSchema(
            id=result.id,
            time_entry_number=result.time_entry_number,
            employee_id=result.employee_id,
            employee_name=result.employee_name,
            project_id=result.project_id,
            project_code=result.project_code,
            project_name=result.project_name,
            work_date=result.work_date,
            hours=result.hours,
            hourly_rate=result.hourly_rate,
            total_amount=result.total_amount,
            description=result.description,
            is_billable=result.is_billable,
            task_code=result.task_code,
            status=TimeEntryStatus(result.status),
            is_billed=result.is_billed,
            billed_invoice_id=result.billed_invoice_id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create time entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/time-entries",
    response_model=list[TimeEntryResponseSchema],
    summary="List time entries",
    operation_id="list_time_entries",
)
async def list_time_entries(
    project_id: UUID | None = Query(None, description="Filter by project"),
    employee_id: UUID | None = Query(None, description="Filter by employee"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    status: TimeEntryStatus | None = Query(None, description="Filter by status"),
    is_billed: bool | None = Query(None, description="Filter by billed status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> list[TimeEntryResponseSchema]:
    """List time entries with filters."""
    try:
        result = await service.list_time_entries(
            legal_entity_id=legal_entity_id,
            project_id=project_id,
            employee_id=employee_id,
            start_date=start_date,
            end_date=end_date,
            status=status.value if status else None,
            is_billed=is_billed,
            page=page,
            page_size=page_size,
        )

        return [
            TimeEntryResponseSchema(
                id=t.id,
                time_entry_number=t.time_entry_number,
                employee_id=t.employee_id,
                employee_name=t.employee_name,
                project_id=t.project_id,
                project_code=t.project_code,
                project_name=t.project_name,
                work_date=t.work_date,
                hours=t.hours,
                hourly_rate=t.hourly_rate,
                total_amount=t.total_amount,
                description=t.description,
                is_billable=t.is_billable,
                task_code=t.task_code,
                status=TimeEntryStatus(t.status),
                is_billed=t.is_billed,
                billed_invoice_id=t.billed_invoice_id,
                created_at=t.created_at,
                updated_at=t.updated_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
                approved_at=t.approved_at,
                approved_by=t.approved_by,
                approved_by_name=t.approved_by_name,
                rejected_at=t.rejected_at,
                rejection_reason=t.rejection_reason,
                version=t.version,
            )
            for t in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list time entries: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/time-entries/{time_entry_id}",
    response_model=TimeEntryResponseSchema,
    summary="Update time entry",
    operation_id="update_time_entry",
)
async def update_time_entry(
    time_entry_id: UUID,
    request: TimeEntryUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:time_entry")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> TimeEntryResponseSchema:
    """Update a time entry (only DRAFT or REJECTED)."""
    method_name = "update_time_entry"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return TimeEntryResponseSchema(**cached)

    try:
        result = await service.update_time_entry(
            time_entry_id=time_entry_id,
            hours=request.hours,
            hourly_rate=request.hourly_rate,
            description=request.description,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Time entry not found or cannot be updated")

        response = TimeEntryResponseSchema(
            id=result.id,
            time_entry_number=result.time_entry_number,
            employee_id=result.employee_id,
            employee_name=result.employee_name,
            project_id=result.project_id,
            project_code=result.project_code,
            project_name=result.project_name,
            work_date=result.work_date,
            hours=result.hours,
            hourly_rate=result.hourly_rate,
            total_amount=result.total_amount,
            description=result.description,
            is_billable=result.is_billable,
            task_code=result.task_code,
            status=TimeEntryStatus(result.status),
            is_billed=result.is_billed,
            billed_invoice_id=result.billed_invoice_id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update time entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/time-entries/{time_entry_id}/approve",
    response_model=TimeEntryResponseSchema,
    summary="Approve time entry",
    operation_id="approve_time_entry",
)
async def approve_time_entry(
    time_entry_id: UUID,
    notes: str = Query("", description="Approval notes"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:time_entry_approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> TimeEntryResponseSchema:
    """Approve a submitted time entry."""
    method_name = "approve_time_entry"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return TimeEntryResponseSchema(**cached)

    try:
        result = await service.approve_time_entry(
            time_entry_id=time_entry_id,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=notes,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Time entry not found or cannot be approved"
            )

        response = TimeEntryResponseSchema(
            id=result.id,
            time_entry_number=result.time_entry_number,
            employee_id=result.employee_id,
            employee_name=result.employee_name,
            project_id=result.project_id,
            project_code=result.project_code,
            project_name=result.project_name,
            work_date=result.work_date,
            hours=result.hours,
            hourly_rate=result.hourly_rate,
            total_amount=result.total_amount,
            description=result.description,
            is_billable=result.is_billable,
            task_code=result.task_code,
            status=TimeEntryStatus(result.status),
            is_billed=result.is_billed,
            billed_invoice_id=result.billed_invoice_id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve time entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/time-entries/{time_entry_id}/reject",
    response_model=TimeEntryResponseSchema,
    summary="Reject time entry",
    operation_id="reject_time_entry",
)
async def reject_time_entry(
    time_entry_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:time_entry_approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> TimeEntryResponseSchema:
    """Reject a submitted time entry."""
    method_name = "reject_time_entry"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return TimeEntryResponseSchema(**cached)

    try:
        result = await service.reject_time_entry(
            time_entry_id=time_entry_id,
            rejector_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Time entry not found or cannot be rejected"
            )

        response = TimeEntryResponseSchema(
            id=result.id,
            time_entry_number=result.time_entry_number,
            employee_id=result.employee_id,
            employee_name=result.employee_name,
            project_id=result.project_id,
            project_code=result.project_code,
            project_name=result.project_name,
            work_date=result.work_date,
            hours=result.hours,
            hourly_rate=result.hourly_rate,
            total_amount=result.total_amount,
            description=result.description,
            is_billable=result.is_billable,
            task_code=result.task_code,
            status=TimeEntryStatus(result.status),
            is_billed=result.is_billed,
            billed_invoice_id=result.billed_invoice_id,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejection_reason=result.rejection_reason,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reject time entry: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# RETAINER CONTRACTS
# ----------------------------------------------------------------------------


@router.post(
    "/retainers",
    response_model=RetainerContractResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create retainer contract",
    operation_id="create_retainer_contract",
)
async def create_retainer_contract(
    request: RetainerContractCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> RetainerContractResponseSchema:
    """Create a retainer contract for a customer."""
    method_name = "create_retainer_contract"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return RetainerContractResponseSchema(**cached)

    try:
        result = await service.create_retainer_contract(
            customer_id=request.customer_id,
            contract_number=request.contract_number,
            monthly_fee=request.monthly_fee,
            start_date=request.start_date,
            end_date=request.end_date,
            max_hours_per_month=request.max_hours_per_month,
            hourly_rate_overtime=request.hourly_rate_overtime,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = RetainerContractResponseSchema(
            id=result.id,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            contract_number=result.contract_number,
            monthly_fee=result.monthly_fee,
            start_date=result.start_date,
            end_date=result.end_date,
            status=RetainerStatus(result.status),
            max_hours_per_month=result.max_hours_per_month,
            hourly_rate_overtime=result.hourly_rate_overtime,
            total_invoiced=result.total_invoiced,
            total_hours_used=result.total_hours_used,
            remaining_hours=result.remaining_hours,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create retainer contract: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REVENUE RECOGNITION
# ----------------------------------------------------------------------------


@router.post(
    "/recognize-revenue",
    response_model=list[RevenueRecognitionResponseSchema],
    status_code=status.HTTP_201_CREATED,
    summary="Recognize revenue for projects",
    operation_id="recognize_revenue",
)
async def recognize_revenue(
    request: RevenueRecognitionRequestSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("project:revenue")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> list[RevenueRecognitionResponseSchema]:
    """Recognize revenue for projects based on recognition method."""
    method_name = "recognize_revenue"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return [RevenueRecognitionResponseSchema(**item) for item in cached]

    try:
        results = await service.recognize_revenue(
            legal_entity_id=legal_entity_id,
            period_end_date=request.period_end_date,
            project_ids=request.project_ids,
            calculate_only=request.calculate_only,
            processed_by=current_user.user_id,
        )

        response_list = [
            RevenueRecognitionResponseSchema(
                recognition_id=r.id,
                project_id=r.project_id,
                project_name=r.project_name,
                period_end_date=request.period_end_date,
                previous_recognized=r.previous_recognized,
                current_recognized=r.current_recognized,
                total_recognized=r.total_recognized,
                remaining_revenue=r.remaining_revenue,
                journal_id=r.journal_id,
                status=r.status,
                created_at=r.created_at,
            )
            for r in results
        ]

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, [item.model_dump() for item in response_list]
            )

        return response_list
    except Exception as e:
        logger.exception("Failed to recognize revenue: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PROJECT DASHBOARD
# ----------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=ProjectDashboardResponseSchema,
    summary="Get project dashboard",
    operation_id="get_project_dashboard",
)
async def get_project_dashboard(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> ProjectDashboardResponseSchema:
    """Get project dashboard with key metrics."""
    try:
        dashboard = await service.get_project_dashboard(legal_entity_id, as_of_date)

        return ProjectDashboardResponseSchema(
            total_projects=dashboard.total_projects,
            active_projects=dashboard.active_projects,
            on_hold_projects=dashboard.on_hold_projects,
            completed_projects=dashboard.completed_projects,
            total_budget=dashboard.total_budget,
            total_cost_to_date=dashboard.total_cost_to_date,
            total_revenue_recognized=dashboard.total_revenue_recognized,
            total_profit=dashboard.total_profit,
            overall_profit_margin=dashboard.overall_profit_margin,
            average_completion_percent=dashboard.average_completion_percent,
            projects_by_status=dashboard.projects_by_status,
            projects_by_customer=dashboard.projects_by_customer,
            top_projects_by_revenue=dashboard.top_projects_by_revenue,
            top_projects_by_cost=dashboard.top_projects_by_cost,
            as_of_date=as_of_date,
        )
    except Exception as e:
        logger.exception("Failed to get project dashboard: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# UTILIZATION REPORT
# ----------------------------------------------------------------------------


@router.get(
    "/utilization",
    response_model=UtilizationReportSchema,
    summary="Get employee utilization report",
    operation_id="get_utilization_report",
)
async def get_utilization_report(
    period_start: date = Query(..., description="Period start"),
    period_end: date = Query(..., description="Period end"),
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> UtilizationReportSchema:
    """Get employee utilization report (billable hours vs available)."""
    try:
        report = await service.get_utilization_report(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
        )

        return UtilizationReportSchema(
            period_start=period_start,
            period_end=period_end,
            total_employees=report.total_employees,
            total_available_hours=report.total_available_hours,
            total_billed_hours=report.total_billed_hours,
            total_non_billed_hours=report.total_non_billed_hours,
            total_utilization_rate=report.total_utilization_rate,
            by_employee=report.by_employee,
            by_project=report.by_project,
        )
    except Exception as e:
        logger.exception("Failed to get utilization report: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PROJECT HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/{project_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get project history",
    operation_id="get_project_history",
)
async def get_project_history(
    project_id: UUID,
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> list[dict[str, Any]]:
    """Get project change history (audit trail)."""
    try:
        history = await service.get_project_history(project_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "from_status": h.from_status,
                "to_status": h.to_status,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
                "notes": h.notes,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get project history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{project_id}/status",
    response_model=dict[str, Any],
    summary="Get project status",
    operation_id="get_project_status",
)
async def get_project_status(
    project_id: UUID,
    _permission: None = Depends(require_permission("project:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> dict[str, Any]:
    """Get detailed project status including workflow state."""
    try:
        status_info = await service.get_project_status(project_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Project not found")

        return {
            "project_id": str(project_id),
            "project_code": status_info.project_code,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_activate": status_info.can_activate,
            "can_suspend": status_info.can_suspend,
            "can_close": status_info.can_close,
            "can_cancel": status_info.can_cancel,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "completion_percent": status_info.completion_percent,
            "on_track": status_info.on_track,
            "days_remaining": status_info.days_remaining,
            "budget_remaining": float(status_info.budget_remaining)
            if status_info.budget_remaining
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get project status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export projects",
    operation_id="export_projects",
)
async def export_projects(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: ProjectStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("project:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_project_service),
) -> Response:
    """Export projects to CSV or Excel."""
    try:
        data = await service.export_projects(
            legal_entity_id=legal_entity_id,
            format=format,
            status=status.value if status else None,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"projects_{legal_entity_id}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export projects: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
