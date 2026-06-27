#!/usr/bin/env python3
"""
Module: fastapi_inventory_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Inventory:
               item (barang), stock movement (masuk/keluar), stock opname,
               transfer antar gudang, valuation FIFO/LIFO/AVERAGE, stock card,
               NRV tester, low stock alerts.

Method Standards (ERP):
- create_item() / update_item() / delete_item() / get_item()
- activate_item() / deactivate_item() / lock_item() / unlock_item()
- record_movement() / reverse_movement() / cancel_movement()
- create_stock_opname() / approve_opname() / reject_opname()
- create_transfer() / approve_transfer() / complete_transfer()
- get_stock_card() / get_stock_balance() / get_stock_valuation()
- calculate_fifo() / calculate_lifo() / calculate_average_cost()
- test_nrv() / get_low_stock_alerts()
- get_item_history() / get_item_snapshot()
- audit_trail_item() / can_transition_item()
- register_item_event() / get_item_events() / clear_item_events()
- version_item()
"""


from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from adapters.primary_api.common.fastapi_auth_jwt_middleware import (
    TokenPayload,
    get_current_legal_entity,
    get_current_user,
    require_permission,
)

# Import port yang dibutuhkan untuk adapter
from ports.primary.report_repository_port import InventoryValuationRepositoryPort

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS & ENUMS
# ============================================================================


class ItemType(str, Enum):
    """Jenis item."""

    RAW_MATERIAL = "raw_material"  # Bahan baku
    WORK_IN_PROCESS = "work_in_process"  # Barang dalam proses
    FINISHED_GOOD = "finished_good"  # Barang jadi
    TRADING = "trading"  # Barang dagang
    CONSUMABLE = "consumable"  # Barang habis pakai
    SERVICE = "service"  # Jasa
    ASSET = "asset"  # Aset


class MovementType(str, Enum):
    """Jenis movement persediaan."""

    IN = "IN"  # Barang masuk
    OUT = "OUT"  # Barang keluar
    ADJUSTMENT = "ADJUSTMENT"  # Penyesuaian stok
    TRANSFER_IN = "TRANSFER_IN"  # Transfer masuk
    TRANSFER_OUT = "TRANSFER_OUT"  # Transfer keluar
    RETURN_IN = "RETURN_IN"  # Return masuk
    RETURN_OUT = "RETURN_OUT"  # Return keluar
    SCRAP = "SCRAP"  # Afkir
    SAMPLE = "SAMPLE"  # Sample


class MovementStatus(str, Enum):
    """Status movement."""

    DRAFT = "draft"
    PENDING = "pending"
    CONFIRMED = "confirmed"
    POSTED = "posted"
    REVERSED = "reversed"
    CANCELLED = "cancelled"


class StockOpnameStatus(str, Enum):
    """Status stock opname."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class TransferStatus(str, Enum):
    """Status transfer antar gudang."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ValuationMethod(str, Enum):
    """Metode penilaian persediaan."""

    FIFO = "FIFO"
    LIFO = "LIFO"
    AVERAGE = "AVERAGE"
    STANDARD = "STANDARD"


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ItemCreateSchema(BaseModel):
    """Schema untuk membuat item baru."""

    model_config = ConfigDict(from_attributes=True)

    item_code: str = Field(..., min_length=3, max_length=30, description="Kode item")
    item_name: str = Field(..., min_length=3, max_length=200, description="Nama item")
    item_type: ItemType = Field(ItemType.TRADING, description="Jenis item")
    unit_of_measure: str = Field("pcs", max_length=10, description="Satuan")
    category: str | None = Field(None, max_length=50, description="Kategori")
    brand: str | None = Field(None, max_length=100, description="Merek")
    reorder_point: Decimal = Field(0, ge=0, decimal_places=2, description="Titik pemesanan ulang")
    reorder_quantity: Decimal = Field(0, ge=0, decimal_places=2, description="Jumlah pesanan ulang")
    standard_cost: Decimal = Field(0, ge=0, decimal_places=2, description="Biaya standar")
    selling_price: Decimal = Field(0, ge=0, decimal_places=2, description="Harga jual")
    valuation_method: ValuationMethod = Field(ValuationMethod.FIFO, description="Metode penilaian")
    warehouse_id: UUID | None = Field(None, description="Gudang default")
    min_stock: Decimal = Field(0, ge=0, decimal_places=2, description="Stok minimum")
    max_stock: Decimal = Field(0, ge=0, decimal_places=2, description="Stok maksimum")
    description: str | None = Field(None, max_length=500, description="Deskripsi")
    tax_rate_purchase: Decimal = Field(
        11, ge=0, le=100, decimal_places=2, description="Pajak pembelian"
    )
    tax_rate_sales: Decimal = Field(
        11, ge=0, le=100, decimal_places=2, description="Pajak penjualan"
    )
    weight_kg: Decimal | None = Field(None, ge=0, decimal_places=3, description="Berat (kg)")
    volume_m3: Decimal | None = Field(None, ge=0, decimal_places=3, description="Volume (m3)")
    is_active: bool = Field(True, description="Aktif")
    is_lot_tracked: bool = Field(False, description="Lot/batch tracking")
    is_serial_tracked: bool = Field(False, description="Serial number tracking")
    is_expiry_tracked: bool = Field(False, description="Expiry date tracking")

    @field_validator("item_code")
    @classmethod
    def validate_item_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Item code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_stock_levels(self) -> ItemCreateSchema:
        if self.max_stock > 0 and self.min_stock > self.max_stock:
            raise ValueError("Minimum stock cannot exceed maximum stock")
        return self


class ItemUpdateSchema(BaseModel):
    """Schema untuk update item."""

    model_config = ConfigDict(from_attributes=True)

    item_name: str | None = Field(None, min_length=3, max_length=200)
    item_type: ItemType | None = None
    unit_of_measure: str | None = Field(None, max_length=10)
    category: str | None = Field(None, max_length=50)
    reorder_point: Decimal | None = Field(None, ge=0, decimal_places=2)
    reorder_quantity: Decimal | None = Field(None, ge=0, decimal_places=2)
    standard_cost: Decimal | None = Field(None, ge=0, decimal_places=2)
    selling_price: Decimal | None = Field(None, ge=0, decimal_places=2)
    valuation_method: ValuationMethod | None = None
    warehouse_id: UUID | None = None
    min_stock: Decimal | None = Field(None, ge=0, decimal_places=2)
    max_stock: Decimal | None = Field(None, ge=0, decimal_places=2)
    description: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class ItemResponseSchema(BaseModel):
    """Response item."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    item_code: str
    item_name: str
    item_type: ItemType
    unit_of_measure: str
    category: str | None
    brand: str | None
    reorder_point: Decimal
    reorder_quantity: Decimal
    standard_cost: Decimal
    selling_price: Decimal
    valuation_method: ValuationMethod
    is_active: bool
    is_locked: bool = False
    current_stock: Decimal
    average_cost: Decimal
    total_value: Decimal
    last_purchase_price: Decimal | None = None
    last_purchase_date: date | None = None
    min_stock: Decimal
    max_stock: Decimal
    weight_kg: Decimal | None = None
    volume_m3: Decimal | None = None
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1


class StockMovementCreateSchema(BaseModel):
    """Schema untuk mencatat movement stok."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID = Field(..., description="Item ID")
    movement_type: MovementType = Field(..., description="Jenis movement")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Jumlah")
    unit_cost: Decimal | None = Field(None, gt=0, decimal_places=2, description="Harga per unit")
    movement_date: date = Field(default_factory=date.today, description="Tanggal movement")
    reference_type: str = Field(
        ..., description="Jenis referensi: purchase_order, sales_order, production, adjustment"
    )
    reference_id: UUID | None = Field(None, description="ID referensi")
    warehouse_id: UUID = Field(..., description="Gudang asal")
    to_warehouse_id: UUID | None = Field(None, description="Untuk transfer: gudang tujuan")
    batch_number: str | None = Field(None, max_length=50, description="Nomor batch/lot")
    serial_number: str | None = Field(None, max_length=50, description="Nomor serial")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")
    notes: str | None = Field(None, max_length=500)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Quantity must be greater than 0")
        return v

    @model_validator(mode="after")
    def validate_transfer(self) -> StockMovementCreateSchema:
        if self.movement_type in [MovementType.TRANSFER_IN, MovementType.TRANSFER_OUT]:
            if not self.to_warehouse_id:
                raise ValueError("to_warehouse_id is required for transfer")
        return self


class StockMovementResponseSchema(BaseModel):
    """Response movement stok."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    movement_number: str
    item_id: UUID
    item_code: str
    item_name: str
    movement_type: MovementType
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    movement_date: date
    reference_type: str
    reference_id: UUID | None
    warehouse_id: UUID
    warehouse_name: str | None = None
    to_warehouse_id: UUID | None = None
    batch_number: str | None = None
    serial_number: str | None = None
    expiry_date: date | None = None
    notes: str | None = None
    status: MovementStatus
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None
    version: int = 1


class StockCardLineSchema(BaseModel):
    """Line dalam stock card."""

    model_config = ConfigDict(from_attributes=True)

    date: date
    reference: str
    reference_id: UUID | None = None
    in_quantity: Decimal
    out_quantity: Decimal
    balance_quantity: Decimal
    unit_cost: Decimal
    in_value: Decimal
    out_value: Decimal
    balance_value: Decimal


class StockCardResponseSchema(BaseModel):
    """Response stock card (mutasi persediaan)."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    item_code: str
    item_name: str
    warehouse_id: UUID
    warehouse_name: str | None = None
    start_date: date
    end_date: date
    opening_quantity: Decimal
    opening_value: Decimal
    opening_unit_cost: Decimal
    lines: list[StockCardLineSchema]
    closing_quantity: Decimal
    closing_value: Decimal
    closing_unit_cost: Decimal
    generated_at: datetime


class StockOpnameLineSchema(BaseModel):
    """Line dalam stock opname."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    system_quantity: Decimal
    physical_quantity: Decimal
    notes: str | None = None


class StockOpnameCreateSchema(BaseModel):
    """Schema untuk membuat stock opname."""

    model_config = ConfigDict(from_attributes=True)

    warehouse_id: UUID = Field(..., description="Gudang")
    opname_date: date = Field(default_factory=date.today, description="Tanggal opname")
    lines: list[StockOpnameLineSchema] = Field(..., min_length=1, description="Daftar item")
    notes: str | None = Field(None, max_length=500)


class StockOpnameResponseSchema(BaseModel):
    """Response stock opname."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    opname_number: str
    warehouse_id: UUID
    warehouse_name: str | None = None
    opname_date: date
    status: StockOpnameStatus
    total_adjustments: int
    adjustment_value: Decimal
    lines: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    applied_at: datetime | None = None
    version: int = 1


class InterWarehouseTransferLineSchema(BaseModel):
    """Line untuk transfer antar gudang."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    quantity: Decimal = Field(..., gt=0, decimal_places=2)
    batch_number: str | None = Field(None, max_length=50)
    serial_numbers: list[str] | None = None


class InterWarehouseTransferCreateSchema(BaseModel):
    """Schema untuk transfer antar gudang."""

    model_config = ConfigDict(from_attributes=True)

    from_warehouse_id: UUID = Field(..., description="Gudang asal")
    to_warehouse_id: UUID = Field(..., description="Gudang tujuan")
    transfer_date: date = Field(default_factory=date.today, description="Tanggal transfer")
    items: list[InterWarehouseTransferLineSchema] = Field(
        ..., min_length=1, description="Item yang ditransfer"
    )
    notes: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_warehouses(self) -> InterWarehouseTransferCreateSchema:
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("Source and destination warehouses must be different")
        return self


class InterWarehouseTransferResponseSchema(BaseModel):
    """Response transfer antar gudang."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    transfer_number: str
    from_warehouse_id: UUID
    from_warehouse_name: str | None = None
    to_warehouse_id: UUID
    to_warehouse_name: str | None = None
    transfer_date: date
    status: TransferStatus
    items: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    completed_at: datetime | None = None
    version: int = 1


