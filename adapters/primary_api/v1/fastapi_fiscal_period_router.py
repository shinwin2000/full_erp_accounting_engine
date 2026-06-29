#!/usr/bin/env python3
"""
Module: fastapi_fiscal_period_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Fiscal Period:
               pembuatan periode, buka, tutup, kunci, buka kembali,
               dan validasi periode untuk posting.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

# Import service
from application.service_layer.service_fiscal_period import (
    FiscalPeriodService,
    CreatePeriodRequest,
    ClosePeriodRequest,
    LockPeriodRequest,
    ReopenPeriodRequest,
    PeriodResponse,
    FiscalPeriodServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class PeriodType(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"


class PeriodStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


# ---------- Request/Response Models ----------

class CreatePeriodRequestModel(BaseModel):
    legal_entity_id: UUID
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    period_type: PeriodType = PeriodType.MONTHLY
    start_date: date | None = None
    end_date: date | None = None

    model_config = ConfigDict(use_enum_values=True)


class PeriodResponseModel(BaseModel):
    period_id: UUID
    legal_entity_id: UUID
    period_type: str
    period_number: int
    year: int
    start_date: date
    end_date: date
    status: str
    created_by: str | None
    created_at: datetime
    closed_at: datetime | None = None
    closed_by: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None


class ClosePeriodRequestModel(BaseModel):
    legal_entity_id: UUID
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    closed_at: datetime | None = None


class LockPeriodRequestModel(BaseModel):
    legal_entity_id: UUID
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)


class ReopenPeriodRequestModel(BaseModel):
    legal_entity_id: UUID
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    reason: str | None = None


class UpdatePeriodRequestModel(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    period_type: PeriodType | None = None


class ValidatePeriodResponseModel(BaseModel):
    is_valid: bool
    period: PeriodResponseModel | None = None
    message: str | None = None


# ============================================================================
# HELPER: Get Correlation ID
# ============================================================================

def get_correlation_id(request: Request) -> str:
    corr_id = request.headers.get("X-Correlation-ID")
    if not corr_id:
        from uuid import uuid4
        corr_id = str(uuid4())
    return corr_id


# ============================================================================
# PERIOD CRUD ENDPOINTS
# ============================================================================

@router.post(
    "/periods",
    response_model=PeriodResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new fiscal period",
)
async def create_period(
    request: Request,
    payload: CreatePeriodRequestModel,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Create a new fiscal period. The period will be created with OPEN status.
    """
    try:
        correlation_id = get_correlation_id(request)
        req = CreatePeriodRequest(
            legal_entity_id=payload.legal_entity_id,
            year=payload.year,
            month=payload.month,
            period_type=payload.period_type.value,
            start_date=payload.start_date,
            end_date=payload.end_date,
            created_by=user.user_id,
        )
        result = await service.create_period(req, correlation_id)
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error creating fiscal period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/periods/{period_id}",
    response_model=PeriodResponseModel,
    summary="Get fiscal period by ID",
)
async def get_period_by_id(
    period_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Get a fiscal period by its UUID.
    """
    try:
        result = await service.get_period_by_id(period_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fiscal period not found",
            )
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fiscal period {period_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/periods",
    response_model=list[PeriodResponseModel],
    summary="List fiscal periods",
)
async def list_periods(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    from_year: int | None = Query(None, description="Filter from year"),
    to_year: int | None = Query(None, description="Filter to year"),
    status: PeriodStatus | None = Query(None, description="Filter by status"),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> list[PeriodResponseModel]:
    """
    List fiscal periods for a legal entity with optional filters.
    """
    try:
        status_enum = None
        if status:
            from domain.fiscal_period.aggregate_root import PeriodStatus as DomainPeriodStatus
            status_enum = DomainPeriodStatus(status.value)
        results = await service.list_periods(
            legal_entity_id=legal_entity_id,
            from_year=from_year,
            to_year=to_year,
            status=status_enum,
        )
        return [
            PeriodResponseModel(
                period_id=p.period_id,
                legal_entity_id=p.legal_entity_id,
                period_type=p.period_type.value,
                period_number=p.period_number,
                year=p.year,
                start_date=p.start_date,
                end_date=p.end_date,
                status=p.status.value,
                created_by=p.created_by,
                created_at=p.created_at,
                closed_at=getattr(p, "closed_at", None),
                closed_by=getattr(p, "closed_by", None),
                updated_at=getattr(p, "updated_at", None),
                updated_by=getattr(p, "updated_by", None),
            )
            for p in results
        ]
    except Exception as e:
        logger.error(f"Error listing fiscal periods: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.patch(
    "/periods/{period_id}",
    response_model=PeriodResponseModel,
    summary="Update fiscal period",
)
async def update_period(
    request: Request,
    period_id: UUID,
    payload: UpdatePeriodRequestModel,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Update fiscal period (start/end dates, period type).
    Only possible for OPEN period.
    """
    try:
        correlation_id = get_correlation_id(request)
        # Need to get the period first to know year/month
        period = await service.get_period_by_id(period_id)
        if not period:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fiscal period not found",
            )
        from application.service_layer.service_fiscal_period import UpdatePeriodRequest as UpdatePeriodRequestDTO
        req = UpdatePeriodRequestDTO(
            start_date=payload.start_date,
            end_date=payload.end_date,
            period_type=payload.period_type.value if payload.period_type else None,
        )
        result = await service.update_period(
            legal_entity_id=period.legal_entity_id,
            year=period.year,
            month=period.period_number,
            request=req,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating fiscal period {period_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# PERIOD STATUS CHANGE ENDPOINTS
# ============================================================================

@router.post(
    "/periods/open",
    response_model=PeriodResponseModel,
    summary="Open a fiscal period",
)
async def open_period(
    request: Request,
    legal_entity_id: UUID = Body(..., description="Legal entity ID"),
    year: int = Body(..., ge=2000, le=2100),
    month: int = Body(..., ge=1, le=12),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Open an existing fiscal period (change status from DRAFT or CLOSED to OPEN).
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.open_period(
            legal_entity_id=legal_entity_id,
            year=year,
            month=month,
            opened_by=user.user_id,
            correlation_id=correlation_id,
        )
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error opening fiscal period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/periods/lock",
    response_model=PeriodResponseModel,
    summary="Lock a fiscal period",
)
async def lock_period(
    request: Request,
    payload: LockPeriodRequestModel,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Lock a fiscal period. Only OPEN period can be locked.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.lock_period(
            legal_entity_id=payload.legal_entity_id,
            year=payload.year,
            month=payload.month,
            locked_by=user.user_id,
            correlation_id=correlation_id,
        )
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error locking fiscal period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/periods/close",
    response_model=PeriodResponseModel,
    summary="Close a fiscal period",
)
async def close_period(
    request: Request,
    payload: ClosePeriodRequestModel,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Close a fiscal period. Period will be locked first if OPEN.
    """
    try:
        correlation_id = get_correlation_id(request)
        req = ClosePeriodRequest(
            legal_entity_id=payload.legal_entity_id,
            year=payload.year,
            month=payload.month,
            closed_by=user.user_id,
            closed_at=payload.closed_at,
        )
        result = await service.close_period(req, correlation_id)
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error closing fiscal period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/periods/reopen",
    response_model=PeriodResponseModel,
    summary="Reopen a closed fiscal period",
)
async def reopen_period(
    request: Request,
    payload: ReopenPeriodRequestModel,
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel:
    """
    Reopen a closed fiscal period (must be CLOSED). Returns to OPEN status.
    """
    try:
        correlation_id = get_correlation_id(request)
        req = ReopenPeriodRequest(
            legal_entity_id=payload.legal_entity_id,
            year=payload.year,
            month=payload.month,
            reopened_by=user.user_id,
            reason=payload.reason,
        )
        result = await service.reopen_period(req, correlation_id)
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error reopening fiscal period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# QUERY ENDPOINTS
# ============================================================================

@router.get(
    "/periods/current",
    response_model=PeriodResponseModel | None,
    summary="Get current open period",
)
async def get_current_period(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    as_of_date: date | None = Query(None, description="As of date (default today)"),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel | None:
    """
    Get the currently open fiscal period for a legal entity.
    """
    try:
        result = await service.get_current_period(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )
        if not result:
            return None
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error getting current period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/periods/validate",
    response_model=ValidatePeriodResponseModel,
    summary="Validate period for posting",
)
async def validate_period_for_posting(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    transaction_date: date = Query(..., description="Transaction date"),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> ValidatePeriodResponseModel:
    """
    Check if the period containing the transaction date is open for posting.
    """
    try:
        is_valid = await service.validate_period_for_posting(
            legal_entity_id=legal_entity_id,
            transaction_date=transaction_date,
        )
        if is_valid:
            period = await service.get_current_period(legal_entity_id, transaction_date)
            if period:
                period_resp = PeriodResponseModel(
                    period_id=period.period_id,
                    legal_entity_id=period.legal_entity_id,
                    period_type=period.period_type.value,
                    period_number=period.period_number,
                    year=period.year,
                    start_date=period.start_date,
                    end_date=period.end_date,
                    status=period.status.value,
                    created_by=period.created_by,
                    created_at=period.created_at,
                    closed_at=getattr(period, "closed_at", None),
                    closed_by=getattr(period, "closed_by", None),
                    updated_at=getattr(period, "updated_at", None),
                    updated_by=getattr(period, "updated_by", None),
                )
                return ValidatePeriodResponseModel(
                    is_valid=True,
                    period=period_resp,
                    message="Period is open for posting",
                )
            else:
                return ValidatePeriodResponseModel(
                    is_valid=False,
                    period=None,
                    message="No open period found for this date",
                )
        else:
            return ValidatePeriodResponseModel(
                is_valid=False,
                period=None,
                message="Period is not open for posting",
            )
    except Exception as e:
        logger.error(f"Error validating period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/periods/next",
    response_model=PeriodResponseModel | None,
    summary="Get next fiscal period",
)
async def get_next_period(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel | None:
    """
    Get the next fiscal period after the given year/month.
    """
    try:
        result = await service.get_next_period(
            legal_entity_id=legal_entity_id,
            year=year,
            month=month,
        )
        if not result:
            return None
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error getting next period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/periods/previous",
    response_model=PeriodResponseModel | None,
    summary="Get previous fiscal period",
)
async def get_previous_period(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> PeriodResponseModel | None:
    """
    Get the previous fiscal period before the given year/month.
    """
    try:
        result = await service.get_previous_period(
            legal_entity_id=legal_entity_id,
            year=year,
            month=month,
        )
        if not result:
            return None
        return PeriodResponseModel(
            period_id=result.period_id,
            legal_entity_id=result.legal_entity_id,
            period_type=result.period_type.value,
            period_number=result.period_number,
            year=result.year,
            start_date=result.start_date,
            end_date=result.end_date,
            status=result.status.value,
            created_by=result.created_by,
            created_at=result.created_at,
            closed_at=getattr(result, "closed_at", None),
            closed_by=getattr(result, "closed_by", None),
            updated_at=getattr(result, "updated_at", None),
            updated_by=getattr(result, "updated_by", None),
        )
    except Exception as e:
        logger.error(f"Error getting previous period: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# STATS ENDPOINT
# ============================================================================

@router.get(
    "/stats",
    response_model=dict[str, int],
    summary="Get fiscal period service statistics",
)
async def get_fiscal_period_stats(
    user: TokenPayload = Depends(get_current_user),
    service: FiscalPeriodService = Depends(get_service(FiscalPeriodService)),
) -> dict[str, int]:
    """
    Get fiscal period service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting fiscal period stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )