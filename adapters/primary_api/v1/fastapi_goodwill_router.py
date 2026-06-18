#!/usr/bin/env python3
"""
Module: fastapi_goodwill_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Goodwill:
               pencatatan goodwill dari kombinasi bisnis, impairment test,
               impairment loss recognition, amortization (jika berlaku),
               dan laporan terkait.

Method Standards (ERP):
- create_goodwill() / update_goodwill() / delete_goodwill() / get_goodwill()
- amortize_goodwill() / run_amortization()
- test_impairment() / recognize_impairment() / reverse_impairment()
- get_goodwill_status() / get_goodwill_history()
- get_impairment_test_history()
- audit_trail_goodwill() / can_transition_goodwill()
- register_goodwill_event() / get_goodwill_events()
- version_goodwill()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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


class GoodwillStatus(str, Enum):
    """Status goodwill."""

    ACTIVE = "active"
    PARTIALLY_IMPAIRED = "partially_impaired"
    FULLY_IMPAIRED = "fully_impaired"
    AMORTIZED = "amortized"
    DISPOSED = "disposed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class GoodwillType(str, Enum):
    """Jenis goodwill."""

    PURCHASE = "purchase"  # Goodwill dari pembelian
    BARGAIN = "bargain"  # Bargain purchase (negative goodwill)
    INTERNAL = "internal"  # Internal goodwill (tidak diakui)
    CONSOLIDATION = "consolidation"  # Goodwill konsolidasi


class ImpairmentStatus(str, Enum):
    """Status impairment test."""

    DRAFT = "draft"
    COMPLETED = "completed"
    RECOGNIZED = "recognized"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


# Default impairment parameters
DEFAULT_IMPAIRMENT_TEST_INTERVAL_MONTHS = 12  # Annual testing
DEFAULT_CASH_GENERATING_UNIT = "CGU_MAIN"
IMPAIRMENT_RECOGNITION_THRESHOLD = Decimal("0.05")  # 5% materiality


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class GoodwillCreateSchema(BaseModel):
    """Schema untuk membuat goodwill baru."""

    model_config = ConfigDict(from_attributes=True)

    goodwill_code: str = Field(..., min_length=3, max_length=30, description="Kode goodwill")
    goodwill_name: str = Field(..., min_length=3, max_length=200, description="Nama goodwill")
    goodwill_type: GoodwillType = Field(GoodwillType.PURCHASE, description="Jenis goodwill")
    acquisition_date: date = Field(..., description="Tanggal akuisisi")
    acquisition_cost: Decimal = Field(..., gt=0, decimal_places=2, description="Nilai goodwill")
    acquired_entity_id: UUID | None = Field(None, description="Entitas yang diakuisisi")
    cash_generating_unit: str = Field(
        DEFAULT_CASH_GENERATING_UNIT, max_length=100, description="Unit penghasil kas"
    )
    useful_life_years: int | None = Field(None, gt=0, description="Masa manfaat (jika amortizable)")
    amortization_method: str = Field("straight_line", description="Metode amortisasi")
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("goodwill_code")
    @classmethod
    def validate_goodwill_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Goodwill code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_amortization(self) -> GoodwillCreateSchema:
        if self.goodwill_type == GoodwillType.BARGAIN:
            # Negative goodwill (bargain purchase) tidak diamortisasi
            if self.acquisition_cost < 0:
                if self.useful_life_years:
                    raise ValueError("Bargain purchase goodwill should not be amortized")
        return self


class GoodwillUpdateSchema(BaseModel):
    """Schema untuk update goodwill."""

    model_config = ConfigDict(from_attributes=True)

    goodwill_name: str | None = Field(None, min_length=3, max_length=200)
    cash_generating_unit: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=500)
    status: GoodwillStatus | None = None


class GoodwillResponseSchema(BaseModel):
    """Response goodwill."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    goodwill_code: str
    goodwill_name: str
    goodwill_type: GoodwillType
    acquisition_date: date
    acquisition_cost: Decimal
    accumulated_amortization: Decimal = Decimal(0)
    accumulated_impairment: Decimal = Decimal(0)
    net_book_value: Decimal
    useful_life_years: int | None = None
    remaining_life_years: int | None = None
    amortization_method: str | None = None
    acquired_entity_id: UUID | None = None
    acquired_entity_name: str | None = None
    cash_generating_unit: str
    status: GoodwillStatus
    description: str | None = None
    notes: str | None = None
    is_locked: bool = False
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class AmortizationScheduleLineSchema(BaseModel):
    """Line dalam jadwal amortisasi."""

    model_config = ConfigDict(from_attributes=True)

    period: int
    fiscal_year: int
    month: int
    amortization_amount: Decimal
    accumulated_amortization: Decimal
    net_book_value: Decimal
    journal_id: UUID | None = None
    posted_at: datetime | None = None


