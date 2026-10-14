#!/usr/bin/env python3
"""
Module: fastapi_legal_entity_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk mengelola Legal Entity.

FIX v4 (2026-10-14) — CRITICAL path mismatch pada /export:
- BUG: `GET /api/v1/legal-entities/legal-entities/export?format=csv` selalu
  balas 422 dengan pesan "Input should be a valid UUID ... found 'x' at 2".
  Setelah men-dump seluruh route aplikasi, ketahuan bahwa endpoint export
  terdaftar di path `/api/v1/legal-entities/export` (SATU kali
  "legal-entities"), padahal frontend (GenericListPage) memanggilnya di
  `/api/v1/legal-entities/legal-entities/export` (DUA kali "legal-entities",
  karena `base_path = "/legal-entities/legal-entities"`).

  Penyebab: file ini punya `APIRouter(prefix="/legal-entities")`, dan
  main.py menambahkan prefix `/api/v1` — sehingga:
    - Route `/login-options`         → `/api/v1/legal-entities/login-options`
    - Route `/export` (bug)          → `/api/v1/legal-entities/export`        ← SATU
    - Route `/legal-entities`        → `/api/v1/legal-entities/legal-entities`
    - Route `/legal-entities/{id}`   → `/api/v1/legal-entities/legal-entities/{id}`

  Route `/legal-entities/{legal_entity_id}` (yang dobel) menangkap "export"
  sebagai path param — coba parse UUID, gagal, balas 422.

- FIX: samakan path endpoint export dengan route lain yang sudah dobel —
  ubah `"/export"` jadi `"/legal-entities/export"`. Dengan prefix router
  `/legal-entities` dan prefix main.py `/api/v1`, path final menjadi
  `/api/v1/legal-entities/legal-entities/export` — cocok dengan yang
  dipanggil frontend, dan konsisten dengan route list/get di file ini.

FIX v3 (2026-10-14) — route ordering:
- Semua route statis (`/login-options`, `/legal-entities/export`,
  `/legal-entities/consolidation-groups`) dideklarasikan SEBELUM route
  dinamis `{legal_entity_id}` supaya FastAPI mencocokkan statis lebih dulu.

FIX v2 (2026-10-14) — response schema tolerance:
- `created_at`/`updated_at` di response schema dibuat Optional supaya
  baris DB lama dengan timestamp NULL tidak menggagalkan seluruh endpoint
  dengan 500.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_user,
    require_permission,
)
from domain.shared_value_objects.npwp_vo import validate_npwp_string

logger = logging.getLogger(__name__)


def _validate_npwp_format(v: str | None) -> str | None:
    """Validasi format NPWP: 15 digit (format lama) ATAU 16 digit (format
    standar sejak 1 Juli 2024 - PMK 112/PMK.03/2022 jo. PER-06/PJ/2024)."""
    if v is None:
        return v
    if not v.isdigit():
        raise ValueError("NPWP must contain only digits")
    if not validate_npwp_string(v):
        raise ValueError(
            f"NPWP '{v}' tidak valid. Harus 15 digit (format lama) atau "
            "16 digit (format standar sejak Juli 2024), dan untuk format "
            "badan/instansi kode KPP (2 digit pertama bagian 15-digitnya) "
            "harus dikenali."
        )
    return v


def _format_local_dt(dt: datetime | None) -> str:
    """Format datetime UTC dari DB ke WIB (UTC+7) tanpa mikrodetik."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    wib = dt.astimezone(timezone(timedelta(hours=7)))
    return wib.strftime("%Y-%m-%d %H:%M:%S WIB")


# ============================================================================
# IDEMPOTENCY MANAGER
# ============================================================================

class IdempotencyManager:
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


_idempotency_manager = IdempotencyManager()


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================

class LegalEntityType(str, Enum):
    CORPORATION = "corporation"
    BRANCH = "branch"
    REPRESENTATIVE_OFFICE = "representative_office"
    PARTNERSHIP = "partnership"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"
    COOPERATIVE = "cooperative"
    FOUNDATION = "foundation"
    CONSOLIDATION_GROUP = "consolidation_group"


class LegalEntityStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"
    BANKRUPT = "bankrupt"
    MERGED = "merged"
    LOCKED = "locked"
    ARCHIVED = "archived"


class BranchStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    CLOSED = "closed"
    SUSPENDED = "suspended"


class TaxStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


def _safe_entity_type(raw_value: str | None) -> LegalEntityType:
    try:
        return LegalEntityType(raw_value)
    except ValueError:
        logger.warning(
            f"Unrecognized entity_type '{raw_value}' pada data legal entity - "
            f"fallback ke '{LegalEntityType.CORPORATION.value}'."
        )
        return LegalEntityType.CORPORATION


def _safe_entity_status(raw_value: str | None) -> LegalEntityStatus:
    try:
        return LegalEntityStatus(raw_value)
    except ValueError:
        logger.warning(
            f"Unrecognized status '{raw_value}' pada data legal entity - "
            f"fallback ke '{LegalEntityStatus.ACTIVE.value}'."
        )
        return LegalEntityStatus.ACTIVE


DEFAULT_FISCAL_YEAR_START_MONTH = 1
DEFAULT_FISCAL_YEAR_END_MONTH = 12
DEFAULT_BASE_CURRENCY = "IDR"
DEFAULT_FUNCTIONAL_CURRENCY = "IDR"
DEFAULT_TAX_RATE_PPN = Decimal("11")
DEFAULT_TAX_RATE_PPH_BADAN = Decimal("22")


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class LegalEntityCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    legal_name: str = Field(..., min_length=3, max_length=200)
    trade_name: str | None = None
    entity_type: LegalEntityType
    registration_number: str | None = None
    npwp: str | None = Field(None, min_length=15, max_length=16)
    nppp: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    province: str | None = None
    country: str = "ID"
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None
    established_date: date | None = None
    fiscal_year_start: int = DEFAULT_FISCAL_YEAR_START_MONTH
    fiscal_year_end: int = DEFAULT_FISCAL_YEAR_END_MONTH
    base_currency: str = DEFAULT_BASE_CURRENCY
    functional_currency: str = DEFAULT_FUNCTIONAL_CURRENCY
    is_taxable: bool = True
    is_withholding_agent: bool = True
    parent_company_id: UUID | None = None
    consolidation_group_id: UUID | None = None
    notes: str | None = None

    @field_validator("npwp")
    @classmethod
    def validate_npwp(cls, v: str | None) -> str | None:
        return _validate_npwp_format(v)


class LegalEntityUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    legal_name: str | None = None
    trade_name: str | None = None
    entity_type: LegalEntityType | None = None
    registration_number: str | None = None
    npwp: str | None = Field(None, min_length=15, max_length=16)
    nppp: str | None = None
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    province: str | None = None
    country: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    website: str | None = None
    fiscal_year_start: int | None = None
    fiscal_year_end: int | None = None
    base_currency: str | None = None
    functional_currency: str | None = None
    is_taxable: bool | None = None
    is_withholding_agent: bool | None = None
    parent_company_id: UUID | None = None
    status: LegalEntityStatus | None = None
    notes: str | None = None

    @field_validator("npwp")
    @classmethod
    def validate_npwp(cls, v: str | None) -> str | None:
        return _validate_npwp_format(v)


class LegalEntityResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_name: str
    trade_name: str | None
    entity_type: LegalEntityType
    registration_number: str | None
    npwp: str | None
    nppp: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    province: str | None
    country: str
    phone: str | None
    fax: str | None
    email: str | None
    website: str | None
    established_date: date | None
    fiscal_year_start: int
    fiscal_year_end: int
    base_currency: str
    functional_currency: str
    is_taxable: bool
    is_withholding_agent: bool
    status: LegalEntityStatus
    is_active: bool
    is_locked: bool = False
    parent_company_id: UUID | None
    parent_company_name: str | None = None
    consolidation_group_id: UUID | None
    consolidation_group_name: str | None = None
    notes: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1


class TaxProfileSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    tax_office: str | None = None
    tax_office_code: str | None = None
    tax_classification: str | None = None
    taxable_date: date | None = None
    vat_collector_number: str | None = None
    annual_tax_return_due_date: int | None = None
    monthly_tax_due_date: int | None = None
    corporate_tax_rate: Decimal = DEFAULT_TAX_RATE_PPH_BADAN
    vat_rate: Decimal = DEFAULT_TAX_RATE_PPN
    is_using_final_tax: bool = False
    final_tax_rate: Decimal | None = None
    notes: str | None = None


class TaxProfileResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    legal_entity_id: UUID
    tax_office: str | None
    tax_office_code: str | None
    tax_classification: str | None
    taxable_date: date | None
    vat_collector_number: str | None
    annual_tax_return_due_date: int | None
    monthly_tax_due_date: int | None
    corporate_tax_rate: Decimal
    vat_rate: Decimal
    is_using_final_tax: bool
    final_tax_rate: Decimal | None
    notes: str | None
    status: TaxStatus
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    version: int = 1


class BranchCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_code: str = Field(..., min_length=2, max_length=20)
    branch_name: str = Field(..., min_length=3, max_length=200)
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    email: str | None = None
    manager_name: str | None = None
    is_active: bool = True
    notes: str | None = None


class BranchUpdateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    branch_name: str | None = None
    address: str | None = None
    city: str | None = None
    phone: str | None = None
    email: str | None = None
    manager_name: str | None = None
    is_active: bool | None = None
    status: BranchStatus | None = None
    notes: str | None = None


class BranchResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_entity_id: UUID
    branch_code: str
    branch_name: str
    address: str | None
    city: str | None
    postal_code: str | None
    phone: str | None
    email: str | None
    manager_name: str | None
    status: BranchStatus
    is_active: bool
    notes: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1


class ConsolidationGroupCreateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    group_code: str = Field(..., min_length=3, max_length=30)
    group_name: str = Field(..., min_length=3, max_length=200)
    description: str | None = None
    base_currency: str = DEFAULT_BASE_CURRENCY
    fiscal_year_start: int = DEFAULT_FISCAL_YEAR_START_MONTH
    fiscal_year_end: int = DEFAULT_FISCAL_YEAR_END_MONTH
    notes: str | None = None


class ConsolidationGroupResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    group_code: str
    group_name: str
    description: str | None
    base_currency: str
    fiscal_year_start: int
    fiscal_year_end: int
    member_count: int
    is_active: bool
    notes: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: UUID | None = None
    created_by_name: str | None = None
    version: int = 1


class LegalEntityLoginOptionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    legal_name: str
    trade_name: str | None = None


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================

async def get_legal_entity_service(request: Request) -> Any:
    from application.service_layer.service_legal_entity import LegalEntityService
    container = request.app.state.container
    return await container.resolve_async(LegalEntityService)


# ============================================================================
# ROUTER
# ============================================================================
# CATATAN PENTING:
# Router ini punya prefix "/legal-entities" — dan main.py menambahkan
# prefix "/api/v1". Akibatnya SETIAP path yang dideklarasikan di bawah
# ini di-prepend dengan "/legal-entities" (dari sini) LALU "/api/v1"
# (dari main.py). Untuk konsisten dengan frontend yang memakai
# base_path = "/legal-entities/legal-entities", semua route yang
# "semantik"-nya milik legal entity (list, get by id, export, create)
# HARUS dideklarasikan dengan path lengkap "/legal-entities/..." di sini,
# supaya hasil akhirnya menjadi "/api/v1/legal-entities/legal-entities/...".
#
# Contoh konkret:
#   Path di file ini     + Prefix router + Prefix main.py  = Path final
#   /login-options       + /legal-entities + /api/v1       = /api/v1/legal-entities/login-options
#   /legal-entities      + /legal-entities + /api/v1       = /api/v1/legal-entities/legal-entities
#   /legal-entities/{id} + /legal-entities + /api/v1       = /api/v1/legal-entities/legal-entities/{id}
#   /legal-entities/export + /legal-entities + /api/v1     = /api/v1/legal-entities/legal-entities/export
#
# Route /export (tanpa prefix /legal-entities) akan jatuh ke
# /api/v1/legal-entities/export — TIDAK match frontend, dan yang lebih
# buruk: route /legal-entities/{legal_entity_id} yang juga terdaftar
# menangkap "export" sebagai UUID dan balas 422.

