#!/usr/bin/env python3
"""
Module: fastapi_intangible_asset_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola intangible assets:
               aset tak berwujud (goodwill, paten, lisensi, merek, hak cipta,
               software, franchise, dll.), amortization schedule, amortization run,
               impairment test, revaluation, disposal.

Method Standards (ERP):
- create_asset() / update_asset() / delete_asset() / get_asset()
- activate_asset() / deactivate_asset() / lock_asset() / unlock_asset()
- capitalize_asset() / amortize_asset() / run_amortization()
- revalue_asset() / transfer_asset() / dispose_asset()
- test_impairment() / restore_impairment()
- get_amortization_schedule() / get_nbv_schedule()
- get_asset_history() / get_asset_snapshot()
- audit_trail_asset() / can_transition_asset()
- register_asset_event() / get_asset_events() / clear_asset_events()
- version_asset()
"""


from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
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


# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class IntangibleAssetCategory(str, Enum):
    """Kategori aset tidak berwujud."""

    PATENT = "patent"  # Paten
    TRADEMARK = "trademark"  # Merek dagang
    COPYRIGHT = "copyright"  # Hak cipta
    SOFTWARE = "software"  # Perangkat lunak
    LICENSE = "license"  # Lisensi
    FRANCHISE = "franchise"  # Waralaba
    GOODWILL = "goodwill"  # Goodwill (terpisah)
    CUSTOMER_RELATIONSHIP = "customer_relationship"  # Hubungan pelanggan
    TECHNOLOGY = "technology"  # Teknologi
    BRAND = "brand"  # Merek
    OTHER = "other"  # Lainnya


class AmortizationMethod(str, Enum):
    """Metode amortisasi."""

    STRAIGHT_LINE = "straight_line"  # Garis lurus
    DECLINING_BALANCE = "declining_balance"  # Saldo menurun
    DOUBLE_DECLINING = "double_declining"  # Double declining balance
    SUM_OF_YEARS = "sum_of_years"  # Jumlah angka tahun
    UNITS_OF_PRODUCTION = "units_of_production"  # Unit produksi


class IntangibleAssetStatus(str, Enum):
    """Status aset tidak berwujud."""

    DRAFT = "draft"
    ACTIVE = "active"
    FULLY_AMORTIZED = "fully_amortized"
    IMPAIRED = "impaired"
    DISPOSED = "disposed"
    SOLD = "sold"
    LOCKED = "locked"
    ARCHIVED = "archived"


class DisposalType(str, Enum):
    """Jenis penghentian aset."""

    SALE = "sale"  # Dijual
    SCRAP = "scrap"  # Diafkirkan
    DONATION = "donation"  # Disumbangkan
    EXPIRED = "expired"  # Kadaluarsa
    LOSS = "loss"  # Hilang


# Default amortization parameters
DEFAULT_USEFUL_LIFE_YEARS = {
    IntangibleAssetCategory.PATENT: 20,
    IntangibleAssetCategory.TRADEMARK: 10,
    IntangibleAssetCategory.COPYRIGHT: 50,
    IntangibleAssetCategory.SOFTWARE: 5,
    IntangibleAssetCategory.LICENSE: 10,
    IntangibleAssetCategory.FRANCHISE: 10,
    IntangibleAssetCategory.CUSTOMER_RELATIONSHIP: 15,
    IntangibleAssetCategory.TECHNOLOGY: 5,
    IntangibleAssetCategory.BRAND: 20,
}

# Indonesian tax amortization rates (for fiscal purposes)
FISCAL_AMORTIZATION_RATES = {
    IntangibleAssetCategory.PATENT: 0.25,  # 25% per year (double declining)
    IntangibleAssetCategory.SOFTWARE: 0.50,  # 50% per year (double declining)
    IntangibleAssetCategory.LICENSE: 0.25,  # 25% per year
    IntangibleAssetCategory.TRADEMARK: 0.25,  # 25% per year
    IntangibleAssetCategory.COPYRIGHT: 0.25,  # 25% per year
}


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class IntangibleAssetCreateSchema(BaseModel):
    """Schema untuk membuat aset tidak berwujud baru."""

    model_config = ConfigDict(from_attributes=True)

    asset_code: str = Field(..., min_length=3, max_length=30, description="Kode aset")
    asset_name: str = Field(..., min_length=3, max_length=200, description="Nama aset")
    asset_category: IntangibleAssetCategory = Field(..., description="Kategori aset")
    acquisition_date: date = Field(..., description="Tanggal perolehan")
    acquisition_cost: Decimal = Field(..., gt=0, decimal_places=2, description="Harga perolehan")
    residual_value: Decimal = Field(0, ge=0, decimal_places=2, description="Nilai residu")
    useful_life_years: int | None = Field(None, gt=0, description="Umur ekonomis (tahun)")
    amortization_method: AmortizationMethod = Field(
        AmortizationMethod.STRAIGHT_LINE, description="Metode amortisasi"
    )
    amortization_rate: Decimal | None = Field(
        None, gt=0, le=100, decimal_places=4, description="Tarif amortisasi"
    )
    registration_number: str | None = Field(None, max_length=50, description="Nomor registrasi")
    issuing_authority: str | None = Field(
        None, max_length=200, description="Penerbit (untuk paten, lisensi)"
    )
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa (jika ada)")
    is_active: bool = Field(True, description="Aktif")
    use_fiscal_amortization: bool = Field(False, description="Gunakan tarif fiskal")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    attachment_ids: list[UUID] | None = Field(None, description="Dokumen pendukung")

    @field_validator("asset_code")
    @classmethod
    def validate_asset_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Asset code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_amortization(self) -> IntangibleAssetCreateSchema:
        if self.useful_life_years is None:
            # Use default based on category
            self.useful_life_years = DEFAULT_USEFUL_LIFE_YEARS.get(self.asset_category, 10)
        if self.amortization_method == AmortizationMethod.UNITS_OF_PRODUCTION:
            if not self.amortization_rate:
                raise ValueError("Amortization rate required for units of production method")
        if self.expiry_date and self.expiry_date <= self.acquisition_date:
            raise ValueError("Expiry date must be after acquisition date")
        return self


class IntangibleAssetUpdateSchema(BaseModel):
    """Schema untuk update aset tidak berwujud."""

    model_config = ConfigDict(from_attributes=True)

    asset_name: str | None = Field(None, min_length=3, max_length=200)
    residual_value: Decimal | None = Field(None, ge=0, decimal_places=2)
    useful_life_years: int | None = Field(None, gt=0)
    amortization_method: AmortizationMethod | None = None
    is_active: bool | None = None
    notes: str | None = Field(None, max_length=500)
    status: IntangibleAssetStatus | None = None


class IntangibleAssetResponseSchema(BaseModel):
    """Response aset tidak berwujud."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_code: str
    asset_name: str
    asset_category: IntangibleAssetCategory
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    amortization_method: AmortizationMethod
    amortization_rate: Decimal | None = None
    accumulated_amortization: Decimal
    accumulated_impairment: Decimal = Decimal(0)
    net_book_value: Decimal
    current_period_amortization: Decimal
    registration_number: str | None
    issuing_authority: str | None
    expiry_date: date | None
    status: IntangibleAssetStatus
    is_active: bool
    is_locked: bool = False
    use_fiscal_amortization: bool = False
    notes: str | None
    attachment_ids: list[UUID] | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class AmortizationScheduleLineSchema(BaseModel):
    """Line dalam jadwal amortisasi."""

    model_config = ConfigDict(from_attributes=True)

    period: int
    fiscal_year: int
    month: int
    period_name: str
    amortization_amount: Decimal
    accumulated_amortization: Decimal
    net_book_value: Decimal
    status: str
    journal_id: UUID | None = None
    posted_at: datetime | None = None


class AmortizationScheduleResponseSchema(BaseModel):
    """Response jadwal amortisasi."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: UUID
    asset_code: str
    asset_name: str
    start_date: date
    end_date: date
    lines: list[AmortizationScheduleLineSchema]
    total_amortization: Decimal
    final_nbv: Decimal
    generated_at: datetime