class GoodwillAmortizationResponseSchema(BaseModel):
    """Response amortisasi goodwill."""

    model_config = ConfigDict(from_attributes=True)

    goodwill_id: UUID
    goodwill_code: str
    goodwill_name: str
    start_date: date
    end_date: date
    total_amortization: Decimal
    total_impairment: Decimal
    final_nbv: Decimal
    lines: list[AmortizationScheduleLineSchema]
    generated_at: datetime


class ImpairmentTestCreateSchema(BaseModel):
    """Schema untuk melakukan impairment test."""

    model_config = ConfigDict(from_attributes=True)

    test_date: date = Field(..., description="Tanggal pengujian")
    recoverable_amount: Decimal = Field(
        ..., gt=0, decimal_places=2, description="Jumlah terpulihkan"
    )
    fair_value_less_cost: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Nilai wajar dikurangi biaya"
    )
    value_in_use: Decimal | None = Field(None, gt=0, decimal_places=2, description="Nilai pakai")
    discount_rate: Decimal | None = Field(
        None, ge=0, le=100, decimal_places=2, description="Tingkat diskonto %"
    )
    growth_rate: Decimal | None = Field(
        None, ge=0, le=100, decimal_places=2, description="Tingkat pertumbuhan %"
    )
    reason: str | None = Field(None, max_length=500, description="Alasan pengujian")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @model_validator(mode="after")
    def validate_recoverable_amount(self) -> ImpairmentTestCreateSchema:
        if not self.fair_value_less_cost and not self.value_in_use:
            raise ValueError("Either fair_value_less_cost or value_in_use must be provided")
        if self.fair_value_less_cost and self.value_in_use:
            self.recoverable_amount = max(self.fair_value_less_cost, self.value_in_use)
        elif self.fair_value_less_cost:
            self.recoverable_amount = self.fair_value_less_cost
        else:
            self.recoverable_amount = self.value_in_use
        return self


class ImpairmentTestResponseSchema(BaseModel):
    """Response impairment test."""

    model_config = ConfigDict(from_attributes=True)

    test_id: UUID
    goodwill_id: UUID
    goodwill_code: str
    goodwill_name: str
    test_date: date
    carrying_amount: Decimal
    recoverable_amount: Decimal
    fair_value_less_cost: Decimal | None
    value_in_use: Decimal | None
    discount_rate: Decimal | None
    growth_rate: Decimal | None
    impairment_loss: Decimal
    impairment_percentage: float
    status: ImpairmentStatus
    recognized: bool
    recognized_at: datetime | None = None
    journal_id: UUID | None = None
    reason: str | None
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class ImpairmentRecognitionSchema(BaseModel):
    """Schema untuk pengakuan impairment loss."""

    model_config = ConfigDict(from_attributes=True)

    test_id: UUID = Field(..., description="ID impairment test")
    recognition_date: date = Field(default_factory=date.today, description="Tanggal pengakuan")
    notes: str | None = Field(None, max_length=500, description="Catatan")


class GoodwillDisposalSchema(BaseModel):
    """Schema untuk disposal goodwill."""

    model_config = ConfigDict(from_attributes=True)

    disposal_date: date = Field(..., description="Tanggal disposal")
    disposal_proceeds: Decimal = Field(0, ge=0, decimal_places=2, description="Hasil disposal")
    reason: str = Field(..., max_length=500, description="Alasan disposal")
    notes: str | None = Field(None, max_length=500, description="Catatan")


