#!/usr/bin/env python3
"""
Module: fastapi_supplier_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Supplier/Vendor:
               CRUD supplier, update status, withholding category,
               payment terms, dan manajemen data supplier.
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
from application.service_layer.service_supplier import (
    Supplier,
    SupplierNotFoundError,
    SupplierService,
    SupplierServiceError,
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

class SupplierStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLACKLISTED = "blacklisted"


class WithholdingCategoryEnum(str, Enum):
    NONE = "none"
    PPH23 = "pph23"
    PPH22 = "pph22"
    PPH4_2 = "pph4_2"


# ---------- Request/Response Models ----------

class CreateSupplierRequest(BaseModel):
    legal_entity_id: UUID
    supplier_code: str = Field(..., min_length=1, max_length=50, description="Unique supplier code")
    name: str = Field(..., min_length=1, max_length=255, description="Supplier name")
    npwp: str | None = Field(None, max_length=20, description="Tax ID (NPWP)")
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    country: str = Field("ID", max_length=2, description="ISO country code")
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    payment_terms_days: int = Field(30, ge=0, le=365, description="Payment terms in days")
    credit_limit: Decimal = Field(Decimal("0"), ge=0)
    withholding_category: WithholdingCategoryEnum = WithholdingCategoryEnum.NONE

    model_config = ConfigDict(use_enum_values=True)


class UpdateSupplierRequest(BaseModel):
    name: str | None = Field(None, max_length=255)
    address: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)
    contact_person: str | None = Field(None, max_length=255)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    credit_limit: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None
    status: SupplierStatusEnum | None = None


class SupplierResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    supplier_code: str
    name: str
    npwp: str | None
    address: str | None
    city: str | None
    country: str
    phone: str | None
    email: str | None
    contact_person: str | None
    payment_terms_days: int
    credit_limit: Decimal
    withholding_category: str
    is_active: bool
    status: str
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    version: int


class UpdateWithholdingCategoryRequest(BaseModel):
    withholding_category: WithholdingCategoryEnum


class SupplierListResponse(BaseModel):
    items: list[SupplierResponseModel]
    total: int


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

def to_supplier_response(supplier: Supplier) -> SupplierResponseModel:
    return SupplierResponseModel(
        id=supplier.id,
        legal_entity_id=supplier.legal_entity_id,
        supplier_code=supplier.supplier_code,
        name=supplier.name,
        npwp=supplier.npwp,
        address=supplier.address,
        city=supplier.city,
        country=supplier.country,
        phone=supplier.phone,
        email=supplier.email,
        contact_person=supplier.contact_person,
        payment_terms_days=supplier.payment_terms_days,
        credit_limit=supplier.credit_limit,
        withholding_category=supplier.withholding_category,
        is_active=supplier.is_active,
        status=supplier.status.value if supplier.status else "active",
        created_at=supplier.created_at,
        updated_at=supplier.updated_at,
        created_by=supplier.created_by,
        version=supplier.version,
    )


# ============================================================================
# SUPPLIER CRUD ENDPOINTS
# ============================================================================

@router.post(
    "/suppliers",
    response_model=SupplierResponseModel,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new supplier",
)
async def create_supplier(
    request: Request,
    payload: CreateSupplierRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Create a new supplier/vendor.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "create_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.create_supplier(
            legal_entity_id=payload.legal_entity_id,
            supplier_code=payload.supplier_code,
            name=payload.name,
            npwp=payload.npwp,
            address=payload.address,
            city=payload.city,
            country=payload.country,
            phone=payload.phone,
            email=payload.email,
            contact_person=payload.contact_person,
            payment_terms_days=payload.payment_terms_days,
            credit_limit=payload.credit_limit,
            withholding_category=payload.withholding_category.value,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except SupplierServiceError as e:
        logger.warning(f"Supplier service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating supplier: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/suppliers/{supplier_id}",
    response_model=SupplierResponseModel,
    summary="Get supplier by ID",
)
async def get_supplier(
    supplier_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Get a single supplier by ID.
    """
    try:
        result = await service.get_supplier(supplier_id)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        return to_supplier_response(result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/suppliers",
    response_model=list[SupplierResponseModel],
    summary="List suppliers",
)
async def list_suppliers(
    legal_entity_id: UUID = Query(..., description="Legal entity ID"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    status: SupplierStatusEnum | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> list[SupplierResponseModel]:
    """
    List suppliers with filters.
    """
    try:
        results = await service.list_suppliers(
            legal_entity_id=legal_entity_id,
            is_active=is_active,
            status=status.value if status else None,
        )
        # Apply pagination manually (since service doesn't support pagination yet)
        paginated = results[offset:offset + limit]
        return [to_supplier_response(s) for s in paginated]
    except Exception as e:
        logger.error(f"Error listing suppliers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.patch(
    "/suppliers/{supplier_id}",
    response_model=SupplierResponseModel,
    summary="Update supplier",
)
async def update_supplier(
    request: Request,
    supplier_id: UUID,
    payload: UpdateSupplierRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Update supplier details (name, address, payment terms, etc.).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        # Convert status to string if provided
        status_str = payload.status.value if payload.status else None
        result = await service.update_supplier(
            supplier_id=supplier_id,
            name=payload.name,
            address=payload.address,
            city=payload.city,
            phone=payload.phone,
            email=payload.email,
            contact_person=payload.contact_person,
            payment_terms_days=payload.payment_terms_days,
            credit_limit=payload.credit_limit,
            is_active=payload.is_active,
            status=status_str,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except SupplierNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found",
        )
    except SupplierServiceError as e:
        logger.warning(f"Supplier service error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error updating supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# SUPPLIER STATUS MANAGEMENT ENDPOINTS
# ============================================================================

@router.post(
    "/suppliers/{supplier_id}/deactivate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate supplier",
)
async def deactivate_supplier(
    request: Request,
    supplier_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """
    Deactivate a supplier (soft delete).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "deactivate_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        # Get current supplier to check if exists
        supplier = await service.get_supplier(supplier_id)
        if not supplier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        # Update to inactive
        await service.update_supplier(
            supplier_id=supplier_id,
            is_active=False,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "supplier_id": str(supplier_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/suppliers/{supplier_id}/activate",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Activate supplier",
)
async def activate_supplier(
    request: Request,
    supplier_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """
    Activate a previously deactivated supplier.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "activate_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        supplier = await service.get_supplier(supplier_id)
        if not supplier:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        await service.update_supplier(
            supplier_id=supplier_id,
            is_active=True,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "supplier_id": str(supplier_id)}
            )

        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/suppliers/{supplier_id}/status",
    response_model=SupplierResponseModel,
    summary="Change supplier status",
)
async def change_supplier_status(
    request: Request,
    supplier_id: UUID,
    status: SupplierStatusEnum = Body(..., description="New status"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Change supplier status (active, inactive, suspended, blacklisted).

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "change_supplier_status"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_supplier(
            supplier_id=supplier_id,
            status=status.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error changing supplier status {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# WITHHOLDING CATEGORY ENDPOINT
# ============================================================================

@router.post(
    "/suppliers/{supplier_id}/withholding-category",
    response_model=SupplierResponseModel,
    summary="Update withholding category",
)
async def update_withholding_category(
    request: Request,
    supplier_id: UUID,
    payload: UpdateWithholdingCategoryRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Update withholding category for a supplier.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "update_withholding_category"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_withholding_category(
            supplier_id=supplier_id,
            withholding_category=payload.withholding_category.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supplier not found",
            )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except SupplierNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Supplier not found",
        )
    except Exception as e:
        logger.error(f"Error updating withholding category for supplier {supplier_id}: {e}", exc_info=True)
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
    summary="Get supplier service statistics",
)
async def get_supplier_stats(
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> dict[str, int]:
    """
    Get supplier service statistics (internal monitoring).
    """
    try:
        return service.get_stats()
    except Exception as e:
        logger.error(f"Error getting supplier stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