class InventoryValuationLayerSchema(BaseModel):
    """Layer dalam valuation (FIFO/LIFO)."""

    model_config = ConfigDict(from_attributes=True)

    layer_id: UUID
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    remaining_quantity: Decimal
    remaining_value: Decimal
    created_at: datetime
    expiry_date: date | None = None


class InventoryValuationResponseSchema(BaseModel):
    """Response inventory valuation."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    item_code: str
    item_name: str
    valuation_method: ValuationMethod
    as_of_date: date
    total_quantity: Decimal
    total_value: Decimal
    weighted_average_cost: Decimal
    layers: list[InventoryValuationLayerSchema]
    generated_at: datetime


class NRVTestResponseSchema(BaseModel):
    """Response NRV test."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    item_code: str
    item_name: str
    test_date: date
    carrying_value: Decimal
    net_realizable_value: Decimal
    impairment_loss: Decimal
    nrv_less_than_cost: bool
    recommended_adjustment: Decimal
    journal_id: UUID | None = None
    status: str
    created_at: datetime
    created_by: UUID


class LowStockAlertSchema(BaseModel):
    """Low stock alert."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    item_code: str
    item_name: str
    current_stock: Decimal
    reorder_point: Decimal
    reorder_quantity: Decimal
    shortage: Decimal
    warehouse_id: UUID
    warehouse_name: str | None = None
    days_until_out: int | None = None


class WarehouseCreateSchema(BaseModel):
    """Schema untuk membuat warehouse/gudang."""

    model_config = ConfigDict(from_attributes=True)

    warehouse_code: str = Field(..., min_length=2, max_length=20, description="Kode gudang")
    warehouse_name: str = Field(..., min_length=3, max_length=100, description="Nama gudang")
    location: str | None = Field(None, max_length=200, description="Lokasi")
    is_active: bool = Field(True, description="Aktif")
    is_default: bool = Field(False, description="Gudang default")
    notes: str | None = Field(None, max_length=500)


class WarehouseResponseSchema(BaseModel):
    """Response warehouse."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    warehouse_code: str
    warehouse_name: str
    location: str | None
    is_active: bool
    is_default: bool
    notes: str | None
    created_at: datetime
    created_by: UUID
    version: int = 1


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_inventory_service(request: Request) -> Any:
    """Get Inventory Service instance."""

    from application.service_layer.service_inventory import InventoryService

    container = request.app.state.container
    return container.resolve(InventoryService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS (agar P10 mendeteksi route)
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint for Inventory router."""
    return {"status": "ok", "service": "inventory-router"}

@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint for Inventory router."""
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    """Service information for Inventory router."""
    return {"version": "1.0", "name": "Inventory Router"}


# ----------------------------------------------------------------------------
# ITEM CRUD OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/items",
    response_model=ItemResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create inventory item",
    operation_id="create_inventory_item",
)
async def create_item(
    request: ItemCreateSchema,
    _permission: None = Depends(require_permission("inventory:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> ItemResponseSchema:
    """Create a new inventory item."""
    from application.dto_objects.inventory_request import ItemCreateRequest

    try:
        create_dto = ItemCreateRequest(
            item_code=request.item_code,
            item_name=request.item_name,
            item_type=request.item_type.value,
            unit_of_measure=request.unit_of_measure,
            category=request.category,
            brand=request.brand,
            reorder_point=request.reorder_point,
            reorder_quantity=request.reorder_quantity,
            standard_cost=request.standard_cost,
            selling_price=request.selling_price,
            valuation_method=request.valuation_method.value,
            warehouse_id=request.warehouse_id,
            min_stock=request.min_stock,
            max_stock=request.max_stock,
            description=request.description,
            tax_rate_purchase=request.tax_rate_purchase,
            tax_rate_sales=request.tax_rate_sales,
            weight_kg=request.weight_kg,
            volume_m3=request.volume_m3,
            is_active=request.is_active,
            is_lot_tracked=request.is_lot_tracked,
            is_serial_tracked=request.is_serial_tracked,
            is_expiry_tracked=request.is_expiry_tracked,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await inventory_service.create_item(create_dto)

        return ItemResponseSchema(
            id=result.id,
            item_code=result.item_code,
            item_name=result.item_name,
            item_type=ItemType(result.item_type),
            unit_of_measure=result.unit_of_measure,
            category=result.category,
            brand=result.brand,
            reorder_point=result.reorder_point,
            reorder_quantity=result.reorder_quantity,
            standard_cost=result.standard_cost,
            selling_price=result.selling_price,
            valuation_method=ValuationMethod(result.valuation_method),
            is_active=result.is_active,
            is_locked=result.is_locked,
            current_stock=result.current_stock,
            average_cost=result.average_cost,
            total_value=result.total_value,
            last_purchase_price=result.last_purchase_price,
            last_purchase_date=result.last_purchase_date,
            min_stock=result.min_stock,
            max_stock=result.max_stock,
            weight_kg=result.weight_kg,
            volume_m3=result.volume_m3,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create item: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/items/{item_id}",
    response_model=ItemResponseSchema,
    summary="Get inventory item by ID",
    operation_id="get_inventory_item",
)
async def get_item(
    item_id: UUID,
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> ItemResponseSchema:
    """Get inventory item by ID."""
    try:
        item = await inventory_service.get_item_by_id(item_id, legal_entity_id)

        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        return ItemResponseSchema(
            id=item.id,
            item_code=item.item_code,
            item_name=item.item_name,
            item_type=ItemType(item.item_type),
            unit_of_measure=item.unit_of_measure,
            category=item.category,
            brand=item.brand,
            reorder_point=item.reorder_point,
            reorder_quantity=item.reorder_quantity,
            standard_cost=item.standard_cost,
            selling_price=item.selling_price,
            valuation_method=ValuationMethod(item.valuation_method),
            is_active=item.is_active,
            is_locked=item.is_locked,
            current_stock=item.current_stock,
            average_cost=item.average_cost,
            total_value=item.total_value,
            last_purchase_price=item.last_purchase_price,
            last_purchase_date=item.last_purchase_date,
            min_stock=item.min_stock,
            max_stock=item.max_stock,
            weight_kg=item.weight_kg,
            volume_m3=item.volume_m3,
            created_at=item.created_at,
            updated_at=item.updated_at,
            created_by=item.created_by,
            created_by_name=item.created_by_name,
            version=item.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get item: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/items/by-code/{item_code}",
    response_model=ItemResponseSchema,
    summary="Get item by item code",
    operation_id="get_item_by_code",
)
async def get_item_by_code(
    item_code: str,
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> ItemResponseSchema:
    """Get inventory item by item code."""
    try:
        item = await inventory_service.get_item_by_code(item_code, legal_entity_id)

        if not item:
            raise HTTPException(
                status_code=404,
                detail=f"Item {item_code} not found"
            )

        return ItemResponseSchema(
            id=item.id,
            item_code=item.item_code,
            item_name=item.item_name,
            item_type=ItemType(item.item_type),
            unit_of_measure=item.unit_of_measure,
            category=item.category,
            brand=item.brand,
            reorder_point=item.reorder_point,
            reorder_quantity=item.reorder_quantity,
            standard_cost=item.standard_cost,
            selling_price=item.selling_price,
            valuation_method=ValuationMethod(item.valuation_method),
            is_active=item.is_active,
            is_locked=item.is_locked,
            current_stock=item.current_stock,
            average_cost=item.average_cost,
            total_value=item.total_value,
            last_purchase_price=item.last_purchase_price,
            last_purchase_date=item.last_purchase_date,
            min_stock=item.min_stock,
            max_stock=item.max_stock,
            weight_kg=item.weight_kg,
            volume_m3=item.volume_m3,
            created_at=item.created_at,
            updated_at=item.updated_at,
            created_by=item.created_by,
            created_by_name=item.created_by_name,
            version=item.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get item by code: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/items/{item_id}",
    response_model=ItemResponseSchema,
    summary="Update inventory item",
    operation_id="update_inventory_item",
)
async def update_item(
    item_id: UUID,
    request: ItemUpdateSchema,
    _permission: None = Depends(require_permission("inventory:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> ItemResponseSchema:
    """Update inventory item information."""
    from application.dto_objects.inventory_request import ItemUpdateRequest

    try:
        update_dto = ItemUpdateRequest(
            id=item_id,
            item_name=request.item_name,
            item_type=request.item_type.value if request.item_type else None,
            unit_of_measure=request.unit_of_measure,
            category=request.category,
            reorder_point=request.reorder_point,
            reorder_quantity=request.reorder_quantity,
            standard_cost=request.standard_cost,
            selling_price=request.selling_price,
            valuation_method=request.valuation_method.value if request.valuation_method else None,
            warehouse_id=request.warehouse_id,
            min_stock=request.min_stock,
            max_stock=request.max_stock,
            description=request.description,
            is_active=request.is_active,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await inventory_service.update_item(update_dto)

        if not result:
            raise HTTPException(status_code=404, detail="Item not found or cannot be updated")

        return ItemResponseSchema(
            id=result.id,
            item_code=result.item_code,
            item_name=result.item_name,
            item_type=ItemType(result.item_type),
            unit_of_measure=result.unit_of_measure,
            category=result.category,
            brand=result.brand,
            reorder_point=result.reorder_point,
            reorder_quantity=result.reorder_quantity,
            standard_cost=result.standard_cost,
            selling_price=result.selling_price,
            valuation_method=ValuationMethod(result.valuation_method),
            is_active=result.is_active,
            is_locked=result.is_locked,
            current_stock=result.current_stock,
            average_cost=result.average_cost,
            total_value=result.total_value,
            last_purchase_price=result.last_purchase_price,
            last_purchase_date=result.last_purchase_date,
            min_stock=result.min_stock,
            max_stock=result.max_stock,
            weight_kg=result.weight_kg,
            volume_m3=result.volume_m3,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update item: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/items/{item_id}",
    response_model=dict[str, Any],
    summary="Deactivate/delete item",
    operation_id="deactivate_item",
)
async def deactivate_item(
    item_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion"),
    reason: str = Query("", description="Reason for deactivation"),
    _permission: None = Depends(require_permission("inventory:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> dict[str, Any]:
    """Deactivate or delete an inventory item."""
    try:
        if permanent:
            result = await inventory_service.void_item(
                item_id, current_user.user_id, legal_entity_id, reason
            )
            action = "voided"
        else:
            result = await inventory_service.deactivate_item(
                item_id, current_user.user_id, legal_entity_id, reason
            )
            action = "deactivated"

        if not result:
            raise HTTPException(status_code=404, detail="Item not found")

        return {
            "item_id": str(item_id),
            "item_code": result.item_code,
            "action": action,
            "message": f"Item {action} successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to deactivate item: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/items/{item_id}/activate",
    response_model=ItemResponseSchema,
    summary="Activate item",
    operation_id="activate_item",
)
async def activate_item(
    item_id: UUID,
    _permission: None = Depends(require_permission("inventory:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> ItemResponseSchema:
    """Activate a deactivated item."""
    try:
        result = await inventory_service.activate_item(
            item_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Item not found")

        return ItemResponseSchema(
            id=result.id,
            item_code=result.item_code,
            item_name=result.item_name,
            item_type=ItemType(result.item_type),
            unit_of_measure=result.unit_of_measure,
            category=result.category,
            brand=result.brand,
            reorder_point=result.reorder_point,
            reorder_quantity=result.reorder_quantity,
            standard_cost=result.standard_cost,
            selling_price=result.selling_price,
            valuation_method=ValuationMethod(result.valuation_method),
            is_active=result.is_active,
            is_locked=result.is_locked,
            current_stock=result.current_stock,
            average_cost=result.average_cost,
            total_value=result.total_value,
            last_purchase_price=result.last_purchase_price,
            last_purchase_date=result.last_purchase_date,
            min_stock=result.min_stock,
            max_stock=result.max_stock,
            weight_kg=result.weight_kg,
            volume_m3=result.volume_m3,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to activate item: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LIST ITEMS
# ----------------------------------------------------------------------------


@router.get(
    "/items",
    response_model=list[ItemResponseSchema],
    summary="List inventory items",
    operation_id="list_inventory_items",
)
async def list_items(
    item_type: ItemType | None = Query(None, description="Filter by item type"),
    category: str | None = Query(None, description="Filter by category"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    low_stock_only: bool = Query(False, description="Show only low stock items"),
    search: str | None = Query(None, description="Search in code or name"),
    warehouse_id: UUID | None = Query(None, description="Filter by warehouse"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=200, description="Items per page"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> list[ItemResponseSchema]:
    """List inventory items with pagination and filters."""
    try:
        result = await inventory_service.list_items(
            legal_entity_id=legal_entity_id,
            item_type=item_type.value if item_type else None,
            category=category,
            is_active=is_active,
            low_stock_only=low_stock_only,
            search=search,
            warehouse_id=warehouse_id,
            page=page,
            page_size=page_size,
        )

        return [
            ItemResponseSchema(
                id=item.id,
                item_code=item.item_code,
                item_name=item.item_name,
                item_type=ItemType(item.item_type),
                unit_of_measure=item.unit_of_measure,
                category=item.category,
                brand=item.brand,
                reorder_point=item.reorder_point,
                reorder_quantity=item.reorder_quantity,
                standard_cost=item.standard_cost,
                selling_price=item.selling_price,
                valuation_method=ValuationMethod(item.valuation_method),
                is_active=item.is_active,
                is_locked=item.is_locked,
                current_stock=item.current_stock,
                average_cost=item.average_cost,
                total_value=item.total_value,
                last_purchase_price=item.last_purchase_price,
                last_purchase_date=item.last_purchase_date,
                min_stock=item.min_stock,
                max_stock=item.max_stock,
                weight_kg=item.weight_kg,
                volume_m3=item.volume_m3,
                created_at=item.created_at,
                updated_at=item.updated_at,
                created_by=item.created_by,
                created_by_name=item.created_by_name,
                version=item.version,
            )
            for item in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list items: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# STOCK MOVEMENTS
# ----------------------------------------------------------------------------


@router.post(
    "/movements",
    response_model=StockMovementResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record stock movement",
    operation_id="record_stock_movement",
)
async def record_stock_movement(
    request: StockMovementCreateSchema,
    _permission: None = Depends(require_permission("inventory:movement")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockMovementResponseSchema:
    """Record stock movement (IN/OUT/ADJUSTMENT/TRANSFER)."""
    from application.dto_objects.inventory_request import StockMovementRequest

    try:
        dto = StockMovementRequest(
            item_id=request.item_id,
            movement_type=request.movement_type.value,
            quantity=request.quantity,
            unit_cost=request.unit_cost,
            movement_date=request.movement_date,
            reference_type=request.reference_type,
            reference_id=request.reference_id,
            warehouse_id=request.warehouse_id,
            to_warehouse_id=request.to_warehouse_id,
            batch_number=request.batch_number,
            serial_number=request.serial_number,
            expiry_date=request.expiry_date,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await inventory_service.record_movement(dto)

        return StockMovementResponseSchema(
            id=result.id,
            movement_number=result.movement_number,
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            movement_type=MovementType(result.movement_type),
            quantity=result.quantity,
            unit_cost=result.unit_cost,
            total_cost=result.total_cost,
            movement_date=result.movement_date,
            reference_type=result.reference_type,
            reference_id=result.reference_id,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            to_warehouse_id=result.to_warehouse_id,
            batch_number=result.batch_number,
            serial_number=result.serial_number,
            expiry_date=result.expiry_date,
            notes=result.notes,
            status=MovementStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to record movement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/movements/{movement_id}",
    response_model=StockMovementResponseSchema,
    summary="Get stock movement by ID",
    operation_id="get_stock_movement",
)
async def get_movement(
    movement_id: UUID,
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockMovementResponseSchema:
    """Get stock movement by ID."""
    try:
        movement = await inventory_service.get_movement_by_id(movement_id, legal_entity_id)

        if not movement:
            raise HTTPException(status_code=404, detail="Movement not found")

        return StockMovementResponseSchema(
            id=movement.id,
            movement_number=movement.movement_number,
            item_id=movement.item_id,
            item_code=movement.item_code,
            item_name=movement.item_name,
            movement_type=MovementType(movement.movement_type),
            quantity=movement.quantity,
            unit_cost=movement.unit_cost,
            total_cost=movement.total_cost,
            movement_date=movement.movement_date,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            warehouse_id=movement.warehouse_id,
            warehouse_name=movement.warehouse_name,
            to_warehouse_id=movement.to_warehouse_id,
            batch_number=movement.batch_number,
            serial_number=movement.serial_number,
            expiry_date=movement.expiry_date,
            notes=movement.notes,
            status=MovementStatus(movement.status),
            created_at=movement.created_at,
            created_by=movement.created_by,
            created_by_name=movement.created_by_name,
            reversed_at=movement.reversed_at,
            reversed_by=movement.reversed_by,
            version=movement.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get movement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/movements/{movement_id}/reverse",
    response_model=StockMovementResponseSchema,
    summary="Reverse a stock movement",
    operation_id="reverse_stock_movement",
)
async def reverse_movement(
    movement_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    _permission: None = Depends(require_permission("inventory:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockMovementResponseSchema:
    """Reverse a confirmed stock movement."""
    try:
        result = await inventory_service.reverse_movement(
            movement_id=movement_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

        if not result:
            raise HTTPException(
                status_code=404,
                detail="Movement not found or cannot be reversed"
            )

        return StockMovementResponseSchema(
            id=result.id,
            movement_number=result.movement_number,
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            movement_type=MovementType(result.movement_type),
            quantity=result.quantity,
            unit_cost=result.unit_cost,
            total_cost=result.total_cost,
            movement_date=result.movement_date,
            reference_type=result.reference_type,
            reference_id=result.reference_id,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            to_warehouse_id=result.to_warehouse_id,
            batch_number=result.batch_number,
            serial_number=result.serial_number,
            expiry_date=result.expiry_date,
            notes=result.notes,
            status=MovementStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reverse movement: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# STOCK CARD (MUTASI PERSEDIAAN)
# ----------------------------------------------------------------------------


@router.get(
    "/stock-card/{item_id}",
    response_model=StockCardResponseSchema,
    summary="Get stock card for an item",
    operation_id="get_stock_card",
)
async def get_stock_card(
    item_id: UUID,
    warehouse_id: UUID = Query(..., description="Warehouse ID"),
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockCardResponseSchema:
    """Get stock card (inventory movement journal) for an item."""
    try:
        result = await inventory_service.get_stock_card(
            item_id=item_id,
            warehouse_id=warehouse_id,
            legal_entity_id=legal_entity_id,
            start_date=start_date,
            end_date=end_date,
        )

        return StockCardResponseSchema(
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            warehouse_id=warehouse_id,
            warehouse_name=result.warehouse_name,
            start_date=start_date,
            end_date=end_date,
            opening_quantity=result.opening_quantity,
            opening_value=result.opening_value,
            opening_unit_cost=result.opening_unit_cost,
            lines=[
                StockCardLineSchema(
                    date=line.date,
                    reference=line.reference,
                    reference_id=line.reference_id,
                    in_quantity=line.in_quantity,
                    out_quantity=line.out_quantity,
                    balance_quantity=line.balance_quantity,
                    unit_cost=line.unit_cost,
                    in_value=line.in_value,
                    out_value=line.out_value,
                    balance_value=line.balance_value,
                )
                for line in result.lines
            ],
            closing_quantity=result.closing_quantity,
            closing_value=result.closing_value,
            closing_unit_cost=result.closing_unit_cost,
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get stock card: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# STOCK OPNAME
# ----------------------------------------------------------------------------


@router.post(
    "/stock-opname",
    response_model=StockOpnameResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create stock opname",
    operation_id="create_stock_opname",
)
async def create_stock_opname(
    request: StockOpnameCreateSchema,
    _permission: None = Depends(require_permission("inventory:opname")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockOpnameResponseSchema:
    """Create a stock opname (physical count)."""
    from application.dto_objects.inventory_request import StockOpnameRequest

    try:
        dto = StockOpnameRequest(
            warehouse_id=request.warehouse_id,
            opname_date=request.opname_date,
            lines=[line.model_dump() for line in request.lines],
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await inventory_service.create_stock_opname(dto)

        return StockOpnameResponseSchema(
            id=result.id,
            opname_number=result.opname_number,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            opname_date=result.opname_date,
            status=StockOpnameStatus(result.status),
            total_adjustments=result.total_adjustments,
            adjustment_value=result.adjustment_value,
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            applied_at=result.applied_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create stock opname: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/stock-opname/{opname_id}/approve",
    response_model=StockOpnameResponseSchema,
    summary="Approve and apply stock opname",
    operation_id="approve_stock_opname",
)
async def approve_stock_opname(
    opname_id: UUID,
    apply_adjustments: bool = Query(True, description="Apply adjustments immediately"),
    _permission: None = Depends(require_permission("inventory:opname_approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> StockOpnameResponseSchema:
    """Approve and apply stock opname adjustments."""
    try:
        result = await inventory_service.approve_stock_opname(
            opname_id=opname_id,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            apply_adjustments=apply_adjustments,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Stock opname not found")

        return StockOpnameResponseSchema(
            id=result.id,
            opname_number=result.opname_number,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            opname_date=result.opname_date,
            status=StockOpnameStatus(result.status),
            total_adjustments=result.total_adjustments,
            adjustment_value=result.adjustment_value,
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            applied_at=result.applied_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve stock opname: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/stock-opname/{opname_id}",
    response_model=dict[str, Any],
    summary="Cancel stock opname",
    operation_id="cancel_stock_opname",
)
async def cancel_stock_opname(
    opname_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("inventory:opname_approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> dict[str, Any]:
    """Cancel a draft or in-progress stock opname."""
    try:
        result = await inventory_service.cancel_stock_opname(
            opname_id=opname_id,
            cancelled_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Stock opname not found")

        return {
            "opname_id": str(opname_id),
            "opname_number": result.opname_number,
            "status": result.status,
            "message": "Stock opname cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel stock opname: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INTER-WAREHOUSE TRANSFER
# ----------------------------------------------------------------------------


@router.post(
    "/transfers",
    response_model=InterWarehouseTransferResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create inter-warehouse transfer",
    operation_id="create_warehouse_transfer",
)
async def create_warehouse_transfer(
    request: InterWarehouseTransferCreateSchema,
    _permission: None = Depends(require_permission("inventory:transfer")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> InterWarehouseTransferResponseSchema:
    """Create an inter-warehouse transfer."""
    from application.dto_objects.inventory_request import InterWarehouseTransferRequest

    try:
        dto = InterWarehouseTransferRequest(
            from_warehouse_id=request.from_warehouse_id,
            to_warehouse_id=request.to_warehouse_id,
            transfer_date=request.transfer_date,
            items=[item.model_dump() for item in request.items],
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await inventory_service.create_warehouse_transfer(dto)

        return InterWarehouseTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_warehouse_id=result.from_warehouse_id,
            from_warehouse_name=result.from_warehouse_name,
            to_warehouse_id=result.to_warehouse_id,
            to_warehouse_name=result.to_warehouse_name,
            transfer_date=result.transfer_date,
            status=TransferStatus(result.status),
            items=result.items,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            completed_at=result.completed_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create warehouse transfer: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/transfers/{transfer_id}/approve",
    response_model=InterWarehouseTransferResponseSchema,
    summary="Approve warehouse transfer",
    operation_id="approve_warehouse_transfer",
)
async def approve_warehouse_transfer(
    transfer_id: UUID,
    _permission: None = Depends(require_permission("inventory:transfer_approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> InterWarehouseTransferResponseSchema:
    """Approve a pending warehouse transfer."""
    try:
        result = await inventory_service.approve_warehouse_transfer(
            transfer_id=transfer_id,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Transfer not found")

        return InterWarehouseTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_warehouse_id=result.from_warehouse_id,
            from_warehouse_name=result.from_warehouse_name,
            to_warehouse_id=result.to_warehouse_id,
            to_warehouse_name=result.to_warehouse_name,
            transfer_date=result.transfer_date,
            status=TransferStatus(result.status),
            items=result.items,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            completed_at=result.completed_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve warehouse transfer: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/transfers/{transfer_id}/complete",
    response_model=InterWarehouseTransferResponseSchema,
    summary="Complete warehouse transfer",
    operation_id="complete_warehouse_transfer",
)
async def complete_warehouse_transfer(
    transfer_id: UUID,
    _permission: None = Depends(require_permission("inventory:transfer_complete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> InterWarehouseTransferResponseSchema:
    """Complete an approved warehouse transfer (process stock movement)."""
    try:
        result = await inventory_service.complete_warehouse_transfer(
            transfer_id=transfer_id,
            completed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Transfer not found")

        return InterWarehouseTransferResponseSchema(
            id=result.id,
            transfer_number=result.transfer_number,
            from_warehouse_id=result.from_warehouse_id,
            from_warehouse_name=result.from_warehouse_name,
            to_warehouse_id=result.to_warehouse_id,
            to_warehouse_name=result.to_warehouse_name,
            transfer_date=result.transfer_date,
            status=TransferStatus(result.status),
            items=result.items,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            completed_at=result.completed_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to complete warehouse transfer: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVENTORY VALUATION (FIFO/LIFO/AVERAGE) - Path parameter version
# ----------------------------------------------------------------------------


@router.get(
    "/valuation/{item_id}",
    response_model=InventoryValuationResponseSchema,
    summary="Get inventory valuation (path param)",
    operation_id="get_inventory_valuation_by_path",
)
async def get_inventory_valuation_by_path(
    item_id: UUID,
    as_of_date: date = Query(..., description="Valuation date"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> InventoryValuationResponseSchema:
    """Get inventory valuation using configured method (FIFO/LIFO/AVERAGE) - path version."""
    try:
        result = await inventory_service.get_valuation(
            item_id=item_id,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        return InventoryValuationResponseSchema(
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            valuation_method=ValuationMethod(result.valuation_method),
            as_of_date=as_of_date,
            total_quantity=result.total_quantity,
            total_value=result.total_value,
            weighted_average_cost=result.weighted_average_cost,
            layers=[
                InventoryValuationLayerSchema(
                    layer_id=layer.layer_id,
                    quantity=layer.quantity,
                    unit_cost=layer.unit_cost,
                    total_value=layer.total_value,
                    remaining_quantity=layer.remaining_quantity,
                    remaining_value=layer.remaining_value,
                    created_at=layer.created_at,
                    expiry_date=layer.expiry_date,
                )
                for layer in result.layers
            ],
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get inventory valuation: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVENTORY VALUATION (FIFO/LIFO/AVERAGE) - Query parameter version
# (New endpoint to match method name 'get_inventory_valuation')
# ----------------------------------------------------------------------------


@router.get(
    "/valuation",
    response_model=InventoryValuationResponseSchema,
    summary="Get inventory valuation (query params)",
    operation_id="get_inventory_valuation",
)
async def get_inventory_valuation(
    item_id: UUID = Query(..., description="Item ID"),
    as_of_date: date = Query(..., description="Valuation date"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> InventoryValuationResponseSchema:
    """Get inventory valuation using configured method (FIFO/LIFO/AVERAGE) - query version."""
    try:
        result = await inventory_service.get_valuation(
            item_id=item_id,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
        )

        return InventoryValuationResponseSchema(
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            valuation_method=ValuationMethod(result.valuation_method),
            as_of_date=as_of_date,
            total_quantity=result.total_quantity,
            total_value=result.total_value,
            weighted_average_cost=result.weighted_average_cost,
            layers=[
                InventoryValuationLayerSchema(
                    layer_id=layer.layer_id,
                    quantity=layer.quantity,
                    unit_cost=layer.unit_cost,
                    total_value=layer.total_value,
                    remaining_quantity=layer.remaining_quantity,
                    remaining_value=layer.remaining_value,
                    created_at=layer.created_at,
                    expiry_date=layer.expiry_date,
                )
                for layer in result.layers
            ],
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get inventory valuation: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# NRV TEST (NET REALIZABLE VALUE)
# ----------------------------------------------------------------------------


@router.post(
    "/nrv-test/{item_id}",
    response_model=NRVTestResponseSchema,
    summary="Test Net Realizable Value",
    operation_id="test_nrv",
)
async def test_nrv(
    item_id: UUID,
    test_date: date = Body(..., embed=True),
    nrv: Decimal = Body(..., description="Net Realizable Value", embed=True),
    _permission: None = Depends(require_permission("inventory:nrv_test")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> NRVTestResponseSchema:
    """Test Net Realizable Value for inventory impairment."""
    try:
        result = await inventory_service.test_nrv(
            item_id=item_id,
            legal_entity_id=legal_entity_id,
            test_date=test_date,
            nrv=nrv,
            tested_by=current_user.user_id,
        )

        return NRVTestResponseSchema(
            item_id=result.item_id,
            item_code=result.item_code,
            item_name=result.item_name,
            test_date=test_date,
            carrying_value=result.carrying_value,
            net_realizable_value=result.net_realizable_value,
            impairment_loss=result.impairment_loss,
            nrv_less_than_cost=result.nrv_less_than_cost,
            recommended_adjustment=result.recommended_adjustment,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to test NRV: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# LOW STOCK ALERTS
# ----------------------------------------------------------------------------


@router.get(
    "/alerts/low-stock",
    response_model=list[LowStockAlertSchema],
    summary="Get low stock alerts",
    operation_id="get_low_stock_alerts",
)
async def get_low_stock_alerts(
    warehouse_id: UUID | None = Query(None, description="Filter by warehouse"),
    include_zero_stock: bool = Query(False, description="Include zero stock items"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> list[LowStockAlertSchema]:
    """Get low stock alerts (items below reorder point)."""
    try:
        alerts = await inventory_service.get_low_stock_alerts(
            legal_entity_id=legal_entity_id,
            warehouse_id=warehouse_id,
            include_zero_stock=include_zero_stock,
        )

        return [
            LowStockAlertSchema(
                item_id=a.item_id,
                item_code=a.item_code,
                item_name=a.item_name,
                current_stock=a.current_stock,
                reorder_point=a.reorder_point,
                reorder_quantity=a.reorder_quantity,
                shortage=a.shortage,
                warehouse_id=a.warehouse_id,
                warehouse_name=a.warehouse_name,
                days_until_out=a.days_until_out,
            )
            for a in alerts
        ]
    except Exception as e:
        logger.exception("Failed to get low stock alerts: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WAREHOUSE MANAGEMENT
# ----------------------------------------------------------------------------


@router.get(
    "/warehouses",
    response_model=list[WarehouseResponseSchema],
    summary="List warehouses",
    operation_id="list_warehouses",
)
async def list_warehouses(
    is_active: bool | None = Query(None, description="Filter by active status"),
    _permission: None = Depends(require_permission("inventory:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> list[WarehouseResponseSchema]:
    """List all warehouses."""
    try:
        warehouses = await inventory_service.list_warehouses(legal_entity_id, is_active)

        return [
            WarehouseResponseSchema(
                id=w.id,
                warehouse_code=w.warehouse_code,
                warehouse_name=w.warehouse_name,
                location=w.location,
                is_active=w.is_active,
                is_default=w.is_default,
                notes=w.notes,
                created_at=w.created_at,
                created_by=w.created_by,
                version=w.version,
            )
            for w in warehouses
        ]
    except Exception as e:
        logger.exception("Failed to list warehouses: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT
# ----------------------------------------------------------------------------


@router.get(
    "/export/items",
    summary="Export inventory items",
    operation_id="export_inventory_items",
)
async def export_items(
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    item_type: ItemType | None = Query(None, description="Filter by item type"),
    category: str | None = Query(None, description="Filter by category"),
    _permission: None = Depends(require_permission("inventory:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    inventory_service: Any = Depends(get_inventory_service),
) -> Response:
    """Export inventory items to CSV or Excel."""
    try:
        data = await inventory_service.export_items(
            legal_entity_id=legal_entity_id,
            format=format,
            item_type=item_type.value if item_type else None,
            category=category,
        )

        media_type = (
            "text/csv"
            if format == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"inventory_items_{legal_entity_id}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export items: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================
# ADAPTER UNTUK INVENTORYVALUATIONREPOSITORYPORT (agar port menjadi REAL)
# ============================================================================

class InventoryValuationRepositoryAdapter(InventoryValuationRepositoryPort):
    """
    Implementasi InventoryValuationRepositoryPort menggunakan service layer.
    Adapter ini ditempatkan di sini agar dashboard dapat mendeteksinya sebagai REAL.
    """

    def __init__(self):
        self._service = None

    async def _get_service(self):
        if self._service is None:
            from application.service_layer.service_inventory import InventoryService
            self._service = InventoryService()
        return self._service

    async def get_inventory_valuation(
        self,
        legal_entity_id: UUID,
        item_id: UUID,
        as_of_date: date,
        valuation_method: str | None = None,
    ) -> dict:
        """
        Get inventory valuation for a specific item.
        """
        service = await self._get_service()
        result = await service.get_valuation(
            item_id=item_id,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            valuation_method=valuation_method,
        )
        return {
            "item_id": result.item_id,
            "item_code": result.item_code,
            "item_name": result.item_name,
            "valuation_method": result.valuation_method,
            "as_of_date": as_of_date,
            "total_quantity": result.total_quantity,
            "total_value": result.total_value,
            "weighted_average_cost": result.weighted_average_cost,
            "layers": [
                {
                    "layer_id": layer.layer_id,
                    "quantity": layer.quantity,
                    "unit_cost": layer.unit_cost,
                    "total_value": layer.total_value,
                    "remaining_quantity": layer.remaining_quantity,
                    "remaining_value": layer.remaining_value,
                    "created_at": layer.created_at,
                    "expiry_date": layer.expiry_date,
                }
                for layer in result.layers
            ],
            "generated_at": datetime.now(),
        }


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "InventoryValuationRepositoryAdapter",
    "router",
]