router = APIRouter(tags=["Legal Entity"])


# ============================================================================
# BAGIAN 1: SEMUA ROUTE STATIS DIDAHULUKAN
# ============================================================================
# FastAPI mencocokkan route secara BERURUTAN dari atas file. Route statis
# ("/export", "/login-options", dll) HARUS dideklarasikan SEBELUM route
# dinamis ("/{legal_entity_id}") supaya tidak tertangkap sebagai path
# parameter.


# ----------------------------------------------------------------------------
# 1a. PUBLIC — LOGIN OPTIONS (TANPA AUTH)
# ----------------------------------------------------------------------------

@router.get(
    "/login-options",
    response_model=list[LegalEntityLoginOptionSchema],
    summary="List active legal entities for login screen (public, no auth)",
    operation_id="legal_list_login_options",
)
async def list_legal_entities_for_login(
    request: Request,
) -> list[LegalEntityLoginOptionSchema]:
    """Endpoint publik TANPA autentikasi untuk dropdown Legal Entity di
    halaman login. Path: /api/v1/legal-entities/login-options"""
    try:
        from adapters.secondary_impl.sqlalchemy_legal_entity_repository_impl import (
            SQLAlchemyLegalEntityRepository,
        )
        from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory

        session_maker = await get_async_session_factory()
        async with session_maker() as session:
            repo = SQLAlchemyLegalEntityRepository(session)
            entities = await repo.find_all_active()
            return [
                LegalEntityLoginOptionSchema(
                    id=e.id,
                    legal_name=e.legal_name,
                    trade_name=getattr(e, "trade_name", None),
                )
                for e in entities
            ]
    except Exception as e:
        logger.exception("Failed to list legal entities for login: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# 1b. EXPORT — Path lengkap /legal-entities/export supaya cocok dengan
#     base_path="/legal-entities/legal-entities" yang dipakai frontend.
# ----------------------------------------------------------------------------
# FIX v4 (2026-10-14): path diubah dari "/export" menjadi
# "/legal-entities/export" supaya hasil akhirnya menjadi
# /api/v1/legal-entities/legal-entities/export — cocok dengan yang
# dipanggil GenericListPage (base_path="/legal-entities/legal-entities"),
# dan konsisten dengan route /legal-entities/{legal_entity_id} di bawah.

@router.get(
    "/legal-entities/export",
    summary="Export legal entities to CSV/Excel/JSON",
    operation_id="legal_export_legal_entities",
)
async def export_legal_entities(
    format: str = Query("csv", pattern="^(csv|excel|json)$"),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> Response:
    """Export daftar legal entity ke CSV/Excel/JSON.

    Filter default: hanya entitas yang aktif (is_active=True), sama seperti
    endpoint list — supaya hasil export konsisten dengan yang dilihat di UI.
    """
    try:
        entities = await service.list_legal_entities(is_active=True)

        if format == "csv":
            buf = io.StringIO()
            import csv as _csv
            writer = _csv.writer(buf)
            writer.writerow([
                "legal_name", "trade_name", "entity_type", "registration_number",
                "npwp", "nppp", "address", "city", "province", "postal_code",
                "country", "phone", "fax", "email", "website",
                "fiscal_year_start", "fiscal_year_end",
                "base_currency", "functional_currency",
                "is_taxable", "is_withholding_agent",
                "status", "is_active",
                "created_at", "updated_at",
            ])
            for le in entities:
                writer.writerow([
                    le.legal_name or "",
                    le.trade_name or "",
                    le.entity_type or "",
                    le.registration_number or "",
                    le.npwp or "",
                    le.nppp or "",
                    (le.address or "").replace("\n", " "),
                    le.city or "",
                    le.province or "",
                    le.postal_code or "",
                    le.country or "",
                    le.phone or "",
                    le.fax or "",
                    le.email or "",
                    le.website or "",
                    le.fiscal_year_start or 1,
                    le.fiscal_year_end or 12,
                    le.base_currency or "IDR",
                    le.functional_currency or "IDR",
                    "1" if le.is_taxable else "0",
                    "1" if le.is_withholding_agent else "0",
                    le.status or "",
                    "1" if le.is_active else "0",
                    _format_local_dt(le.created_at),
                    _format_local_dt(le.updated_at),
                ])
            csv_bytes = b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")
            return Response(
                content=csv_bytes,
                media_type="text/csv; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="legal_entities_export.csv"',
                },
            )

        elif format == "json":
            data = [le.to_dict() for le in entities]
            return Response(
                content=json.dumps(data, indent=2, default=str),
                media_type="application/json; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="legal_entities_export.json"',
                },
            )

        elif format == "excel":
            try:
                from openpyxl import Workbook
            except ImportError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Export Excel belum didukung: install 'openpyxl' di server "
                        "(pip install openpyxl) lalu restart backend."
                    ),
                )
            wb = Workbook()
            ws = wb.active
            ws.title = "Legal Entities"
            ws.append([
                "legal_name", "trade_name", "entity_type", "registration_number",
                "npwp", "nppp", "address", "city", "province", "postal_code",
                "country", "phone", "fax", "email", "website",
                "fiscal_year_start", "fiscal_year_end",
                "base_currency", "functional_currency",
                "is_taxable", "is_withholding_agent",
                "status", "is_active",
                "created_at", "updated_at",
            ])
            for le in entities:
                ws.append([
                    le.legal_name or "",
                    le.trade_name or "",
                    le.entity_type or "",
                    le.registration_number or "",
                    le.npwp or "",
                    le.nppp or "",
                    le.address or "",
                    le.city or "",
                    le.province or "",
                    le.postal_code or "",
                    le.country or "",
                    le.phone or "",
                    le.fax or "",
                    le.email or "",
                    le.website or "",
                    le.fiscal_year_start or 1,
                    le.fiscal_year_end or 12,
                    le.base_currency or "IDR",
                    le.functional_currency or "IDR",
                    "1" if le.is_taxable else "0",
                    "1" if le.is_withholding_agent else "0",
                    le.status or "",
                    "1" if le.is_active else "0",
                    _format_local_dt(le.created_at),
                    _format_local_dt(le.updated_at),
                ])
            xlsx_buf = io.BytesIO()
            wb.save(xlsx_buf)
            xlsx_buf.seek(0)
            return Response(
                content=xlsx_buf.read(),
                media_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                headers={
                    "Content-Disposition": 'attachment; filename="legal_entities_export.xlsx"',
                },
            )

        else:
            raise HTTPException(
                status_code=400, detail=f"Format '{format}' belum didukung"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to export legal entities: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# 1c. CONSOLIDATION GROUP (static path, HARUS di atas {legal_entity_id})
# ----------------------------------------------------------------------------

@router.post(
    "/legal-entities/consolidation-groups",
    response_model=ConsolidationGroupResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create consolidation group",
    operation_id="legal_create_consolidation_group",
)
async def create_consolidation_group(
    request: ConsolidationGroupCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    method_name = "create_consolidation_group"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return ConsolidationGroupResponseSchema(**cached)
    try:
        result = await service.create_consolidation_group(
            group_code=request.group_code,
            group_name=request.group_name,
            description=request.description,
            base_currency=request.base_currency,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            description=result.description,
            base_currency=result.base_currency,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            member_count=result.member_count,
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/consolidation-groups",
    response_model=list[ConsolidationGroupResponseSchema],
    summary="List consolidation groups",
    operation_id="legal_list_consolidation_groups",
)
async def list_consolidation_groups(
    is_active: bool | None = Query(None),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[ConsolidationGroupResponseSchema]:
    try:
        groups = await service.list_consolidation_groups(is_active=is_active)
        return [
            ConsolidationGroupResponseSchema(
                id=g.id,
                group_code=g.group_code,
                group_name=g.group_name,
                description=g.description,
                base_currency=g.base_currency,
                fiscal_year_start=g.fiscal_year_start,
                fiscal_year_end=g.fiscal_year_end,
                member_count=g.member_count,
                is_active=g.is_active,
                notes=g.notes,
                created_at=g.created_at,
                updated_at=g.updated_at,
                created_by=g.created_by,
                created_by_name=g.created_by_name,
                version=g.version,
            )
            for g in groups
        ]
    except Exception as e:
        logger.exception("Failed to list consolidation groups: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/consolidation-groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Get consolidation group by ID",
    operation_id="legal_get_consolidation_group",
)
async def get_consolidation_group(
    group_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    try:
        group = await service.get_consolidation_group_by_id(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Consolidation group not found")
        return ConsolidationGroupResponseSchema(
            id=group.id,
            group_code=group.group_code,
            group_name=group.group_name,
            description=group.description,
            base_currency=group.base_currency,
            fiscal_year_start=group.fiscal_year_start,
            fiscal_year_end=group.fiscal_year_end,
            member_count=group.member_count,
            is_active=group.is_active,
            notes=group.notes,
            created_at=group.created_at,
            updated_at=group.updated_at,
            created_by=group.created_by,
            created_by_name=group.created_by_name,
            version=group.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/legal-entities/consolidation-groups/{group_id}",
    response_model=ConsolidationGroupResponseSchema,
    summary="Update consolidation group",
    operation_id="legal_update_consolidation_group",
)
async def update_consolidation_group(
    group_id: UUID,
    request: ConsolidationGroupCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> ConsolidationGroupResponseSchema:
    method_name = "update_consolidation_group"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return ConsolidationGroupResponseSchema(**cached)
    try:
        result = await service.update_consolidation_group(
            group_id=group_id,
            group_name=request.group_name,
            description=request.description,
            base_currency=request.base_currency,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            notes=request.notes,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Consolidation group not found")
        response = ConsolidationGroupResponseSchema(
            id=result.id,
            group_code=result.group_code,
            group_name=result.group_name,
            description=result.description,
            base_currency=result.base_currency,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            member_count=result.member_count,
            is_active=result.is_active,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/legal-entities/consolidation-groups/{group_id}",
    response_model=dict[str, Any],
    summary="Deactivate consolidation group",
    operation_id="legal_deactivate_consolidation_group",
)
async def deactivate_consolidation_group(
    group_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    method_name = "deactivate_consolidation_group"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await service.deactivate_consolidation_group(group_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Consolidation group not found")
        response = {
            "group_id": str(group_id),
            "group_code": result.group_code,
            "is_active": result.is_active,
            "message": "Consolidation group deactivated",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate consolidation group: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/legal-entities/consolidation-groups/{group_id}/members/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Add member to consolidation group",
    operation_id="legal_add_group_member",
)
async def add_group_member(
    group_id: UUID,
    legal_entity_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    method_name = "add_group_member"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await service.add_member_to_group(group_id, legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Group or legal entity not found")
        response = {
            "group_id": str(group_id),
            "legal_entity_id": str(legal_entity_id),
            "legal_entity_name": result.legal_entity_name,
            "added": True,
            "message": "Member added to consolidation group",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to add group member: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/legal-entities/consolidation-groups/{group_id}/members/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Remove member from consolidation group",
    operation_id="legal_remove_group_member",
)
async def remove_group_member(
    group_id: UUID,
    legal_entity_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    method_name = "remove_group_member"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await service.remove_member_from_group(group_id, legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Group or legal entity not found")
        response = {
            "group_id": str(group_id),
            "legal_entity_id": str(legal_entity_id),
            "legal_entity_name": result.legal_entity_name,
            "removed": True,
            "message": "Member removed from consolidation group",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to remove group member: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# BAGIAN 2: CRUD LEGAL ENTITY (root /legal-entities)
# ============================================================================

@router.post(
    "/legal-entities",
    response_model=LegalEntityResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create legal entity",
    operation_id="legal_create_legal_entity",
)
async def create_legal_entity(
    request: LegalEntityCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:create")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    method_name = "create_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return LegalEntityResponseSchema(**cached)
    try:
        result = await service.create_legal_entity(
            legal_name=request.legal_name,
            trade_name=request.trade_name,
            entity_type=request.entity_type.value,
            registration_number=request.registration_number,
            npwp=request.npwp,
            nppp=request.nppp,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            province=request.province,
            country=request.country,
            phone=request.phone,
            fax=request.fax,
            email=request.email,
            website=request.website,
            established_date=request.established_date,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            base_currency=request.base_currency,
            functional_currency=request.functional_currency,
            is_taxable=request.is_taxable,
            is_withholding_agent=request.is_withholding_agent,
            parent_company_id=request.parent_company_id,
            consolidation_group_id=request.consolidation_group_id,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = LegalEntityResponseSchema(
            id=result.id,
            legal_name=result.legal_name,
            trade_name=result.trade_name,
            entity_type=_safe_entity_type(result.entity_type),
            registration_number=result.registration_number,
            npwp=result.npwp,
            nppp=result.nppp,
            address=result.address,
            city=result.city,
            postal_code=result.postal_code,
            province=result.province,
            country=result.country,
            phone=result.phone,
            fax=result.fax,
            email=result.email,
            website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start,
            fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency,
            functional_currency=result.functional_currency,
            is_taxable=result.is_taxable,
            is_withholding_agent=result.is_withholding_agent,
            status=_safe_entity_status(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities",
    response_model=list[LegalEntityResponseSchema],
    summary="List legal entities",
    operation_id="legal_list_legal_entities",
)
async def list_legal_entities(
    entity_type: LegalEntityType | None = Query(None),
    status: LegalEntityStatus | None = Query(None),
    is_active: bool | None = Query(
        None,
        description="Filter aktif/nonaktif. Tidak diisi -> default hanya yang aktif.",
    ),
    parent_company_id: UUID | None = Query(None),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[LegalEntityResponseSchema]:
    try:
        effective_is_active = is_active if is_active is not None else True

        raw_result = await service.list_legal_entities(
            entity_type=entity_type.value if entity_type else None,
            status=status.value if status else None,
            is_active=effective_is_active,
        )
        entities = getattr(raw_result, "items", raw_result)

        def _matches(le: Any) -> bool:
            if parent_company_id is not None and getattr(le, "parent_company_id", None) != parent_company_id:
                return False
            if search:
                needle = search.lower()
                name = (getattr(le, "legal_name", "") or "").lower()
                trade = (getattr(le, "trade_name", "") or "").lower()
                if needle not in name and needle not in trade:
                    return False
            return True

        filtered = [le for le in entities if _matches(le)]
        start = (page - 1) * page_size
        page_items = filtered[start : start + page_size]

        return [
            LegalEntityResponseSchema(
                id=le.id,
                legal_name=le.legal_name,
                trade_name=le.trade_name,
                entity_type=_safe_entity_type(le.entity_type),
                registration_number=le.registration_number,
                npwp=le.npwp,
                nppp=getattr(le, "nppp", None),
                address=le.address,
                city=le.city,
                postal_code=le.postal_code,
                province=getattr(le, "province", None),
                country=le.country,
                phone=le.phone,
                fax=getattr(le, "fax", None),
                email=le.email,
                website=le.website,
                established_date=le.established_date,
                fiscal_year_start=le.fiscal_year_start,
                fiscal_year_end=le.fiscal_year_end,
                base_currency=le.base_currency,
                functional_currency=le.functional_currency,
                is_taxable=getattr(le, "is_taxable", True),
                is_withholding_agent=le.is_withholding_agent,
                status=_safe_entity_status(le.status),
                is_active=le.is_active,
                is_locked=getattr(le, "is_locked", False),
                parent_company_id=le.parent_company_id,
                parent_company_name=getattr(le, "parent_company_name", None),
                consolidation_group_id=le.consolidation_group_id,
                consolidation_group_name=getattr(le, "consolidation_group_name", None),
                notes=getattr(le, "notes", None),
                created_at=le.created_at,
                updated_at=le.updated_at,
                created_by=le.created_by or UUID(int=0),
                created_by_name=getattr(le, "created_by_name", None),
                version=le.version,
            )
            for le in page_items
        ]
    except Exception as e:
        logger.exception("Failed to list legal entities: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# 2b. DYNAMIC — GET /{legal_entity_id} dan sub-route (STATIS SUDAH DI ATAS)
# ----------------------------------------------------------------------------

@router.get(
    "/legal-entities/by-npwp/{npwp}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by NPWP",
    operation_id="legal_get_legal_entity_by_npwp",
)
async def get_legal_entity_by_npwp(
    npwp: str,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    try:
        le = await service.get_legal_entity_by_npwp(npwp)
        if not le:
            raise HTTPException(status_code=404, detail=f"Legal entity with NPWP {npwp} not found")
        return LegalEntityResponseSchema(
            id=le.id, legal_name=le.legal_name, trade_name=le.trade_name,
            entity_type=_safe_entity_type(le.entity_type),
            registration_number=le.registration_number, npwp=le.npwp, nppp=le.nppp,
            address=le.address, city=le.city, postal_code=le.postal_code,
            province=le.province, country=le.country, phone=le.phone, fax=le.fax,
            email=le.email, website=le.website, established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start, fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency, functional_currency=le.functional_currency,
            is_taxable=le.is_taxable, is_withholding_agent=le.is_withholding_agent,
            status=_safe_entity_status(le.status), is_active=le.is_active,
            is_locked=le.is_locked, parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes, created_at=le.created_at, updated_at=le.updated_at,
            created_by=le.created_by, created_by_name=le.created_by_name, version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get legal entity by NPWP: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/by-registration/{registration_number}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by registration number",
    operation_id="legal_get_legal_entity_by_registration",
)
async def get_legal_entity_by_registration(
    registration_number: str,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    try:
        le = await service.get_legal_entity_by_registration(registration_number)
        if not le:
            raise HTTPException(status_code=404, detail=f"Legal entity with registration {registration_number} not found")
        return LegalEntityResponseSchema(
            id=le.id, legal_name=le.legal_name, trade_name=le.trade_name,
            entity_type=_safe_entity_type(le.entity_type),
            registration_number=le.registration_number, npwp=le.npwp, nppp=le.nppp,
            address=le.address, city=le.city, postal_code=le.postal_code,
            province=le.province, country=le.country, phone=le.phone, fax=le.fax,
            email=le.email, website=le.website, established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start, fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency, functional_currency=le.functional_currency,
            is_taxable=le.is_taxable, is_withholding_agent=le.is_withholding_agent,
            status=_safe_entity_status(le.status), is_active=le.is_active,
            is_locked=le.is_locked, parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes, created_at=le.created_at, updated_at=le.updated_at,
            created_by=le.created_by, created_by_name=le.created_by_name, version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get legal entity by registration: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/{legal_entity_id}",
    response_model=LegalEntityResponseSchema,
    summary="Get legal entity by ID",
    operation_id="legal_get_legal_entity",
)
async def get_legal_entity(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    try:
        le = await service.get_legal_entity_by_id(legal_entity_id)
        if not le:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        return LegalEntityResponseSchema(
            id=le.id,
            legal_name=le.legal_name,
            trade_name=le.trade_name,
            entity_type=_safe_entity_type(le.entity_type),
            registration_number=le.registration_number,
            npwp=le.npwp,
            nppp=le.nppp,
            address=le.address,
            city=le.city,
            postal_code=le.postal_code,
            province=le.province,
            country=le.country,
            phone=le.phone,
            fax=le.fax,
            email=le.email,
            website=le.website,
            established_date=le.established_date,
            fiscal_year_start=le.fiscal_year_start,
            fiscal_year_end=le.fiscal_year_end,
            base_currency=le.base_currency,
            functional_currency=le.functional_currency,
            is_taxable=le.is_taxable,
            is_withholding_agent=le.is_withholding_agent,
            status=_safe_entity_status(le.status),
            is_active=le.is_active,
            is_locked=le.is_locked,
            parent_company_id=le.parent_company_id,
            parent_company_name=le.parent_company_name,
            consolidation_group_id=le.consolidation_group_id,
            consolidation_group_name=le.consolidation_group_name,
            notes=le.notes,
            created_at=le.created_at,
            updated_at=le.updated_at,
            created_by=le.created_by,
            created_by_name=le.created_by_name,
            version=le.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/legal-entities/{legal_entity_id}",
    response_model=LegalEntityResponseSchema,
    summary="Update legal entity",
    operation_id="legal_update_legal_entity",
)
async def update_legal_entity(
    legal_entity_id: UUID,
    request: LegalEntityUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    method_name = "update_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return LegalEntityResponseSchema(**cached)
    try:
        result = await service.update_legal_entity(
            legal_entity_id=legal_entity_id,
            legal_name=request.legal_name,
            trade_name=request.trade_name,
            entity_type=request.entity_type.value if request.entity_type else None,
            registration_number=request.registration_number,
            npwp=request.npwp,
            nppp=request.nppp,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            province=request.province,
            country=request.country,
            phone=request.phone,
            fax=request.fax,
            email=request.email,
            website=request.website,
            fiscal_year_start=request.fiscal_year_start,
            fiscal_year_end=request.fiscal_year_end,
            base_currency=request.base_currency,
            functional_currency=request.functional_currency,
            is_taxable=request.is_taxable,
            is_withholding_agent=request.is_withholding_agent,
            parent_company_id=request.parent_company_id,
            status=request.status.value if request.status else None,
            notes=request.notes,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found or cannot be updated")
        response = LegalEntityResponseSchema(
            id=result.id, legal_name=result.legal_name, trade_name=result.trade_name,
            entity_type=_safe_entity_type(result.entity_type),
            registration_number=result.registration_number, npwp=result.npwp, nppp=result.nppp,
            address=result.address, city=result.city, postal_code=result.postal_code,
            province=result.province, country=result.country, phone=result.phone,
            fax=result.fax, email=result.email, website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start, fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency, functional_currency=result.functional_currency,
            is_taxable=result.is_taxable, is_withholding_agent=result.is_withholding_agent,
            status=_safe_entity_status(result.status), is_active=result.is_active,
            is_locked=result.is_locked, parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name, version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/legal-entities/{legal_entity_id}",
    response_model=dict[str, Any],
    summary="Deactivate legal entity",
    operation_id="legal_deactivate_legal_entity",
)
async def deactivate_legal_entity(
    legal_entity_id: UUID,
    reason: str = Query("", description="Reason for deactivation"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    method_name = "deactivate_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await service.deactivate_legal_entity(legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        response = {
            "legal_entity_id": str(legal_entity_id),
            "legal_name": result.legal_name,
            "status": result.status,
            "message": "Legal entity deactivated",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/legal-entities/{legal_entity_id}/activate",
    response_model=LegalEntityResponseSchema,
    summary="Activate legal entity",
    operation_id="legal_activate_legal_entity",
)
async def activate_legal_entity(
    legal_entity_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    method_name = "activate_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return LegalEntityResponseSchema(**cached)
    try:
        result = await service.activate_legal_entity(legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        response = LegalEntityResponseSchema(
            id=result.id, legal_name=result.legal_name, trade_name=result.trade_name,
            entity_type=_safe_entity_type(result.entity_type),
            registration_number=result.registration_number, npwp=result.npwp, nppp=result.nppp,
            address=result.address, city=result.city, postal_code=result.postal_code,
            province=result.province, country=result.country, phone=result.phone,
            fax=result.fax, email=result.email, website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start, fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency, functional_currency=result.functional_currency,
            is_taxable=result.is_taxable, is_withholding_agent=result.is_withholding_agent,
            status=_safe_entity_status(result.status), is_active=result.is_active,
            is_locked=result.is_locked, parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name, version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to activate legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/legal-entities/{legal_entity_id}/lock",
    response_model=LegalEntityResponseSchema,
    summary="Lock legal entity",
    operation_id="legal_lock_legal_entity",
)
async def lock_legal_entity(
    legal_entity_id: UUID,
    reason: str = Query("", description="Lock reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    method_name = "lock_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return LegalEntityResponseSchema(**cached)
    try:
        result = await service.lock_legal_entity(legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        response = LegalEntityResponseSchema(
            id=result.id, legal_name=result.legal_name, trade_name=result.trade_name,
            entity_type=_safe_entity_type(result.entity_type),
            registration_number=result.registration_number, npwp=result.npwp, nppp=result.nppp,
            address=result.address, city=result.city, postal_code=result.postal_code,
            province=result.province, country=result.country, phone=result.phone,
            fax=result.fax, email=result.email, website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start, fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency, functional_currency=result.functional_currency,
            is_taxable=result.is_taxable, is_withholding_agent=result.is_withholding_agent,
            status=_safe_entity_status(result.status), is_active=result.is_active,
            is_locked=True, parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name, version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to lock legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/legal-entities/{legal_entity_id}/unlock",
    response_model=LegalEntityResponseSchema,
    summary="Unlock legal entity",
    operation_id="legal_unlock_legal_entity",
)
async def unlock_legal_entity(
    legal_entity_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:lock")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> LegalEntityResponseSchema:
    method_name = "unlock_legal_entity"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return LegalEntityResponseSchema(**cached)
    try:
        result = await service.unlock_legal_entity(legal_entity_id, current_user.user_id)
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        response = LegalEntityResponseSchema(
            id=result.id, legal_name=result.legal_name, trade_name=result.trade_name,
            entity_type=_safe_entity_type(result.entity_type),
            registration_number=result.registration_number, npwp=result.npwp, nppp=result.nppp,
            address=result.address, city=result.city, postal_code=result.postal_code,
            province=result.province, country=result.country, phone=result.phone,
            fax=result.fax, email=result.email, website=result.website,
            established_date=result.established_date,
            fiscal_year_start=result.fiscal_year_start, fiscal_year_end=result.fiscal_year_end,
            base_currency=result.base_currency, functional_currency=result.functional_currency,
            is_taxable=result.is_taxable, is_withholding_agent=result.is_withholding_agent,
            status=_safe_entity_status(result.status), is_active=result.is_active,
            is_locked=False, parent_company_id=result.parent_company_id,
            parent_company_name=result.parent_company_name,
            consolidation_group_id=result.consolidation_group_id,
            consolidation_group_name=result.consolidation_group_name,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name, version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock legal entity: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# TAX PROFILE
# ----------------------------------------------------------------------------

@router.get(
    "/legal-entities/{legal_entity_id}/tax-profile",
    response_model=TaxProfileResponseSchema,
    summary="Get tax profile",
    operation_id="legal_get_tax_profile",
)
async def get_tax_profile(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> TaxProfileResponseSchema:
    try:
        profile = await service.get_tax_profile(legal_entity_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Tax profile not found")
        return TaxProfileResponseSchema(
            legal_entity_id=profile.legal_entity_id,
            tax_office=profile.tax_office,
            tax_office_code=profile.tax_office_code,
            tax_classification=profile.tax_classification,
            taxable_date=profile.taxable_date,
            vat_collector_number=profile.vat_collector_number,
            annual_tax_return_due_date=profile.annual_tax_return_due_date,
            monthly_tax_due_date=profile.monthly_tax_due_date,
            corporate_tax_rate=profile.corporate_tax_rate,
            vat_rate=profile.vat_rate,
            is_using_final_tax=profile.is_using_final_tax,
            final_tax_rate=profile.final_tax_rate,
            notes=profile.notes,
            status=TaxStatus(profile.status),
            updated_at=profile.updated_at,
            updated_by=profile.updated_by,
            version=profile.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get tax profile: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/legal-entities/{legal_entity_id}/tax-profile",
    response_model=TaxProfileResponseSchema,
    summary="Update tax profile",
    operation_id="legal_update_tax_profile",
)
async def update_tax_profile(
    legal_entity_id: UUID,
    request: TaxProfileSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> TaxProfileResponseSchema:
    method_name = "update_tax_profile"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return TaxProfileResponseSchema(**cached)
    try:
        result = await service.update_tax_profile(
            legal_entity_id=legal_entity_id,
            tax_office=request.tax_office,
            tax_office_code=request.tax_office_code,
            tax_classification=request.tax_classification,
            taxable_date=request.taxable_date,
            vat_collector_number=request.vat_collector_number,
            annual_tax_return_due_date=request.annual_tax_return_due_date,
            monthly_tax_due_date=request.monthly_tax_due_date,
            corporate_tax_rate=request.corporate_tax_rate,
            vat_rate=request.vat_rate,
            is_using_final_tax=request.is_using_final_tax,
            final_tax_rate=request.final_tax_rate,
            notes=request.notes,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        response = TaxProfileResponseSchema(
            legal_entity_id=result.legal_entity_id,
            tax_office=result.tax_office,
            tax_office_code=result.tax_office_code,
            tax_classification=result.tax_classification,
            taxable_date=result.taxable_date,
            vat_collector_number=result.vat_collector_number,
            annual_tax_return_due_date=result.annual_tax_return_due_date,
            monthly_tax_due_date=result.monthly_tax_due_date,
            corporate_tax_rate=result.corporate_tax_rate,
            vat_rate=result.vat_rate,
            is_using_final_tax=result.is_using_final_tax,
            final_tax_rate=result.final_tax_rate,
            notes=result.notes,
            status=TaxStatus(result.status),
            updated_at=result.updated_at,
            updated_by=result.updated_by,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update tax profile: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BRANCH MANAGEMENT
# ----------------------------------------------------------------------------

@router.post(
    "/legal-entities/{legal_entity_id}/branches",
    response_model=BranchResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create branch",
    operation_id="legal_create_branch",
)
async def create_branch(
    legal_entity_id: UUID,
    request: BranchCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    method_name = "create_branch"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return BranchResponseSchema(**cached)
    try:
        result = await service.create_branch(
            legal_entity_id=legal_entity_id,
            branch_code=request.branch_code,
            branch_name=request.branch_name,
            address=request.address,
            city=request.city,
            postal_code=request.postal_code,
            phone=request.phone,
            email=request.email,
            manager_name=request.manager_name,
            is_active=request.is_active,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = BranchResponseSchema(
            id=result.id, legal_entity_id=result.legal_entity_id,
            branch_code=result.branch_code, branch_name=result.branch_name,
            address=result.address, city=result.city, postal_code=result.postal_code,
            phone=result.phone, email=result.email, manager_name=result.manager_name,
            status=BranchStatus(result.status), is_active=result.is_active,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create branch: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/{legal_entity_id}/branches",
    response_model=list[BranchResponseSchema],
    summary="List branches",
    operation_id="legal_list_branches",
)
async def list_branches(
    legal_entity_id: UUID,
    status: BranchStatus | None = Query(None),
    is_active: bool | None = Query(None),
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[BranchResponseSchema]:
    try:
        branches = await service.list_branches(
            legal_entity_id=legal_entity_id,
            status=status.value if status else None,
            is_active=is_active,
        )
        return [
            BranchResponseSchema(
                id=b.id, legal_entity_id=b.legal_entity_id,
                branch_code=b.branch_code, branch_name=b.branch_name,
                address=b.address, city=b.city, postal_code=b.postal_code,
                phone=b.phone, email=b.email, manager_name=b.manager_name,
                status=BranchStatus(b.status), is_active=b.is_active,
                notes=b.notes, created_at=b.created_at, updated_at=b.updated_at,
                created_by=b.created_by, created_by_name=b.created_by_name,
                version=b.version,
            )
            for b in branches
        ]
    except Exception as e:
        logger.exception("Failed to list branches: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/{legal_entity_id}/branches/{branch_id}",
    response_model=BranchResponseSchema,
    summary="Get branch by ID",
    operation_id="legal_get_branch",
)
async def get_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    try:
        branch = await service.get_branch_by_id(branch_id, legal_entity_id)
        if not branch:
            raise HTTPException(status_code=404, detail="Branch not found")
        return BranchResponseSchema(
            id=branch.id, legal_entity_id=branch.legal_entity_id,
            branch_code=branch.branch_code, branch_name=branch.branch_name,
            address=branch.address, city=branch.city, postal_code=branch.postal_code,
            phone=branch.phone, email=branch.email, manager_name=branch.manager_name,
            status=BranchStatus(branch.status), is_active=branch.is_active,
            notes=branch.notes, created_at=branch.created_at, updated_at=branch.updated_at,
            created_by=branch.created_by, created_by_name=branch.created_by_name,
            version=branch.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get branch: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/legal-entities/{legal_entity_id}/branches/{branch_id}",
    response_model=BranchResponseSchema,
    summary="Update branch",
    operation_id="legal_update_branch",
)
async def update_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    request: BranchUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:update")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> BranchResponseSchema:
    method_name = "update_branch"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return BranchResponseSchema(**cached)
    try:
        result = await service.update_branch(
            branch_id=branch_id, legal_entity_id=legal_entity_id,
            branch_name=request.branch_name, address=request.address,
            city=request.city, phone=request.phone, email=request.email,
            manager_name=request.manager_name, is_active=request.is_active,
            status=request.status.value if request.status else None,
            notes=request.notes, updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Branch not found")
        response = BranchResponseSchema(
            id=result.id, legal_entity_id=result.legal_entity_id,
            branch_code=result.branch_code, branch_name=result.branch_name,
            address=result.address, city=result.city, postal_code=result.postal_code,
            phone=result.phone, email=result.email, manager_name=result.manager_name,
            status=BranchStatus(result.status), is_active=result.is_active,
            notes=result.notes, created_at=result.created_at, updated_at=result.updated_at,
            created_by=result.created_by, created_by_name=result.created_by_name,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update branch: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/legal-entities/{legal_entity_id}/branches/{branch_id}",
    response_model=dict[str, Any],
    summary="Close branch",
    operation_id="legal_close_branch",
)
async def close_branch(
    legal_entity_id: UUID,
    branch_id: UUID,
    reason: str = Query("", description="Reason for closure"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("legal_entity:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    method_name = "close_branch"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            return cached
    try:
        result = await service.close_branch(branch_id, legal_entity_id, current_user.user_id, reason)
        if not result:
            raise HTTPException(status_code=404, detail="Branch not found")
        response = {
            "branch_id": str(branch_id),
            "branch_code": result.branch_code,
            "branch_name": result.branch_name,
            "status": result.status,
            "message": "Branch closed",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close branch: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# HISTORY & STATUS
# ----------------------------------------------------------------------------

@router.get(
    "/legal-entities/{legal_entity_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get legal entity history",
    operation_id="legal_get_legal_entity_history",
)
async def get_legal_entity_history(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> list[dict[str, Any]]:
    try:
        history = await service.get_legal_entity_history(legal_entity_id)
        return [
            {
                "timestamp": h.timestamp.isoformat() if h.timestamp else None,
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id) if h.actor_id else None,
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get legal entity history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/legal-entities/{legal_entity_id}/status",
    response_model=dict[str, Any],
    summary="Get legal entity status",
    operation_id="legal_get_legal_entity_status",
)
async def get_legal_entity_status(
    legal_entity_id: UUID,
    _permission: None = Depends(require_permission("legal_entity:read")),
    service: Any = Depends(get_legal_entity_service),
) -> dict[str, Any]:
    try:
        status_info = await service.get_legal_entity_status(legal_entity_id)
        if not status_info:
            raise HTTPException(status_code=404, detail="Legal entity not found")
        return {
            "legal_entity_id": str(legal_entity_id),
            "legal_name": status_info.legal_name,
            "status": status_info.status,
            "is_active": status_info.is_active,
            "is_locked": status_info.is_locked,
            "can_edit": status_info.can_edit,
            "can_delete": status_info.can_delete,
            "can_add_branch": status_info.can_add_branch,
            "can_modify_tax": status_info.can_modify_tax,
            "tax_status": status_info.tax_status,
            "registration_valid": status_info.registration_valid,
            "npwp_valid": status_info.npwp_valid,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get legal entity status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["router"]
