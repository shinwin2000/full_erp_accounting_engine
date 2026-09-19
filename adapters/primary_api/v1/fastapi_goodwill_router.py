#!/usr/bin/env python3
"""
Module: fastapi_goodwill_router.py
Layer: Adapters (Primary API - v1)
Responsibility: REST API endpoint untuk modul Goodwill (PSAK 22/IFRS 3 -
               pengakuan awal; PSAK 48/IAS 36 - impairment testing).

REWRITE NOTES (2026-09-15): file ini ditulis ulang total. Versi
sebelumnya (~2800 baris) memanggil belasan method service yang TIDAK
PERNAH ada (list_goodwill, create_goodwill, get_goodwill_by_id,
get_goodwill_history, get_goodwill_status, get_goodwill_summary,
export_goodwill, get_amortization_schedule, archive_goodwill,
restore_goodwill, get_impairment_test/s, recognize_impairment,
run_amortization) dan skema Pydantic-nya menjanjikan field yang tidak
pernah ada di database sama sekali (goodwill_type, useful_life_years,
amortization_method, acquired_entity_id). SETIAP endpoint di versi lama
pasti crash begitu benar-benar dipanggil dengan data valid.

Router ini disederhanakan untuk PERSIS mengikuti apa yang benar-benar
diimplementasikan di application/service_layer/service_goodwill.py
(yang sendirinya sudah ditulis ulang mengikuti kolom GoodwillTable yang
sesungguhnya). Endpoint yang tidak punya dukungan nyata di service/DB
(amortisasi, export, summary/history laporan, archive/restore) SENGAJA
TIDAK disertakan lagi di sini, dari pada berpura-pura ada padahal akan
selalu 500 - lihat catatan "Endpoint yang belum ada" di bagian akhir file.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/goodwill", tags=["Goodwill"])


# ============================================================================
# ENUMS (disamakan persis dengan CheckConstraint di goodwill_table.py)
# ============================================================================


class GoodwillStatus(str, Enum):
    ACTIVE = "active"
    PARTIALLY_IMPAIRED = "partially_impaired"
    FULLY_IMPAIRED = "fully_impaired"
    DISPOSED = "disposed"


# ============================================================================
# SCHEMAS
# ============================================================================


class GoodwillCreateSchema(BaseModel):
    """Field-fieldnya mengikuti persis GoodwillRecognitionRequest di
    service_goodwill.py, yang mengikuti persis kolom GoodwillTable."""

    goodwill_code: str = Field(..., min_length=1, max_length=50, description="Kode unik goodwill")
    name: str = Field(..., min_length=1, max_length=200, description="Nama/judul goodwill")
    acquisition_date: date
    acquiree_name: str = Field(..., min_length=1, max_length=200, description="Nama entitas yang diakuisisi")
    acquiree_tax_id: str | None = Field(None, max_length=20, description="NPWP entitas yang diakuisisi")
    purchase_price: Decimal = Field(..., gt=0, description="Harga akuisisi/harga beli")
    fair_value_identifiable_net_assets: Decimal = Field(
        ..., ge=0, description="Nilai wajar aset bersih teridentifikasi dari entitas yang diakuisisi"
    )
    cash_generating_unit: str | None = Field(None, max_length=200)
    allocated_to_segment: str | None = Field(None, max_length=100)
    currency: str = Field("IDR", min_length=3, max_length=3)
    exchange_rate_at_acquisition: Decimal = Field(Decimal("1"), gt=0)
    description: str | None = None


class GoodwillUpdateSchema(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    cash_generating_unit: str | None = Field(None, max_length=200)
    allocated_to_segment: str | None = Field(None, max_length=100)
    description: str | None = None


class GoodwillResponseSchema(BaseModel):
    id: UUID
    legal_entity_id: UUID
    goodwill_code: str
    name: str
    description: str | None
    acquisition_date: date
    acquiree_name: str
    acquiree_tax_id: str | None
    purchase_price: Decimal
    fair_value_identifiable_net_assets: Decimal
    goodwill_initial: Decimal
    carrying_amount: Decimal
    impairment_accumulated: Decimal
    net_carrying_amount: Decimal
    currency: str
    exchange_rate_at_acquisition: Decimal
    cash_generating_unit: str | None
    allocated_to_segment: str | None
    status: GoodwillStatus
    is_active: bool
    last_impairment_date: date | None
    last_impairment_loss: Decimal | None
    disposal_date: date | None
    disposal_proceeds: Decimal | None
    disposal_gain_loss: Decimal | None
    disposal_reason: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class ImpairmentTestCreateSchema(BaseModel):
    test_date: date
    recoverable_amount: Decimal = Field(..., ge=0, description="Jumlah terpulihkan (recoverable amount)")
    valuation_method: str = Field("fair_value_less_cost", description="fair_value_less_cost atau value_in_use")
    discount_rate: Decimal | None = Field(None, ge=0, le=1)
    growth_rate: Decimal | None = None
    impairment_source: str = Field("annual_test", description="annual_test, trigger_based, disposal, atau reversal")
    description: str | None = None

    @field_validator("valuation_method")
    @classmethod
    def validate_valuation_method(cls, v: str) -> str:
        if v not in ("fair_value_less_cost", "value_in_use"):
            raise ValueError("valuation_method must be 'fair_value_less_cost' or 'value_in_use'")
        return v

    @field_validator("impairment_source")
    @classmethod
    def validate_impairment_source(cls, v: str) -> str:
        if v not in ("annual_test", "trigger_based", "disposal", "reversal"):
            raise ValueError("impairment_source must be one of: annual_test, trigger_based, disposal, reversal")
        return v


class ImpairmentTestResponseSchema(BaseModel):
    id: UUID
    goodwill_id: UUID
    goodwill_code: str
    test_date: date
    test_period: str
    recoverable_amount: Decimal
    carrying_amount_before: Decimal
    impairment_loss: Decimal
    carrying_amount_after: Decimal
    valuation_method: str
    discount_rate: Decimal | None
    growth_rate: Decimal | None
    impairment_source: str
    description: str | None
    is_impaired: bool
    created_at: datetime


class ImpairmentReversalSchema(BaseModel):
    reversal_date: date
    reversal_amount: Decimal = Field(..., gt=0)
    reason: str = Field(..., min_length=5, max_length=500)


class GoodwillDisposalSchema(BaseModel):
    disposal_date: date
    proceeds: Decimal = Field(Decimal("0"), ge=0, description="Hasil pelepasan/penjualan (jika ada)")
    reason: str | None = Field(None, max_length=500)


class GoodwillDisposalResponseSchema(BaseModel):
    goodwill_id: UUID
    goodwill_code: str
    disposal_date: date
    carrying_amount_before: Decimal
    disposal_proceeds: Decimal
    gain_loss: Decimal
    status: GoodwillStatus


# ============================================================================
# DEPENDENCIES
# ============================================================================


async def get_goodwill_service(request: Request) -> Any:
    """Get GoodwillService instance dari IoC container."""
    from application.service_layer.service_goodwill import GoodwillService

    container = request.app.state.container
    return await container.resolve_async(GoodwillService)


def _to_response_schema(result: Any) -> GoodwillResponseSchema:
    return GoodwillResponseSchema(**result.__dict__)


def _to_impairment_response_schema(result: Any) -> ImpairmentTestResponseSchema:
    return ImpairmentTestResponseSchema(**result.__dict__)


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.post("/", response_model=GoodwillResponseSchema, status_code=status.HTTP_201_CREATED)
async def create_goodwill(
    payload: GoodwillCreateSchema,
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:create")),
) -> GoodwillResponseSchema:
    from application.service_layer.service_goodwill import GoodwillRecognitionRequest

    try:
        result = await service.recognize_goodwill(
            GoodwillRecognitionRequest(
                legal_entity_id=legal_entity_id,
                goodwill_code=payload.goodwill_code,
                name=payload.name,
                acquisition_date=payload.acquisition_date,
                acquiree_name=payload.acquiree_name,
                acquiree_tax_id=payload.acquiree_tax_id,
                purchase_price=payload.purchase_price,
                fair_value_identifiable_net_assets=payload.fair_value_identifiable_net_assets,
                cash_generating_unit=payload.cash_generating_unit,
                allocated_to_segment=payload.allocated_to_segment,
                currency=payload.currency,
                exchange_rate_at_acquisition=payload.exchange_rate_at_acquisition,
                description=payload.description,
                created_by=current_user.user_id,
            ),
        )
        return _to_response_schema(result)
    except Exception as e:
        logger.error(f"Failed to create goodwill: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/", response_model=list[GoodwillResponseSchema])
async def list_goodwill(
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    goodwill_status: GoodwillStatus | None = Query(None, alias="status"),
    cash_generating_unit: str | None = Query(None),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:read")),
) -> list[GoodwillResponseSchema]:
    try:
        results = await service.list_goodwill(
            legal_entity_id=legal_entity_id,
            status=goodwill_status.value if goodwill_status else None,
            cash_generating_unit=cash_generating_unit,
        )
        return [_to_response_schema(r) for r in results]
    except Exception as e:
        logger.error(f"Failed to list goodwill: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


@router.get("/{goodwill_id}", response_model=GoodwillResponseSchema)
async def get_goodwill(
    goodwill_id: UUID,
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:read")),
) -> GoodwillResponseSchema:
    result = await service.get_goodwill(goodwill_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goodwill not found")
    return _to_response_schema(result)


@router.put("/{goodwill_id}", response_model=GoodwillResponseSchema)
async def update_goodwill(
    goodwill_id: UUID,
    payload: GoodwillUpdateSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:update")),
) -> GoodwillResponseSchema:
    from application.service_layer.service_goodwill import (
        GoodwillAlreadyDisposedError,
        GoodwillNotFoundError,
        GoodwillUpdateRequest,
    )

    try:
        result = await service.update_goodwill(
            goodwill_id=goodwill_id,
            request=GoodwillUpdateRequest(
                name=payload.name,
                cash_generating_unit=payload.cash_generating_unit,
                allocated_to_segment=payload.allocated_to_segment,
                description=payload.description,
            ),
            updated_by=current_user.user_id,
        )
        return _to_response_schema(result)
    except GoodwillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except GoodwillAlreadyDisposedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.post("/{goodwill_id}/impairment-tests", response_model=ImpairmentTestResponseSchema)
async def test_impairment(
    goodwill_id: UUID,
    payload: ImpairmentTestCreateSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:impairment")),
) -> ImpairmentTestResponseSchema:
    from application.service_layer.service_goodwill import (
        GoodwillNotFoundError,
        ImpairmentTestRequest,
        InvalidImpairmentTestError,
    )

    try:
        result = await service.test_impairment(
            ImpairmentTestRequest(
                goodwill_id=goodwill_id,
                test_date=payload.test_date,
                recoverable_amount=payload.recoverable_amount,
                valuation_method=payload.valuation_method,
                discount_rate=payload.discount_rate,
                growth_rate=payload.growth_rate,
                impairment_source=payload.impairment_source,
                description=payload.description,
                created_by=current_user.user_id,
            ),
        )
        return _to_impairment_response_schema(result)
    except GoodwillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidImpairmentTestError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.get("/{goodwill_id}/impairment-tests", response_model=list[ImpairmentTestResponseSchema])
async def get_impairment_tests(
    goodwill_id: UUID,
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:read")),
) -> list[ImpairmentTestResponseSchema]:
    results = await service.get_impairment_tests(goodwill_id)
    return [_to_impairment_response_schema(r) for r in results]


@router.post("/{goodwill_id}/reverse-impairment", response_model=GoodwillResponseSchema)
async def reverse_impairment(
    goodwill_id: UUID,
    payload: ImpairmentReversalSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:impairment")),
) -> GoodwillResponseSchema:
    """PERINGATAN: IFRS/PSAK melarang pemulihan rugi impairment goodwill
    kecuali untuk koreksi kesalahan input - lihat docstring
    GoodwillService.reverse_impairment. Gunakan dengan sangat hati-hati."""
    from application.service_layer.service_goodwill import (
        GoodwillNotFoundError,
        InvalidImpairmentTestError,
    )

    try:
        await service.reverse_impairment(
            goodwill_id=goodwill_id,
            reversal_date=payload.reversal_date,
            reversal_amount=payload.reversal_amount,
            reason=payload.reason,
            user_id=current_user.user_id,
        )
        result = await service.get_goodwill(goodwill_id)
        return _to_response_schema(result)
    except GoodwillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except InvalidImpairmentTestError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


@router.post("/{goodwill_id}/dispose", response_model=GoodwillDisposalResponseSchema)
async def dispose_goodwill(
    goodwill_id: UUID,
    payload: GoodwillDisposalSchema,
    current_user: TokenPayload = Depends(get_current_user),
    service: Any = Depends(get_goodwill_service),
    _permission: None = Depends(require_permission("goodwill:dispose")),
) -> GoodwillDisposalResponseSchema:
    from application.service_layer.service_goodwill import (
        GoodwillAlreadyDisposedError,
        GoodwillDisposalRequest,
        GoodwillNotFoundError,
    )

    try:
        result = await service.dispose_goodwill(
            GoodwillDisposalRequest(
                goodwill_id=goodwill_id,
                disposal_date=payload.disposal_date,
                proceeds=payload.proceeds,
                reason=payload.reason,
                disposed_by=current_user.user_id,
            ),
        )
        return GoodwillDisposalResponseSchema(**result.__dict__)
    except GoodwillNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except GoodwillAlreadyDisposedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e


# ============================================================================
# Endpoint yang BELUM ada (dihapus dari versi lama, bukan lupa ditulis)
# ============================================================================
# Berikut endpoint yang ada di versi router SEBELUMNYA tapi memanggil method
# service yang tidak pernah ada dan tidak pernah bisa berhasil - sengaja
# tidak disertakan lagi di sini daripada berpura-pura berfungsi:
#   - amortize_goodwill / run_amortization / get_amortization_schedule
#     (goodwill tidak diamortisasi - PSAK 22/IFRS 3, keputusan sudah
#     dikonfirmasi user saat audit modul ini)
#   - get_goodwill_history / get_goodwill_status / get_goodwill_summary
#     (perlu desain baru - agregasi/laporan, belum ada logikanya)
#   - export_goodwill (perlu desain format ekspor)
#   - archive_goodwill / restore_goodwill (belum ada konsep archive
#     terpisah dari status 'disposed' di skema saat ini)
#   - get_goodwill_by_code (trivial ditambahkan kalau dibutuhkan - query
#     WHERE goodwill_code = ... AND legal_entity_id = ...)
#   - recognize_impairment terpisah dari test_impairment (di desain baru
#     ini, test_impairment LANGSUNG mengakui impairment-nya, tidak ada
#     tahap draft/recognize terpisah)

__all__ = ["router"]
