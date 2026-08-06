#!/usr/bin/env python3
"""
Module: fastapi_budget_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk manajemen anggaran (budget).
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)
from application.dto_objects.budget_request import (
    BudgetCreateRequest,
    BudgetLineCreateRequest,
    BudgetLineUpdateRequest,
    BudgetResponse,
    BudgetUpdateRequest,
    BudgetVsActualResponse,
)
from application.service_layer.service_budget import BudgetService
from infrastructure.database.session_factory_sqlalchemy import get_async_session

logger = logging.getLogger(__name__)


# ============================================================================
# SCHEMAS (Pydantic) - PERBAIKI DUPLIKASI version
# ============================================================================


class BudgetLineSchema(BaseModel):
    account_id: UUID
    account_code: str
    amount: Decimal = Field(..., ge=0, decimal_places=2)
    note: str | None = None


class BudgetCreateSchema(BaseModel):
    budget_code: str = Field(..., min_length=3, max_length=50)
    budget_name: str = Field(..., min_length=3, max_length=200)
    budget_type: str = Field("operational", pattern="^(operational|capital|cash|project|department|fixed_asset|sales|production|labor)$")
    fiscal_year: int = Field(..., ge=2000, le=2100)
    period: str = Field("monthly", pattern="^(monthly|quarterly|yearly)$")
    version: str = Field("1.0", description="Versi budget (string)")
    effective_date: date
    expiry_date: date | None = None
    currency: str = "IDR"
    lines: list[BudgetLineSchema] = Field(..., min_length=1)
    notes: str | None = None
    tags: list[str] | None = None


class BudgetUpdateSchema(BaseModel):
    budget_name: str | None = Field(None, min_length=3, max_length=200)
    effective_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    tags: list[str] | None = None


class BudgetLineUpdateSchema(BaseModel):
    line_id: UUID
    amount: Decimal = Field(..., ge=0, decimal_places=2)
    note: str | None = None


class BudgetResponseSchema(BaseModel):
    """Response budget - HANYA SATU field 'version' (string)."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    budget_code: str
    budget_name: str
    budget_type: str
    fiscal_year: int
    period: str
    version: str  # Hanya satu version (string)
    status: str
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
    # version_number tetap ada untuk internal, tapi bukan field conflict
    version_number: int = 1
    lines: list[dict[str, Any]] = []


# ============================================================================
# DEPENDENCY
# ============================================================================


