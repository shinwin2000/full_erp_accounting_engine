#!/usr/bin/env python3
"""
Module: fastapi_supplier_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Supplier/Vendor:
               CRUD supplier, update status, withholding category,
               payment terms, saldo hutang, import/export, dan statistik.

PERBAIKAN (refactor sinkronisasi Supplier/Vendor Frontend <-> Backend <-> DB):
    1. `legal_entity_id` sebelumnya WAJIB dikirim manual di body (create) dan
       query string (list) — padahal Frontend TIDAK PERNAH mengirimkannya
       (sudah ter-embed di JWT). Sekarang diambil otomatis lewat
       `Depends(get_current_legal_entity)`, sama seperti router lain
       (fastapi_purchase_sales_router.py dst).
    2. List endpoint sekarang menerima `search` (dipakai GenericListPage di
       Frontend) dan mengembalikan amplop `{items, total}` supaya pagination
       akurat.
    3. Ditambahkan endpoint `/suppliers/export` dan `/suppliers/import` yang
       sebelumnya tidak ada sama sekali (tombol Export di Frontend generik
       memanggil endpoint ini dan sebelumnya selalu 404).
    4. Skema request/response menambahkan seluruh kolom master data baru
       (company_name, tax_name, mobile, province, credit_limit,
       opening_balance, opening_balance_date, remarks) sesuai kolom yang
       sudah ditambahkan ke database (lihat migration 0047).
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
from pydantic import BaseModel, ConfigDict, Field

from adapters.dependency_provider import get_service
from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
)

# Import service
from application.service_layer.service_supplier import (
    Supplier,
    SupplierHasTransactionsError,
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
    BLOCKED = "blocked"
    SUSPENDED = "suspended"


class SupplierTypeEnum(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    GOVERNMENT = "government"
    NON_PROFIT = "non_profit"


class WithholdingCategoryEnum(str, Enum):
    NONE = "none"
    PPH23 = "pph23"
    PPH26 = "pph26"
    BOTH = "both"


# ---------- Request/Response Models ----------
# Field-field berikut disepakati sebagai kontrak stabil antara Frontend
# (registry/module_registry.py & ui/pages/suppliers_page.py) dan Backend.
# JANGAN ubah nama field di sini tanpa mengubah kedua file Frontend tsb.

class CreateSupplierRequest(BaseModel):
    supplier_code: str = Field(..., min_length=1, max_length=30, description="Kode supplier unik")
    name: str = Field(..., min_length=1, max_length=200, description="Nama supplier")
    company_name: str | None = Field(None, max_length=200, description="Nama perusahaan")
    supplier_type: SupplierTypeEnum = SupplierTypeEnum.COMPANY
    npwp: str | None = Field(None, max_length=20, description="Tax ID (NPWP)")
    tax_name: str | None = Field(None, max_length=200, description="Nama wajib pajak")
    address: str | None = Field(None, description="Alamat")
    city: str | None = Field(None, max_length=100)
    province: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str = Field("ID", max_length=2, description="ISO country code")
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=200)
    contact_person: str | None = Field(None, max_length=100)
    payment_terms_days: int = Field(30, ge=0, le=365, description="Termin pembayaran (hari)")
    credit_limit: Decimal = Field(Decimal("0"), ge=0, description="Limit kredit")
    opening_balance: Decimal = Field(Decimal("0"), ge=0, description="Saldo awal hutang")
    opening_balance_date: date | None = Field(None, description="Tanggal saldo awal")
    bank_name: str | None = Field(None, max_length=100)
    bank_account_number: str | None = Field(None, max_length=50)
    bank_account_name: str | None = Field(None, max_length=100, description="Nama pemilik rekening")
    withholding_category: WithholdingCategoryEnum = WithholdingCategoryEnum.NONE
    remarks: str | None = Field(None, description="Catatan")

    model_config = ConfigDict(use_enum_values=True)


class UpdateSupplierRequest(BaseModel):
    name: str | None = Field(None, max_length=200)
    company_name: str | None = Field(None, max_length=200)
    supplier_type: SupplierTypeEnum | None = None
    npwp: str | None = Field(None, max_length=20)
    tax_name: str | None = Field(None, max_length=200)
    address: str | None = None
    city: str | None = Field(None, max_length=100)
    province: str | None = Field(None, max_length=100)
    postal_code: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=2)
    phone: str | None = Field(None, max_length=20)
    mobile: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=200)
    website: str | None = Field(None, max_length=200)
    contact_person: str | None = Field(None, max_length=100)
    payment_terms_days: int | None = Field(None, ge=0, le=365)
    credit_limit: Decimal | None = Field(None, ge=0)
    opening_balance: Decimal | None = Field(None, ge=0)
    opening_balance_date: date | None = None
    bank_name: str | None = Field(None, max_length=100)
    bank_account_number: str | None = Field(None, max_length=50)
    bank_account_name: str | None = Field(None, max_length=100)
    withholding_category: WithholdingCategoryEnum | None = None
    remarks: str | None = None
    is_active: bool | None = None
    status: SupplierStatusEnum | None = None

    model_config = ConfigDict(use_enum_values=True)


class SupplierResponseModel(BaseModel):
    id: UUID
    legal_entity_id: UUID
    supplier_code: str
    name: str
    company_name: str | None
    supplier_type: str
    npwp: str | None
    tax_name: str | None
    address: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    phone: str | None
    mobile: str | None
    email: str | None
    website: str | None
    contact_person: str | None
    payment_terms_days: int
    credit_limit: Decimal
    opening_balance: Decimal
    opening_balance_date: date | None
    bank_name: str | None
    bank_account_number: str | None
    bank_account_name: str | None
    withholding_category: str
    remarks: str | None
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


class SupplierBalanceResponse(BaseModel):
    supplier_id: UUID
    outstanding_balance: Decimal


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
        company_name=supplier.company_name,
        supplier_type=supplier.supplier_type,
        npwp=supplier.npwp,
        tax_name=supplier.tax_name,
        address=supplier.address,
        city=supplier.city,
        province=supplier.province,
        postal_code=supplier.postal_code,
        country=supplier.country,
        phone=supplier.phone,
        mobile=supplier.mobile,
        email=supplier.email,
        website=supplier.website,
        contact_person=supplier.contact_person,
        payment_terms_days=supplier.payment_terms_days,
        credit_limit=supplier.credit_limit,
        opening_balance=supplier.opening_balance,
        opening_balance_date=supplier.opening_balance_date,
        bank_name=supplier.bank_name,
        bank_account_number=supplier.bank_account_number,
        bank_account_name=supplier.bank_account_name,
        withholding_category=supplier.withholding_category,
        remarks=supplier.remarks,
        is_active=supplier.is_active,
        status=supplier.status.value if hasattr(supplier.status, "value") else supplier.status,
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Create a new supplier/vendor.

    `legal_entity_id` diambil otomatis dari JWT pengguna yang login — TIDAK
    perlu (dan tidak boleh) dikirim manual dari Frontend.

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
            legal_entity_id=legal_entity_id,
            supplier_code=payload.supplier_code,
            name=payload.name,
            company_name=payload.company_name,
            supplier_type=payload.supplier_type,
            npwp=payload.npwp,
            tax_name=payload.tax_name,
            address=payload.address,
            city=payload.city,
            province=payload.province,
            postal_code=payload.postal_code,
            country=payload.country,
            phone=payload.phone,
            mobile=payload.mobile,
            email=payload.email,
            website=payload.website,
            contact_person=payload.contact_person,
            payment_terms_days=payload.payment_terms_days,
            credit_limit=payload.credit_limit,
            opening_balance=payload.opening_balance,
            opening_balance_date=payload.opening_balance_date,
            bank_name=payload.bank_name,
            bank_account_number=payload.bank_account_number,
            bank_account_name=payload.bank_account_name,
            withholding_category=payload.withholding_category,
            remarks=payload.remarks,
            created_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except SupplierServiceError as e:
        logger.warning(f"Supplier service error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating supplier: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/export",
    summary="Export suppliers to CSV",
)
async def export_suppliers(
    format: str = Query("csv", description="Format export: csv"),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """
    Export seluruh data supplier milik legal entity aktif ke CSV.

    NOTE: path adalah "/export" (BUKAN "/suppliers/export") karena
    Frontend (`ui/widgets/generic_list_page.py::_export`) memanggil
    `{config.base_path}/export` = "/suppliers/export", sedangkan router
    ini sudah dimount dengan prefix "/api/v1/suppliers" oleh
    fastapi_app_factory.py. Jadi path final = "/api/v1/suppliers/export".
    """
    try:
        csv_content = await service.export_csv(legal_entity_id)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=suppliers_export.csv"},
        )
    except Exception as e:
        logger.error(f"Error exporting suppliers: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.post(
    "/import",
    summary="Import suppliers from CSV",
)
async def import_suppliers(
    request: Request,
    rows: list[CreateSupplierRequest] = Body(..., description="Daftar supplier untuk diimpor"),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> dict[str, Any]:
    """
    Import massal supplier. Baris yang gagal (kode duplikat, NPWP duplikat,
    dsb) dilaporkan per baris tanpa menggagalkan keseluruhan proses.
    """
    correlation_id = get_correlation_id(request)
    created = 0
    errors: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        try:
            await service.create_supplier(
                legal_entity_id=legal_entity_id,
                supplier_code=row.supplier_code,
                name=row.name,
                company_name=row.company_name,
                supplier_type=row.supplier_type,
                npwp=row.npwp,
                tax_name=row.tax_name,
                address=row.address,
                city=row.city,
                province=row.province,
                postal_code=row.postal_code,
                country=row.country,
                phone=row.phone,
                mobile=row.mobile,
                email=row.email,
                website=row.website,
                contact_person=row.contact_person,
                payment_terms_days=row.payment_terms_days,
                credit_limit=row.credit_limit,
                opening_balance=row.opening_balance,
                opening_balance_date=row.opening_balance_date,
                bank_name=row.bank_name,
                bank_account_number=row.bank_account_number,
                bank_account_name=row.bank_account_name,
                withholding_category=row.withholding_category,
                remarks=row.remarks,
                created_by=user.user_id,
                correlation_id=correlation_id,
            )
            created += 1
        except SupplierServiceError as e:
            errors.append({"row": idx, "supplier_code": row.supplier_code, "error": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.error(f"Unexpected error importing row {idx}: {e}", exc_info=True)
            errors.append({"row": idx, "supplier_code": row.supplier_code, "error": str(e)})

    return {"created": created, "failed": len(errors), "errors": errors}


@router.get(
    "/next-code",
    summary="Get next auto-generated supplier code",
)
async def get_next_supplier_code(
    prefix: str = Query("SUP", description="Prefix kode, mis. 'SUP'"),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> dict[str, str]:
    """
    Kode supplier berikutnya secara otomatis (mis. "SUP-001", "SUP-002", dst),
    dihitung dari kode dengan angka urut terbesar yang sudah ada untuk legal
    entity aktif. Dipanggil Frontend saat tombol "Tambah Supplier" diklik
    supaya field Kode Supplier langsung terisi otomatis.

    NOTE: didaftarkan SEBELUM `/suppliers/{supplier_id}` supaya path
    "/next-code" tidak salah ter-match sebagai supplier_id="next-code".
    """
    try:
        next_code = await service.get_next_code(legal_entity_id, prefix)
        return {"supplier_code": next_code}
    except Exception as e:
        logger.error(f"Error getting next supplier code: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/stats",
    summary="Get supplier statistics",
)
async def get_supplier_stats(
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> dict[str, Any]:
    """Statistik supplier (total, aktif, per kategori, per status)."""
    try:
        return await service.get_statistics(legal_entity_id)
    except Exception as e:
        logger.error(f"Error getting supplier stats: {e}", exc_info=True)
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """Get a single supplier by ID."""
    try:
        result = await service.get_supplier(supplier_id, legal_entity_id)
        if not result:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
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
    response_model=SupplierListResponse,
    summary="List suppliers",
)
async def list_suppliers(
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    search: str | None = Query(None, description="Cari berdasarkan kode/nama/NPWP/email/PIC"),
    city: str | None = Query(None, description="Filter kota"),
    is_active: bool | None = Query(None, description="Filter status aktif/nonaktif"),
    status_filter: SupplierStatusEnum | None = Query(None, alias="status", description="Filter status"),
    page: int = Query(1, ge=1, description="Nomor halaman (1-based, dipakai Frontend)"),
    page_size: int | None = Query(None, ge=1, le=1000, description="Ukuran halaman (alias limit)"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierListResponse:
    """
    List suppliers dengan pencarian, filter, dan pagination.

    Mendukung dua gaya pagination sekaligus supaya kompatibel dengan
    Frontend generik (page/page_size) maupun klien lain (limit/offset):
    jika `page`/`page_size` dikirim, itu yang dipakai; kalau tidak, jatuh
    ke `limit`/`offset`.
    """
    try:
        effective_limit = page_size or limit
        effective_offset = (page - 1) * effective_limit if page_size else offset

        results, total = await service.list_suppliers(
            legal_entity_id=legal_entity_id,
            search=search,
            city=city,
            is_active=is_active,
            status=status_filter.value if status_filter else None,
            limit=effective_limit,
            offset=effective_offset,
        )
        return SupplierListResponse(
            items=[to_supplier_response(s) for s in results],
            total=total,
        )
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """
    Update supplier details (nama, alamat, termin pembayaran, dsb).

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
        result = await service.update_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            name=payload.name,
            company_name=payload.company_name,
            supplier_type=payload.supplier_type,
            npwp=payload.npwp,
            tax_name=payload.tax_name,
            address=payload.address,
            city=payload.city,
            province=payload.province,
            postal_code=payload.postal_code,
            country=payload.country,
            phone=payload.phone,
            mobile=payload.mobile,
            email=payload.email,
            website=payload.website,
            contact_person=payload.contact_person,
            payment_terms_days=payload.payment_terms_days,
            credit_limit=payload.credit_limit,
            opening_balance=payload.opening_balance,
            opening_balance_date=payload.opening_balance_date,
            bank_name=payload.bank_name,
            bank_account_number=payload.bank_account_number,
            bank_account_name=payload.bank_account_name,
            withholding_category=payload.withholding_category,
            remarks=payload.remarks,
            is_active=payload.is_active,
            status=payload.status if payload.status else None,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_supplier_response(result)

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except SupplierNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    except SupplierServiceError as e:
        logger.warning(f"Supplier service error: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """Deactivate a supplier (soft update, bukan hapus)."""
    method_name = "deactivate_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        supplier = await service.get_supplier(supplier_id, legal_entity_id)
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        await service.update_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            is_active=False,
            status=SupplierStatusEnum.INACTIVE.value,
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """Activate a previously deactivated supplier."""
    method_name = "activate_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)
        supplier = await service.get_supplier(supplier_id, legal_entity_id)
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        await service.update_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            is_active=True,
            status=SupplierStatusEnum.ACTIVE.value,
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


@router.delete(
    "/suppliers/{supplier_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete (soft-delete) a supplier",
)
async def delete_supplier(
    request: Request,
    supplier_id: UUID,
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> Response:
    """
    Delete a supplier.

    Supplier yang SUDAH memiliki transaksi (PO/GRN/Invoice/Payment) tidak
    bisa dihapus — akan menghasilkan 409 Conflict, sesuai aturan bisnis
    "tidak boleh menghapus supplier yang sudah memiliki transaksi".
    Gunakan endpoint /deactivate sebagai gantinya.

    This endpoint is idempotent. Provide Idempotency-Key header to safely retry.
    """
    method_name = "delete_supplier"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        correlation_id = get_correlation_id(request)  # noqa: F841 (reserved for future audit use)
        await service.delete_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            deleted_by=user.user_id,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(
                idempotency_key, method_name, {"status": "success", "supplier_id": str(supplier_id)}
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except SupplierNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    except SupplierHasTransactionsError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting supplier {supplier_id}: {e}", exc_info=True)
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
    new_status: SupplierStatusEnum = Body(..., description="New status"),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """Change supplier status (active, inactive, blocked, suspended)."""
    method_name = "change_supplier_status"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_supplier(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            status=new_status.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_supplier_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except SupplierNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
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
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierResponseModel:
    """Update withholding category (PPh 23/26) untuk supplier."""
    method_name = "update_withholding_category"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return SupplierResponseModel(**cached)

    try:
        correlation_id = get_correlation_id(request)
        result = await service.update_withholding_category(
            supplier_id=supplier_id,
            legal_entity_id=legal_entity_id,
            withholding_category=payload.withholding_category.value,
            updated_by=user.user_id,
            correlation_id=correlation_id,
        )
        response = to_supplier_response(result)
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except SupplierNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    except Exception as e:
        logger.error(f"Error updating withholding category for supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# BALANCE / SALDO HUTANG ENDPOINT
# ============================================================================

@router.get(
    "/suppliers/{supplier_id}/balance",
    response_model=SupplierBalanceResponse,
    summary="Get supplier outstanding AP balance",
)
async def get_supplier_balance(
    supplier_id: UUID,
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> SupplierBalanceResponse:
    """Saldo hutang (AP) yang belum lunas untuk supplier ini."""
    try:
        supplier = await service.get_supplier(supplier_id, legal_entity_id)
        if not supplier:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
        balance = await service.get_outstanding_balance(supplier_id)
        return SupplierBalanceResponse(supplier_id=supplier_id, outstanding_balance=balance)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting balance for supplier {supplier_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


# ============================================================================
# AUDIT HISTORY ENDPOINT
# ============================================================================

@router.get(
    "/suppliers/{supplier_id}/history",
    summary="Get supplier change history (audit trail)",
)
async def get_supplier_history(
    supplier_id: UUID,
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    user: TokenPayload = Depends(get_current_user),
    service: SupplierService = Depends(get_service(SupplierService)),
) -> list[dict[str, Any]]:
    """Riwayat perubahan supplier (siapa mengubah apa, kapan)."""
    supplier = await service.get_supplier(supplier_id, legal_entity_id)
    if not supplier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supplier not found")
    return [
        entry
        for entry in service.get_audit_trail()
        if entry.get("details", {}).get("supplier_id") == str(supplier_id)
    ]
