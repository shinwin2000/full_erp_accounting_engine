#!/usr/bin/env python3
"""
Module: fastapi_payment_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Payment (AP/AR):
               CRUD payment, status transitions (approve, process, confirm,
               send, receive, apply, allocate, cancel, void), dan query payment.
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

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

# Import service
from application.service_layer.service_payment import (
    PaymentService,
    Payment,
    PaymentStatus,
    PaymentType,
    PaymentServiceError,
    PaymentNotFoundError,
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

class PaymentStatusEnum(str, Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    SENT = "sent"
    RECEIVED = "received"
    APPLIED = "applied"
    ALLOCATED = "allocated"
    CANCELLED = "cancelled"
    VOIDED = "voided"


class PaymentTypeEnum(str, Enum):
    AP = "ap"  # Accounts Payable
    AR = "ar"  # Accounts Receivable


# ---------- Request/Response Models ----------

class CreatePaymentRequest(BaseModel):
    legal_entity_id: UUID
    payment_number: str = Field(..., min_length=1, max_length=50, description="Unique payment number")
    payment_type: PaymentTypeEnum
    counterparty_id: UUID = Field(..., description="Supplier ID for AP, Customer ID for AR")
    amount: Decimal = Field(..., gt=0, description="Payment amount")
    payment_date: date
    invoice_id: UUID | None = None
    reference_number: str | None = Field(None, max_length=100)
    description: str | None = Field(None, max_length=500)

    model_config = ConfigDict(use_enum_values=True)


class UpdatePaymentRequest(BaseModel):
    description: str | None = Field(None, max_length=500)
    reference_number: str | None = Field(None, max_length=100)


class PaymentResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    payment_number: str
    payment_type: str
    counterparty_id: UUID
    invoice_id: UUID | None
    amount: Decimal
    payment_date: date
    reference_number: str | None
    description: str | None
    status: str
    is_allocated: bool
    is_applied: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    version: int


class ApprovePaymentRequest(BaseModel):
    payment_id: UUID


class ProcessPaymentRequest(BaseModel):
    payment_id: UUID


class ConfirmPaymentRequest(BaseModel):
    payment_id: UUID


class SendPaymentRequest(BaseModel):
    payment_id: UUID


class ReceivePaymentRequest(BaseModel):
    payment_id: UUID


class ApplyPaymentRequest(BaseModel):
    payment_id: UUID
    applied_to: str = Field(..., description="Invoice number or reference")


class AllocatePaymentRequest(BaseModel):
    payment_id: UUID
    allocation_data: dict[str, Any] = Field(..., description="Allocation details")


class CancelPaymentRequest(BaseModel):
    payment_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)


class VoidPaymentRequest(BaseModel):
    payment_id: UUID
    reason: str = Field(..., min_length=1, max_length=500)


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
# HELPER: Convert Domain to Response
# ============================================================================

def to_payment_response(payment: Payment) -> PaymentResponseModel:
    return PaymentResponseModel(
        id=payment.id,
        legal_entity_id=payment.legal_entity_id,
        payment_number=payment.payment_number,
        payment_type=payment.payment_type.value if payment.payment_type else "ap",
        counterparty_id=payment.counterparty_id,
        invoice_id=payment.invoice_id,
        amount=payment.amount,
        payment_date=payment.payment_date,
        reference_number=payment.reference_number,
        description=payment.description,
        status=payment.status.value if payment.status else "draft",
        is_allocated=payment.is_allocated,
        is_applied=payment.is_applied,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        created_by=payment.created_by,
        version=payment.version,
    )


# ============================================================================
# PAYMENT CRUD ENDPOINTS
# ============================================================================

@router.post(
    "/payments",
    response_model=PaymentResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new payment",
)
async def create_payment(
    request: Request,
    payload: CreatePaymentRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Create a new payment (AP or AR).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "create_payment"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PaymentResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.create_payment(
            legal_entity_id=payload.legal_entity_id,
            payment_number=payload.payment_number,
            payment_type=payload.payment_type.value,
            counterparty_id=payload.counterparty_id,
            amount=payload.amount,
            payment_date=payload.payment_date,
            invoice_id=payload.invoice_id,
            reference_number=payload.reference_number,
            description=payload.description,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_payment_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating payment: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentResponseModel,
    summary="Get payment by ID",
)
async def get_payment(
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Get a single payment by ID.
    """
    try:
        result = await service.get_payment(payment_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )
        return to_payment_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/payments",
    response_model=list[PaymentResponseModel],
    summary="List payments",
)
async def list_payments(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    payment_type: PaymentTypeEnum | None = Query(None, description="Filter by payment type"),
    status: PaymentStatusEnum | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> list[PaymentResponseModel]:
    """
    List payments with filters.
    """
    try:
        results = await service.list_payments(
            legal_entity_id=legal_entity_id,
            payment_type=payment_type.value if payment_type else None,
            status=status.value if status else None,
        )
        # Apply pagination manually (since service doesn't support pagination yet)
        paginated = results[offset:offset + limit]
        return [to_payment_response(p) for p in paginated]
    except Exception as e:
        logger.error(f"Error listing payments: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.patch(
    "/payments/{payment_id}",
    response_model=PaymentResponseModel,
    summary="Update payment",
)
async def update_payment(
    request: Request,
    payment_id: UUID,
    payload: UpdatePaymentRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Update payment details (description, reference number).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_payment"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PaymentResponseModel(**cached)

    try:
        # Note: This endpoint is currently not fully implemented in the service.
        # We add idempotency support but still raise 501 as per original logic.
        correlation_id = get_correlation_id(request)
        # Get current payment to check if exists
        payment = await service.get_payment(payment_id)
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )
        # Since service doesn't have a direct update method, we'll raise 501.
        # However, we cache a placeholder response to satisfy idempotency.
        # In a real implementation, you would call the actual update method.
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Update payment not yet implemented in service",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# PAYMENT STATUS TRANSITION ENDPOINTS
# ============================================================================

@router.post(
    "/payments/{payment_id}/approve",
    response_model=PaymentResponseModel,
    summary="Approve payment",
)
async def approve_payment(
    request: Request,
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Approve a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.approve_payment(
            payment_id=payment_id,
            approved_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error approving payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/process",
    response_model=PaymentResponseModel,
    summary="Process payment",
)
async def process_payment(
    request: Request,
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Process a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.process_payment(
            payment_id=payment_id,
            processed_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error processing payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/confirm",
    response_model=PaymentResponseModel,
    summary="Confirm payment",
)
async def confirm_payment(
    request: Request,
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Confirm a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.confirm_payment(
            payment_id=payment_id,
            confirmed_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error confirming payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/send",
    response_model=PaymentResponseModel,
    summary="Send payment",
)
async def send_payment(
    request: Request,
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Send a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.send_payment(
            payment_id=payment_id,
            sent_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error sending payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/receive",
    response_model=PaymentResponseModel,
    summary="Receive payment",
)
async def receive_payment(
    request: Request,
    payment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Receive a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.receive_payment(
            payment_id=payment_id,
            received_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error receiving payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/apply",
    response_model=PaymentResponseModel,
    summary="Apply payment",
)
async def apply_payment(
    request: Request,
    payment_id: UUID,
    payload: ApplyPaymentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Apply a payment to an invoice or reference.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.apply_payment(
            payment_id=payment_id,
            applied_to=payload.applied_to,
            applied_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error applying payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/allocate",
    response_model=PaymentResponseModel,
    summary="Allocate payment",
)
async def allocate_payment(
    request: Request,
    payment_id: UUID,
    payload: AllocatePaymentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Allocate a payment to multiple invoices or lines.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.allocate_payment(
            payment_id=payment_id,
            allocation_data=payload.allocation_data,
            allocated_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error allocating payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/cancel",
    response_model=PaymentResponseModel,
    summary="Cancel payment",
)
async def cancel_payment(
    request: Request,
    payment_id: UUID,
    payload: CancelPaymentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Cancel a payment.
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.cancel_payment(
            payment_id=payment_id,
            reason=payload.reason,
            cancelled_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error cancelling payment {payment_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/payments/{payment_id}/void",
    response_model=PaymentResponseModel,
    summary="Void payment",
)
async def void_payment(
    request: Request,
    payment_id: UUID,
    payload: VoidPaymentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> PaymentResponseModel:
    """
    Void a payment (can only be done before posting).
    """
    try:
        correlation_id = get_correlation_id(request)
        result = await service.void_payment(
            payment_id=payment_id,
            reason=payload.reason,
            voided_by=user.user_id,
            correlation_id=correlation_id,
        )
        return to_payment_response(result)
    except PaymentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )
    except PaymentServiceError as e:
        logger.warning(f"Payment service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error voiding payment {payment_id}: {e}", exc_info=True)
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
    summary="Get payment service statistics",
)
async def get_payment_stats(
    user: TokenPayload = Depends(get_current_user),
    service: PaymentService = Depends(get_service(PaymentService)),
) -> dict[str, int]:
    """
    Get payment service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting payment stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )