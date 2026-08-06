#!/usr/bin/env python3
"""
Module: fastapi_customer_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Customer:
               CRUD customer, update status, credit limit management,
               balance management, dan data customer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
)

# Import service
from application.service_layer.service_customer import (
    Customer,
    CustomerNotFoundError,
    CustomerService,
    CustomerServiceError,
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

class CustomerStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


# ---------- Request/Response Models ----------

class CreateCustomerRequest(BaseModel):
    legal_entity_id: UUID
    customer_code: str = Field(..., min_length=1, max_length=50, description="Unique customer code")
    name: str = Field(..., min_length=1, max_length=255, description="Customer name")
    npwp: str | None = Field(None, max_length=20, description="Tax ID (NPWP)")
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    country: str = Field("ID", max_length=2, description="ISO country code")
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    credit_limit: Decimal = Field(Decimal("0"), ge=0, description="Credit limit")

    model_config = ConfigDict(use_enum_values=True)


class UpdateCustomerRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    is_active: bool | None = None
    status: CustomerStatusEnum | None = None


class CustomerResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    customer_code: str
    name: str
    npwp: str | None
    address: str | None
    city: str | None
    country: str
    phone: str | None
    email: str | None
    contact_person: str | None
    credit_limit: Decimal
    current_balance: Decimal
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    version: int


class UpdateCreditLimitRequest(BaseModel):
    new_limit: Decimal = Field(..., ge=0, description="New credit limit")


class UpdateBalanceRequest(BaseModel):
    delta: Decimal = Field(..., description="Amount to add/subtract (positive = increase balance)")


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

def to_customer_response(customer: Customer) -> CustomerResponseModel:
    return CustomerResponseModel(
        id=customer.id,
        legal_entity_id=customer.legal_entity_id,
        customer_code=customer.customer_code,
        name=customer.name,
        npwp=customer.npwp,
        address=customer.address,
        city=customer.city,
        country=customer.country,
        phone=customer.phone,
        email=customer.email,
        contact_person=customer.contact_person,
        credit_limit=customer.credit_limit,
        current_balance=customer.current_balance,
        is_active=customer.is_active,
        status=customer.status.value if customer.status else "active",
        created_at=customer.created_at,
        updated_at=customer.updated_at,
        created_by=customer.created_by,
        version=customer.version,
    )


# ============================================================================
# CUSTOMER CRUD ENDPOINTS
# ============================================================================

@router.post(
    "/customers",
    response_model=CustomerResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new customer",
)
async def create_customer(
    request: Request,
    payload: CreateCustomerRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    """
    Create a new customer.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "create_customer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CustomerResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.create_customer(
            legal_entity_id=payload.legal_entity_id,
            customer_code=payload.customer_code,
            name=payload.name,
            npwp=payload.npwp,
            address=payload.address,
            city=payload.city,
            country=payload.country,
            phone=payload.phone,
            email=payload.email,
            contact_person=payload.contact_person,
            credit_limit=payload.credit_limit,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_customer_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except CustomerServiceError as e:
        logger.warning(f"Customer service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating customer: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/customers/{customer_id}",
    response_model=CustomerResponseModel,
    summary="Get customer by ID",
)
async def get_customer(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    """
    Get a single customer by ID.
    """
    try:
        result = await service.get_customer(customer_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        return to_customer_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/customers",
    response_model=list[CustomerResponseModel],
    summary="List customers",
)
async def list_customers(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    status: CustomerStatusEnum | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[CustomerResponseModel]:
    """
    List customers with filters.
    """
    try:
        results = await service.list_customers(
            legal_entity_id=legal_entity_id,
            is_active=is_active,
            status=status.value if status else None,
        )
        # Apply pagination manually (since service doesn't support pagination yet)
        paginated = results[offset:offset + limit]
        return [to_customer_response(c) for c in paginated]
    except Exception as e:
        logger.error(f"Error listing customers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.patch(
    "/customers/{customer_id}",
    response_model=CustomerResponseModel,
    summary="Update customer",
)
async def update_customer(
    request: Request,
    customer_id: UUID,
    payload: UpdateCustomerRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    """
    Update customer details (name, address, contact, etc.).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_customer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CustomerResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        # Convert status to string if provided
        status_str = payload.status.value if payload.status else None
        result = await service.update_customer(
            customer_id=customer_id,
            name=payload.name,
            address=payload.address,
            city=payload.city,
            phone=payload.phone,
            email=payload.email,
            contact_person=payload.contact_person,
            is_active=payload.is_active,
            status=status_str,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        response = to_customer_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    except CustomerServiceError as e:
        logger.warning(f"Customer service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# CUSTOMER STATUS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/customers/{customer_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate customer",
)
async def deactivate_customer(
    request: Request,
    customer_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> Response:
    """
    Deactivate a customer (soft delete).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "deactivate_customer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        # Get current customer to check if exists
        customer = await service.get_customer(customer_id)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        # Update to inactive
        await service.update_customer(
            customer_id=customer_id,
            is_active=False,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "customer_id": str(customer_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/customers/{customer_id}/activate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Activate customer",
)
async def activate_customer(
    request: Request,
    customer_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> Response:
    """
    Activate a previously deactivated customer.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "activate_customer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        customer = await service.get_customer(customer_id)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        await service.update_customer(
            customer_id=customer_id,
            is_active=True,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "customer_id": str(customer_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.delete(
    "/customers/{customer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete (soft-delete) a customer",
)
async def delete_customer(
    request: Request,
    customer_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> Response:
    """
    Delete a customer.

    Customers are never hard-deleted: doing so would break referential
    integrity with existing AR invoices, journal entries, and audit trails.
    DELETE performs the same soft-delete (deactivate) as
    POST /customers/{customer_id}/deactivate, so REST-conventional
    clients that issue DELETE don't hit a 405.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "delete_customer"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        customer = await service.get_customer(customer_id)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        await service.update_customer(
            customer_id=customer_id,
            is_active=False,
            status=CustomerStatusEnum.INACTIVE.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "customer_id": str(customer_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/customers/{customer_id}/status",
    response_model=CustomerResponseModel,
    summary="Change customer status",
)
async def change_customer_status(
    request: Request,
    customer_id: UUID,
    new_status: CustomerStatusEnum = Body(..., description="New status"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    """
    Change customer status (active, inactive, suspended, blacklisted).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "change_customer_status"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CustomerResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_customer(
            customer_id=customer_id,
            status=new_status.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        response = to_customer_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except HTTPException:
        raise
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    except Exception as e:
        logger.error(f"Error changing customer status {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# CREDIT LIMIT MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/customers/{customer_id}/credit-limit",
    response_model=CustomerResponseModel,
    summary="Update customer credit limit",
)
async def update_credit_limit(
    request: Request,
    customer_id: UUID,
    payload: UpdateCreditLimitRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    """
    Update credit limit for a customer.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_credit_limit"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return CustomerResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_credit_limit(
            customer_id=customer_id,
            new_limit=payload.new_limit,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        response = to_customer_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    except Exception as e:
        logger.error(f"Error updating credit limit for customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# BALANCE MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/customers/{customer_id}/balance",
    response_model=dict[str, Decimal],
    summary="Update customer balance",
)
async def update_balance(
    request: Request,
    customer_id: UUID,
    payload: UpdateBalanceRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, Decimal]:
    """
    Update customer balance (add/subtract amount).
    Positive delta increases balance (customer owes more).
    Negative delta decreases balance (customer pays).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_balance"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        correlation_id = get_correlation_id(request)
        new_balance = await service.update_balance(
            customer_id=customer_id,
            delta=payload.delta,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = {"new_balance": new_balance}

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)

        return response
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found",
        )
    except Exception as e:
        logger.error(f"Error updating balance for customer {customer_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/customers/{customer_id}/balance",
    response_model=dict[str, Decimal],
    summary="Get customer balance",
)
async def get_balance(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, Decimal]:
    """
    Get current balance for a customer.
    """
    try:
        customer = await service.get_customer(customer_id)
        if not customer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer not found",
            )
        return {"current_balance": customer.current_balance}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting balance for customer {customer_id}: {e}", exc_info=True)
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
    summary="Get customer service statistics",
)
async def get_customer_stats(
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, int]:
    """
    Get customer service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting customer stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
