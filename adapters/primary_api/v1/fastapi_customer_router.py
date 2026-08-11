#!/usr/bin/env python3
"""
Module: fastapi_customer_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API modul Customer skala ERP produksi -- sinkron
    penuh dengan CustomerService (DB-backed) dan tabel-tabel di
    customer_table.py:

        /customers                              CRUD utama
        /customers/{id}/activate|deactivate|block
        /customers/{id}/credit-limit             GET/POST + riwayat
        /customers/{id}/balance                  GET/POST + riwayat
        /customers/{id}/addresses                Tab Address
        /customers/{id}/contacts                 Tab Contact Person
        /customers/{id}/attachments              Tab Attachment
        /customers/{id}/notes                    catatan internal
        /customers/{id}/tags                     kategori/label
        /customers/search, /customers/by-code, /customers/statistics
        /customers/bulk-delete, /customers/bulk-update-status

    NOTE PATH: main.py mount modul ini di /api/v1/customers, dan router
    ini sendiri sudah pakai prefix "/customers" di setiap path (pola
    double-naming yang sama dipakai semua modul lain di proyek ini --
    lihat catatan di registry/module_registry.py sisi frontend), jadi
    hasil akhirnya /api/v1/customers/customers/...
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
)
from application.service_layer.service_customer import (
    CustomerListItem,
    CustomerNotFoundError,
    CustomerService,
    CustomerServiceError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# ENUMS
# ============================================================================

class CustomerStatusEnum(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    BLOCKED = "blocked"


class CustomerTypeEnum(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    GOVERNMENT = "government"
    NON_PROFIT = "non_profit"


class AddressTypeEnum(str, Enum):
    BILLING = "billing"
    SHIPPING = "shipping"
    WAREHOUSE = "warehouse"
    OTHER = "other"


# ============================================================================
# PYDANTIC MODELS -- Customer inti
# ============================================================================

class CreateCustomerRequest(BaseModel):
    legal_entity_id: UUID
    customer_code: str | None = Field(
        None, max_length=30,
        description="Kosongkan untuk auto-generate (CUST-0001, CUST-0002, dst).",
    )
    customer_name: str = Field(..., min_length=1, max_length=200)
    company_name: str | None = Field(None, max_length=200)
    customer_type: CustomerTypeEnum = CustomerTypeEnum.COMPANY
    tax_id: str | None = Field(None, max_length=20, description="NPWP")
    tax_status: str = Field("pkp", description="pkp | non_pkp")
    is_taxable: bool = True
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    province: str | None = Field(None, max_length=100)
    district: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str = Field("ID", max_length=2)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=200)
    contact_person: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=20)
    contact_email: str | None = Field(None, max_length=200)
    credit_limit: Decimal = Field(Decimal("0"), ge=0)
    opening_balance: Decimal = Field(Decimal("0"))
    currency: str = Field("IDR", max_length=3)
    payment_term_days: int = Field(30, ge=0)
    discount_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    category: str | None = Field(None, max_length=50)
    price_group: str | None = Field(None, max_length=50)

    model_config = ConfigDict(use_enum_values=True)


class UpdateCustomerRequest(BaseModel):
    customer_name: str | None = Field(None, max_length=200)
    company_name: str | None = Field(None, max_length=200)
    tax_id: str | None = Field(None, max_length=20, description="NPWP")
    tax_status: str | None = None
    is_taxable: bool | None = None
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    province: str | None = Field(None, max_length=100)
    district: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=200)
    contact_person: str | None = Field(None, max_length=100)
    contact_phone: str | None = Field(None, max_length=20)
    contact_email: str | None = Field(None, max_length=200)
    payment_term_days: int | None = Field(None, ge=0)
    discount_percent: Decimal | None = Field(None, ge=0, le=100)
    category: str | None = Field(None, max_length=50)
    price_group: str | None = Field(None, max_length=50)
    is_active: bool | None = None
    is_blacklist: bool | None = None
    status: CustomerStatusEnum | None = None


class CustomerResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    customer_code: str
    customer_name: str
    company_name: str | None
    customer_type: str
    tax_id: str | None
    tax_status: str
    is_taxable: bool
    address: str | None
    city: str | None
    province: str | None
    district: str | None
    postal_code: str | None
    country: str
    phone: str | None
    mobile: str | None
    email: str | None
    website: str | None
    contact_person: str | None
    contact_phone: str | None
    contact_email: str | None
    credit_limit: Decimal
    used_credit: Decimal
    opening_balance: Decimal
    current_balance: Decimal
    currency: str
    payment_term_days: int
    discount_percent: Decimal
    category: str | None
    price_group: str | None
    status: str
    is_active: bool
    is_blacklist: bool
    blocked_reason: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None
    updated_by: UUID | None
    version: int


class UpdateCreditLimitRequest(BaseModel):
    new_limit: Decimal = Field(..., ge=0)
    reason: str | None = None


class UpdateBalanceRequest(BaseModel):
    delta: Decimal
    source: str | None = None
    reference: str | None = None


class BlockCustomerRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class BulkIdsRequest(BaseModel):
    customer_ids: list[UUID] = Field(..., min_length=1)


class BulkUpdateStatusRequest(BaseModel):
    customer_ids: list[UUID] = Field(..., min_length=1)
    status: CustomerStatusEnum


# ---------- Child resource models ----------

class AddressRequest(BaseModel):
    address_type: AddressTypeEnum = AddressTypeEnum.OTHER
    label: str | None = Field(None, max_length=100)
    address_line: str = Field(..., min_length=1)
    city: str | None = Field(None, max_length=100)
    province: str | None = Field(None, max_length=100)
    district: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str = Field("ID", max_length=2)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    is_primary: bool = False

    model_config = ConfigDict(use_enum_values=True)


class ContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    position: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    whatsapp: str | None = Field(None, max_length=20)
    is_primary: bool = False


class AttachmentRequest(BaseModel):
    document_type: str = Field("other", max_length=30, description="npwp|siup|ktp|kontrak|foto|other")
    file_name: str = Field(..., min_length=1, max_length=255)
    file_path: str = Field(..., min_length=1, description="path/URL penyimpanan file")
    file_size_bytes: int | None = None
    mime_type: str | None = Field(None, max_length=100)
    notes: str | None = None


class NoteRequest(BaseModel):
    note: str = Field(..., min_length=1)


class TagRequest(BaseModel):
    tag: str = Field(..., min_length=1, max_length=50)


# ============================================================================
# HELPERS
# ============================================================================

def to_customer_response(c: CustomerListItem) -> CustomerResponseModel:
    return CustomerResponseModel(**c.__dict__)


def _handle_common_errors(e: Exception, action: str, entity_id: Any = None):
    if isinstance(e, CustomerNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e) or "Customer not found")
    if isinstance(e, CustomerServiceError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    logger.error(f"Error {action} ({entity_id}): {e}", exc_info=True)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# CUSTOMER CRUD
# ============================================================================

@router.post("/customers", response_model=CustomerResponseModel, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CreateCustomerRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        result = await service.create_customer(
            legal_entity_id=payload.legal_entity_id,
            customer_code=payload.customer_code,
            name=payload.customer_name,
            company_name=payload.company_name,
            customer_type=payload.customer_type,
            npwp=payload.tax_id,
            tax_status=payload.tax_status,
            is_taxable=payload.is_taxable,
            address=payload.address,
            city=payload.city,
            province=payload.province,
            district=payload.district,
            postal_code=payload.postal_code,
            country=payload.country,
            phone=payload.phone,
            mobile=payload.mobile,
            email=payload.email,
            website=payload.website,
            contact_person=payload.contact_person,
            contact_phone=payload.contact_phone,
            contact_email=payload.contact_email,
            credit_limit=payload.credit_limit,
            opening_balance=payload.opening_balance,
            currency=payload.currency,
            payment_term_days=payload.payment_term_days,
            discount_percent=payload.discount_percent,
            category=payload.category,
            price_group=payload.price_group,
            created_by=user.user_id,
        )
        return to_customer_response(result)
    except Exception as e:
        _handle_common_errors(e, "creating customer")


@router.get("/customers/statistics", response_model=dict[str, Any])
async def get_statistics(
    legal_entity_id: UUID = Query(...),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, Any]:
    try:
        return await service.get_statistics(legal_entity_id)
    except Exception as e:
        _handle_common_errors(e, "getting statistics")


@router.get("/customers/by-code", response_model=CustomerResponseModel)
async def get_by_code(
    legal_entity_id: UUID = Query(...),
    customer_code: str = Query(...),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        result = await service.get_customer_by_code(legal_entity_id, customer_code)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return to_customer_response(result)
    except HTTPException:
        raise
    except Exception as e:
        _handle_common_errors(e, "getting customer by code")


@router.get("/customers/search", response_model=list[CustomerResponseModel])
async def search_customers(
    legal_entity_id: UUID = Query(...),
    q: str = Query(..., min_length=1, description="Cari nama/kode/telepon/email/NPWP"),
    limit: int = Query(20, ge=1, le=200),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[CustomerResponseModel]:
    try:
        results, _total = await service.list_customers(
            legal_entity_id=legal_entity_id, search=q, limit=limit, offset=0,
        )
        return [to_customer_response(c) for c in results]
    except Exception as e:
        _handle_common_errors(e, "searching customers")


@router.get("/customers", response_model=list[CustomerResponseModel])
async def list_customers(
    legal_entity_id: UUID = Query(...),
    is_active: bool | None = Query(None),
    status_filter: CustomerStatusEnum | None = Query(None, alias="status"),
    category: str | None = Query(None),
    is_blacklist: bool | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("customer_name"),
    sort_dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int | None = Query(None, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[CustomerResponseModel]:
    try:
        effective_limit = limit if limit is not None else page_size
        effective_offset = offset if offset is not None else (page - 1) * effective_limit
        results, _total = await service.list_customers(
            legal_entity_id=legal_entity_id,
            is_active=is_active,
            status=status_filter.value if status_filter else None,
            category=category,
            is_blacklist=is_blacklist,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            limit=effective_limit,
            offset=effective_offset,
        )
        return [to_customer_response(c) for c in results]
    except Exception as e:
        _handle_common_errors(e, "listing customers")


@router.get("/customers/{customer_id}", response_model=CustomerResponseModel)
async def get_customer(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        result = await service.get_customer(customer_id)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return to_customer_response(result)
    except HTTPException:
        raise
    except Exception as e:
        _handle_common_errors(e, "getting customer", customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerResponseModel)
async def update_customer(
    customer_id: UUID,
    payload: UpdateCustomerRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        result = await service.update_customer(
            customer_id=customer_id,
            name=payload.customer_name, company_name=payload.company_name, npwp=payload.tax_id,
            tax_status=payload.tax_status, is_taxable=payload.is_taxable,
            address=payload.address, city=payload.city, province=payload.province,
            district=payload.district, postal_code=payload.postal_code,
            phone=payload.phone, mobile=payload.mobile, email=payload.email,
            website=payload.website, contact_person=payload.contact_person,
            contact_phone=payload.contact_phone, contact_email=payload.contact_email,
            payment_term_days=payload.payment_term_days, discount_percent=payload.discount_percent,
            category=payload.category, price_group=payload.price_group,
            is_active=payload.is_active, is_blacklist=payload.is_blacklist,
            status=payload.status.value if payload.status else None,
            updated_by=user.user_id,
        )
        return to_customer_response(result)
    except Exception as e:
        _handle_common_errors(e, "updating customer", customer_id)


@router.delete("/customers/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_customer(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    """Soft-delete. Lihat docstring CustomerService.delete_customer."""
    try:
        await service.delete_customer(customer_id, deleted_by=user.user_id)
    except Exception as e:
        _handle_common_errors(e, "deleting customer", customer_id)


@router.post("/customers/{customer_id}/activate", response_model=CustomerResponseModel)
async def activate_customer(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        return to_customer_response(await service.activate_customer(customer_id, updated_by=user.user_id))
    except Exception as e:
        _handle_common_errors(e, "activating customer", customer_id)


@router.post("/customers/{customer_id}/deactivate", response_model=CustomerResponseModel)
async def deactivate_customer(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        return to_customer_response(await service.deactivate_customer(customer_id, updated_by=user.user_id))
    except Exception as e:
        _handle_common_errors(e, "deactivating customer", customer_id)


@router.post("/customers/{customer_id}/block", response_model=CustomerResponseModel)
async def block_customer(
    customer_id: UUID,
    payload: BlockCustomerRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        return to_customer_response(
            await service.block_customer(customer_id, payload.reason, updated_by=user.user_id)
        )
    except Exception as e:
        _handle_common_errors(e, "blocking customer", customer_id)


# ============================================================================
# CREDIT LIMIT
# ============================================================================

@router.post("/customers/{customer_id}/credit-limit", response_model=CustomerResponseModel)
async def update_credit_limit(
    customer_id: UUID,
    payload: UpdateCreditLimitRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> CustomerResponseModel:
    try:
        result = await service.update_credit_limit(
            customer_id=customer_id, new_limit=payload.new_limit,
            updated_by=user.user_id, reason=payload.reason,
        )
        return to_customer_response(result)
    except Exception as e:
        _handle_common_errors(e, "updating credit limit", customer_id)


@router.get("/customers/{customer_id}/credit-limit/history", response_model=list[dict])
async def get_credit_history(
    customer_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.get_credit_history(customer_id, limit=limit, offset=offset)
    except Exception as e:
        _handle_common_errors(e, "getting credit history", customer_id)


# ============================================================================
# BALANCE
# ============================================================================

@router.post("/customers/{customer_id}/balance", response_model=dict[str, Decimal])
async def update_balance(
    customer_id: UUID,
    payload: UpdateBalanceRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, Decimal]:
    try:
        new_balance = await service.update_balance(
            customer_id=customer_id, delta=payload.delta, updated_by=user.user_id,
            source=payload.source, reference=payload.reference,
        )
        return {"new_balance": new_balance}
    except Exception as e:
        _handle_common_errors(e, "updating balance", customer_id)


@router.get("/customers/{customer_id}/balance", response_model=dict[str, Decimal])
async def get_balance(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, Decimal]:
    try:
        result = await service.get_customer(customer_id)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return {"current_balance": result.current_balance}
    except HTTPException:
        raise
    except Exception as e:
        _handle_common_errors(e, "getting balance", customer_id)


@router.get("/customers/{customer_id}/balance/history", response_model=list[dict])
async def get_balance_history(
    customer_id: UUID,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.get_balance_history(customer_id, limit=limit, offset=offset)
    except Exception as e:
        _handle_common_errors(e, "getting balance history", customer_id)


# ============================================================================
# ADDRESSES
# ============================================================================

@router.get("/customers/{customer_id}/addresses", response_model=list[dict])
async def list_addresses(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.list_addresses(customer_id)
    except Exception as e:
        _handle_common_errors(e, "listing addresses", customer_id)


@router.post("/customers/{customer_id}/addresses", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_address(
    customer_id: UUID,
    payload: AddressRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.add_address(customer_id, **payload.model_dump())
    except Exception as e:
        _handle_common_errors(e, "adding address", customer_id)


@router.patch("/customers/{customer_id}/addresses/{address_id}", response_model=dict)
async def update_address(
    customer_id: UUID,
    address_id: UUID,
    payload: AddressRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.update_address(customer_id, address_id, **payload.model_dump())
    except Exception as e:
        _handle_common_errors(e, "updating address", address_id)


@router.delete("/customers/{customer_id}/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_address(
    customer_id: UUID,
    address_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    try:
        await service.delete_address(customer_id, address_id)
    except Exception as e:
        _handle_common_errors(e, "deleting address", address_id)


# ============================================================================
# CONTACTS
# ============================================================================

@router.get("/customers/{customer_id}/contacts", response_model=list[dict])
async def list_contacts(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.list_contacts(customer_id)
    except Exception as e:
        _handle_common_errors(e, "listing contacts", customer_id)


@router.post("/customers/{customer_id}/contacts", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_contact(
    customer_id: UUID,
    payload: ContactRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.add_contact(customer_id, **payload.model_dump())
    except Exception as e:
        _handle_common_errors(e, "adding contact", customer_id)


@router.patch("/customers/{customer_id}/contacts/{contact_id}", response_model=dict)
async def update_contact(
    customer_id: UUID,
    contact_id: UUID,
    payload: ContactRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.update_contact(customer_id, contact_id, **payload.model_dump())
    except Exception as e:
        _handle_common_errors(e, "updating contact", contact_id)


@router.delete("/customers/{customer_id}/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_contact(
    customer_id: UUID,
    contact_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    try:
        await service.delete_contact(customer_id, contact_id)
    except Exception as e:
        _handle_common_errors(e, "deleting contact", contact_id)


# ============================================================================
# ATTACHMENTS
# ============================================================================

@router.get("/customers/{customer_id}/attachments", response_model=list[dict])
async def list_attachments(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.list_attachments(customer_id)
    except Exception as e:
        _handle_common_errors(e, "listing attachments", customer_id)


@router.post("/customers/{customer_id}/attachments", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_attachment(
    customer_id: UUID,
    payload: AttachmentRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    """
    Menyimpan metadata dokumen (nama file, path/URL penyimpanan, tipe,
    ukuran). Upload biner file itu sendiri dilakukan lewat endpoint
    storage terpisah (mis. object storage/S3) di luar router ini --
    router ini hanya mencatat referensinya ke database.
    """
    try:
        fields = payload.model_dump()
        fields["uploaded_by"] = user.user_id
        return await service.add_attachment(customer_id, **fields)
    except Exception as e:
        _handle_common_errors(e, "adding attachment", customer_id)


@router.delete("/customers/{customer_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_attachment(
    customer_id: UUID,
    attachment_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    try:
        await service.delete_attachment(customer_id, attachment_id)
    except Exception as e:
        _handle_common_errors(e, "deleting attachment", attachment_id)


# ============================================================================
# NOTES
# ============================================================================

@router.get("/customers/{customer_id}/notes", response_model=list[dict])
async def list_notes(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.list_notes(customer_id)
    except Exception as e:
        _handle_common_errors(e, "listing notes", customer_id)


@router.post("/customers/{customer_id}/notes", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_note(
    customer_id: UUID,
    payload: NoteRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.add_note(customer_id, payload.note, created_by=user.user_id)
    except Exception as e:
        _handle_common_errors(e, "adding note", customer_id)


@router.delete("/customers/{customer_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_note(
    customer_id: UUID,
    note_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    try:
        await service.delete_note(customer_id, note_id)
    except Exception as e:
        _handle_common_errors(e, "deleting note", note_id)


# ============================================================================
# TAGS
# ============================================================================

@router.get("/customers/{customer_id}/tags", response_model=list[dict])
async def list_tags(
    customer_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> list[dict]:
    try:
        return await service.list_tags(customer_id)
    except Exception as e:
        _handle_common_errors(e, "listing tags", customer_id)


@router.post("/customers/{customer_id}/tags", response_model=dict, status_code=status.HTTP_201_CREATED)
async def add_tag(
    customer_id: UUID,
    payload: TagRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict:
    try:
        return await service.add_tag(customer_id, payload.tag)
    except Exception as e:
        _handle_common_errors(e, "adding tag", customer_id)


@router.delete("/customers/{customer_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_tag(
    customer_id: UUID,
    tag_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> None:
    try:
        await service.remove_tag(customer_id, tag_id)
    except Exception as e:
        _handle_common_errors(e, "removing tag", tag_id)


# ============================================================================
# BULK
# ============================================================================

@router.post("/customers/bulk-delete", response_model=dict[str, int])
async def bulk_delete(
    payload: BulkIdsRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, int]:
    try:
        count = await service.bulk_delete(payload.customer_ids, deleted_by=user.user_id)
        return {"deleted": count}
    except Exception as e:
        _handle_common_errors(e, "bulk deleting customers")


@router.post("/customers/bulk-update-status", response_model=dict[str, int])
async def bulk_update_status(
    payload: BulkUpdateStatusRequest,
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, int]:
    try:
        count = await service.bulk_update_status(
            payload.customer_ids, payload.status.value, updated_by=user.user_id
        )
        return {"updated": count}
    except Exception as e:
        _handle_common_errors(e, "bulk updating customer status")


# ============================================================================
# STATS (internal monitoring, dipertahankan dari versi sebelumnya)
# ============================================================================

@router.get("/stats", response_model=dict[str, int])
async def get_customer_stats(
    user: TokenPayload = Depends(get_current_user),
    service: CustomerService = Depends(get_service(CustomerService)),
) -> dict[str, int]:
    try:
        return service.get_stats()
    except Exception as e:
        _handle_common_errors(e, "getting customer stats")