async def get_budget_service(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> BudgetService:
    container = request.app.state.container
    svc = await container.resolve_async(BudgetService)
    if hasattr(svc, '_budget_repo') and hasattr(svc._budget_repo, '_session'):
        svc._budget_repo._session = session
    return svc


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/budget", tags=["Budget"])


# ----------------------------------------------------------------------------
# STATIC ROUTES (didahulukan agar tidak tertangkap /{budget_id})
# ----------------------------------------------------------------------------

@router.get(
    "/dashboard",
    summary="Get budget dashboard",
    operation_id="get_budget_dashboard",
)
async def get_budget_dashboard(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> dict[str, Any]:
    try:
        return await service.get_budget_dashboard(legal_entity_id, as_of_date)
    except Exception as e:
        logger.exception(f"Failed to get budget dashboard: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/alerts",
    summary="Get budget alerts",
    operation_id="get_budget_alerts",
)
async def get_budget_alerts(
    threshold_percent: float = Query(5.0, ge=0, le=100),
    severity: str | None = Query(None),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> list[dict[str, Any]]:
    try:
        return await service.get_budget_alerts(
            legal_entity_id,
            threshold_percent=Decimal(str(threshold_percent)),
            severity=severity,
        )
    except Exception as e:
        logger.exception(f"Failed to get budget alerts: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export",
    summary="Export budgets",
    operation_id="export_budgets",
)
async def export_budgets(
    fiscal_year: int = Query(..., description="Fiscal year"),
    format: str = Query("csv", pattern="^(csv|excel)$"),
    budget_type: str | None = Query(None),
    _permission: None = Depends(require_permission("budget:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> Response:
    try:
        data = await service.export_budgets(legal_entity_id, fiscal_year, format, budget_type)
        media_type = "text/csv" if format == "csv" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"budgets_{legal_entity_id}_{fiscal_year}.{format}"
        return Response(content=data, media_type=media_type, headers={"Content-Disposition": f"attachment; filename={filename}"})
    except Exception as e:
        logger.exception(f"Failed to export budgets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{budget_id}/vs-actual",
    response_model=BudgetVsActualResponse | None,
    summary="Get budget vs actual for a specific period",
    operation_id="get_budget_vs_actual",
)
async def get_budget_vs_actual(
    budget_id: UUID,
    period: int = Query(..., ge=1, le=12),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetVsActualResponse | None:
    try:
        return await service.get_budget_vs_actual(budget_id, legal_entity_id, period)
    except Exception as e:
        logger.exception(f"Failed to get budget vs actual: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{budget_id}/vs-actual-ytd",
    response_model=BudgetVsActualResponse | None,
    summary="Get budget vs actual YTD",
    operation_id="get_budget_vs_actual_ytd",
)
async def get_budget_vs_actual_ytd(
    budget_id: UUID,
    as_of_month: int = Query(..., ge=1, le=12),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetVsActualResponse | None:
    try:
        return await service.get_budget_vs_actual_ytd(budget_id, legal_entity_id, as_of_month)
    except Exception as e:
        logger.exception(f"Failed to get budget vs actual YTD: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DYNAMIC ROUTES (dengan path parameter)
# ----------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[BudgetResponseSchema],
    summary="List budgets",
    operation_id="list_budgets",
)
async def list_budgets(
    fiscal_year: int | None = Query(None),
    status: str | None = Query(None),
    _permission: None = Depends(require_permission("budget:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> list[BudgetResponseSchema]:
    try:
        budgets = await service.list_budgets(legal_entity_id, fiscal_year, status)
        return [BudgetResponseSchema(**b.__dict__) for b in budgets]
    except Exception as e:
        logger.exception(f"Failed to list budgets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/",
    response_model=BudgetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create budget",
    operation_id="create_budget",
)
async def create_budget(
    request: BudgetCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("budget:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        if idempotency_key:
            # cek cache sederhana
            from hashlib import sha256
            import json
            cache_key = sha256(f"create_budget:{idempotency_key}".encode()).hexdigest()
            # (implementasi sederhana, skip untuk singkat)
            pass

        create_request = BudgetCreateRequest(
            budget_code=request.budget_code,
            budget_name=request.budget_name,
            budget_type=request.budget_type,
            fiscal_year=request.fiscal_year,
            period=request.period,
            version=request.version,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            currency=request.currency,
            lines=[
                BudgetLineCreateRequest(
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                )
                for line in request.lines
            ],
            notes=request.notes,
            tags=request.tags,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.create_budget(create_request)
        return BudgetResponseSchema(**result.__dict__)
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
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.get_budget(budget_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to get budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{budget_id}",
    response_model=BudgetResponseSchema,
    summary="Update budget",
    operation_id="update_budget",
)
async def update_budget(
    budget_id: UUID,
    request: BudgetUpdateSchema,
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        update_request = BudgetUpdateRequest(
            id=budget_id,
            budget_name=request.budget_name,
            effective_date=request.effective_date,
            expiry_date=request.expiry_date,
            notes=request.notes,
            tags=request.tags,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.update_budget(update_request)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to update budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{budget_id}",
    response_model=dict[str, Any],
    summary="Delete/archive budget",
    operation_id="delete_budget",
)
async def delete_budget(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> dict[str, Any]:
    try:
        result = await service.delete_budget(budget_id, current_user.user_id)
        return {"budget_id": str(budget_id), "deleted": result, "message": "Budget archived" if result else "Budget not found"}
    except Exception as e:
        logger.exception(f"Failed to delete budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WORKFLOW ACTIONS
# ----------------------------------------------------------------------------

@router.post(
    "/{budget_id}/submit",
    response_model=BudgetResponseSchema,
    summary="Submit budget for approval",
    operation_id="submit_budget",
)
async def submit_budget(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.submit_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
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
    _permission: None = Depends(require_permission("budget:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.approve_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
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
    reason: str = Query(..., min_length=5),
    _permission: None = Depends(require_permission("budget:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.reject_budget(budget_id, current_user.user_id, reason)
        return BudgetResponseSchema(**result.__dict__)
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
    _permission: None = Depends(require_permission("budget:activate")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.activate_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
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
    _permission: None = Depends(require_permission("budget:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.lock_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
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
    _permission: None = Depends(require_permission("budget:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.unlock_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to unlock budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/archive",
    response_model=BudgetResponseSchema,
    summary="Archive budget",
    operation_id="archive_budget",
)
async def archive_budget(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.archive_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to archive budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/close",
    response_model=BudgetResponseSchema,
    summary="Close budget",
    operation_id="close_budget",
)
async def close_budget(
    budget_id: UUID,
    _permission: None = Depends(require_permission("budget:close")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.close_budget(budget_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to close budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{budget_id}/cancel",
    response_model=BudgetResponseSchema,
    summary="Cancel budget",
    operation_id="cancel_budget",
)
async def cancel_budget(
    budget_id: UUID,
    reason: str = Query(..., min_length=5),
    _permission: None = Depends(require_permission("budget:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.cancel_budget(budget_id, current_user.user_id, reason)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to cancel budget: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LINE OPERATIONS
# ----------------------------------------------------------------------------

@router.post(
    "/{budget_id}/lines",
    response_model=BudgetResponseSchema,
    summary="Add line to budget",
    operation_id="add_budget_line",
)
async def add_budget_line(
    budget_id: UUID,
    request: BudgetLineSchema,
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        line_request = BudgetLineCreateRequest(
            account_id=request.account_id,
            account_code=request.account_code,
            amount=request.amount,
            note=request.note,
        )
        result = await service.add_line(budget_id, line_request, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to add budget line: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch(
    "/{budget_id}/lines",
    response_model=BudgetResponseSchema,
    summary="Update budget line",
    operation_id="update_budget_line",
)
async def update_budget_line(
    budget_id: UUID,
    request: BudgetLineUpdateSchema,
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        line_request = BudgetLineUpdateRequest(
            line_id=request.line_id,
            amount=request.amount,
            note=request.note,
        )
        result = await service.update_line(budget_id, line_request, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to update budget line: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{budget_id}/lines/{line_id}",
    response_model=BudgetResponseSchema,
    summary="Remove budget line",
    operation_id="remove_budget_line",
)
async def remove_budget_line(
    budget_id: UUID,
    line_id: UUID,
    _permission: None = Depends(require_permission("budget:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: BudgetService = Depends(get_budget_service),
) -> BudgetResponseSchema:
    try:
        result = await service.remove_line(budget_id, line_id, current_user.user_id)
        return BudgetResponseSchema(**result.__dict__)
    except Exception as e:
        logger.exception(f"Failed to remove budget line: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]