class AmortizationRunRequestSchema(BaseModel):
    """Schema untuk menjalankan amortisasi massal."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date = Field(..., description="Tanggal amortisasi")
    asset_ids: list[UUID] | None = Field(None, description="Aset yang diproses (kosong = semua)")
    post_to_ledger: bool = Field(True, description="Posting ke GL")
    fiscal_year: int | None = Field(None, description="Tahun fiskal")
    period: int | None = Field(None, ge=1, le=12, description="Periode")


class AmortizationRunResponseSchema(BaseModel):
    """Response amortisasi massal."""

    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    run_number: str
    as_of_date: date
    total_assets: int
    total_amortization: Decimal
    journal_ids: list[UUID]
    status: str
    errors: list[str] = []
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class RevaluationRequestSchema(BaseModel):
    """Schema untuk revaluasi aset tidak berwujud."""

    model_config = ConfigDict(from_attributes=True)

    revaluation_date: date = Field(..., description="Tanggal revaluasi")
    new_acquisition_cost: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Nilai perolehan baru"
    )
    new_residual_value: Decimal | None = Field(
        None, ge=0, decimal_places=2, description="Nilai residu baru"
    )
    new_useful_life_years: int | None = Field(None, gt=0, description="Umur ekonomis baru")
    revaluation_surplus: Decimal | None = Field(None, description="Surplus revaluasi")
    reason: str = Field(..., max_length=500, description="Alasan revaluasi")
    appraiser_name: str | None = Field(None, max_length=200, description="Nama penilai independen")
    appraisal_report_number: str | None = Field(
        None, max_length=50, description="Nomor laporan penilaian"
    )


class RevaluationResponseSchema(BaseModel):
    """Response revaluasi aset."""

    model_config = ConfigDict(from_attributes=True)

    revaluation_id: UUID
    asset_id: UUID
    asset_code: str
    revaluation_date: date
    old_acquisition_cost: Decimal
    new_acquisition_cost: Decimal
    old_accumulated_amortization: Decimal
    new_accumulated_amortization: Decimal
    old_nbv: Decimal
    new_nbv: Decimal
    surplus_deficit: Decimal
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


class DisposalRequestSchema(BaseModel):
    """Schema untuk penghentian aset tidak berwujud."""

    model_config = ConfigDict(from_attributes=True)

    disposal_date: date = Field(..., description="Tanggal penghentian")
    disposal_type: DisposalType = Field(..., description="Jenis penghentian")
    disposal_proceeds: Decimal = Field(0, ge=0, decimal_places=2, description="Hasil penjualan")
    disposal_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya penghentian")
    reason: str = Field(..., max_length=500, description="Alasan penghentian")
    buyer_name: str | None = Field(None, max_length=200, description="Nama pembeli")
    notes: str | None = Field(None, max_length=500)


class DisposalResponseSchema(BaseModel):
    """Response penghentian aset."""

    model_config = ConfigDict(from_attributes=True)

    disposal_id: UUID
    asset_id: UUID
    asset_code: str
    disposal_date: date
    disposal_type: DisposalType
    disposal_proceeds: Decimal
    disposal_cost: Decimal
    net_proceeds: Decimal
    nbv_at_disposal: Decimal
    gain_loss: Decimal
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


class ImpairmentTestRequestSchema(BaseModel):
    """Schema untuk impairment test."""

    model_config = ConfigDict(from_attributes=True)

    test_date: date = Field(..., description="Tanggal pengujian")
    recoverable_amount: Decimal = Field(
        ..., gt=0, decimal_places=2, description="Jumlah terpulihkan"
    )
    reason: str | None = Field(None, max_length=500, description="Alasan penurunan nilai")
    valuation_method: str | None = Field(None, description="Metode penilaian")


class ImpairmentTestResponseSchema(BaseModel):
    """Response impairment test."""

    model_config = ConfigDict(from_attributes=True)

    test_id: UUID
    asset_id: UUID
    asset_code: str
    test_date: date
    carrying_amount: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    impairment_percentage: float
    journal_id: UUID | None = None
    status: str
    created_at: datetime
    created_by: UUID


class AssetTransferRequestSchema(BaseModel):
    """Schema untuk transfer aset antar entitas."""

    model_config = ConfigDict(from_attributes=True)

    transfer_date: date = Field(..., description="Tanggal transfer")
    from_legal_entity_id: UUID = Field(..., description="Entitas asal")
    to_legal_entity_id: UUID = Field(..., description="Entitas tujuan")
    reason: str = Field(..., max_length=500, description="Alasan transfer")
    notes: str | None = Field(None, max_length=500)


class AssetTransferResponseSchema(BaseModel):
    """Response transfer aset."""

    model_config = ConfigDict(from_attributes=True)

    transfer_id: UUID
    asset_id: UUID
    asset_code: str
    transfer_date: date
    from_legal_entity_id: UUID
    from_legal_entity_name: str | None
    to_legal_entity_id: UUID
    to_legal_entity_name: str | None
    nbv_at_transfer: Decimal
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


class IntangibleAssetSummaryResponseSchema(BaseModel):
    """Response ringkasan aset tidak berwujud."""

    model_config = ConfigDict(from_attributes=True)

    total_assets: int
    total_acquisition_cost: Decimal
    total_accumulated_amortization: Decimal
    total_accumulated_impairment: Decimal
    total_net_book_value: Decimal
    monthly_amortization_charge: Decimal
    by_category: dict[str, dict[str, Any]]
    by_status: dict[str, int]
    as_of_date: date
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_intangible_asset_svc(request: Request) -> Any:
    """
    Get Intangible Asset Service instance.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.service_layer.service_intangible_asset import IntangibleAssetService

    container = request.app.state.container
    return container.resolve(IntangibleAssetService)


