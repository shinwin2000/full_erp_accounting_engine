#!/usr/bin/env python3
"""
Module: fastapi_capital_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Capital,
               Dividend, dan Retained Earnings:
               - Capital Contribution (setoran modal)
               - Capital Withdrawal (penarikan modal)
               - Dividend (deviden)
               - Retained Earnings (laba ditahan)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
)

# Import service
from application.service_layer.service_capital import (
    CapitalContributionRequest,
    CapitalService,
    DividendDeclarationRequest,
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


router = APIRouter()


# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class ContributionType(str, Enum):
    CASH = "CASH"
    ASSET = "ASSET"
    INVENTORY = "INVENTORY"
    INTELLECTUAL_PROPERTY = "INTELLECTUAL_PROPERTY"


class DividendStatus(str, Enum):
    DECLARED = "DECLARED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    CANCELLED = "CANCELLED"


# ---------- Capital Contribution Models ----------

class RecordCapitalContributionRequest(BaseModel):
    legal_entity_id: UUID
    amount: Decimal = Field(..., gt=0, description="Amount in base currency")
    contribution_date: date
    description: str | None = Field(None, max_length=500)
    contributor_id: UUID | None = None
    contribution_type: ContributionType = ContributionType.CASH

    model_config = ConfigDict(use_enum_values=True)


class CapitalContributionResponseModel(BaseModel):
    contribution_id: UUID
    legal_entity_id: UUID
    amount: Decimal
    contribution_date: date
    status: str
    created_at: datetime


class ApproveCapitalContributionRequest(BaseModel):
    contribution_id: UUID


class PostCapitalContributionRequest(BaseModel):
    contribution_id: UUID


class CancelCapitalContributionRequest(BaseModel):
    contribution_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)


# ---------- Capital Withdrawal Models ----------

class RecordCapitalWithdrawalRequest(BaseModel):
    legal_entity_id: UUID
    amount: Decimal = Field(..., gt=0, description="Amount in base currency")
    withdrawal_date: date
    description: str | None = Field(None, max_length=500)


class ApproveCapitalWithdrawalRequest(BaseModel):
    withdrawal_id: UUID


class PostCapitalWithdrawalRequest(BaseModel):
    withdrawal_id: UUID


class CancelCapitalWithdrawalRequest(BaseModel):
    withdrawal_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)


# ---------- Dividend Models ----------

class DeclareDividendRequest(BaseModel):
    legal_entity_id: UUID
    total_amount: Decimal = Field(..., gt=0, description="Total dividend amount")
    declaration_date: date
    payment_date: date | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("payment_date")
    def validate_payment_date(cls, v, info):
        if v and v < info.data.get("declaration_date", date.min):
            raise ValueError("Payment date must be after declaration date")
        return v


class DividendResponseModel(BaseModel):
    dividend_id: UUID
    legal_entity_id: UUID
    total_amount: Decimal
    paid_amount: Decimal
    declaration_date: date
    status: str
    created_at: datetime


class ApproveDividendRequest(BaseModel):
    dividend_id: UUID


class PayDividendRequest(BaseModel):
    dividend_id: UUID
    amount: Decimal = Field(..., gt=0)
    is_full: bool = True


class CancelDividendRequest(BaseModel):
    dividend_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)


# ---------- Retained Earnings Models ----------

class AdjustRetainedEarningsRequest(BaseModel):
    legal_entity_id: UUID
    amount: Decimal
    adjustment_date: date
    description: str = Field(..., min_length=1, max_length=500)


class TransferRetainedEarningsRequest(BaseModel):
    from_legal_entity_id: UUID
    to_legal_entity_id: UUID
    amount: Decimal = Field(..., gt=0)
    transfer_date: date


class UpdateRetainedEarningsRequest(BaseModel):
    legal_entity_id: UUID
    new_balance: Decimal
    as_of_date: date


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
# CAPITAL CONTRIBUTION ENDPOINTS
# ============================================================================

@router.post(
    "/contributions",
    response_model=CapitalContributionResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Record a capital contribution",
)
async def record_capital_contribution(
    request: Request,
    payload: RecordCapitalContributionRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> CapitalContributionResponseModel:
    """
    Record a capital contribution (setoran modal) to the company.
    """
    try:
        correlation_id = get_correlation_id(request)
        req = CapitalContributionRequest(
            legal_entity_id=payload.legal_entity_id,
            amount=payload.amount,
            contribution_date=payload.contribution_date,
            description=payload.description,
            contributor_id=payload.contributor_id,
            contribution_type=payload.contribution_type,
        )
        result = await service.record_capital_contribution(
            request=req,
            user_id=user.user_id,
            correlation_id=correlation_id,
        )
        return CapitalContributionResponseModel(
            contribution_id=result.contribution_id,
            legal_entity_id=result.legal_entity_id,
            amount=result.amount,
            contribution_date=result.contribution_date,
            status=result.status,
            created_at=result.created_at,
        )
    except Exception as e:
        logger.error(f"Error recording capital contribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/contributions/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve a capital contribution",
)
async def approve_capital_contribution(
    request: Request,
    payload: ApproveCapitalContributionRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Approve a capital contribution.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.approve_capital_contribution(
            contribution_id=payload.contribution_id,
            approved_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error approving capital contribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/contributions/post",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Post capital contribution to GL",
)
async def post_capital_contribution(
    request: Request,
    payload: PostCapitalContributionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Post capital contribution to General Ledger.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "post_capital_contribution"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        await service.post_capital_contribution(
            contribution_id=payload.contribution_id,
            posted_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "contribution_id": str(payload.contribution_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error posting capital contribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/contributions/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a capital contribution",
)
async def cancel_capital_contribution(
    request: Request,
    payload: CancelCapitalContributionRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Cancel a capital contribution.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.cancel_capital_contribution(
            contribution_id=payload.contribution_id,
            reason=payload.reason,
            cancelled_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error cancelling capital contribution: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# CAPITAL WITHDRAWAL ENDPOINTS
# ============================================================================

@router.post(
    "/withdrawals",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record a capital withdrawal",
)
async def record_capital_withdrawal(
    request: Request,
    payload: RecordCapitalWithdrawalRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Record a capital withdrawal (penarikan modal).
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.record_capital_withdrawal(
            legal_entity_id=payload.legal_entity_id,
            amount=payload.amount,
            withdrawal_date=payload.withdrawal_date,
            description=payload.description,
            user_id=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error recording capital withdrawal: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/withdrawals/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve a capital withdrawal",
)
async def approve_capital_withdrawal(
    request: Request,
    payload: ApproveCapitalWithdrawalRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Approve a capital withdrawal.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.approve_capital_withdrawal(
            withdrawal_id=payload.withdrawal_id,
            approved_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error approving capital withdrawal: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/withdrawals/post",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Post capital withdrawal to GL",
)
async def post_capital_withdrawal(
    request: Request,
    payload: PostCapitalWithdrawalRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Post capital withdrawal to General Ledger.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "post_capital_withdrawal"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        await service.post_capital_withdrawal(
            withdrawal_id=payload.withdrawal_id,
            posted_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "withdrawal_id": str(payload.withdrawal_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error posting capital withdrawal: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/withdrawals/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a capital withdrawal",
)
async def cancel_capital_withdrawal(
    request: Request,
    payload: CancelCapitalWithdrawalRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Cancel a capital withdrawal.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.cancel_capital_withdrawal(
            withdrawal_id=payload.withdrawal_id,
            reason=payload.reason,
            cancelled_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error cancelling capital withdrawal: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# DIVIDEND ENDPOINTS
# ============================================================================

@router.post(
    "/dividends",
    response_model=DividendResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Declare a dividend",
)
async def declare_dividend(
    request: Request,
    payload: DeclareDividendRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> DividendResponseModel:
    """
    Declare a dividend (deviden).
    """
    try:
        correlation_id = get_correlation_id(request)
        req = DividendDeclarationRequest(
            legal_entity_id=payload.legal_entity_id,
            total_amount=payload.total_amount,
            declaration_date=payload.declaration_date,
            payment_date=payload.payment_date,
            description=payload.description,
            declared_by=user.user_id,
        )
        result = await service.declare_dividend(
            request=req,
            user_id=user.user_id,
            correlation_id=correlation_id,
        )
        return DividendResponseModel(
            dividend_id=result.dividend_id,
            legal_entity_id=result.legal_entity_id,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            declaration_date=result.declaration_date,
            status=result.status,
            created_at=result.created_at,
        )
    except Exception as e:
        logger.error(f"Error declaring dividend: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/dividends/approve",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Approve a dividend",
)
async def approve_dividend(
    request: Request,
    payload: ApproveDividendRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Approve a dividend.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.approve_dividend(
            dividend_id=payload.dividend_id,
            approved_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error approving dividend: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/dividends/pay",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Pay dividend",
)
async def pay_dividend(
    request: Request,
    payload: PayDividendRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Pay dividend (full or partial).
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.pay_dividend(
            dividend_id=payload.dividend_id,
            amount=payload.amount,
            paid_by=user.user_id,
            is_full=payload.is_full,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error paying dividend: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/dividends/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a dividend",
)
async def cancel_dividend(
    request: Request,
    payload: CancelDividendRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Cancel a dividend.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.cancel_dividend(
            dividend_id=payload.dividend_id,
            reason=payload.reason,
            cancelled_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error cancelling dividend: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# RETAINED EARNINGS ENDPOINTS
# ============================================================================

@router.post(
    "/retained-earnings/adjust",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Adjust retained earnings",
)
async def adjust_retained_earnings(
    request: Request,
    payload: AdjustRetainedEarningsRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Adjust retained earnings (laba ditahan).
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.adjust_retained_earnings(
            legal_entity_id=payload.legal_entity_id,
            amount=payload.amount,
            adjustment_date=payload.adjustment_date,
            description=payload.description,
            adjusted_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error adjusting retained earnings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/retained-earnings/transfer",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Transfer retained earnings",
)
async def transfer_retained_earnings(
    request: Request,
    payload: TransferRetainedEarningsRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Transfer retained earnings between legal entities.
    """
    try:
        correlation_id = get_correlation_id(request)
        await service.transfer_retained_earnings(
            from_legal_entity_id=payload.from_legal_entity_id,
            to_legal_entity_id=payload.to_legal_entity_id,
            amount=payload.amount,
            transfer_date=payload.transfer_date,
            transferred_by=user.user_id,
            correlation_id=correlation_id,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error transferring retained earnings: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/retained-earnings/update",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Update retained earnings balance",
)
async def update_retained_earnings(
    request: Request,
    payload: UpdateRetainedEarningsRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> Response:
    """
    Update retained earnings balance (for manual corrections).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_retained_earnings"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        await service.update_retained_earnings(
            legal_entity_id=payload.legal_entity_id,
            new_balance=payload.new_balance,
            as_of_date=payload.as_of_date,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "legal_entity_id": str(payload.legal_entity_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error(f"Error updating retained earnings: {e}", exc_info=True)
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
    summary="Get capital service statistics",
)
async def get_capital_stats(
    user: TokenPayload = Depends(get_current_user),
    service: CapitalService = Depends(get_service(CapitalService)),
) -> dict[str, int]:
    """
    Get capital service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting capital stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )