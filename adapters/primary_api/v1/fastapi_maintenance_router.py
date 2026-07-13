#!/usr/bin/env python3
"""
Module: fastapi_maintenance_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Maintenance:
               asset maintenance (aset yang dirawat), maintenance schedules,
               work orders untuk perawatan, preventive maintenance, corrective maintenance,
               spare parts usage, maintenance cost tracking, dan laporan.

Method Standards (ERP):
- create_maintenance_asset() / update_maintenance_asset() / delete_maintenance_asset() / get_maintenance_asset()
- create_maintenance_schedule() / update_maintenance_schedule() / delete_maintenance_schedule()
- create_work_order() / update_work_order() / delete_work_order() / get_work_order()
- release_work_order() / complete_work_order() / cancel_work_order()
- assign_technician() / record_spare_parts_usage()
- get_maintenance_history() / get_maintenance_cost()
- get_asset_status() / get_schedule_status()
- audit_trail_work_order() / can_transition_work_order()
- register_work_order_event() / get_work_order_events()
- version_work_order()
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


class MaintenanceAssetStatus(str, Enum):
    """Status aset maintenance."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    UNDER_MAINTENANCE = "under_maintenance"
    OUT_OF_SERVICE = "out_of_service"
    OBSOLETE = "obsolete"
    ARCHIVED = "archived"


class MaintenanceType(str, Enum):
    """Jenis maintenance."""
    PREVENTIVE = "preventive"      # Preventif
    CORRECTIVE = "corrective"      # Korektif
    PREDICTIVE = "predictive"      # Prediktif
    EMERGENCY = "emergency"        # Darurat
    ROUTINE = "routine"            # Rutin


class MaintenancePriority(str, Enum):
    """Prioritas maintenance."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkOrderStatus(str, Enum):
    """Status work order maintenance."""
    DRAFT = "draft"
    PLANNED = "planned"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class ScheduleFrequency(str, Enum):
    """Frekuensi jadwal maintenance."""
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"
    CUSTOM = "custom"


class SparePartUsageStatus(str, Enum):
    """Status penggunaan spare part."""
    REQUESTED = "requested"
    ISSUED = "issued"
    USED = "used"
    RETURNED = "returned"


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class MaintenanceAssetCreateSchema(BaseModel):
    """Schema untuk membuat aset maintenance."""

    model_config = ConfigDict(from_attributes=True)

    asset_code: str = Field(..., min_length=3, max_length=50, description="Kode aset")
    asset_name: str = Field(..., min_length=3, max_length=200, description="Nama aset")
    asset_category: str = Field(..., max_length=100, description="Kategori")
    location: str | None = Field(None, max_length=200, description="Lokasi")
    serial_number: str | None = Field(None, max_length=50, description="Nomor seri")
    manufacturer: str | None = Field(None, max_length=100, description="Pabrikan")
    model: str | None = Field(None, max_length=100, description="Model")
    purchase_date: date | None = Field(None, description="Tanggal pembelian")
    warranty_expiry_date: date | None = Field(None, description="Tanggal habis garansi")
    maintenance_interval_days: int | None = Field(None, ge=1, description="Interval maintenance (hari)")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    is_active: bool = Field(True, description="Aktif")

    @field_validator("asset_code")
    @classmethod
    def validate_asset_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Asset code is required")
        return v.upper()


class MaintenanceAssetUpdateSchema(BaseModel):
    """Schema untuk update aset maintenance."""

    model_config = ConfigDict(from_attributes=True)

    asset_name: str | None = Field(None, min_length=3, max_length=200)
    location: str | None = Field(None, max_length=200)
    status: MaintenanceAssetStatus | None = None
    maintenance_interval_days: int | None = Field(None, ge=1)
    notes: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class MaintenanceAssetResponseSchema(BaseModel):
    """Response aset maintenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_code: str
    asset_name: str
    asset_category: str
    location: str | None
    serial_number: str | None
    manufacturer: str | None
    model: str | None
    purchase_date: date | None
    warranty_expiry_date: date | None
    maintenance_interval_days: int | None
    status: MaintenanceAssetStatus
    is_active: bool
    is_locked: bool = False
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class MaintenanceScheduleCreateSchema(BaseModel):
    """Schema untuk membuat jadwal maintenance."""

    model_config = ConfigDict(from_attributes=True)

    asset_id: UUID = Field(..., description="Asset ID")
    schedule_code: str = Field(..., min_length=3, max_length=50, description="Kode jadwal")
    schedule_name: str = Field(..., min_length=3, max_length=200, description="Nama jadwal")
    maintenance_type: MaintenanceType = Field(..., description="Jenis maintenance")
    frequency: ScheduleFrequency = Field(..., description="Frekuensi")
    custom_interval_days: int | None = Field(None, ge=1, description="Interval custom (hari)")
    start_date: date = Field(..., description="Tanggal mulai")
    end_date: date | None = Field(None, description="Tanggal selesai")
    estimated_duration_hours: Decimal = Field(0, ge=0, decimal_places=2, description="Durasi estimasi (jam)")
    assigned_team: str | None = Field(None, max_length=100, description="Tim yang ditugaskan")
    notes: str | None = Field(None, max_length=500, description="Catatan")
    is_active: bool = Field(True, description="Aktif")

    @field_validator("schedule_code")
    @classmethod
    def validate_schedule_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Schedule code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_frequency(self) -> MaintenanceScheduleCreateSchema:
        if self.frequency == ScheduleFrequency.CUSTOM and not self.custom_interval_days:
            raise ValueError("Custom interval days required for CUSTOM frequency")
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("End date must be after start date")
        return self


class MaintenanceScheduleUpdateSchema(BaseModel):
    """Schema untuk update jadwal maintenance."""

    model_config = ConfigDict(from_attributes=True)

    schedule_name: str | None = Field(None, min_length=3, max_length=200)
    frequency: ScheduleFrequency | None = None
    custom_interval_days: int | None = Field(None, ge=1)
    start_date: date | None = None
    end_date: date | None = None
    estimated_duration_hours: Decimal | None = Field(None, ge=0, decimal_places=2)
    assigned_team: str | None = None
    notes: str | None = None
    is_active: bool | None = None


class MaintenanceScheduleResponseSchema(BaseModel):
    """Response jadwal maintenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    asset_id: UUID
    asset_code: str | None = None
    asset_name: str | None = None
    schedule_code: str
    schedule_name: str
    maintenance_type: MaintenanceType
    frequency: ScheduleFrequency
    custom_interval_days: int | None
    start_date: date
    end_date: date | None
    estimated_duration_hours: Decimal
    assigned_team: str | None
    status: str
    is_active: bool
    next_due_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class WorkOrderMaintenanceCreateSchema(BaseModel):
    """Schema untuk membuat work order maintenance."""

    model_config = ConfigDict(from_attributes=True)

    wo_number: str = Field(..., max_length=50, description="Nomor WO")
    asset_id: UUID = Field(..., description="Asset ID")
    schedule_id: UUID | None = Field(None, description="Schedule ID (jika dari jadwal)")
    maintenance_type: MaintenanceType = Field(..., description="Jenis maintenance")
    priority: MaintenancePriority = Field(MaintenancePriority.MEDIUM, description="Prioritas")
    description: str = Field(..., max_length=1000, description="Deskripsi")
    requested_by: UUID = Field(..., description="ID peminta")
    planned_start_date: date = Field(..., description="Tanggal mulai rencana")
    planned_end_date: date = Field(..., description="Tanggal selesai rencana")
    estimated_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya estimasi")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("wo_number")
    @classmethod
    def validate_wo_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Work order number is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> WorkOrderMaintenanceCreateSchema:
        if self.planned_end_date < self.planned_start_date:
            raise ValueError("Planned end date must be after planned start date")
        return self


class WorkOrderMaintenanceUpdateSchema(BaseModel):
    """Schema untuk update work order maintenance."""

    model_config = ConfigDict(from_attributes=True)

    description: str | None = Field(None, max_length=1000)
    priority: MaintenancePriority | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    estimated_cost: Decimal | None = Field(None, ge=0, decimal_places=2)
    notes: str | None = None
    assigned_technician_id: UUID | None = None
    status: WorkOrderStatus | None = None


class WorkOrderMaintenanceResponseSchema(BaseModel):
    """Response work order maintenance."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    wo_number: str
    asset_id: UUID
    asset_code: str | None = None
    asset_name: str | None = None
    schedule_id: UUID | None
    maintenance_type: MaintenanceType
    priority: MaintenancePriority
    description: str
    requested_by: UUID
    requested_by_name: str | None = None
    assigned_technician_id: UUID | None = None
    assigned_technician_name: str | None = None
    planned_start_date: date
    planned_end_date: date
    actual_start_date: date | None
    actual_end_date: date | None
    estimated_cost: Decimal
    actual_cost: Decimal
    status: WorkOrderStatus
    is_locked: bool = False
    notes: str | None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    completed_at: datetime | None = None
    completed_by: UUID | None = None
    version: int = 1


class SparePartUsageSchema(BaseModel):
    """Schema untuk penggunaan spare part."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID = Field(..., description="Item ID")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas")
    unit_cost: Decimal = Field(..., gt=0, decimal_places=2, description="Biaya per unit")
    work_order_id: UUID = Field(..., description="WO ID")
    issued_date: date = Field(default_factory=date.today, description="Tanggal pengeluaran")
    notes: str | None = Field(None, max_length=500)


class SparePartUsageResponseSchema(BaseModel):
    """Response penggunaan spare part."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_id: UUID
    item_code: str | None = None
    item_name: str | None = None
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    work_order_id: UUID
    work_order_number: str | None = None
    issued_date: date
    status: SparePartUsageStatus
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None


class MaintenanceCostSummarySchema(BaseModel):
    """Response ringkasan biaya maintenance."""

    model_config = ConfigDict(from_attributes=True)

    period_start: date
    period_end: date
    total_maintenance_cost: Decimal
    preventive_cost: Decimal
    corrective_cost: Decimal
    emergency_cost: Decimal
    labor_cost: Decimal
    spare_parts_cost: Decimal
    other_cost: Decimal
    by_asset: list[dict[str, Any]]
    by_work_order: list[dict[str, Any]]


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_maintenance_svc(request: Request) -> Any:
    """
    Get Maintenance Service instance.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    from application.service_layer.service_maintenance import MaintenanceService
    container = request.app.state.container
    return container.resolve(MaintenanceService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    return {"status": "ok", "service": "maintenance-router"}

@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    return {"version": "1.0", "name": "Maintenance Router"}


# ----------------------------------------------------------------------------
# MAINTENANCE ASSET CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/assets",
    response_model=MaintenanceAssetResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create maintenance asset",
    operation_id="create_maintenance_asset",
)
async def create_maintenance_asset(
    request: MaintenanceAssetCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceAssetResponseSchema:
    """
    Create a new maintenance asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "create_maintenance_asset"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return MaintenanceAssetResponseSchema(**cached)

    try:
        result = await maintenance_svc.create_maintenance_asset(
            legal_entity_id=legal_entity_id,
            asset_code=request.asset_code,
            asset_name=request.asset_name,
            asset_category=request.asset_category,
            location=request.location,
            serial_number=request.serial_number,
            manufacturer=request.manufacturer,
            model=request.model,
            purchase_date=request.purchase_date,
            warranty_expiry_date=request.warranty_expiry_date,
            maintenance_interval_days=request.maintenance_interval_days,
            notes=request.notes,
            is_active=request.is_active,
            created_by=current_user.user_id,
        )
        response = MaintenanceAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=result.asset_category,
            location=result.location,
            serial_number=result.serial_number,
            manufacturer=result.manufacturer,
            model=result.model,
            purchase_date=result.purchase_date,
            warranty_expiry_date=result.warranty_expiry_date,
            maintenance_interval_days=result.maintenance_interval_days,
            status=MaintenanceAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
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
        logger.exception("Failed to create maintenance asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/assets",
    response_model=list[MaintenanceAssetResponseSchema],
    summary="List maintenance assets",
    operation_id="list_maintenance_assets",
)
async def list_maintenance_assets(
    category: str | None = Query(None, description="Filter by category"),
    status: MaintenanceAssetStatus | None = Query(None, description="Filter by status"),
    is_active: bool | None = Query(None),
    search: str | None = Query(None, description="Search in code or name"),
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> list[MaintenanceAssetResponseSchema]:
    try:
        assets = await maintenance_svc.list_maintenance_assets(
            legal_entity_id=legal_entity_id,
            category=category,
            status=status.value if status else None,
            is_active=is_active,
            search=search,
        )
        return [
            MaintenanceAssetResponseSchema(
                id=a.id,
                asset_code=a.asset_code,
                asset_name=a.asset_name,
                asset_category=a.asset_category,
                location=a.location,
                serial_number=a.serial_number,
                manufacturer=a.manufacturer,
                model=a.model,
                purchase_date=a.purchase_date,
                warranty_expiry_date=a.warranty_expiry_date,
                maintenance_interval_days=a.maintenance_interval_days,
                status=MaintenanceAssetStatus(a.status),
                is_active=a.is_active,
                is_locked=a.is_locked,
                notes=a.notes,
                created_at=a.created_at,
                updated_at=a.updated_at,
                created_by=a.created_by,
                created_by_name=a.created_by_name,
                version=a.version,
            )
            for a in assets
        ]
    except Exception as e:
        logger.exception("Failed to list maintenance assets: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/assets/{asset_id}",
    response_model=MaintenanceAssetResponseSchema,
    summary="Get maintenance asset by ID",
    operation_id="get_maintenance_asset",
)
async def get_maintenance_asset(
    asset_id: UUID,
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceAssetResponseSchema:
    try:
        asset = await maintenance_svc.get_maintenance_asset_by_id(asset_id, legal_entity_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        return MaintenanceAssetResponseSchema(
            id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.asset_name,
            asset_category=asset.asset_category,
            location=asset.location,
            serial_number=asset.serial_number,
            manufacturer=asset.manufacturer,
            model=asset.model,
            purchase_date=asset.purchase_date,
            warranty_expiry_date=asset.warranty_expiry_date,
            maintenance_interval_days=asset.maintenance_interval_days,
            status=MaintenanceAssetStatus(asset.status),
            is_active=asset.is_active,
            is_locked=asset.is_locked,
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
        logger.exception("Failed to get maintenance asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/assets/{asset_id}",
    response_model=MaintenanceAssetResponseSchema,
    summary="Update maintenance asset",
    operation_id="update_maintenance_asset",
)
async def update_maintenance_asset(
    asset_id: UUID,
    request: MaintenanceAssetUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceAssetResponseSchema:
    """
    Update maintenance asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "update_maintenance_asset"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return MaintenanceAssetResponseSchema(**cached)

    try:
        result = await maintenance_svc.update_maintenance_asset(
            asset_id=asset_id,
            legal_entity_id=legal_entity_id,
            asset_name=request.asset_name,
            location=request.location,
            status=request.status.value if request.status else None,
            maintenance_interval_days=request.maintenance_interval_days,
            notes=request.notes,
            is_active=request.is_active,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")
        response = MaintenanceAssetResponseSchema(
            id=result.id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            asset_category=result.asset_category,
            location=result.location,
            serial_number=result.serial_number,
            manufacturer=result.manufacturer,
            model=result.model,
            purchase_date=result.purchase_date,
            warranty_expiry_date=result.warranty_expiry_date,
            maintenance_interval_days=result.maintenance_interval_days,
            status=MaintenanceAssetStatus(result.status),
            is_active=result.is_active,
            is_locked=result.is_locked,
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
        logger.exception("Failed to update maintenance asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/assets/{asset_id}",
    response_model=dict[str, Any],
    summary="Deactivate/archive maintenance asset",
    operation_id="deactivate_maintenance_asset",
)
async def deactivate_maintenance_asset(
    asset_id: UUID,
    reason: str = Query("", description="Reason"),
    _permission: None = Depends(require_permission("maintenance:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> dict[str, Any]:
    """
    Deactivate a maintenance asset.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await maintenance_svc.deactivate_maintenance_asset(
            asset_id, legal_entity_id, current_user.user_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Asset not found")
        return {
            "asset_id": str(asset_id),
            "asset_code": result.asset_code,
            "status": result.status,
            "message": "Asset deactivated",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate maintenance asset: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# MAINTENANCE SCHEDULE
# ----------------------------------------------------------------------------


@router.post(
    "/schedules",
    response_model=MaintenanceScheduleResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create maintenance schedule",
    operation_id="create_maintenance_schedule",
)
async def create_maintenance_schedule(
    request: MaintenanceScheduleCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceScheduleResponseSchema:
    """
    Create a new maintenance schedule.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "create_maintenance_schedule"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return MaintenanceScheduleResponseSchema(**cached)

    try:
        result = await maintenance_svc.create_maintenance_schedule(
            legal_entity_id=legal_entity_id,
            asset_id=request.asset_id,
            schedule_code=request.schedule_code,
            schedule_name=request.schedule_name,
            maintenance_type=request.maintenance_type.value,
            frequency=request.frequency.value,
            custom_interval_days=request.custom_interval_days,
            start_date=request.start_date,
            end_date=request.end_date,
            estimated_duration_hours=request.estimated_duration_hours,
            assigned_team=request.assigned_team,
            notes=request.notes,
            is_active=request.is_active,
            created_by=current_user.user_id,
        )
        response = MaintenanceScheduleResponseSchema(
            id=result.id,
            asset_id=result.asset_id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            schedule_code=result.schedule_code,
            schedule_name=result.schedule_name,
            maintenance_type=MaintenanceType(result.maintenance_type),
            frequency=ScheduleFrequency(result.frequency),
            custom_interval_days=result.custom_interval_days,
            start_date=result.start_date,
            end_date=result.end_date,
            estimated_duration_hours=result.estimated_duration_hours,
            assigned_team=result.assigned_team,
            status=result.status,
            is_active=result.is_active,
            next_due_date=result.next_due_date,
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
        logger.exception("Failed to create maintenance schedule: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/schedules",
    response_model=list[MaintenanceScheduleResponseSchema],
    summary="List maintenance schedules",
    operation_id="list_maintenance_schedules",
)
async def list_maintenance_schedules(
    asset_id: UUID | None = Query(None, description="Filter by asset"),
    maintenance_type: MaintenanceType | None = Query(None),
    is_active: bool | None = Query(None),
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> list[MaintenanceScheduleResponseSchema]:
    try:
        schedules = await maintenance_svc.list_maintenance_schedules(
            legal_entity_id=legal_entity_id,
            asset_id=asset_id,
            maintenance_type=maintenance_type.value if maintenance_type else None,
            is_active=is_active,
        )
        return [
            MaintenanceScheduleResponseSchema(
                id=s.id,
                asset_id=s.asset_id,
                asset_code=s.asset_code,
                asset_name=s.asset_name,
                schedule_code=s.schedule_code,
                schedule_name=s.schedule_name,
                maintenance_type=MaintenanceType(s.maintenance_type),
                frequency=ScheduleFrequency(s.frequency),
                custom_interval_days=s.custom_interval_days,
                start_date=s.start_date,
                end_date=s.end_date,
                estimated_duration_hours=s.estimated_duration_hours,
                assigned_team=s.assigned_team,
                status=s.status,
                is_active=s.is_active,
                next_due_date=s.next_due_date,
                notes=s.notes,
                created_at=s.created_at,
                updated_at=s.updated_at,
                created_by=s.created_by,
                created_by_name=s.created_by_name,
                version=s.version,
            )
            for s in schedules
        ]
    except Exception as e:
        logger.exception("Failed to list maintenance schedules: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/schedules/{schedule_id}",
    response_model=MaintenanceScheduleResponseSchema,
    summary="Get maintenance schedule by ID",
    operation_id="get_maintenance_schedule",
)
async def get_maintenance_schedule(
    schedule_id: UUID,
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceScheduleResponseSchema:
    try:
        schedule = await maintenance_svc.get_maintenance_schedule_by_id(schedule_id, legal_entity_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return MaintenanceScheduleResponseSchema(
            id=schedule.id,
            asset_id=schedule.asset_id,
            asset_code=schedule.asset_code,
            asset_name=schedule.asset_name,
            schedule_code=schedule.schedule_code,
            schedule_name=schedule.schedule_name,
            maintenance_type=MaintenanceType(schedule.maintenance_type),
            frequency=ScheduleFrequency(schedule.frequency),
            custom_interval_days=schedule.custom_interval_days,
            start_date=schedule.start_date,
            end_date=schedule.end_date,
            estimated_duration_hours=schedule.estimated_duration_hours,
            assigned_team=schedule.assigned_team,
            status=schedule.status,
            is_active=schedule.is_active,
            next_due_date=schedule.next_due_date,
            notes=schedule.notes,
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
            created_by=schedule.created_by,
            created_by_name=schedule.created_by_name,
            version=schedule.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get maintenance schedule: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/schedules/{schedule_id}",
    response_model=MaintenanceScheduleResponseSchema,
    summary="Update maintenance schedule",
    operation_id="update_maintenance_schedule",
)
async def update_maintenance_schedule(
    schedule_id: UUID,
    request: MaintenanceScheduleUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceScheduleResponseSchema:
    """
    Update maintenance schedule.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "update_maintenance_schedule"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return MaintenanceScheduleResponseSchema(**cached)

    try:
        result = await maintenance_svc.update_maintenance_schedule(
            schedule_id=schedule_id,
            legal_entity_id=legal_entity_id,
            schedule_name=request.schedule_name,
            frequency=request.frequency.value if request.frequency else None,
            custom_interval_days=request.custom_interval_days,
            start_date=request.start_date,
            end_date=request.end_date,
            estimated_duration_hours=request.estimated_duration_hours,
            assigned_team=request.assigned_team,
            notes=request.notes,
            is_active=request.is_active,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Schedule not found")
        response = MaintenanceScheduleResponseSchema(
            id=result.id,
            asset_id=result.asset_id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            schedule_code=result.schedule_code,
            schedule_name=result.schedule_name,
            maintenance_type=MaintenanceType(result.maintenance_type),
            frequency=ScheduleFrequency(result.frequency),
            custom_interval_days=result.custom_interval_days,
            start_date=result.start_date,
            end_date=result.end_date,
            estimated_duration_hours=result.estimated_duration_hours,
            assigned_team=result.assigned_team,
            status=result.status,
            is_active=result.is_active,
            next_due_date=result.next_due_date,
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
        logger.exception("Failed to update maintenance schedule: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/schedules/{schedule_id}",
    response_model=dict[str, Any],
    summary="Deactivate maintenance schedule",
    operation_id="deactivate_maintenance_schedule",
)
async def deactivate_maintenance_schedule(
    schedule_id: UUID,
    reason: str = Query("", description="Reason"),
    _permission: None = Depends(require_permission("maintenance:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> dict[str, Any]:
    """
    Deactivate maintenance schedule.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    try:
        result = await maintenance_svc.deactivate_maintenance_schedule(
            schedule_id, legal_entity_id, current_user.user_id, reason
        )
        if not result:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {
            "schedule_id": str(schedule_id),
            "schedule_code": result.schedule_code,
            "status": result.status,
            "message": "Schedule deactivated",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate maintenance schedule: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WORK ORDER MAINTENANCE
# ----------------------------------------------------------------------------


@router.post(
    "/work-orders",
    response_model=WorkOrderMaintenanceResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create maintenance work order",
    operation_id="create_maintenance_work_order",
)
async def create_maintenance_work_order(
    request: WorkOrderMaintenanceCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> WorkOrderMaintenanceResponseSchema:
    """
    Create a new maintenance work order.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "create_maintenance_work_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return WorkOrderMaintenanceResponseSchema(**cached)

    try:
        result = await maintenance_svc.create_maintenance_work_order(
            legal_entity_id=legal_entity_id,
            wo_number=request.wo_number,
            asset_id=request.asset_id,
            schedule_id=request.schedule_id,
            maintenance_type=request.maintenance_type.value,
            priority=request.priority.value,
            description=request.description,
            requested_by=request.requested_by,
            planned_start_date=request.planned_start_date,
            planned_end_date=request.planned_end_date,
            estimated_cost=request.estimated_cost,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = WorkOrderMaintenanceResponseSchema(
            id=result.id,
            wo_number=result.wo_number,
            asset_id=result.asset_id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            schedule_id=result.schedule_id,
            maintenance_type=MaintenanceType(result.maintenance_type),
            priority=MaintenancePriority(result.priority),
            description=result.description,
            requested_by=result.requested_by,
            requested_by_name=result.requested_by_name,
            assigned_technician_id=result.assigned_technician_id,
            assigned_technician_name=result.assigned_technician_name,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            estimated_cost=result.estimated_cost,
            actual_cost=result.actual_cost,
            status=WorkOrderStatus(result.status),
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create maintenance work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/work-orders",
    response_model=list[WorkOrderMaintenanceResponseSchema],
    summary="List maintenance work orders",
    operation_id="list_maintenance_work_orders",
)
async def list_maintenance_work_orders(
    asset_id: UUID | None = Query(None, description="Filter by asset"),
    status: WorkOrderStatus | None = Query(None, description="Filter by status"),
    priority: MaintenancePriority | None = Query(None, description="Filter by priority"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> list[WorkOrderMaintenanceResponseSchema]:
    try:
        result = await maintenance_svc.list_maintenance_work_orders(
            legal_entity_id=legal_entity_id,
            asset_id=asset_id,
            status=status.value if status else None,
            priority=priority.value if priority else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
        return [
            WorkOrderMaintenanceResponseSchema(
                id=wo.id,
                wo_number=wo.wo_number,
                asset_id=wo.asset_id,
                asset_code=wo.asset_code,
                asset_name=wo.asset_name,
                schedule_id=wo.schedule_id,
                maintenance_type=MaintenanceType(wo.maintenance_type),
                priority=MaintenancePriority(wo.priority),
                description=wo.description,
                requested_by=wo.requested_by,
                requested_by_name=wo.requested_by_name,
                assigned_technician_id=wo.assigned_technician_id,
                assigned_technician_name=wo.assigned_technician_name,
                planned_start_date=wo.planned_start_date,
                planned_end_date=wo.planned_end_date,
                actual_start_date=wo.actual_start_date,
                actual_end_date=wo.actual_end_date,
                estimated_cost=wo.estimated_cost,
                actual_cost=wo.actual_cost,
                status=WorkOrderStatus(wo.status),
                is_locked=wo.is_locked,
                notes=wo.notes,
                created_at=wo.created_at,
                updated_at=wo.updated_at,
                created_by=wo.created_by,
                created_by_name=wo.created_by_name,
                completed_at=wo.completed_at,
                completed_by=wo.completed_by,
                version=wo.version,
            )
            for wo in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list maintenance work orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/work-orders/{wo_id}",
    response_model=WorkOrderMaintenanceResponseSchema,
    summary="Get maintenance work order by ID",
    operation_id="get_maintenance_work_order",
)
async def get_maintenance_work_order(
    wo_id: UUID,
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> WorkOrderMaintenanceResponseSchema:
    try:
        wo = await maintenance_svc.get_maintenance_work_order_by_id(wo_id, legal_entity_id)
        if not wo:
            raise HTTPException(status_code=404, detail="Work order not found")
        return WorkOrderMaintenanceResponseSchema(
            id=wo.id,
            wo_number=wo.wo_number,
            asset_id=wo.asset_id,
            asset_code=wo.asset_code,
            asset_name=wo.asset_name,
            schedule_id=wo.schedule_id,
            maintenance_type=MaintenanceType(wo.maintenance_type),
            priority=MaintenancePriority(wo.priority),
            description=wo.description,
            requested_by=wo.requested_by,
            requested_by_name=wo.requested_by_name,
            assigned_technician_id=wo.assigned_technician_id,
            assigned_technician_name=wo.assigned_technician_name,
            planned_start_date=wo.planned_start_date,
            planned_end_date=wo.planned_end_date,
            actual_start_date=wo.actual_start_date,
            actual_end_date=wo.actual_end_date,
            estimated_cost=wo.estimated_cost,
            actual_cost=wo.actual_cost,
            status=WorkOrderStatus(wo.status),
            is_locked=wo.is_locked,
            notes=wo.notes,
            created_at=wo.created_at,
            updated_at=wo.updated_at,
            created_by=wo.created_by,
            created_by_name=wo.created_by_name,
            completed_at=wo.completed_at,
            completed_by=wo.completed_by,
            version=wo.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get maintenance work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/work-orders/{wo_id}",
    response_model=WorkOrderMaintenanceResponseSchema,
    summary="Update maintenance work order",
    operation_id="update_maintenance_work_order",
)
async def update_maintenance_work_order(
    wo_id: UUID,
    request: WorkOrderMaintenanceUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> WorkOrderMaintenanceResponseSchema:
    """
    Update maintenance work order.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "update_maintenance_work_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return WorkOrderMaintenanceResponseSchema(**cached)

    try:
        result = await maintenance_svc.update_maintenance_work_order(
            wo_id=wo_id,
            legal_entity_id=legal_entity_id,
            description=request.description,
            priority=request.priority.value if request.priority else None,
            planned_start_date=request.planned_start_date,
            planned_end_date=request.planned_end_date,
            estimated_cost=request.estimated_cost,
            notes=request.notes,
            assigned_technician_id=request.assigned_technician_id,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Work order not found")
        response = WorkOrderMaintenanceResponseSchema(
            id=result.id,
            wo_number=result.wo_number,
            asset_id=result.asset_id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            schedule_id=result.schedule_id,
            maintenance_type=MaintenanceType(result.maintenance_type),
            priority=MaintenancePriority(result.priority),
            description=result.description,
            requested_by=result.requested_by,
            requested_by_name=result.requested_by_name,
            assigned_technician_id=result.assigned_technician_id,
            assigned_technician_name=result.assigned_technician_name,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            estimated_cost=result.estimated_cost,
            actual_cost=result.actual_cost,
            status=WorkOrderStatus(result.status),
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update maintenance work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/work-orders/{wo_id}/complete",
    response_model=WorkOrderMaintenanceResponseSchema,
    summary="Complete maintenance work order",
    operation_id="complete_maintenance_work_order",
)
async def complete_maintenance_work_order(
    wo_id: UUID,
    actual_end_date: date = Query(default_factory=date.today, description="Actual end date"),
    actual_cost: Decimal = Query(0, ge=0, decimal_places=2, description="Actual cost"),
    notes: str = Query("", description="Completion notes"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:complete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> WorkOrderMaintenanceResponseSchema:
    """
    Complete a maintenance work order.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "complete_maintenance_work_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return WorkOrderMaintenanceResponseSchema(**cached)

    try:
        result = await maintenance_svc.complete_maintenance_work_order(
            wo_id=wo_id,
            legal_entity_id=legal_entity_id,
            actual_end_date=actual_end_date,
            actual_cost=actual_cost,
            notes=notes,
            completed_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Work order not found or cannot be completed")
        response = WorkOrderMaintenanceResponseSchema(
            id=result.id,
            wo_number=result.wo_number,
            asset_id=result.asset_id,
            asset_code=result.asset_code,
            asset_name=result.asset_name,
            schedule_id=result.schedule_id,
            maintenance_type=MaintenanceType(result.maintenance_type),
            priority=MaintenancePriority(result.priority),
            description=result.description,
            requested_by=result.requested_by,
            requested_by_name=result.requested_by_name,
            assigned_technician_id=result.assigned_technician_id,
            assigned_technician_name=result.assigned_technician_name,
            planned_start_date=result.planned_start_date,
            planned_end_date=result.planned_end_date,
            actual_start_date=result.actual_start_date,
            actual_end_date=result.actual_end_date,
            estimated_cost=result.estimated_cost,
            actual_cost=result.actual_cost,
            status=WorkOrderStatus(result.status),
            is_locked=result.is_locked,
            notes=result.notes,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            completed_at=result.completed_at,
            completed_by=result.completed_by,
            version=result.version,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to complete maintenance work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/work-orders/{wo_id}",
    response_model=dict[str, Any],
    summary="Cancel maintenance work order",
    operation_id="cancel_maintenance_work_order",
)
async def cancel_maintenance_work_order(
    wo_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> dict[str, Any]:
    """
    Cancel a maintenance work order.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "cancel_maintenance_work_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return cached

    try:
        result = await maintenance_svc.cancel_maintenance_work_order(
            wo_id=wo_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
            cancelled_by=current_user.user_id,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Work order not found or cannot be cancelled")
        response = {
            "wo_id": str(wo_id),
            "wo_number": result.wo_number,
            "status": result.status,
            "message": "Work order cancelled",
        }
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response)
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel maintenance work order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SPARE PARTS USAGE
# ----------------------------------------------------------------------------


@router.post(
    "/spare-parts/usage",
    response_model=SparePartUsageResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record spare parts usage",
    operation_id="record_spare_parts_usage",
)
async def record_spare_parts_usage(
    request: SparePartUsageSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("maintenance:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> SparePartUsageResponseSchema:
    """
    Record spare parts usage for a work order.
    LOCKING: Service layer uses SELECT FOR UPDATE for concurrency control.
    """
    method_name = "record_spare_parts_usage"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SparePartUsageResponseSchema(**cached)

    try:
        result = await maintenance_svc.record_spare_parts_usage(
            legal_entity_id=legal_entity_id,
            item_id=request.item_id,
            quantity=request.quantity,
            unit_cost=request.unit_cost,
            work_order_id=request.work_order_id,
            issued_date=request.issued_date,
            notes=request.notes,
            created_by=current_user.user_id,
        )
        response = SparePartUsageResponseSchema(
            id=result.id,
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            quantity=result.quantity,
            unit_cost=result.unit_cost,
            total_cost=result.total_cost,
            work_order_id=result.work_order_id,
            work_order_number=result.work_order_number,
            issued_date=result.issued_date,
            status=SparePartUsageStatus(result.status),
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
        )
        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())
        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to record spare parts usage: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# MAINTENANCE COST SUMMARY
# ----------------------------------------------------------------------------


@router.get(
    "/cost-summary",
    response_model=MaintenanceCostSummarySchema,
    summary="Get maintenance cost summary",
    operation_id="get_maintenance_cost_summary",
)
async def get_maintenance_cost_summary(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("maintenance:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> MaintenanceCostSummarySchema:
    try:
        summary = await maintenance_svc.get_maintenance_cost_summary(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )
        return MaintenanceCostSummarySchema(
            period_start=start_date,
            period_end=end_date,
            total_maintenance_cost=summary.total_maintenance_cost,
            preventive_cost=summary.preventive_cost,
            corrective_cost=summary.corrective_cost,
            emergency_cost=summary.emergency_cost,
            labor_cost=summary.labor_cost,
            spare_parts_cost=summary.spare_parts_cost,
            other_cost=summary.other_cost,
            by_asset=summary.by_asset,
            by_work_order=summary.by_work_order,
        )
    except Exception as e:
        logger.exception("Failed to get maintenance cost summary: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export/work-orders",
    summary="Export maintenance work orders",
    operation_id="export_maintenance_work_orders",
)
async def export_maintenance_work_orders(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: WorkOrderStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("maintenance:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    maintenance_svc: Any = Depends(get_maintenance_svc),
) -> Response:
    try:
        data = await maintenance_svc.export_maintenance_work_orders(
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
            format=format,
            status=status.value if status else None,
        )
        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"maintenance_work_orders_{legal_entity_id}_{start_date}_{end_date}.{format}"
        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export maintenance work orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
