#!/usr/bin/env python3
"""
Module: fastapi_budget_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk manajemen anggaran (budget):
               budget header, budget lines per akun, budget versions, budget vs actual analysis,
               budget approval workflow, rolling forecast, budget transfer, dan laporan varians.

Method Standards (ERP):
- create_budget() / update_budget() / delete_budget() / get_budget()
- submit_budget() / approve_budget() / reject_budget()
- activate_budget() / deactivate_budget() / lock_budget() / unlock_budget()
- create_budget_version() / compare_versions()
- get_budget_vs_actual() / get_budget_variance()
- calculate_consumption() / get_remaining_budget()
- transfer_budget() / reallocate_budget()
- get_budget_status() / get_budget_history()
- get_budget_summary() / get_budget_dashboard()
- audit_trail_budget() / can_transition_budget()
- register_budget_event() / get_budget_events()
- version_budget()
"""


from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
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
# IDEMPOTENCY MANAGER
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
        if (datetime.now(UTC) - timestamp).total_seconds() > self._ttl_seconds:
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
        self._storage[storage_key] = (result_json, datetime.now(UTC))


# Global instance
_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class BudgetStatus(str, Enum):
    """Status budget."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    LOCKED = "locked"
    ARCHIVED = "archived"
    EXPIRED = "expired"


class BudgetType(str, Enum):
    """Jenis budget."""
    OPERATIONAL = "operational"     # Budget operasional
    CAPITAL = "capital"             # Budget modal (CAPEX)
    CASH = "cash"                   # Budget kas
    PROJECT = "project"             # Budget project
    DEPARTMENT = "department"       # Budget departemen
    FIXED_ASSET = "fixed_asset"     # Budget aset tetap
    SALES = "sales"                 # Budget penjualan
    PRODUCTION = "production"       # Budget produksi
    LABOR = "labor"                 # Budget tenaga kerja


class BudgetPeriod(str, Enum):
    """Periode budget."""
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class VarianceType(str, Enum):
    """Jenis varians."""
    FAVORABLE = "favorable"         # Menguntungkan (actual < budget untuk expense, > untuk revenue)
    UNFAVORABLE = "unfavorable"     # Tidak menguntungkan
    NEUTRAL = "neutral"             # Netral (tidak ada perbedaan signifikan)


# Default budget settings
DEFAULT_VARIANCE_THRESHOLD_PERCENT = Decimal("5")  # 5% threshold for alert
DEFAULT_CURRENCY = "IDR"
MAX_BUDGET_VERSIONS = 10


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class BudgetLineSchema(BaseModel):
    """Line dalam budget per akun."""
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID = Field(..., description="ID akun")
    account_code: str | None = Field(None, description="Kode akun (optional)")
    amount: Decimal = Field(..., ge=0, decimal_places=2, description="Jumlah budget")
    note: str | None = Field(None, max_length=500, description="Catatan line")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("Amount cannot be negative")
        return v


class BudgetCreateSchema(BaseModel):
    """Schema untuk membuat budget baru."""
    model_config = ConfigDict(from_attributes=True)

    budget_code: str = Field(..., min_length=3, max_length=50, description="Kode budget")
    budget_name: str = Field(..., min_length=3, max_length=200, description="Nama budget")
    budget_type: BudgetType = Field(BudgetType.OPERATIONAL, description="Jenis budget")
    fiscal_year: int = Field(..., ge=2000, le=2100, description="Tahun fiskal")
    period: BudgetPeriod = Field(BudgetPeriod.MONTHLY, description="Periode budget")
    version: str = Field("1.0", description="Versi budget")
    effective_date: date = Field(default_factory=date.today, description="Tanggal berlaku")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")
    currency: str = Field(DEFAULT_CURRENCY, min_length=3, max_length=3, description="Mata uang")
    lines: list[BudgetLineSchema] = Field(..., min_length=1, description="Line items")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    tags: list[str] | None = Field(None, description="Tags")

    @field_validator("budget_code")
    @classmethod
    def validate_budget_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Budget code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_dates(self) -> BudgetCreateSchema:
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("Expiry date must be after effective date")
        return self

    @property
    def total_amount(self) -> Decimal:
        return sum(line.amount for line in self.lines)


class BudgetUpdateSchema(BaseModel):
    """Schema untuk update budget."""
    model_config = ConfigDict(from_attributes=True)

    budget_name: str | None = Field(None, min_length=3, max_length=200)
    effective_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = Field(None, max_length=500)
    tags: list[str] | None = None
    status: BudgetStatus | None = None


class BudgetLineUpdateSchema(BaseModel):
    """Schema untuk update line budget."""
    model_config = ConfigDict(from_attributes=True)

    line_id: UUID
    amount: Decimal = Field(..., ge=0, decimal_places=2)
    note: str | None = Field(None, max_length=500)


class BudgetResponseSchema(BaseModel):
    """Response budget."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    budget_code: str
    budget_name: str
    budget_type: BudgetType
    fiscal_year: int
    period: BudgetPeriod
    version: str                          # Hanya satu field 'version' (string)
    status: BudgetStatus
    effective_date: date
    expiry_date: date | None
    currency: str
    total_amount: Decimal
    actual_amount_ytd: Decimal = Decimal(0)
    variance_amount: Decimal = Decimal(0)
    variance_percent: float = 0.0
    consumption_percent: float = 0.0
    notes: str | None
    tags: list[str] | None
    is_locked: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    # revision integer dihapus karena duplikat; jika diperlukan, tambahkan sebagai field terpisah
    lines: list[dict[str, Any]] = []


