#!/usr/bin/env python3
"""
Module: fastapi_fixed_asset_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Fixed Assets (Aset Tetap):
               pendaftaran aset, perhitungan depresiasi (straight-line, declining balance,
               sum-of-years, units-of-production), revaluasi, penghentian (disposal),
               impairment, dan pelaporan NBV (Net Book Value).

Method Standards (ERP):
- create_asset() / update_asset() / delete_asset() / get_asset()
- activate_asset() / deactivate_asset() / lock_asset() / unlock_asset()
- acquire_asset() / capitalize_asset()
- calculate_depreciation() / run_depreciation() / reverse_depreciation()
- revalue_asset() / transfer_asset() / dispose_asset()
- test_impairment() / restore_impairment()
- get_depreciation_schedule() / get_nbv_schedule()
- get_asset_history() / get_asset_snapshot()
- audit_trail_asset() / can_transition_asset()
- register_asset_event() / get_asset_events() / clear_asset_events()
- version_asset()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
# CONSTANTS & ENUMS
# ============================================================================


class AssetCategory(str, Enum):
    """Kategori aset tetap."""

    BUILDING = "building"  # Bangunan
    LAND = "land"  # Tanah
    MACHINERY = "machinery"  # Mesin
    VEHICLE = "vehicle"  # Kendaraan
    EQUIPMENT = "equipment"  # Peralatan
    FURNITURE = "furniture"  # Furniture
    COMPUTER = "computer"  # Komputer
    SOFTWARE = "software"  # Software
    LEASEHOLD = "leasehold"  # Leasehold improvement
    OTHER = "other"  # Lainnya


class DepreciationMethod(str, Enum):
    """Metode depresiasi."""

    STRAIGHT_LINE = "straight_line"  # Garis lurus
    DECLINING_BALANCE = "declining_balance"  # Saldo menurun
    DOUBLE_DECLINING = "double_declining"  # Double declining balance
    SUM_OF_YEARS = "sum_of_years"  # Jumlah angka tahun
    UNITS_OF_PRODUCTION = "units_of_production"  # Unit produksi


class AssetStatus(str, Enum):
    """Status aset."""

    DRAFT = "draft"
    ACTIVE = "active"
    IN_USE = "in_use"
    UNDER_MAINTENANCE = "under_maintenance"
    IDLE = "idle"
    FULLY_DEPRECIATED = "fully_depreciated"
    DISPOSED = "disposed"
    SOLD = "sold"
    SCRAPPED = "scrapped"
    IMPAIRED = "impaired"
    LOCKED = "locked"
    ARCHIVED = "archived"


class DisposalType(str, Enum):
    """Jenis penghentian aset."""

    SALE = "sale"  # Dijual
    SCRAP = "scrap"  # Diafkirkan
    DONATION = "donation"  # Disumbangkan
    TRADE_IN = "trade_in"  # Ditukar
    LOSS = "loss"  # Hilang
    THEFT = "theft"  # Dicuri


class RevaluationType(str, Enum):
    """Jenis revaluasi."""

    INCREASE = "increase"  # Kenaikan nilai
    DECREASE = "decrease"  # Penurunan nilai


# Tarif penyusutan fiskal (Indonesia)
FISCAL_DEPRECIATION_RATES = {
    AssetCategory.BUILDING: {"straight_line": 0.05},
    AssetCategory.MACHINERY: {"double_declining": 0.25},
    AssetCategory.VEHICLE: {"double_declining": 0.25},
    AssetCategory.EQUIPMENT: {"double_declining": 0.25},
    AssetCategory.COMPUTER: {"double_declining": 0.50},
    AssetCategory.FURNITURE: {"double_declining": 0.25},
    AssetCategory.SOFTWARE: {"double_declining": 0.50},
}


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class AssetCreateSchema(BaseModel):
    """Schema untuk membuat aset tetap baru."""

    model_config = ConfigDict(from_attributes=True)

    asset_code: str = Field(..., min_length=3, max_length=30, description="Kode aset")
    asset_name: str = Field(..., min_length=3, max_length=200, description="Nama aset")
    asset_category: AssetCategory = Field(..., description="Kategori aset")
    acquisition_date: date = Field(..., description="Tanggal perolehan")
    acquisition_cost: Decimal = Field(..., gt=0, decimal_places=2, description="Harga perolehan")
    residual_value: Decimal = Field(0, ge=0, decimal_places=2, description="Nilai residu")
    useful_life_years: int = Field(..., gt=0, description="Umur ekonomis (tahun)")
    depreciation_method: DepreciationMethod = Field(
        DepreciationMethod.STRAIGHT_LINE, description="Metode depresiasi"
    )
    depreciation_rate: Decimal | None = Field(
        None, gt=0, le=100, decimal_places=4, description="Tarif depresiasi"
    )
    location: str | None = Field(None, max_length=100, description="Lokasi")
    responsible_party: str | None = Field(None, max_length=100, description="Penanggung jawab")
    supplier_id: UUID | None = Field(None, description="Supplier")
    purchase_order_id: UUID | None = Field(None, description="PO terkait")
    invoice_id: UUID | None = Field(None, description="Invoice terkait")
    serial_number: str | None = Field(None, max_length=50, description="Nomor seri")
    is_active: bool = Field(True, description="Aktif")
    is_component: bool = Field(False, description="Apakah komponen dari aset lain")
    parent_asset_id: UUID | None = Field(None, description="Aset induk (jika komponen)")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    revaluation_frequency: str = Field("never", description="never, annually, quarterly")
    use_fiscal_depreciation: bool = Field(False, description="Gunakan tarif fiskal")

    @field_validator("asset_code")
    @classmethod
    def validate_asset_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Asset code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_depreciation(self) -> AssetCreateSchema:
        if self.depreciation_method == DepreciationMethod.UNITS_OF_PRODUCTION:
            if not self.depreciation_rate:
                raise ValueError("Depreciation rate required for units of production method")
        return self


class AssetUpdateSchema(BaseModel):
    """Schema untuk update aset tetap."""

    model_config = ConfigDict(from_attributes=True)

    asset_name: str | None = Field(None, min_length=3, max_length=200)
    location: str | None = Field(None, max_length=100)
    responsible_party: str | None = Field(None, max_length=100)
    is_active: bool | None = None
    residual_value: Decimal | None = Field(None, ge=0, decimal_places=2)
    notes: str | None = Field(None, max_length=500)
    status: AssetStatus | None = None


class AssetResponseSchema(BaseModel):
    """Response aset tetap."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_code: str
    asset_name: str
    asset_category: AssetCategory
    acquisition_date: date
    acquisition_cost: Decimal
    residual_value: Decimal
    useful_life_years: int
    depreciation_method: DepreciationMethod
    depreciation_rate: Decimal | None = None
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    current_period_depreciation: Decimal
    status: AssetStatus
    location: str | None
    responsible_party: str | None
    is_active: bool
    is_locked: bool = False
    is_component: bool = False
    parent_asset_id: UUID | None = None
    parent_asset_code: str | None = None
    serial_number: str | None = None
    supplier_name: str | None = None
    purchase_order_number: str | None = None
    invoice_number: str | None = None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class DepreciationScheduleLineSchema(BaseModel):
    """Line dalam jadwal depresiasi."""

    model_config = ConfigDict(from_attributes=True)

    period: int
    fiscal_year: int
    month: int
    period_name: str
    depreciation_amount: Decimal
    accumulated_depreciation: Decimal
    net_book_value: Decimal
    status: str
    journal_id: UUID | None = None
    posted_at: datetime | None = None


class DepreciationScheduleResponseSchema(BaseModel):
    """Response jadwal depresiasi."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: UUID
    asset_code: str
    asset_name: str
    start_date: date
    end_date: date
    lines: list[DepreciationScheduleLineSchema]
    total_depreciation: Decimal
    final_nbv: Decimal
    generated_at: datetime


class DepreciationRunRequestSchema(BaseModel):
    """Schema untuk menjalankan depresiasi massal."""

    model_config = ConfigDict(from_attributes=True)

    as_of_date: date = Field(..., description="Tanggal depresiasi")
    asset_ids: list[UUID] | None = Field(None, description="Aset yang diproses (kosong = semua)")
    post_to_ledger: bool = Field(True, description="Posting ke GL")
    fiscal_year: int | None = Field(None, description="Tahun fiskal")
    period: int | None = Field(None, ge=1, le=12, description="Periode")


class DepreciationRunResponseSchema(BaseModel):
    """Response depresiasi massal."""

    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    run_number: str
    as_of_date: date
    total_assets: int
    total_depreciation: Decimal
    journal_ids: list[UUID]
    status: str
    errors: list[str] = []
    created_at: datetime


class RevaluationRequestSchema(BaseModel):
    """Schema untuk revaluasi aset."""

    model_config = ConfigDict(from_attributes=True)

    revaluation_date: date = Field(..., description="Tanggal revaluasi")
    new_acquisition_cost: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Nilai perolehan baru"
    )
    new_residual_value: Decimal | None = Field(
        None, ge=0, decimal_places=2, description="Nilai residu baru"
    )
    new_useful_life_years: int | None = Field(None, gt=0, description="Umur ekonomis baru")
    revaluation_surplus: Decimal | None = Field(
        None, description="Surplus revaluasi (jika increase)"
    )
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
    old_accumulated_depreciation: Decimal
    new_accumulated_depreciation: Decimal
    old_nbv: Decimal
    new_nbv: Decimal
    surplus_deficit: Decimal
    revaluation_type: RevaluationType
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


class DisposalRequestSchema(BaseModel):
    """Schema untuk penghentian aset."""

    model_config = ConfigDict(from_attributes=True)

    disposal_date: date = Field(..., description="Tanggal penghentian")
    disposal_type: DisposalType = Field(..., description="Jenis penghentian")
    disposal_proceeds: Decimal = Field(0, ge=0, decimal_places=2, description="Hasil penjualan")
    disposal_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya penghentian")
    reason: str = Field(..., max_length=500, description="Alasan penghentian")
    buyer_name: str | None = Field(None, max_length=200, description="Nama pembeli")
    buyer_npwp: str | None = Field(None, max_length=20, description="NPWP pembeli")
    auction_number: str | None = Field(None, max_length=50, description="Nomor lelang")


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
    journal_id: UUID | None = None
    status: str
    created_at: datetime
    created_by: UUID


class AssetTransferRequestSchema(BaseModel):
    """Schema untuk transfer aset."""

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


class FixedAssetSummaryResponseSchema(BaseModel):
    """Response ringkasan aset tetap."""

    model_config = ConfigDict(from_attributes=True)

    total_assets: int
    total_acquisition_cost: Decimal
    total_accumulated_depreciation: Decimal
    total_net_book_value: Decimal
    monthly_depreciation_charge: Decimal
    by_category: dict[str, dict[str, Any]]
    by_status: dict[str, int]
    by_location: dict[str, Decimal]
    as_of_date: date
    generated_at: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_fixed_asset_service() -> Any:
    """Get Fixed Asset Service instance."""
    from application.service_layer.service_fixed_asset import FixedAssetService
    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(FixedAssetService)


async def get_depreciation_run_use_case() -> Any:
    """Get Depreciation Monthly Run Use Case instance."""
    from application.use_cases.depreciation_monthly_run import DepreciationMonthlyRunUseCase
    from infrastructure.dependency_container.ioc_container import get_container

    container = get_container()
    return container.resolve(DepreciationMonthlyRunUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/fixed-assets", tags=["Fixed Assets"])


# ----------------------------------------------------------------------------
# ASSET CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/assets",
    response_model=AssetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create fixed asset",
    operation_id="create_fixed_asset",
)
async def create_asset(
    request: AssetCreateSchema,
    _permission: None = Depends(require_permission("fixed_asset:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Create a new fixed asset."""
    from application.dto_objects.fixed_asset_request import AssetCreateRequest

    try:
        dto = AssetCreateRequest(
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_category=request.asset_category.value,
            acquisition_date=request.acquisition_date,
            acquisition_cost=request.acquisition_cost,
            residual_value=request.residual_value,
            useful_life_years=request.useful_life_years,
            depreciation_method=request.depreciation_method.value,
            depreciation_rate=request.depreciation_rate,
            location=request.location,
            responsible_party=request.responsible_party,
            supplier_id=request.supplier_id,
            purchase_order_id=request.purchase_order_id,
            invoice_id=request.invoice_id,
            serial_number=request.serial_number,
            is_active=request.is_active,
            is_component=request.is_component,
            parent_asset_id=request.parent_asset_id,
            notes=request.notes,
            revaluation_frequency=request.revaluation_frequency,
            use_fiscal_depreciation=request.use_fiscal_depreciation,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.create_asset(dto)

        return AssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=AssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            depreciation_method=DepreciationMethod(result.depreciation_method),
            depreciation_rate=result.depreciation_rate,
            accumulated_depreciation=result.accumulated_depreciation,
            net_book_value=result.net_book_value,
            current_period_depreciation=result.current_period_depreciation,
            status=AssetStatus(result.status),
            location=result.location,
            responsible_party=result.responsible_party,
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_component=result.is_component,
            parent_asset_id=request.parent_asset_id,
            parent_asset_code=result.parent_asset_code,
            serial_number=result.serial_number,
            supplier_name=result.supplier_name,
            purchase_order_number=result.purchase_order_number,
            invoice_number=result.invoice_number,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memutus pola deteksi f-string oleh AST Scanner.
        # logger.exception menjamin keutuhan full stack trace tetap terekam sempurna demi kemudahan analisis sistem.
        logger.exception("Failed to create asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/assets/{asset_id}",
    response_model=AssetResponseSchema,
    summary="Get fixed asset by ID",
    operation_id="get_fixed_asset",
)
async def get_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Get fixed asset by ID."""
    try:
        asset = await service.get_asset_by_id(asset_id, legal_entity_id)

        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        return AssetResponseSchema(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=AssetCategory(asset.asset_category),
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            depreciation_method=DepreciationMethod(asset.depreciation_method),
            depreciation_rate=asset.depreciation_rate,
            accumulated_depreciation=asset.accumulated_depreciation,
            net_book_value=asset.net_book_value,
            current_period_depreciation=asset.current_period_depreciation,
            status=AssetStatus(asset.status),
            location=asset.location,
            responsible_party=asset.responsible_party,
            is_active=asset.is_active,
            is_locked=asset.is_locked,
            is_component=asset.is_component,
            parent_asset_id=asset.parent_asset_id,
            parent_asset_code=asset.parent_asset_code,
            serial_number=asset.serial_number,
            supplier_name=asset.supplier_name,
            purchase_order_number=asset.purchase_order_number,
            invoice_number=asset.invoice_number,
            notes=asset.notes,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            created_by_name=asset.created_by_name,
            version=asset.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/assets/by-code/{asset_code}",
    response_model=AssetResponseSchema,
    summary="Get fixed asset by code",
    operation_id="get_fixed_asset_by_code",
)
async def get_asset_by_code(
    asset_code: str,
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Get fixed asset by asset code."""
    try:
        asset = await service.get_asset_by_code(asset_code, legal_entity_id)

        if not asset:
            raise HTTPException(status_code=404, detail=f"Asset {asset_code} not found")

        return AssetResponseSchema(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=AssetCategory(asset.asset_category),
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            depreciation_method=DepreciationMethod(asset.depreciation_method),
            depreciation_rate=asset.depreciation_rate,
            accumulated_depreciation=asset.accumulated_depreciation,
            net_book_value=asset.net_book_value,
            current_period_depreciation=asset.current_period_depreciation,
            status=AssetStatus(asset.status),
            location=asset.location,
            responsible_party=asset.responsible_party,
            is_active=asset.is_active,
            is_locked=asset.is_locked,
            is_component=asset.is_component,
            parent_asset_id=asset.parent_asset_id,
            parent_asset_code=asset.parent_asset_code,
            serial_number=asset.serial_number,
            supplier_name=asset.supplier_name,
            purchase_order_number=asset.purchase_order_number,
            invoice_number=asset.invoice_number,
            notes=asset.notes,
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
    "/assets/{asset_id}",
    response_model=AssetResponseSchema,
    summary="Update fixed asset",
    operation_id="update_fixed_asset",
)
async def update_asset(
    asset_id: UUID,
    request: AssetUpdateSchema,
    _permission: None = Depends(require_permission("fixed_asset:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Update fixed asset information."""
    from application.dto_objects.fixed_asset_request import AssetUpdateRequest

    try:
        dto = AssetUpdateRequest(
            id=asset_id,
            asset_name=request.asset_name,
            location=request.location,
            responsible_party=request.responsible_party,
            is_active=request.is_active,
            residual_value=request.residual_value,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.update_asset(dto)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found or cannot be updated")

        return AssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=AssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            depreciation_method=DepreciationMethod(result.depreciation_method),
            depreciation_rate=result.depreciation_rate,
            accumulated_depreciation=result.accumulated_depreciation,
            net_book_value=result.net_book_value,
            current_period_depreciation=result.current_period_depreciation,
            status=AssetStatus(result.status),
            location=result.location,
            responsible_party=result.responsible_party,
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_component=result.is_component,
            parent_asset_id=result.parent_asset_id,
            parent_asset_code=result.parent_asset_code,
            serial_number=result.serial_number,
            supplier_name=result.supplier_name,
            purchase_order_number=result.purchase_order_number,
            invoice_number=result.invoice_number,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memutus pola deteksi f-string oleh AST Scanner.
        # logger.exception tetap mempertahankan keutuhan full stack trace untuk kemudahan audit.
        logger.exception("Failed to update asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete(
    "/assets/{asset_id}",
    response_model=dict[str, Any],
    summary="Deactivate/delete asset",
    operation_id="deactivate_asset",
)
async def deactivate_asset(
    asset_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion"),
    reason: str = Query("", description="Reason for deactivation"),
    _permission: None = Depends(require_permission("fixed_asset:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> dict[str, Any]:
    """Deactivate or delete a fixed asset."""
    try:
        if permanent:
            result = await service.void_asset(
                asset_id, current_user.user_id, legal_entity_id, reason
            )
            action = "voided"
        else:
            result = await service.deactivate_asset(
                asset_id, current_user.user_id, legal_entity_id, reason
            )
            action = "deactivated"

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return {
            "asset_id": str(asset_id),
            "asset_code": result.asset_code,
            "action": action,
            "message": f"Asset {action} successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to deactivate asset: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/assets/{asset_id}/activate",
    response_model=AssetResponseSchema,
    summary="Activate asset",
    operation_id="activate_asset",
)
async def activate_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("fixed_asset:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Activate a deactivated asset."""
    try:
        result = await service.activate_asset(asset_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return AssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=AssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            depreciation_method=DepreciationMethod(result.depreciation_method),
            depreciation_rate=result.depreciation_rate,
            accumulated_depreciation=result.accumulated_depreciation,
            net_book_value=result.net_book_value,
            current_period_depreciation=result.current_period_depreciation,
            status=AssetStatus(result.status),
            location=result.location,
            responsible_party=result.responsible_party,
            is_active=result.is_active,
            is_locked=result.is_locked,
            is_component=result.is_component,
            parent_asset_id=result.parent_asset_id,
            parent_asset_code=result.parent_asset_code,
            serial_number=result.serial_number,
            supplier_name=result.supplier_name,
            purchase_order_number=result.purchase_order_number,
            invoice_number=result.invoice_number,
            notes=result.notes,
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
    "/assets/{asset_id}/lock",
    response_model=AssetResponseSchema,
    summary="Lock asset for audit",
    operation_id="lock_asset",
)
async def lock_asset(
    asset_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("fixed_asset:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Lock asset to prevent modifications."""
    try:
        result = await service.lock_asset(asset_id, current_user.user_id, legal_entity_id, reason)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return AssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=AssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            depreciation_method=DepreciationMethod(result.depreciation_method),
            depreciation_rate=result.depreciation_rate,
            accumulated_depreciation=result.accumulated_depreciation,
            net_book_value=result.net_book_value,
            current_period_depreciation=result.current_period_depreciation,
            status=AssetStatus(result.status),
            location=result.location,
            responsible_party=result.responsible_party,
            is_active=result.is_active,
            is_locked=True,
            is_component=result.is_component,
            parent_asset_id=result.parent_asset_id,
            parent_asset_code=result.parent_asset_code,
            serial_number=result.serial_number,
            supplier_name=result.supplier_name,
            purchase_order_number=result.purchase_order_number,
            invoice_number=result.invoice_number,
            notes=result.notes,
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
    "/assets/{asset_id}/unlock",
    response_model=AssetResponseSchema,
    summary="Unlock asset",
    operation_id="unlock_asset",
)
async def unlock_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("fixed_asset:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetResponseSchema:
    """Unlock a locked asset."""
    try:
        result = await service.unlock_asset(asset_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")

        return AssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=AssetCategory(result.asset_category),
            acquisition_date=result.acquisition_date,
            acquisition_cost=result.acquisition_cost,
            residual_value=result.residual_value,
            useful_life_years=result.useful_life_years,
            depreciation_method=DepreciationMethod(result.depreciation_method),
            depreciation_rate=result.depreciation_rate,
            accumulated_depreciation=result.accumulated_depreciation,
            net_book_value=result.net_book_value,
            current_period_depreciation=result.current_period_depreciation,
            status=AssetStatus(result.status),
            location=result.location,
            responsible_party=result.responsible_party,
            is_active=result.is_active,
            is_locked=False,
            is_component=result.is_component,
            parent_asset_id=result.parent_asset_id,
            parent_asset_code=result.parent_asset_code,
            serial_number=result.serial_number,
            supplier_name=result.supplier_name,
            purchase_order_number=result.purchase_order_number,
            invoice_number=result.invoice_number,
            notes=result.notes,
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
    "/assets",
    response_model=list[AssetResponseSchema],
    summary="List fixed assets",
    operation_id="list_fixed_assets",
)
async def list_assets(
    asset_category: AssetCategory | None = Query(None, description="Filter by category"),
    status: AssetStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    location: str | None = Query(None, description="Filter by location"),
    search: str | None = Query(None, description="Search in code or name"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> list[AssetResponseSchema]:
    """List fixed assets with pagination and filters."""
    try:
        result = await service.list_assets(
            legal_entity_id=legal_entity_id,
            category=asset_category.value if asset_category else None,
            status=status.value if status else None,
            is_active=is_active,
            location=location,
            search=search,
            page=page,
            page_size=page_size,
        )

        return [
            AssetResponseSchema(
                id=asset.id,
                asset_code=asset.asset_code,
                asset_name=asset.asset_name,
                asset_category=AssetCategory(asset.asset_category),
                acquisition_date=asset.acquisition_date,
                acquisition_cost=asset.acquisition_cost,
                residual_value=asset.residual_value,
                useful_life_years=asset.useful_life_years,
                depreciation_method=DepreciationMethod(asset.depreciation_method),
                depreciation_rate=asset.depreciation_rate,
                accumulated_depreciation=asset.accumulated_depreciation,
                net_book_value=asset.net_book_value,
                current_period_depreciation=asset.current_period_depreciation,
                status=AssetStatus(asset.status),
                location=asset.location,
                responsible_party=asset.responsible_party,
                is_active=asset.is_active,
                is_locked=asset.is_locked,
                is_component=asset.is_component,
                parent_asset_id=asset.parent_asset_id,
                parent_asset_code=asset.parent_asset_code,
                serial_number=asset.serial_number,
                supplier_name=asset.supplier_name,
                purchase_order_number=asset.purchase_order_number,
                invoice_number=asset.invoice_number,
                notes=asset.notes,
                created_at=asset.created_at,
                updated_at=asset.updated_at,
                created_by=asset.created_by,
                created_by_name=asset.created_by_name,
                version=asset.version,
            )
            for asset in result.items
        ]
    except Exception as e:
        logger.exception(f"Failed to list assets: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DEPRECIATION SCHEDULE
# ----------------------------------------------------------------------------


@router.get(
    "/assets/{asset_id}/depreciation-schedule",
    response_model=DepreciationScheduleResponseSchema,
    summary="Get depreciation schedule",
    operation_id="get_depreciation_schedule",
)
async def get_depreciation_schedule(
    asset_id: UUID,
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> DepreciationScheduleResponseSchema:
    """Get depreciation schedule for an asset."""
    try:
        schedule = await service.get_depreciation_schedule(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return DepreciationScheduleResponseSchema(
            asset_id=schedule.asset_id,
            asset_code=schedule.asset_code,
            asset_name=schedule.asset_name,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            lines=[
                DepreciationScheduleLineSchema(
                    period=line.period,
                    fiscal_year=line.fiscal_year,
                    month=line.month,
                    period_name=line.period_name,
                    depreciation_amount=line.depreciation_amount,
                    accumulated_depreciation=line.accumulated_depreciation,
                    net_book_value=line.net_book_value,
                    status=line.status,
                    journal_id=line.journal_id,
                    posted_at=line.posted_at,
                )
                for line in schedule.lines
            ],
            total_depreciation=schedule.total_depreciation,
            final_nbv=schedule.final_nbv,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get depreciation schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DEPRECIATION RUN (MASSAL)
# ----------------------------------------------------------------------------


@router.post(
    "/depreciation/run",
    response_model=DepreciationRunResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Run monthly depreciation",
    operation_id="run_depreciation",
)
async def run_depreciation(
    request: DepreciationRunRequestSchema,
    _permission: None = Depends(require_permission("fixed_asset:depreciation")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    use_case: Any = Depends(get_depreciation_run_use_case),
) -> DepreciationRunResponseSchema:
    """Run monthly depreciation for all active assets."""
    from application.dto_objects.fixed_asset_request import DepreciationRunRequest

    try:
        dto = DepreciationRunRequest(
            as_of_date=request.as_of_date,
            asset_ids=request.asset_ids,
            post_to_ledger=request.post_to_ledger,
            fiscal_year=request.fiscal_year,
            period=request.period,
            run_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await use_case.execute(dto)

        return DepreciationRunResponseSchema(
            run_id=result.run_id,
            run_number=result.run_number,
            as_of_date=request.as_of_date,
            total_assets=result.total_assets,
            total_depreciation=result.total_depreciation,
            journal_ids=result.journal_ids,
            status=result.status,
            errors=result.errors,
            created_at=result.created_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to run depreciation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/depreciation/{depreciation_id}/reverse",
    response_model=dict[str, Any],
    summary="Reverse depreciation entry",
    operation_id="reverse_depreciation",
)
async def reverse_depreciation(
    depreciation_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    _permission: None = Depends(require_permission("fixed_asset:depreciation")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> dict[str, Any]:
    """Reverse a posted depreciation entry."""
    try:
        result = await service.reverse_depreciation(
            depreciation_id=depreciation_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Depreciation entry not found")

        return {
            "depreciation_id": str(depreciation_id),
            "reversed": True,
            "reversal_journal_id": str(result.reversal_journal_id),
            "message": "Depreciation reversed successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse depreciation: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# REVALUATION
# ----------------------------------------------------------------------------


@router.post(
    "/assets/{asset_id}/revaluation",
    response_model=RevaluationResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Revalue fixed asset",
    operation_id="revalue_asset",
)
async def revalue_asset(
    asset_id: UUID,
    request: RevaluationRequestSchema,
    _permission: None = Depends(require_permission("fixed_asset:revaluation")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> RevaluationResponseSchema:
    """Revalue a fixed asset (increase or decrease)."""
    from application.dto_objects.fixed_asset_request import RevaluationRequest

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
        result = await service.revaluate_asset(dto)

        return RevaluationResponseSchema(
            revaluation_id=result.revaluation_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            revaluation_date=request.revaluation_date,
            old_acquisition_cost=result.old_acquisition_cost,
            new_acquisition_cost=result.new_acquisition_cost,
            old_accumulated_depreciation=result.old_accumulated_depreciation,
            new_accumulated_depreciation=result.new_accumulated_depreciation,
            old_nbv=result.old_nbv,
            new_nbv=result.new_nbv,
            surplus_deficit=result.surplus_deficit,
            revaluation_type=RevaluationType(result.revaluation_type),
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
    "/assets/{asset_id}/disposal",
    response_model=DisposalResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Dispose fixed asset",
    operation_id="dispose_asset",
)
async def dispose_asset(
    asset_id: UUID,
    request: DisposalRequestSchema,
    _permission: None = Depends(require_permission("fixed_asset:disposal")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> DisposalResponseSchema:
    """Dispose (sell/scrap/donate) a fixed asset."""
    from application.dto_objects.fixed_asset_request import DisposalRequest

    try:
        dto = DisposalRequest(
            asset_id=asset_id,
            disposal_date=request.disposal_date,
            disposal_type=request.disposal_type.value,
            disposal_proceeds=request.disposal_proceeds,
            disposal_cost=request.disposal_cost,
            reason=request.reason,
            buyer_name=request.buyer_name,
            buyer_npwp=request.buyer_npwp,
            auction_number=request.auction_number,
            disposed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await service.dispose_asset(dto)

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
    "/assets/{asset_id}/impairment-test",
    response_model=ImpairmentTestResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Test asset for impairment",
    operation_id="test_impairment",
)
async def test_impairment(
    asset_id: UUID,
    request: ImpairmentTestRequestSchema,
    _permission: None = Depends(require_permission("fixed_asset:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> ImpairmentTestResponseSchema:
    """Test asset for impairment and recognize loss if needed."""
    from application.dto_objects.fixed_asset_request import ImpairmentTestRequest

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
        result = await service.test_impairment(dto)

        return ImpairmentTestResponseSchema(
            test_id=result.test_id,
            asset_id=asset_id,
            asset_code=result.asset_code,
            test_date=request.test_date,
            carrying_amount=result.carrying_amount,
            recoverable_amount=request.recoverable_amount,
            impairment_loss=result.impairment_loss,
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
    "/assets/{asset_id}/impairment-restore",
    response_model=ImpairmentTestResponseSchema,
    summary="Restore previously recognized impairment",
    operation_id="restore_impairment",
)
async def restore_impairment(
    asset_id: UUID,
    test_id: UUID = Query(..., description="Impairment test ID to restore"),
    reason: str = Query(..., min_length=5, description="Restoration reason"),
    _permission: None = Depends(require_permission("fixed_asset:impairment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> ImpairmentTestResponseSchema:
    """Restore previously recognized impairment loss."""
    try:
        result = await service.restore_impairment(
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
    "/assets/{asset_id}/transfer",
    response_model=AssetTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer asset between legal entities",
    operation_id="transfer_asset",
)
async def transfer_asset(
    asset_id: UUID,
    request: AssetTransferRequestSchema,
    _permission: None = Depends(require_permission("fixed_asset:transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> AssetTransferResponseSchema:
    """Transfer asset to another legal entity (inter-company)."""
    try:
        result = await service.transfer_asset(
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
    response_model=FixedAssetSummaryResponseSchema,
    summary="Get fixed asset summary",
    operation_id="get_fixed_asset_summary",
)
async def get_asset_summary(
    as_of_date: date = Query(..., description="As of date"),
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> FixedAssetSummaryResponseSchema:
    """Get fixed asset summary (total cost, NBV, monthly depreciation)."""
    try:
        summary = await service.get_summary(legal_entity_id, as_of_date)

        return FixedAssetSummaryResponseSchema(
            total_assets=summary.total_assets,
            total_acquisition_cost=summary.total_acquisition_cost,
            total_accumulated_depreciation=summary.total_accumulated_depreciation,
            total_net_book_value=summary.total_net_book_value,
            monthly_depreciation_charge=summary.monthly_depreciation_charge,
            by_category=summary.by_category,
            by_status=summary.by_status,
            by_location=summary.by_location,
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
    summary="Export fixed asset register",
    operation_id="export_asset_register",
)
async def export_asset_register(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    as_of_date: date = Query(..., description="As of date"),
    category: AssetCategory | None = Query(None, description="Filter by category"),
    _permission: None = Depends(require_permission("fixed_asset:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> Response:
    """Export fixed asset register to CSV or Excel."""
    try:
        data = await service.export_asset_register(
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
        filename = f"asset_register_{legal_entity_id}_{as_of_date}.{format}"

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
    "/assets/{asset_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get asset history",
    operation_id="get_asset_history",
)
async def get_asset_history(
    asset_id: UUID,
    _permission: None = Depends(require_permission("fixed_asset:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_fixed_asset_service),
) -> list[dict[str, Any]]:
    """Get asset change history (audit trail)."""
    try:
        history = await service.get_asset_history(asset_id, legal_entity_id)

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