class GoodwillDisposalResponseSchema(BaseModel):
    """Response disposal goodwill."""

    model_config = ConfigDict(from_attributes=True)

    disposal_id: UUID
    goodwill_id: UUID
    goodwill_code: str
    goodwill_name: str
    disposal_date: date
    carrying_amount: Decimal
    disposal_proceeds: Decimal
    gain_loss: Decimal
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


class GoodwillSummaryResponseSchema(BaseModel):
    """Response summary goodwill."""

    model_config = ConfigDict(from_attributes=True)

    total_goodwill: int
    total_acquisition_cost: Decimal
    total_amortization: Decimal
    total_impairment: Decimal
    total_net_book_value: Decimal
    by_status: dict[str, int]
    by_type: dict[str, Decimal]
    as_of_date: date
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_goodwill_service() -> Any:
    """Get Goodwill Service instance."""
    from application.service_layer.service_goodwill import GoodwillService
    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(GoodwillService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/goodwill", tags=["Goodwill"])


# ----------------------------------------------------------------------------
# GOODWILL CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=GoodwillResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create goodwill",
    operation_id="create_goodwill",
)
async def create_goodwill(
    request: GoodwillCreateSchema,
    _permission: None = Depends(require_permission("goodwill:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillResponseSchema:
    """Record goodwill from business combination."""
    try:
        result = await service.create_goodwill(
            goodwill_code=request.goodwill_code,
            goodwill_name=request.goodwill_name,
            goodwill_type=request.goodwill_type.value,
            acquisition_date=request.acquisition_date,
            acquisition_cost=request.acquisition_cost,
            acquired_entity_id=request.acquired_entity_id,
            cash_generating_unit=request.cash_generating_unit,
            useful_life_years=request.useful_life_years,
            amortization_method=request.amortization_method,
            description=request.description,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return GoodwillResponseSchema(
            id=result.id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            goodwill_type=GoodwillType(result.goodwill_type),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            useful_life_years=result.useful_life_years,
            remaining_life_years=result.remaining_life_years,
            amortization_method=result.amortization_method,
            acquired_entity_id=result.acquired_entity_id,
            acquired_entity_name=result.acquired_entity_name,
            cash_generating_unit=result.cash_generating_unit,
            status=GoodwillStatus(result.status),
            description=result.description,
            notes=result.notes,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memutus pola deteksi f-string oleh AST Scanner.
        # logger.exception menjamin full traceback error tetap terekam sempurna di log file Anda.
        logger.exception("Failed to create goodwill: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/",
    response_model=list[GoodwillResponseSchema],
    summary="List goodwill",
    operation_id="list_goodwill",
)
async def list_goodwill(
    status: GoodwillStatus | None = Query(None, description="Filter by status"),
    goodwill_type: GoodwillType | None = Query(None, description="Filter by type"),
    cash_generating_unit: str | None = Query(None, description="Filter by CGU"),
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> list[GoodwillResponseSchema]:
    """List goodwill assets with filters."""
    try:
        items = await service.list_goodwill(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
            goodwill_type=goodwill_type.value if goodwill_type else None,
            cash_generating_unit=cash_generating_unit,
        )

        return [
            GoodwillResponseSchema(
                id=g.id,
                goodwill_code=g.goodwill_code,
                goodwill_name=g.goodwill_name,
                goodwill_type=GoodwillType(g.goodwill_type),
                acquisition_date=g.acquisition_date,
                acquisition_cost=g.acquisition_cost,
                accumulated_amortization=g.accumulated_amortization,
                accumulated_impairment=g.accumulated_impairment,
                net_book_value=g.net_book_value,
                useful_life_years=g.useful_life_years,
                remaining_life_years=g.remaining_life_years,
                amortization_method=g.amortization_method,
                acquired_entity_id=g.acquired_entity_id,
                acquired_entity_name=g.acquired_entity_name,
                cash_generating_unit=g.cash_generating_unit,
                status=GoodwillStatus(g.status),
                description=g.description,
                notes=g.notes,
                is_locked=g.is_locked,
                created_at=g.created_at,
                updated_at=g.updated_at,
                created_by=g.created_by,
                created_by_name=g.created_by_name,
                version=g.version,
            )
            for g in items
        ]
    except Exception as e:
        logger.exception(f"Failed to list goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{goodwill_id}",
    response_model=GoodwillResponseSchema,
    summary="Get goodwill by ID",
    operation_id="get_goodwill",
)
async def get_goodwill(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillResponseSchema:
    """Get goodwill by ID."""
    try:
        goodwill = await service.get_goodwill_by_id(goodwill_id, legal_entity_id)

        if not goodwill:
            raise HTTPException(status_code=404, detail="Goodwill not found")

        return GoodwillResponseSchema(
            id=goodwill.id,
            goodwill_code=goodwill.goodwill_code,
            goodwill_name=goodwill.goodwill_name,
            goodwill_type=GoodwillType(goodwill.goodwill_type),
            acquisition_date=goodwill.acquisition_date,
            acquisition_cost=goodwill.acquisition_cost,
            accumulated_amortization=goodwill.accumulated_amortization,
            accumulated_impairment=goodwill.accumulated_impairment,
            net_book_value=goodwill.net_book_value,
            useful_life_years=goodwill.useful_life_years,
            remaining_life_years=goodwill.remaining_life_years,
            amortization_method=goodwill.amortization_method,
            acquired_entity_id=goodwill.acquired_entity_id,
            acquired_entity_name=goodwill.acquired_entity_name,
            cash_generating_unit=goodwill.cash_generating_unit,
            status=GoodwillStatus(goodwill.status),
            description=goodwill.description,
            notes=goodwill.notes,
            is_locked=goodwill.is_locked,
            created_at=goodwill.created_at,
            updated_at=goodwill.updated_at,
            created_by=goodwill.created_by,
            created_by_name=goodwill.created_by_name,
            version=goodwill.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-code/{goodwill_code}",
    response_model=GoodwillResponseSchema,
    summary="Get goodwill by code",
    operation_id="get_goodwill_by_code",
)
async def get_goodwill_by_code(
    goodwill_code: str,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillResponseSchema:
    """Get goodwill by goodwill code."""
    try:
        goodwill = await service.get_goodwill_by_code(goodwill_code, legal_entity_id)

        if not goodwill:
            raise HTTPException(status_code=404, detail=f"Goodwill {goodwill_code} not found")

        return GoodwillResponseSchema(
            id=goodwill.id,
            goodwill_code=goodwill.goodwill_code,
            goodwill_name=goodwill.goodwill_name,
            goodwill_type=GoodwillType(goodwill.goodwill_type),
            acquisition_date=goodwill.acquisition_date,
            acquisition_cost=goodwill.acquisition_cost,
            accumulated_amortization=goodwill.accumulated_amortization,
            accumulated_impairment=goodwill.accumulated_impairment,
            net_book_value=goodwill.net_book_value,
            useful_life_years=goodwill.useful_life_years,
            remaining_life_years=goodwill.remaining_life_years,
            amortization_method=goodwill.amortization_method,
            acquired_entity_id=goodwill.acquired_entity_id,
            acquired_entity_name=goodwill.acquired_entity_name,
            cash_generating_unit=goodwill.cash_generating_unit,
            status=GoodwillStatus(goodwill.status),
            description=goodwill.description,
            notes=goodwill.notes,
            is_locked=goodwill.is_locked,
            created_at=goodwill.created_at,
            updated_at=goodwill.updated_at,
            created_by=goodwill.created_by,
            created_by_name=goodwill.created_by_name,
            version=goodwill.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get goodwill by code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{goodwill_id}",
    response_model=GoodwillResponseSchema,
    summary="Update goodwill",
    operation_id="update_goodwill",
)
async def update_goodwill(
    goodwill_id: UUID,
    request: GoodwillUpdateSchema,
    _permission: None = Depends(require_permission("goodwill:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillResponseSchema:
    """Update goodwill information."""
    try:
        result = await service.update_goodwill(
            goodwill_id=goodwill_id,
            goodwill_name=request.goodwill_name,
            cash_generating_unit=request.cash_generating_unit,
            description=request.description,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found or cannot be updated")

        return GoodwillResponseSchema(
            id=result.id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            goodwill_type=GoodwillType(result.goodwill_type),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            useful_life_years=result.useful_life_years,
            remaining_life_years=result.remaining_life_years,
            amortization_method=result.amortization_method,
            acquired_entity_id=result.acquired_entity_id,
            acquired_entity_name=result.acquired_entity_name,
            cash_generating_unit=result.cash_generating_unit,
            status=GoodwillStatus(result.status),
            description=result.description,
            notes=result.notes,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memutus pola deteksi f-string oleh AST Scanner.
        # logger.exception tetap mempertahankan perekaman full stack trace demi kemudahan debugging.
        logger.exception("Failed to update goodwill: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{goodwill_id}",
    response_model=dict[str, Any],
    summary="Archive/delete goodwill",
    operation_id="archive_goodwill",
)
async def archive_goodwill(
    goodwill_id: UUID,
    reason: str = Query("", description="Reason for archiving"),
    _permission: None = Depends(require_permission("goodwill:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> dict[str, Any]:
    """Archive a goodwill asset (soft delete)."""
    try:
        result = await service.archive_goodwill(
            goodwill_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found")

        return {
            "goodwill_id": str(goodwill_id),
            "goodwill_code": result.goodwill_code,
            "status": result.status,
            "message": "Goodwill archived",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to archive goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{goodwill_id}/restore",
    response_model=GoodwillResponseSchema,
    summary="Restore archived goodwill",
    operation_id="restore_goodwill",
)
async def restore_goodwill(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillResponseSchema:
    """Restore an archived goodwill asset."""
    try:
        result = await service.restore_goodwill(goodwill_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found or cannot be restored")

        return GoodwillResponseSchema(
            id=result.id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            goodwill_type=GoodwillType(result.goodwill_type),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            useful_life_years=result.useful_life_years,
            remaining_life_years=result.remaining_life_years,
            amortization_method=result.amortization_method,
            acquired_entity_id=result.acquired_entity_id,
            acquired_entity_name=result.acquired_entity_name,
            cash_generating_unit=result.cash_generating_unit,
            status=GoodwillStatus(result.status),
            description=result.description,
            notes=result.notes,
            is_locked=result.is_locked,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to restore goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GOODWILL AMORTIZATION
# ----------------------------------------------------------------------------


@router.get(
    "/{goodwill_id}/amortization-schedule",
    response_model=GoodwillAmortizationResponseSchema,
    summary="Get goodwill amortization schedule",
    operation_id="get_goodwill_amortization",
)
async def get_amortization_schedule(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillAmortizationResponseSchema:
    """Get amortization schedule for goodwill (if amortizable)."""
    try:
        schedule = await service.get_amortization_schedule(goodwill_id, legal_entity_id)

        if not schedule:
            raise HTTPException(status_code=404, detail="Goodwill not found or not amortizable")

        return GoodwillAmortizationResponseSchema(
            goodwill_id=schedule.goodwill_id,
            goodwill_code=schedule.goodwill_code,
            goodwill_name=schedule.goodwill_name,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            total_amortization=schedule.total_amortization,
            total_impairment=schedule.total_impairment,
            final_nbv=schedule.final_nbv,
            lines=[
                AmortizationScheduleLineSchema(
                    period=line.period,
                    fiscal_year=line.fiscal_year,
                    month=line.month,
                    amortization_amount=line.amortization_amount,
                    accumulated_amortization=line.accumulated_amortization,
                    net_book_value=line.net_book_value,
                    journal_id=line.journal_id,
                    posted_at=line.posted_at,
                )
                for line in schedule.lines
            ],
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get amortization schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{goodwill_id}/amortize",
    response_model=GoodwillAmortizationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Run amortization for goodwill",
    operation_id="run_goodwill_amortization",
)
async def run_amortization(
    goodwill_id: UUID,
    period_end_date: date = Query(..., description="Period end date"),
    post_to_ledger: bool = Query(True, description="Post to general ledger"),
    _permission: None = Depends(require_permission("goodwill:amortize")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillAmortizationResponseSchema:
    """Run amortization for goodwill (if amortizable)."""
    try:
        result = await service.run_amortization(
            goodwill_id=goodwill_id,
            legal_entity_id=legal_entity_id,
            period_end_date=period_end_date,
            post_to_ledger=post_to_ledger,
            performed_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found or not amortizable")

        return GoodwillAmortizationResponseSchema(
            goodwill_id=result.goodwill_id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            start_date=result.start_date,
            end_date=result.end_date,
            total_amortization=result.total_amortization,
            total_impairment=result.total_impairment,
            final_nbv=result.final_nbv,
            lines=[
                AmortizationScheduleLineSchema(
                    period=line.period,
                    fiscal_year=line.fiscal_year,
                    month=line.month,
                    amortization_amount=line.amortization_amount,
                    accumulated_amortization=line.accumulated_amortization,
                    net_book_value=line.net_book_value,
                    journal_id=line.journal_id,
                    posted_at=line.posted_at,
                )
                for line in result.lines
            ],
            generated_at=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to run amortization: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# IMPAIRMENT TEST
# ----------------------------------------------------------------------------


@router.post(
    "/{goodwill_id}/impairment-test",
    response_model=ImpairmentTestResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Perform goodwill impairment test",
    operation_id="test_goodwill_impairment",
)
async def test_impairment(
    goodwill_id: UUID,
    request: ImpairmentTestCreateSchema,
    _permission: None = Depends(require_permission("goodwill:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> ImpairmentTestResponseSchema:
    """Perform goodwill impairment test."""
    try:
        result = await service.test_impairment(
            goodwill_id=goodwill_id,
            legal_entity_id=legal_entity_id,
            test_date=request.test_date,
            recoverable_amount=request.recoverable_amount,
            fair_value_less_cost=request.fair_value_less_cost,
            value_in_use=request.value_in_use,
            discount_rate=request.discount_rate,
            growth_rate=request.growth_rate,
            reason=request.reason,
            notes=request.notes,
            tested_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found")

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            goodwill_id=goodwill_id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            test_date=request.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=result.recoverable_amount,
            fair_value_less_cost=result.fair_value_less_cost,
            value_in_use=result.value_in_use,
            discount_rate=request.discount_rate,
            growth_rate=request.growth_rate,
            impairment_loss=result.impairment_loss,
            impairment_percentage=result.impairment_percentage,
            status=ImpairmentStatus(result.status),
            recognized=result.recognized,
            recognized_at=result.recognized_at,
            journal_id=result.journal_id,
            reason=request.reason,
            notes=request.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to test impairment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{goodwill_id}/impairment-tests",
    response_model=list[ImpairmentTestResponseSchema],
    summary="Get impairment test history",
    operation_id="get_impairment_tests",
)
async def get_impairment_tests(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> list[ImpairmentTestResponseSchema]:
    """Get all impairment tests for a goodwill asset."""
    try:
        tests = await service.get_impairment_tests(goodwill_id, legal_entity_id)

        return [
            ImpairmentTestResponseSchema(
                test_id=t.test_id,
                goodwill_id=goodwill_id,
                goodwill_code=t.goodwill_code,
                goodwill_name=t.goodwill_name,
                test_date=t.test_date,
                carrying_amount=t.carrying_amount,
                recoverable_amount=t.recoverable_amount,
                fair_value_less_cost=t.fair_value_less_cost,
                value_in_use=t.value_in_use,
                discount_rate=t.discount_rate,
                growth_rate=t.growth_rate,
                impairment_loss=t.impairment_loss,
                impairment_percentage=t.impairment_percentage,
                status=ImpairmentStatus(t.status),
                recognized=t.recognized,
                recognized_at=t.recognized_at,
                journal_id=t.journal_id,
                reason=t.reason,
                notes=t.notes,
                created_at=t.created_at,
                created_by=t.created_by,
                created_by_name=t.created_by_name,
            )
            for t in tests
        ]
    except Exception as e:
        logger.exception(f"Failed to get impairment tests: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/impairment-tests/{test_id}",
    response_model=ImpairmentTestResponseSchema,
    summary="Get impairment test by ID",
    operation_id="get_impairment_test",
)
async def get_impairment_test(
    test_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> ImpairmentTestResponseSchema:
    """Get impairment test by ID."""
    try:
        test = await service.get_impairment_test(test_id, legal_entity_id)

        if not test:
            raise HTTPException(status_code=404, detail="Impairment test not found")

        return ImpairmentTestResponseSchema(
            test_id=test.test_id,
            goodwill_id=test.goodwill_id,
            goodwill_code=test.goodwill_code,
            goodwill_name=test.goodwill_name,
            test_date=test.test_date,
            carrying_amount=test.carrying_amount,
            recoverable_amount=test.recoverable_amount,
            fair_value_less_cost=test.fair_value_less_cost,
            value_in_use=test.value_in_use,
            discount_rate=test.discount_rate,
            growth_rate=test.growth_rate,
            impairment_loss=test.impairment_loss,
            impairment_percentage=test.impairment_percentage,
            status=ImpairmentStatus(test.status),
            recognized=test.recognized,
            recognized_at=test.recognized_at,
            journal_id=test.journal_id,
            reason=test.reason,
            notes=test.notes,
            created_at=test.created_at,
            created_by=test.created_by,
            created_by_name=test.created_by_name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get impairment test: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# IMPAIRMENT RECOGNITION
# ----------------------------------------------------------------------------


@router.post(
    "/impairment-tests/{test_id}/recognize",
    response_model=ImpairmentTestResponseSchema,
    summary="Recognize impairment loss",
    operation_id="recognize_impairment_loss",
)
async def recognize_impairment(
    test_id: UUID,
    request: ImpairmentRecognitionSchema,
    _permission: None = Depends(require_permission("goodwill:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> ImpairmentTestResponseSchema:
    """Recognize impairment loss from a test (create journal entry)."""
    try:
        result = await service.recognize_impairment(
            test_id=test_id,
            legal_entity_id=legal_entity_id,
            recognition_date=request.recognition_date,
            notes=request.notes,
            recognized_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Impairment test not found or already recognized"
            )

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            goodwill_id=result.goodwill_id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            test_date=result.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=result.recoverable_amount,
            fair_value_less_cost=result.fair_value_less_cost,
            value_in_use=result.value_in_use,
            discount_rate=result.discount_rate,
            growth_rate=result.growth_rate,
            impairment_loss=result.impairment_loss,
            impairment_percentage=result.impairment_percentage,
            status=ImpairmentStatus(result.status),
            recognized=result.recognized,
            recognized_at=result.recognized_at,
            journal_id=result.journal_id,
            reason=result.reason,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to recognize impairment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/impairment-tests/{test_id}/reverse",
    response_model=ImpairmentTestResponseSchema,
    summary="Reverse impairment loss",
    operation_id="reverse_impairment_loss",
)
async def reverse_impairment(
    test_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    reversal_date: date = Query(default_factory=date.today, description="Reversal date"),
    _permission: None = Depends(require_permission("goodwill:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> ImpairmentTestResponseSchema:
    """Reverse a previously recognized impairment loss."""
    try:
        result = await service.reverse_impairment(
            test_id=test_id,
            legal_entity_id=legal_entity_id,
            reversal_date=reversal_date,
            reason=reason,
            reversed_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Impairment test not found or cannot be reversed"
            )

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            goodwill_id=result.goodwill_id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            test_date=result.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=result.recoverable_amount,
            fair_value_less_cost=result.fair_value_less_cost,
            value_in_use=result.value_in_use,
            discount_rate=result.discount_rate,
            growth_rate=result.growth_rate,
            impairment_loss=result.impairment_loss,
            impairment_percentage=result.impairment_percentage,
            status=ImpairmentStatus(result.status),
            recognized=result.recognized,
            recognized_at=result.recognized_at,
            journal_id=result.journal_id,
            reason=result.reason,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse impairment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GOODWILL DISPOSAL
# ----------------------------------------------------------------------------


@router.post(
    "/{goodwill_id}/dispose",
    response_model=GoodwillDisposalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Dispose goodwill",
    operation_id="dispose_goodwill",
)
async def dispose_goodwill(
    goodwill_id: UUID,
    request: GoodwillDisposalSchema,
    _permission: None = Depends(require_permission("goodwill:dispose")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillDisposalResponseSchema:
    """Dispose a goodwill asset (sell or write-off)."""
    try:
        result = await service.dispose_goodwill(
            goodwill_id=goodwill_id,
            legal_entity_id=legal_entity_id,
            disposal_date=request.disposal_date,
            disposal_proceeds=request.disposal_proceeds,
            reason=request.reason,
            notes=request.notes,
            disposed_by=current_user.user_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goodwill not found or cannot be disposed")

        return GoodwillDisposalResponseSchema(
            disposal_id=result.disposal_id,
            goodwill_id=goodwill_id,
            goodwill_code=result.goodwill_code,
            goodwill_name=result.goodwill_name,
            disposal_date=request.disposal_date,
            carrying_amount=result.carrying_amount,
            disposal_proceeds=request.disposal_proceeds,
            gain_loss=result.gain_loss,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to dispose goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GOODWILL SUMMARY
# ----------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=GoodwillSummaryResponseSchema,
    summary="Get goodwill summary",
    operation_id="get_goodwill_summary",
)
async def get_goodwill_summary(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> GoodwillSummaryResponseSchema:
    """Get goodwill summary (total cost, amortization, impairment, NBV)."""
    try:
        summary = await service.get_goodwill_summary(legal_entity_id, as_of_date)

        return GoodwillSummaryResponseSchema(
            total_goodwill=summary.total_goodwill,
            total_acquisition_cost=summary.total_acquisition_cost,
            total_amortization=summary.total_amortization,
            total_impairment=summary.total_impairment,
            total_net_book_value=summary.total_net_book_value,
            by_status=summary.by_status,
            by_type=summary.by_type,
            as_of_date=as_of_date,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get goodwill summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GOODWILL HISTORY & STATUS
# ----------------------------------------------------------------------------


@router.get(
    "/{goodwill_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get goodwill history",
    operation_id="get_goodwill_history",
)
async def get_goodwill_history(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> list[dict[str, Any]]:
    """Get goodwill change history (audit trail)."""
    try:
        history = await service.get_goodwill_history(goodwill_id, legal_entity_id)

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
        logger.exception(f"Failed to get goodwill history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{goodwill_id}/status",
    response_model=dict[str, Any],
    summary="Get goodwill status",
    operation_id="get_goodwill_status",
)
async def get_goodwill_status(
    goodwill_id: UUID,
    _permission: None = Depends(require_permission("goodwill:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> dict[str, Any]:
    """Get detailed goodwill status including impairment status."""
    try:
        status_info = await service.get_goodwill_status(goodwill_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Goodwill not found")

        return {
            "goodwill_id": str(goodwill_id),
            "goodwill_code": status_info.goodwill_code,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_amortize": status_info.can_amortize,
            "can_test_impairment": status_info.can_test_impairment,
            "can_recognize_impairment": status_info.can_recognize_impairment,
            "can_dispose": status_info.can_dispose,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "impairment_status": status_info.impairment_status,
            "last_impairment_test": status_info.last_impairment_test.isoformat()
            if status_info.last_impairment_test
            else None,
            "last_impairment_loss": float(status_info.last_impairment_loss)
            if status_info.last_impairment_loss
            else None,
            "remaining_value": float(status_info.remaining_value)
            if status_info.remaining_value
            else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get goodwill status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export goodwill data",
    operation_id="export_goodwill",
)
async def export_goodwill(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("goodwill:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_goodwill_service),
) -> Response:
    """Export goodwill data to CSV or Excel."""
    try:
        data = await service.export_goodwill(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            format=format,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"goodwill_{legal_entity_id}_{as_of_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export goodwill: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