class BudgetVersionResponseSchema(BaseModel):
    """Response versi budget."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    budget_code: str
    version: str
    status: BudgetStatus
    total_amount: Decimal
    effective_date: date
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class BudgetTransferSchema(BaseModel):
    """Schema untuk transfer budget antar akun."""
    model_config = ConfigDict(from_attributes=True)

    from_account_id: UUID = Field(..., description="Akun sumber")
    to_account_id: UUID = Field(..., description="Akun tujuan")
    amount: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah transfer")
    reason: str = Field(..., min_length=5, max_length=500, description="Alasan transfer")
    effective_date: date = Field(default_factory=date.today, description="Tanggal efektif")

    @model_validator(mode="after")
    def validate_accounts(self) -> BudgetTransferSchema:
        if self.from_account_id == self.to_account_id:
            raise ValueError("Source and destination accounts must be different")
        return self


class BudgetTransferResponseSchema(BaseModel):
    """Response transfer budget."""
    model_config = ConfigDict(from_attributes=True)

    transfer_id: UUID
    budget_id: UUID
    from_account_id: UUID
    from_account_code: str
    from_account_name: str
    to_account_id: UUID
    to_account_code: str
    to_account_name: str
    amount: Decimal
    reason: str
    effective_date: date
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None


class BudgetVsActualLineSchema(BaseModel):
    """Line budget vs actual."""
    model_config = ConfigDict(from_attributes=True)

    account_id: UUID
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    variance_amount: Decimal
    variance_percent: float
    variance_type: VarianceType
    consumption_percent: float
    remaining_budget: Decimal


class BudgetVsActualResponseSchema(BaseModel):
    """Response budget vs actual."""
    model_config = ConfigDict(from_attributes=True)

    budget_id: UUID
    budget_name: str
    fiscal_year: int
    period: int  # 0 = YTD, 1-12 = specific month
    period_name: str
    total_budget: Decimal
    total_actual: Decimal
    total_variance: Decimal
    variance_percent: float
    variance_type: VarianceType
    consumption_rate: float
    remaining_budget: Decimal
    lines: list[BudgetVsActualLineSchema]
    generated_at: datetime


class BudgetDashboardResponseSchema(BaseModel):
    """Response dashboard budget."""
    model_config = ConfigDict(from_attributes=True)

    as_of_date: date
    total_budgets: int
    active_budgets: int
    total_budget_amount: Decimal
    total_actual_ytd: Decimal
    total_variance: Decimal
    overall_consumption_rate: float
    by_type: dict[str, dict[str, Any]]
    by_status: dict[str, int]
    top_variance_items: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    generated_at: datetime


class BudgetAlertSchema(BaseModel):
    """Schema alert budget."""
    model_config = ConfigDict(from_attributes=True)

    budget_id: UUID
    budget_name: str
    account_id: UUID
    account_code: str
    account_name: str
    budget_amount: Decimal
    actual_amount: Decimal
    consumption_percent: float
    threshold_percent: float
    message: str
    severity: str  # warning, critical
    created_at: datetime


class BudgetRollingForecastSchema(BaseModel):
    """Schema untuk rolling forecast."""
    model_config = ConfigDict(from_attributes=True)

    base_budget_id: UUID = Field(..., description="Budget ID sebagai basis")
    forecast_months: int = Field(..., ge=1, le=12, description="Jumlah bulan forecast")
    adjustment_factors: dict[int, Decimal] | None = Field(None, description="Faktor adjustment per bulan")
    notes: str | None = Field(None, max_length=500)


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_budget_service(request: Request, ) -> Any:
    """Get Budget Service instance."""

    from application.service_layer.service_budget import BudgetService

    container = request.app.state.container
    return container.resolve(BudgetService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/budget", tags=["Budget"])


# ----------------------------------------------------------------------------
# BUDGET CRUD OPERATIONS
# ----------------------------------------------------------------------------

@router.post(
    "/",
    response_model=BudgetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new budget",
    operation_id="create_budget",
)
async def create_budget(
    request: BudgetCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Create a new budget."""
    method_name = "create_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    from application.dto_objects.budget_request import BudgetCreateRequest

    try:
        dto = BudgetCreateRequest(
            budget_code=request.budget_code,
            budget_name=request.budget_name,
            budget_type=request.budget_type.value,
            fiscal_year=request.fiscal_year,
            period=request.period.value,
            version=request.version,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            currency=request.currency,
            lines=[{"account_id": line.account_id, "amount": line.amount, "note": line.note} for line in request.lines],
            notes=request.notes,
            tags=request.tags,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.create_budget(dto)

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{budget_id}",
    response_model=BudgetResponseSchema,
    summary="Get budget by ID",
    operation_id="get_budget",
)
async def get_budget(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Get budget by ID."""
    try:
        budget = await service.get_budget_by_id(budget_id, legal_entity_id)

        if not budget:
            raise HTTPException(status_code=404, detail="Budget not found")

        return BudgetResponseSchema(
            id=budget.id,
            budget_code=budget.budget_code,
            budget_name=budget.budget_name,
            budget_type=BudgetType(budget.budget_type),
            fiscal_year=budget.fiscal_year,
            period=BudgetPeriod(budget.period),
            version=budget.version,
            status=BudgetStatus(budget.status),
            effective_date=budget.effective_date,
            expiry_date=budget.expiry_date,
            currency=budget.currency,
            total_amount=budget.total_amount,
            actual_amount_ytd=budget.actual_amount_ytd,
            variance_amount=budget.variance_amount,
            variance_percent=budget.variance_percent,
            consumption_percent=budget.consumption_percent,
            notes=budget.notes,
            tags=budget.tags,
            is_locked=budget.is_locked,
            created_at=budget.created_at,
            updated_at=budget.updated_at,
            created_by=budget.created_by,
            created_by_name=budget.created_by_name,
            approved_at=budget.approved_at,
            approved_by=budget.approved_by,
            approved_by_name=budget.approved_by_name,
            lines=budget.lines,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-code/{budget_code}",
    response_model=BudgetResponseSchema,
    summary="Get budget by code",
    operation_id="get_budget_by_code",
)
async def get_budget_by_code(
    budget_code: str,
    fiscal_year: int = Query(..., description="Fiscal year"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Get budget by budget code and fiscal year."""
    try:
        budget = await service.get_budget_by_code(budget_code, fiscal_year, legal_entity_id)

        if not budget:
            raise HTTPException(
                status_code=404,
                detail=f"Budget {budget_code} not found for fiscal year {fiscal_year}"
            )

        return BudgetResponseSchema(
            id=budget.id,
            budget_code=budget.budget_code,
            budget_name=budget.budget_name,
            budget_type=BudgetType(budget.budget_type),
            fiscal_year=budget.fiscal_year,
            period=BudgetPeriod(budget.period),
            version=budget.version,
            status=BudgetStatus(budget.status),
            effective_date=budget.effective_date,
            expiry_date=budget.expiry_date,
            currency=budget.currency,
            total_amount=budget.total_amount,
            actual_amount_ytd=budget.actual_amount_ytd,
            variance_amount=budget.variance_amount,
            variance_percent=budget.variance_percent,
            consumption_percent=budget.consumption_percent,
            notes=budget.notes,
            tags=budget.tags,
            is_locked=budget.is_locked,
            created_at=budget.created_at,
            updated_at=budget.updated_at,
            created_by=budget.created_by,
            created_by_name=budget.created_by_name,
            approved_at=budget.approved_at,
            approved_by=budget.approved_by,
            approved_by_name=budget.approved_by_name,
            lines=budget.lines,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get budget by code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{budget_id}",
    response_model=BudgetResponseSchema,
    summary="Update budget (only DRAFT status)",
    operation_id="update_budget",
)
async def update_budget(
    budget_id: UUID,
    request: BudgetUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Update budget information (only DRAFT or REJECTED status)."""
    method_name = "update_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    from application.dto_objects.budget_request import BudgetUpdateRequest

    try:
        dto = BudgetUpdateRequest(
            id=budget_id,
            budget_name=request.budget_name,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            notes=request.notes,
            tags=request.tags,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.update_budget(dto)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be updated")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch(
    "/{budget_id}/lines",
    response_model=BudgetResponseSchema,
    summary="Update budget lines",
    operation_id="update_budget_lines",
)
async def update_budget_lines(
    budget_id: UUID,
    lines: list[BudgetLineUpdateSchema] = Body(..., description="Updated lines"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Update budget line amounts (only DRAFT status)."""
    method_name = "update_budget_lines"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    from application.dto_objects.budget_request import BudgetLineUpdateRequest

    try:
        line_dtos = [
            BudgetLineUpdateRequest(
                line_id=line.line_id,
                amount=line.amount,
                note=line.note,
            )
            for line in lines
        ]

        result = await service.update_budget_lines(
            budget_id=budget_id,
            lines=line_dtos,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be updated")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to update budget lines: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{budget_id}",
    response_model=dict[str, Any],
    summary="Archive budget",
    operation_id="archive_budget",
)
async def archive_budget(
    budget_id: UUID,
    reason: str = Query("", description="Reason for archiving"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> dict[str, Any]:
    """Archive a budget (soft delete)."""
    method_name = "archive_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await service.archive_budget(budget_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found")

        response = {
            "budget_id": str(budget_id),
            "budget_code": result.budget_code,
            "status": result.status,
            "message": "Budget archived",
        }

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to archive budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET WORKFLOW (submit, approve, reject, activate)
# ----------------------------------------------------------------------------

@router.post(
    "/{budget_id}/submit",
    response_model=BudgetResponseSchema,
    summary="Submit budget for approval",
    operation_id="submit_budget",
)
async def submit_budget(
    budget_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Submit budget for approval workflow."""
    method_name = "submit_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.submit_budget(budget_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be submitted")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to submit budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/approve",
    response_model=BudgetResponseSchema,
    summary="Approve budget",
    operation_id="approve_budget",
)
async def approve_budget(
    budget_id: UUID,
    notes: str = Query("", description="Approval notes"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Approve a submitted budget."""
    method_name = "approve_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.approve_budget(budget_id, current_user.user_id, legal_entity_id, notes)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be approved")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to approve budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/reject",
    response_model=BudgetResponseSchema,
    summary="Reject budget",
    operation_id="reject_budget",
)
async def reject_budget(
    budget_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Reject a submitted budget."""
    method_name = "reject_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.reject_budget(budget_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be rejected")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reject budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/activate",
    response_model=BudgetResponseSchema,
    summary="Activate budget",
    operation_id="activate_budget",
)
async def activate_budget(
    budget_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:activate")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Activate an approved budget (make it effective)."""
    method_name = "activate_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.activate_budget(budget_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found or cannot be activated")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to activate budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/lock",
    response_model=BudgetResponseSchema,
    summary="Lock budget",
    operation_id="lock_budget",
)
async def lock_budget(
    budget_id: UUID,
    reason: str = Query("", description="Lock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Lock a budget to prevent modifications."""
    method_name = "lock_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.lock_budget(budget_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=True,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/unlock",
    response_model=BudgetResponseSchema,
    summary="Unlock budget",
    operation_id="unlock_budget",
)
async def unlock_budget(
    budget_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Unlock a locked budget."""
    method_name = "unlock_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.unlock_budget(budget_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=False,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST BUDGETS
# ----------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[BudgetResponseSchema],
    summary="List budgets",
    operation_id="list_budgets",
)
async def list_budgets(
    budget_type: BudgetType | None = Query(None, description="Filter by budget type"),
    fiscal_year: int | None = Query(None, description="Filter by fiscal year"),
    status: BudgetStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status (effective date)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> list[BudgetResponseSchema]:
    """List budgets with pagination and filters."""
    try:
        result = await service.list_budgets(
            legal_entity_id=legal_entity_id,
            budget_type=budget_type.value if budget_type else None,
            fiscal_year=fiscal_year,
            status=status.value if status else None,
            is_active=is_active,
            page=page,
            page_size=page_size,
        )

        return [
            BudgetResponseSchema(
                id=b.id,
                budget_code=b.budget_code,
                budget_name=b.budget_name,
                budget_type=BudgetType(b.budget_type),
                fiscal_year=b.fiscal_year,
                period=BudgetPeriod(b.period),
                version=b.version,
                status=BudgetStatus(b.status),
                effective_date=b.effective_date,
                expiry_date=b.expiry_date,
                currency=b.currency,
                total_amount=b.total_amount,
                actual_amount_ytd=b.actual_amount_ytd,
                variance_amount=b.variance_amount,
                variance_percent=b.variance_percent,
                consumption_percent=b.consumption_percent,
                notes=b.notes,
                tags=b.tags,
                is_locked=b.is_locked,
                created_at=b.created_at,
                updated_at=b.updated_at,
                created_by=b.created_by,
                created_by_name=b.created_by_name,
                approved_at=b.approved_at,
                approved_by=b.approved_by,
                approved_by_name=b.approved_by_name,
                lines=b.lines,
            )
            for b in result.items
        ]
    except Exception as e:
        logger.exception(f"Failed to list budgets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET VERSIONS
# ----------------------------------------------------------------------------

@router.get(
    "/versions/{budget_code}",
    response_model=list[BudgetVersionResponseSchema],
    summary="Get budget versions",
    operation_id="get_budget_versions",
)
async def get_budget_versions(
    budget_code: str,
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> list[BudgetVersionResponseSchema]:
    """Get all versions of a budget by code."""
    try:
        versions = await service.get_budget_versions(budget_code, legal_entity_id)

        return [
            BudgetVersionResponseSchema(
                id=v.id,
                budget_code=v.budget_code,
                version=v.version,
                status=BudgetStatus(v.status),
                total_amount=v.total_amount,
                effective_date=v.effective_date,
                created_at=v.created_at,
                created_by=v.created_by,
                created_by_name=v.created_by_name,
            )
            for v in versions
        ]
    except Exception as e:
        logger.exception(f"Failed to get budget versions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/version",
    response_model=BudgetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create new budget version",
    operation_id="create_budget_version",
)
async def create_budget_version(
    budget_id: UUID,
    version: str = Body(..., description="New version number"),
    notes: str = Body("", description="Version notes"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Create a new version of an existing budget."""
    method_name = "create_budget_version"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.create_budget_version(
            budget_id=budget_id,
            version=version,
            notes=notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Budget not found")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create budget version: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET VS ACTUAL ANALYSIS
# ----------------------------------------------------------------------------

@router.get(
    "/vs-actual/{budget_id}",
    response_model=BudgetVsActualResponseSchema,
    summary="Get budget vs actual for a specific period",
    operation_id="get_budget_vs_actual",
)
async def get_budget_vs_actual(
    budget_id: UUID,
    period: int = Query(..., ge=1, le=12, description="Month number (1-12)"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetVsActualResponseSchema:
    """Get budget vs actual analysis for a specific month."""
    try:
        analysis = await service.get_budget_vs_actual(
            budget_id=budget_id,
            legal_entity_id=legal_entity_id,
            period=period,
        )

        if not analysis:
            raise HTTPException(status_code=404, detail="Budget not found")

        return BudgetVsActualResponseSchema(
            budget_id=analysis.budget_id,
            budget_name=analysis.budget_name,
            fiscal_year=analysis.fiscal_year,
            period=analysis.period,
            period_name=analysis.period_name,
            total_budget=analysis.total_budget,
            total_actual=analysis.total_actual,
            total_variance=analysis.total_variance,
            variance_percent=analysis.variance_percent,
            variance_type=VarianceType(analysis.variance_type),
            consumption_rate=analysis.consumption_rate,
            remaining_budget=analysis.remaining_budget,
            lines=[
                BudgetVsActualLineSchema(
                    account_id=l.account_id,
                    account_code=l.account_code,
                    account_name=l.account_name,
                    budget_amount=l.budget_amount,
                    actual_amount=l.actual_amount,
                    variance_amount=l.variance_amount,
                    variance_percent=l.variance_percent,
                    variance_type=VarianceType(l.variance_type),
                    consumption_percent=l.consumption_percent,
                    remaining_budget=l.remaining_budget,
                )
                for l in analysis.lines
            ],
            generated_at=analysis.generated_at,
        )
    except Exception as e:
        logger.exception(f"Failed to get budget vs actual: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/vs-actual-ytd/{budget_id}",
    response_model=BudgetVsActualResponseSchema,
    summary="Get budget vs actual YTD",
    operation_id="get_budget_vs_actual_ytd",
)
async def get_budget_vs_actual_ytd(
    budget_id: UUID,
    as_of_month: int = Query(..., ge=1, le=12, description="Month up to which to calculate YTD"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetVsActualResponseSchema:
    """Get budget vs actual YTD analysis."""
    try:
        analysis = await service.get_budget_vs_actual_ytd(
            budget_id=budget_id,
            legal_entity_id=legal_entity_id,
            as_of_month=as_of_month,
        )

        if not analysis:
            raise HTTPException(status_code=404, detail="Budget not found")

        return BudgetVsActualResponseSchema(
            budget_id=analysis.budget_id,
            budget_name=analysis.budget_name,
            fiscal_year=analysis.fiscal_year,
            period=0,
            period_name=f"YTD (month {as_of_month})",
            total_budget=analysis.total_budget,
            total_actual=analysis.total_actual,
            total_variance=analysis.total_variance,
            variance_percent=analysis.variance_percent,
            variance_type=VarianceType(analysis.variance_type),
            consumption_rate=analysis.consumption_rate,
            remaining_budget=analysis.remaining_budget,
            lines=[
                BudgetVsActualLineSchema(
                    account_id=l.account_id,
                    account_code=l.account_code,
                    account_name=l.account_name,
                    budget_amount=l.budget_amount,
                    actual_amount=l.actual_amount,
                    variance_amount=l.variance_amount,
                    variance_percent=l.variance_percent,
                    variance_type=VarianceType(l.variance_type),
                    consumption_percent=l.consumption_percent,
                    remaining_budget=l.remaining_budget,
                )
                for l in analysis.lines
            ],
            generated_at=analysis.generated_at,
        )
    except Exception as e:
        logger.exception(f"Failed to get budget vs actual YTD: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET TRANSFER / REALLOCATION
# ----------------------------------------------------------------------------

@router.post(
    "/transfer",
    response_model=BudgetTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer budget between accounts",
    operation_id="transfer_budget",
)
async def transfer_budget(
    request: BudgetTransferSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetTransferResponseSchema:
    """Transfer budget amount from one account to another."""
    method_name = "transfer_budget"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetTransferResponseSchema(**cached)

    try:
        result = await service.transfer_budget(
            budget_id=request.budget_id if hasattr(request, 'budget_id') else None,
            from_account_id=request.from_account_id,
            to_account_id=request.to_account_id,
            amount=request.amount,
            reason=request.reason,
            effective_date=request.effective_date,
            transferred_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = BudgetTransferResponseSchema(
            transfer_id=result.transfer_id,
            budget_id=result.budget_id,
            from_account_id=result.from_account_id,
            from_account_code=result.from_account_code,
            from_account_name=result.from_account_name,
            to_account_id=result.to_account_id,
            to_account_code=result.to_account_code,
            to_account_name=result.to_account_name,
            amount=result.amount,
            reason=result.reason,
            effective_date=result.effective_date,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to transfer budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET DASHBOARD
# ----------------------------------------------------------------------------

@router.get(
    "/dashboard",
    response_model=BudgetDashboardResponseSchema,
    summary="Get budget dashboard",
    operation_id="get_budget_dashboard",
)
async def get_budget_dashboard(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetDashboardResponseSchema:
    """Get budget dashboard with key metrics and alerts."""
    try:
        dashboard = await service.get_budget_dashboard(legal_entity_id, as_of_date)

        return BudgetDashboardResponseSchema(
            as_of_date=as_of_date,
            total_budgets=dashboard.total_budgets,
            active_budgets=dashboard.active_budgets,
            total_budget_amount=dashboard.total_budget_amount,
            total_actual_ytd=dashboard.total_actual_ytd,
            total_variance=dashboard.total_variance,
            overall_consumption_rate=dashboard.overall_consumption_rate,
            by_type=dashboard.by_type,
            by_status=dashboard.by_status,
            top_variance_items=dashboard.top_variance_items,
            alerts=dashboard.alerts,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get budget dashboard: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/alerts",
    response_model=list[BudgetAlertSchema],
    summary="Get budget alerts",
    operation_id="get_budget_alerts",
)
async def get_budget_alerts(
    threshold_percent: float = Query(DEFAULT_VARIANCE_THRESHOLD_PERCENT, ge=0, le=100, description="Threshold percentage"),
    severity: str | None = Query(None, description="Filter by severity (warning, critical)"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> list[BudgetAlertSchema]:
    """Get budget alerts for accounts exceeding threshold."""
    try:
        alerts = await service.get_budget_alerts(
            legal_entity_id=legal_entity_id,
            threshold_percent=Decimal(str(threshold_percent)),
            severity=severity,
        )

        return [
            BudgetAlertSchema(
                budget_id=a.budget_id,
                budget_name=a.budget_name,
                account_id=a.account_id,
                account_code=a.account_code,
                account_name=a.account_name,
                budget_amount=a.budget_amount,
                actual_amount=a.actual_amount,
                consumption_percent=a.consumption_percent,
                threshold_percent=a.threshold_percent,
                message=a.message,
                severity=a.severity,
                created_at=a.created_at,
            )
            for a in alerts
        ]
    except Exception as e:
        logger.exception(f"Failed to get budget alerts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ROLLING FORECAST
# ----------------------------------------------------------------------------

@router.post(
    "/rolling-forecast",
    response_model=BudgetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create rolling forecast from budget",
    operation_id="create_rolling_forecast",
)
async def create_rolling_forecast(
    request: BudgetRollingForecastSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> BudgetResponseSchema:
    """Create a rolling forecast based on existing budget."""
    method_name = "create_rolling_forecast"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return BudgetResponseSchema(**cached)

    try:
        result = await service.create_rolling_forecast(
            base_budget_id=request.base_budget_id,
            forecast_months=request.forecast_months,
            adjustment_factors=request.adjustment_factors,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Base budget not found")

        response = BudgetResponseSchema(
            id=result.id,
            budget_code=result.budget_code,
            budget_name=result.budget_name,
            budget_type=BudgetType(result.budget_type),
            fiscal_year=result.fiscal_year,
            period=BudgetPeriod(result.period),
            version=result.version,
            status=BudgetStatus(result.status),
            effective_date=result.effective_date,
            expiry_date=result.expiry_date,
            currency=result.currency,
            total_amount=result.total_amount,
            actual_amount_ytd=result.actual_amount_ytd,
            variance_amount=result.variance_amount,
            variance_percent=result.variance_percent,
            consumption_percent=result.consumption_percent,
            notes=result.notes,
            tags=result.tags,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            lines=result.lines,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to create rolling forecast: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BUDGET HISTORY & STATUS
# ----------------------------------------------------------------------------

@router.get(
    "/{budget_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get budget history",
    operation_id="get_budget_history",
)
async def get_budget_history(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> list[dict[str, Any]]:
    """Get budget change history (audit trail)."""
    try:
        history = await service.get_budget_history(budget_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get budget history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{budget_id}/status",
    response_model=dict[str, Any],
    summary="Get budget status",
    operation_id="get_budget_status",
)
async def get_budget_status(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> dict[str, Any]:
    """Get detailed budget status including workflow state."""
    try:
        status_info = await service.get_budget_status(budget_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Budget not found")

        return {
            "budget_id": str(budget_id),
            "budget_code": status_info.budget_code,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_submit": status_info.can_submit,
            "can_approve": status_info.can_approve,
            "can_reject": status_info.can_reject,
            "can_activate": status_info.can_activate,
            "can_lock": status_info.can_lock,
            "can_edit": status_info.can_edit,
            "can_delete": status_info.can_delete,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "current_approver": status_info.current_approver,
            "approval_level": status_info.approval_level,
            "submitted_at": status_info.submitted_at.isoformat() if status_info.submitted_at else None,
            "approved_at": status_info.approved_at.isoformat() if status_info.approved_at else None,
            "activated_at": status_info.activated_at.isoformat() if status_info.activated_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get budget status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------

@router.get(
    "/export",
    summary="Export budgets",
    operation_id="export_budgets",
)
async def export_budgets(
    fiscal_year: int = Query(..., description="Fiscal year"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    budget_type: BudgetType | None = Query(None, description="Filter by budget type"),
    _permission: None = Depends(require_permission("budget:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_budget_service),
) -> Response:
    """Export budgets to CSV or Excel."""
    try:
        data = await service.export_budgets(
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            format=format,
            budget_type=budget_type.value if budget_type else None,
        )

        media_type = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"budgets_{legal_entity_id}_{fiscal_year}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export budgets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