async def get_amortization_run_use_case(request: Request) -> Any:
    """Get Amortization Monthly Run Use Case instance."""
    from application.use_cases.amortization_monthly_run import AmortizationMonthlyRunUseCase

    container = request.app.state.container
    return container.resolve(AmortizationMonthlyRunUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/intangible-assets", tags=["Intangible Assets"])


# ----------------------------------------------------------------------------
# ASSET CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/",
    response_model=IntangibleAssetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create intangible asset",
    operation_id="intangible_create_intangible_asset",
)
async def create_asset(
    request: IntangibleAssetCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("intangible_asset:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """
    Create a new intangible asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import IntangibleAssetCreateRequest

    method_name = "create_intangible_asset"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return IntangibleAssetResponseSchema(**cached)

    try:
        # Calculate amortization rate if not provided
        amortization_rate = request.amortization_rate
        if amortization_rate is None and request.useful_life_years:
            if request.amortization_method == AmortizationMethod.STRAIGHT_LINE:
                amortization_rate = (Decimal(100) / Decimal(request.useful_life_years)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
            elif request.amortization_method == AmortizationMethod.DOUBLE_DECLINING:
                straight_rate = Decimal(100) / Decimal(request.useful_life_years)
                amortization_rate = (straight_rate * Decimal(2)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )

        dto = IntangibleAssetCreateRequest(
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_category=request.asset_category.value,
            acquisition_date=request.acquisition_date,
            acquisition_cost=request.acquisition_cost,
            residual_value=request.residual_value,
            useful_life_years=request.useful_life_years,
            amortization_method=request.amortization_method.value,
            amortization_rate=amortization_rate,
            registration_number=request.registration_number,
            issuing_authority=request.issuing_authority,
            expiry_date=request.expiry_date,
            is_active=request.is_active,
            use_fiscal_amortization=request.use_fiscal_amortization,
            notes=request.notes,
            attachment_ids=request.attachment_ids,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await intangible_asset_svc.create_asset(dto)

        response = IntangibleAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=IntangibleAssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            amortization_method=AmortizationMethod(result.amortization_method),
            amortization_rate=result.amortization_rate,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            current_period_amortization=result.current_period_amortization,
            registration_number=result.registration_number,
            issuing_authority=result.issuing_authority,
            expiry_date=result.expiry_date,
            status=IntangibleAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            use_fiscal_amortization=result.use_fiscal_amortization,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
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
        logger.exception("Failed to create intangible asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/{asset_id}",
    response_model=IntangibleAssetResponseSchema,
    summary="Get intangible asset by ID",
    operation_id="intangible_get_intangible_asset",
)
async def get_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """Get intangible asset by ID."""
    try:
        asset = await intangible_asset_svc.get_asset_by_id(asset_id, legal_entity_id)

        if not asset:
            raise HTTPException(status_code=404, detail="Intangible asset not found")

        return IntangibleAssetResponseSchema(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=IntangibleAssetCategory(asset.asset_category),
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=AmortizationMethod(asset.amortization_method),
            amortization_rate=asset.amortization_rate,
            accumulated_amortization=asset.accumulated_amortization,
            accumulated_impairment=asset.accumulated_impairment,
            net_book_value=asset.net_book_value,
            current_period_amortization=asset.current_period_amortization,
            registration_number=asset.registration_number,
            issuing_authority=asset.issuing_authority,
            expiry_date=asset.expiry_date,
            status=IntangibleAssetStatus(asset.status),
            is_active=asset.is_active,
            is_locked=asset.is_locked,
            use_fiscal_amortization=asset.use_fiscal_amortization,
            notes=asset.notes,
            attachment_ids=asset.attachment_ids,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            created_by_name=asset.created_by_name,
            version=asset.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get intangible asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/by-code/{asset_code}",
    response_model=IntangibleAssetResponseSchema,
    summary="Get intangible asset by code",
    operation_id="intangible_get_intangible_asset_by_code",
)
async def get_asset_by_code(
    asset_code: str,
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """Get intangible asset by asset code."""
    try:
        asset = await intangible_asset_svc.get_asset_by_code(asset_code, legal_entity_id)

        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {asset_code} not found")

        return IntangibleAssetResponseSchema(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=IntangibleAssetCategory(asset.asset_category),
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            amortization_method=AmortizationMethod(asset.amortization_method),
            amortization_rate=asset.amortization_rate,
            accumulated_amortization=asset.accumulated_amortization,
            accumulated_impairment=asset.accumulated_impairment,
            net_book_value=asset.net_book_value,
            current_period_amortization=asset.current_period_amortization,
            registration_number=asset.registration_number,
            issuing_authority=asset.issuing_authority,
            expiry_date=asset.expiry_date,
            status=IntangibleAssetStatus(asset.status),
            is_active=asset.is_active,
            is_locked=asset.is_locked,
            use_fiscal_amortization=asset.use_fiscal_amortization,
            notes=asset.notes,
            attachment_ids=asset.attachment_ids,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            created_by_name=asset.created_by_name,
            version=asset.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get asset by code: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/{asset_id}",
    response_model=IntangibleAssetResponseSchema,
    summary="Update intangible asset",
    operation_id="intangible_update_intangible_asset",
)
async def update_asset(
    asset_id: UUID,
    request: IntangibleAssetUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("intangible_asset:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """
    Update intangible asset information.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import IntangibleAssetUpdateRequest

    method_name = "update_intangible_asset"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return IntangibleAssetResponseSchema(**cached)

    try:
        dto = IntangibleAssetUpdateRequest(
            id=asset_id,
            asset_name=request.asset_name,
            residual_value=request.residual_value,
            useful_life_years=request.useful_life_years,
            amortization_method=request.amortization_method.value
            if request.amortization_method
            else None,
            is_active=request.is_active,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await intangible_asset_svc.update_asset(dto)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found or cannot be updated")

        response = IntangibleAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=IntangibleAssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            amortization_method=AmortizationMethod(result.amortization_method),
            amortization_rate=result.amortization_rate,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            current_period_amortization=result.current_period_amortization,
            registration_number=result.registration_number,
            issuing_authority=result.issuing_authority,
            expiry_date=result.expiry_date,
            status=IntangibleAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            use_fiscal_amortization=result.use_fiscal_amortization,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
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
        logger.exception("Failed to update intangible asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/{asset_id}",
    response_model=dict[str, Any],
    summary="Archive intangible asset",
    operation_id="intangible_archive_intangible_asset",
)
async def archive_asset(
    asset_id: UUID,
    reason: str = Query("", description="Reason for archiving"),
    _permission: None = Depends(require_permission("intangible_asset:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> dict[str, Any]:
    """
    Archive an intangible asset (soft delete).
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.archive_asset(
            asset_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return {
            "asset_id": str(asset_id),
            "asset_code": result.asset_code,
            "status": result.status,
            "message": "Asset archived",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to archive asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{asset_id}/activate",
    response_model=IntangibleAssetResponseSchema,
    summary="Activate intangible asset",
    operation_id="intangible_activate_intangible_asset",
)
async def activate_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("intangible_asset:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """
    Activate a deactivated intangible asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.activate_asset(asset_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return IntangibleAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=IntangibleAssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            amortization_method=AmortizationMethod(result.amortization_method),
            amortization_rate=result.amortization_rate,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            current_period_amortization=result.current_period_amortization,
            registration_number=result.registration_number,
            issuing_authority=result.issuing_authority,
            expiry_date=result.expiry_date,
            status=IntangibleAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
            use_fiscal_amortization=result.use_fiscal_amortization,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to activate asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{asset_id}/lock",
    response_model=IntangibleAssetResponseSchema,
    summary="Lock intangible asset for audit",
    operation_id="intangible_lock_intangible_asset",
)
async def lock_asset(
    asset_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("intangible_asset:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """
    Lock asset to prevent modifications.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.lock_asset(asset_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return IntangibleAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=IntangibleAssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            amortization_method=AmortizationMethod(result.amortization_method),
            amortization_rate=result.amortization_rate,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            current_period_amortization=result.current_period_amortization,
            registration_number=result.registration_number,
            issuing_authority=result.issuing_authority,
            expiry_date=result.expiry_date,
            status=IntangibleAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=True,
            use_fiscal_amortization=result.use_fiscal_amortization,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{asset_id}/unlock",
    response_model=IntangibleAssetResponseSchema,
    summary="Unlock intangible asset",
    operation_id="intangible_unlock_intangible_asset",
)
async def unlock_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("intangible_asset:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetResponseSchema:
    """
    Unlock a locked intangible asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.unlock_asset(asset_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return IntangibleAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=IntangibleAssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            amortization_method=AmortizationMethod(result.amortization_method),
            amortization_rate=result.amortization_rate,
            accumulated_amortization=result.accumulated_amortization,
            accumulated_impairment=result.accumulated_impairment,
            net_book_value=result.net_book_value,
            current_period_amortization=result.current_period_amortization,
            registration_number=result.registration_number,
            issuing_authority=result.issuing_authority,
            expiry_date=result.expiry_date,
            status=IntangibleAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=False,
            use_fiscal_amortization=result.use_fiscal_amortization,
            notes=result.notes,
            attachment_ids=result.attachment_ids,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST ASSETS
# ----------------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[IntangibleAssetResponseSchema],
    summary="List intangible assets",
    operation_id="intangible_list_intangible_assets",
)
async def list_assets(
    asset_category: IntangibleAssetCategory | None = Query(None, description="Filter by category"),
    status: IntangibleAssetStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    search: str | None = Query(None, description="Search in code or name"),
    expiry_before: date | None = Query(None, description="Assets expiring before date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> list[IntangibleAssetResponseSchema]:
    """List intangible assets with pagination and filters."""
    try:
        result = await intangible_asset_svc.list_assets(
            legal_entity_id=legal_entity_id,
            category=asset_category.value if asset_category else None,
            status=status.value if status else None,
            is_active=is_active,
            search=search,
            expiry_before=expiry_before,
            page=page,
            page_size=page_size,
        )

        return [
            IntangibleAssetResponseSchema(
                id=asset.id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                asset_category=IntangibleAssetCategory(asset.asset_category),
                acquisition_date=asset.acquisition_date,
                acquisition_cost=asset.acquisition_cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                amortization_method=AmortizationMethod(asset.amortization_method),
                amortization_rate=asset.amortization_rate,
                accumulated_amortization=asset.accumulated_amortization,
                accumulated_impairment=asset.accumulated_impairment,
                net_book_value=asset.net_book_value,
                current_period_amortization=asset.current_period_amortization,
                registration_number=asset.registration_number,
                issuing_authority=asset.issuing_authority,
                expiry_date=asset.expiry_date,
                status=IntangibleAssetStatus(asset.status),
                is_active=asset.is_active,
                is_locked=asset.is_locked,
                use_fiscal_amortization=asset.use_fiscal_amortization,
                notes=asset.notes,
                attachment_ids=asset.attachment_ids,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
                created_by=asset.created_by,
                created_by_name=asset.created_by_name,
                version=asset.version,
            )
            for asset in result.items
        ]
    except Exception as e:
        logger.exception(f"Failed to list intangible assets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AMORTIZATION SCHEDULE
# ----------------------------------------------------------------------------


@router.get(
    "/{asset_id}/amortization-schedule",
    response_model=AmortizationScheduleResponseSchema,
    summary="Get amortization schedule",
    operation_id="intangible_get_amortization_schedule",
)
async def get_amortization_schedule(
    asset_id: UUID,
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> AmortizationScheduleResponseSchema:
    """Get amortization schedule for an intangible asset."""
    try:
        schedule = await intangible_asset_svc.get_amortization_schedule(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return AmortizationScheduleResponseSchema(
            asset_id=schedule.asset_id,
            asset_code=schedule.asset_code,
            asset_name=schedule.asset_name,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            lines=[
                AmortizationScheduleLineSchema(
                    period=line.period,
                    fiscal_year=line.fiscal_year,
                    month=line.month,
                    period_name=line.period_name,
                    amortization_amount=line.amortization_amount,
                    accumulated_amortization=line.accumulated_amortization,
                    net_book_value=line.net_book_value,
                    status=line.status,
                    journal_id=line.journal_id,
                    posted_at=line.posted_at,
                )
                for line in schedule.lines
            ],
            total_amortization=schedule.total_amortization,
            final_nbv=schedule.final_nbv,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get amortization schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AMORTIZATION RUN (MASSAL)
# ----------------------------------------------------------------------------


@router.post(
    "/amortization/run",
    response_model=AmortizationRunResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Run monthly amortization",
    operation_id="intangible_run_amortization",
)
async def run_amortization(
    request: AmortizationRunRequestSchema,
    _permission: None = Depends(require_permission("intangible_asset:amortize")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    use_case: Any = Depends(get_amortization_run_use_case),
) -> AmortizationRunResponseSchema:
    """
    Run monthly amortization for all active intangible assets.
    LOCKING: Use case layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import AmortizationRunRequest

    try:
        dto = AmortizationRunRequest(
            as_of_date=request.as_of_date,
            asset_ids=request.asset_ids,
            post_to_ledger=request.post_to_ledger,
            fiscal_year=request.fiscal_year,
            period=request.period,
            run_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await use_case.execute(dto)

        return AmortizationRunResponseSchema(
            run_id=result.run_id,
            run_number=result.run_number,
            as_of_date=request.as_of_date,
            total_assets=result.total_assets,
            total_amortization=result.total_amortization,
            journal_ids=result.journal_ids,
            status=result.status,
            errors=result.errors,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to run amortization: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/amortization/{amortization_id}/reverse",
    response_model=dict[str, Any],
    summary="Reverse amortization entry",
    operation_id="intangible_reverse_amortization",
)
async def reverse_amortization(
    amortization_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    _permission: None = Depends(require_permission("intangible_asset:amortize")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> dict[str, Any]:
    """
    Reverse a posted amortization entry.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.reverse_amortization(
            amortization_id=amortization_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Amortization entry not found")

        return {
            "amortization_id": str(amortization_id),
            "reversed": True,
            "reversal_journal_id": str(result.reversal_journal_id),
            "message": "Amortization reversed successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse amortization: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REVALUATION
# ----------------------------------------------------------------------------


@router.post(
    "/{asset_id}/revaluation",
    response_model=RevaluationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Revalue intangible asset",
    operation_id="intangible_revalue_intangible_asset",
)
async def revalue_asset(
    asset_id: UUID,
    request: RevaluationRequestSchema,
    _permission: None = Depends(require_permission("intangible_asset:revaluation")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> RevaluationResponseSchema:
    """
    Revalue an intangible asset (increase or decrease).
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import RevaluationRequest

    try:
        dto = RevaluationRequest(
            asset_id=asset_id,
            revaluation_date=request.revaluation_date,
            new_acquisition_cost=request.new_acquisition_cost,
            new_residual_value=request.new_residual_value,
            new_useful_life_years=request.new_useful_life_years,
            revaluation_surplus=request.revaluation_surplus,
            reason=request.reason,
            appraiser_name=request.appraiser_name,
            appraisal_report_number=request.appraisal_report_number,
            performed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await intangible_asset_svc.revaluate_asset(dto)

        return RevaluationResponseSchema(
            revaluation_id=result.revaluation_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            revaluation_date=request.revaluation_date,
            old_acquisition_cost=result.old_acquisition_cost,
            new_acquisition_cost=result.new_acquisition_cost,
            old_accumulated_amortization=result.old_accumulated_amortization,
            new_accumulated_amortization=result.new_accumulated_amortization,
            old_nbv=result.old_nbv,
            new_nbv=result.new_nbv,
            surplus_deficit=result.surplus_deficit,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to revalue asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DISPOSAL (PENGENTIAN ASET)
# ----------------------------------------------------------------------------


@router.post(
    "/{asset_id}/disposal",
    response_model=DisposalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Dispose intangible asset",
    operation_id="intangible_dispose_intangible_asset",
)
async def dispose_asset(
    asset_id: UUID,
    request: DisposalRequestSchema,
    _permission: None = Depends(require_permission("intangible_asset:disposal")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> DisposalResponseSchema:
    """
    Dispose (sell/scrap/expire) an intangible asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import DisposalRequest

    try:
        dto = DisposalRequest(
            asset_id=asset_id,
            disposal_date=request.disposal_date,
            disposal_type=request.disposal_type.value,
            disposal_proceeds=request.disposal_proceeds,
            disposal_cost=request.disposal_cost,
            reason=request.reason,
            buyer_name=request.buyer_name,
            notes=request.notes,
            disposed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await intangible_asset_svc.dispose_asset(dto)

        return DisposalResponseSchema(
            disposal_id=result.disposal_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            disposal_date=request.disposal_date,
            disposal_type=DisposalType(result.disposal_type),
            disposal_proceeds=request.disposal_proceeds,
            disposal_cost=request.disposal_cost,
            net_proceeds=result.net_proceeds,
            nbv_at_disposal=result.nbv_at_disposal,
            gain_loss=result.gain_loss,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to dispose asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# IMPAIRMENT TEST
# ----------------------------------------------------------------------------


@router.post(
    "/{asset_id}/impairment-test",
    response_model=ImpairmentTestResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Test intangible asset for impairment",
    operation_id="intangible_test_intangible_asset_impairment",
)
async def test_impairment(
    asset_id: UUID,
    request: ImpairmentTestRequestSchema,
    _permission: None = Depends(require_permission("intangible_asset:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> ImpairmentTestResponseSchema:
    """
    Test intangible asset for impairment and recognize loss if needed.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.dto_objects.intangible_asset_request import ImpairmentTestRequest

    try:
        dto = ImpairmentTestRequest(
            asset_id=asset_id,
            test_date=request.test_date,
            recoverable_amount=request.recoverable_amount,
            reason=request.reason,
            valuation_method=request.valuation_method,
            tested_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await intangible_asset_svc.test_impairment(dto)

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            test_date=request.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=request.recoverable_amount,
            impairment_loss=result.impairment_loss,
            impairment_percentage=result.impairment_percentage,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to test impairment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/{asset_id}/impairment-restore",
    response_model=ImpairmentTestResponseSchema,
    summary="Restore previously recognized impairment",
    operation_id="intangible_restore_impairment",
)
async def restore_impairment(
    asset_id: UUID,
    test_id: UUID = Query(..., description="Impairment test ID to restore"),
    reason: str = Query(..., min_length=5, description="Restoration reason"),
    _permission: None = Depends(require_permission("intangible_asset:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> ImpairmentTestResponseSchema:
    """
    Restore previously recognized impairment loss.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.restore_impairment(
            asset_id=asset_id,
            test_id=test_id,
            reason=reason,
            restored_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Impairment test not found")

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            test_date=result.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=result.recoverable_amount,
            impairment_loss=result.impairment_loss,
            impairment_percentage=result.impairment_percentage,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to restore impairment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ASSET TRANSFER
# ----------------------------------------------------------------------------


@router.post(
    "/{asset_id}/transfer",
    response_model=AssetTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer intangible asset between legal entities",
    operation_id="intangible_transfer_intangible_asset",
)
async def transfer_asset(
    asset_id: UUID,
    request: AssetTransferRequestSchema,
    _permission: None = Depends(require_permission("intangible_asset:transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> AssetTransferResponseSchema:
    """
    Transfer intangible asset to another legal entity (inter-company).
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await intangible_asset_svc.transfer_asset(
            asset_id=asset_id,
            from_legal_entity_id=legal_entity_id,
            to_legal_entity_id=request.to_legal_entity_id,
            transfer_date=request.transfer_date,
            reason=request.reason,
            notes=request.notes,
            transferred_by=current_user.user_id,
        )

        return AssetTransferResponseSchema(
            transfer_id=result.transfer_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            transfer_date=request.transfer_date,
            from_legal_entity_id=legal_entity_id,
            from_legal_entity_name=result.from_legal_entity_name,
            to_legal_entity_id=request.to_legal_entity_id,
            to_legal_entity_name=result.to_legal_entity_name,
            nbv_at_transfer=result.nbv_at_transfer,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to transfer asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ASSET SUMMARY
# ----------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=IntangibleAssetSummaryResponseSchema,
    summary="Get intangible asset summary",
    operation_id="intangible_get_intangible_asset_summary",
)
async def get_asset_summary(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> IntangibleAssetSummaryResponseSchema:
    """Get intangible asset summary (total cost, NBV, monthly amortization)."""
    try:
        summary = await intangible_asset_svc.get_summary(legal_entity_id, as_of_date)

        return IntangibleAssetSummaryResponseSchema(
            total_assets=summary.total_assets,
            total_acquisition_cost=summary.total_acquisition_cost,
            total_accumulated_amortization=summary.total_accumulated_amortization,
            total_accumulated_impairment=summary.total_accumulated_impairment,
            total_net_book_value=summary.total_net_book_value,
            monthly_amortization_charge=summary.monthly_amortization_charge,
            by_category=summary.by_category,
            by_status=summary.by_status,
            as_of_date=as_of_date,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get asset summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT ASSET REGISTER
# ----------------------------------------------------------------------------


@router.get(
    "/export",
    summary="Export intangible asset register",
    operation_id="intangible_export_intangible_asset_register",
)
async def export_asset_register(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    as_of_date: date = Query(..., description="As of date"),
    category: IntangibleAssetCategory | None = Query(None, description="Filter by category"),
    _permission: None = Depends(require_permission("intangible_asset:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> Response:
    """Export intangible asset register to CSV or Excel."""
    try:
        data = await intangible_asset_svc.export_asset_register(
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            format=format,
            category=category.value if category else None,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"intangible_asset_register_{legal_entity_id}_{as_of_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Failed to export asset register: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ASSET HISTORY & AUDIT
# ----------------------------------------------------------------------------


@router.get(
    "/{asset_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get asset history",
    operation_id="intangible_get_intangible_asset_history",
)
async def get_asset_history(
    asset_id: UUID,
    _permission: None = Depends(require_permission("intangible_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    intangible_asset_svc: Any = Depends(get_intangible_asset_svc),
) -> list[dict[str, Any]]:
    """Get asset change history (audit trail)."""
    try:
        history = await intangible_asset_svc.get_asset_history(asset_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "field": h.field,
                "old_value": h.old_value,
                "new_value": h.new_value,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception(f"Failed to get asset history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]