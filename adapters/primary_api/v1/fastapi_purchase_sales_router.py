#!/usr/bin/env python3
"""
Module: fastapi_purchase_sales_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Purchase Order (PO),
               Sales Order (SO), Goods Receipt Note (GRN), Delivery Order (DO),
               dan proses terkait pembelian/penjualan.

Method Standards (ERP):
- create_purchase_order() / update_purchase_order() / delete_purchase_order() / get_purchase_order()
- submit_purchase_order() / approve_purchase_order() / reject_purchase_order()
- cancel_purchase_order() / close_purchase_order() / reopen_purchase_order()
- create_sales_order() / update_sales_order() / delete_sales_order() / get_sales_order()
- submit_sales_order() / approve_sales_order() / reject_sales_order()
- cancel_sales_order() / close_sales_order() / reopen_sales_order()
- create_goods_receipt() / confirm_goods_receipt() / cancel_goods_receipt()
- create_delivery_order() / confirm_delivery_order() / ship_delivery_order()
- get_purchase_order_status() / get_sales_order_status()
- get_purchase_order_history() / get_sales_order_history()
- audit_trail_po() / audit_trail_so()
- can_transition_po() / can_transition_so()
- register_po_event() / register_so_event()
- version_po() / version_so()
"""


from __future__ import annotationsimport hashlibimport jsonimport loggingfrom datetime import date, datetimefrom decimal import ROUND_HALF_UP, Decimalfrom enum import Enumfrom typing import Anyfrom uuid import UUIDfrom fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, statusfrom fastapi.responses import Responsefrom pydantic import BaseModel, ConfigDict, Field, field_validator, model_validatorfrom adapters.primary_api.common.fastapi_auth_jwt_middleware import (    TokenPayload,    get_current_legal_entity,    get_current_user,    require_permission,)logger = logging.getLogger(__name__)

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


class PurchaseOrderStatus(str, Enum):
    """Status Purchase Order."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIALLY_RECEIVED = "partially_received"
    FULLY_RECEIVED = "fully_received"
    PARTIALLY_INVOICED = "partially_invoiced"
    FULLY_INVOICED = "fully_invoiced"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class SalesOrderStatus(str, Enum):
    """Status Sales Order."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIALLY_SHIPPED = "partially_shipped"
    FULLY_SHIPPED = "fully_shipped"
    PARTIALLY_INVOICED = "partially_invoiced"
    FULLY_INVOICED = "fully_invoiced"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    LOCKED = "locked"
    ARCHIVED = "archived"


class GoodsReceiptStatus(str, Enum):
    """Status Goods Receipt Note."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    POSTED = "posted"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class DeliveryOrderStatus(str, Enum):
    """Status Delivery Order."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class OrderType(str, Enum):
    """Jenis order."""

    STANDARD = "standard"
    RUSH = "rush"
    BACKORDER = "backorder"
    CONSIGNMENT = "consignment"
    DROPSHIP = "dropship"


class Incoterm(str, Enum):
    """Incoterms."""

    EXW = "EXW"  # Ex Works
    FCA = "FCA"  # Free Carrier
    FAS = "FAS"  # Free Alongside Ship
    FOB = "FOB"  # Free On Board
    CFR = "CFR"  # Cost and Freight
    CIF = "CIF"  # Cost, Insurance and Freight
    CPT = "CPT"  # Carriage Paid To
    CIP = "CIP"  # Carriage and Insurance Paid To
    DAP = "DAP"  # Delivered At Place
    DPU = "DPU"  # Delivered At Place Unloaded
    DDP = "DDP"  # Delivered Duty Paid


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


# ---- PURCHASE ORDER ----


class POLineSchema(BaseModel):
    """Line item dalam Purchase Order."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID = Field(..., description="Item ID")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas")
    unit_price: Decimal = Field(..., gt=0, decimal_places=2, description="Harga per unit")
    discount_percent: Decimal = Field(0, ge=0, le=100, decimal_places=2, description="Diskon %")
    tax_rate: Decimal = Field(0, ge=0, le=100, decimal_places=2, description="Pajak %")
    expected_delivery_date: date | None = Field(
        None, description="Tanggal pengiriman yang diharapkan"
    )
    description: str | None = Field(None, max_length=500, description="Deskripsi")

    @property
    def net_amount(self) -> Decimal:
        return (self.quantity * self.unit_price * (1 - self.discount_percent / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def tax_amount(self) -> Decimal:
        return (self.net_amount * self.tax_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def total_amount(self) -> Decimal:
        return (self.net_amount + self.tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PurchaseOrderCreateSchema(BaseModel):
    """Schema untuk membuat Purchase Order baru."""

    model_config = ConfigDict(from_attributes=True)

    po_number: str = Field(..., max_length=50, description="Nomor PO")
    po_date: date = Field(default_factory=date.today, description="Tanggal PO")
    supplier_id: UUID = Field(..., description="Supplier ID")
    lines: list[POLineSchema] = Field(..., min_length=1, description="Line items")
    expected_delivery_date: date | None = Field(
        None, description="Tanggal pengiriman yang diharapkan"
    )
    delivery_term_days: int = Field(30, ge=0, description="Term pengiriman (hari)")
    payment_term_days: int = Field(30, ge=0, description="Term pembayaran (hari)")
    incoterm: Incoterm = Field(Incoterm.FOB, description="Incoterm")
    order_type: OrderType = Field(OrderType.STANDARD, description="Jenis order")
    reference_number: str | None = Field(None, max_length=50, description="Nomor referensi")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("po_number")
    @classmethod
    def validate_po_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("PO number is required")
        return v.strip()

    @property
    def total_amount(self) -> Decimal:
        return sum(line.total_amount for line in self.lines)


class PurchaseOrderUpdateSchema(BaseModel):
    """Schema untuk update Purchase Order."""

    model_config = ConfigDict(from_attributes=True)

    expected_delivery_date: date | None = None
    delivery_term_days: int | None = Field(None, ge=0)
    payment_term_days: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)
    status: PurchaseOrderStatus | None = None


class PurchaseOrderResponseSchema(BaseModel):
    """Response Purchase Order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    po_number: str
    po_date: date
    supplier_id: UUID
    supplier_name: str | None = None
    supplier_code: str | None = None
    total_amount: Decimal
    received_amount: Decimal
    invoiced_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: PurchaseOrderStatus
    expected_delivery_date: date | None
    actual_delivery_date: date | None
    delivery_term_days: int
    payment_term_days: int
    incoterm: Incoterm
    order_type: OrderType
    reference_number: str | None
    notes: str | None
    lines: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    rejected_at: datetime | None = None
    rejected_by: UUID | None = None
    rejection_reason: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    closed_at: datetime | None = None
    is_locked: bool = False
    version: int = 1


# ---- SALES ORDER ----


class SOLineSchema(BaseModel):
    """Line item dalam Sales Order."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID = Field(..., description="Item ID")
    quantity: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas")
    unit_price: Decimal = Field(..., gt=0, decimal_places=2, description="Harga per unit")
    discount_percent: Decimal = Field(0, ge=0, le=100, decimal_places=2, description="Diskon %")
    tax_rate: Decimal = Field(0, ge=0, le=100, decimal_places=2, description="Pajak %")
    expected_ship_date: date | None = Field(None, description="Tanggal pengiriman yang diharapkan")
    description: str | None = Field(None, max_length=500, description="Deskripsi")

    @property
    def net_amount(self) -> Decimal:
        return (self.quantity * self.unit_price * (1 - self.discount_percent / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def tax_amount(self) -> Decimal:
        return (self.net_amount * self.tax_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def total_amount(self) -> Decimal:
        return (self.net_amount + self.tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class SalesOrderCreateSchema(BaseModel):
    """Schema untuk membuat Sales Order baru."""

    model_config = ConfigDict(from_attributes=True)

    so_number: str = Field(..., max_length=50, description="Nomor SO")
    so_date: date = Field(default_factory=date.today, description="Tanggal SO")
    customer_id: UUID = Field(..., description="Customer ID")
    lines: list[SOLineSchema] = Field(..., min_length=1, description="Line items")
    expected_ship_date: date | None = Field(None, description="Tanggal pengiriman yang diharapkan")
    shipping_term_days: int = Field(7, ge=0, description="Term pengiriman (hari)")
    payment_term_days: int = Field(30, ge=0, description="Term pembayaran (hari)")
    incoterm: Incoterm = Field(Incoterm.FOB, description="Incoterm")
    order_type: OrderType = Field(OrderType.STANDARD, description="Jenis order")
    reference_number: str | None = Field(None, max_length=50, description="Nomor referensi")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("so_number")
    @classmethod
    def validate_so_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("SO number is required")
        return v.strip()

    @property
    def total_amount(self) -> Decimal:
        return sum(line.total_amount for line in self.lines)


class SalesOrderUpdateSchema(BaseModel):
    """Schema untuk update Sales Order."""

    model_config = ConfigDict(from_attributes=True)

    expected_ship_date: date | None = None
    shipping_term_days: int | None = Field(None, ge=0)
    payment_term_days: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=500)
    status: SalesOrderStatus | None = None


class SalesOrderResponseSchema(BaseModel):
    """Response Sales Order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    so_number: str
    so_date: date
    customer_id: UUID
    customer_name: str | None = None
    customer_code: str | None = None
    total_amount: Decimal
    shipped_amount: Decimal
    invoiced_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: SalesOrderStatus
    expected_ship_date: date | None
    actual_ship_date: date | None
    shipping_term_days: int
    payment_term_days: int
    incoterm: Incoterm
    order_type: OrderType
    reference_number: str | None
    notes: str | None
    lines: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    rejected_at: datetime | None = None
    rejected_by: UUID | None = None
    rejection_reason: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    closed_at: datetime | None = None
    is_locked: bool = False
    version: int = 1


# ---- GOODS RECEIPT NOTE ----


class GRNLineSchema(BaseModel):
    """Line dalam Goods Receipt Note."""

    model_config = ConfigDict(from_attributes=True)

    purchase_order_line_id: UUID = Field(..., description="PO line ID")
    item_id: UUID = Field(..., description="Item ID")
    quantity_received: Decimal = Field(
        ..., gt=0, decimal_places=2, description="Kuantitas diterima"
    )
    quantity_accepted: Decimal | None = Field(
        None, gt=0, decimal_places=2, description="Kuantitas diterima (good)"
    )
    quantity_rejected: Decimal = Field(0, ge=0, decimal_places=2, description="Kuantitas ditolak")
    rejection_reason: str | None = Field(None, max_length=500, description="Alasan penolakan")
    batch_number: str | None = Field(None, max_length=50, description="Batch number")
    expiry_date: date | None = Field(None, description="Tanggal kadaluarsa")

    @model_validator(mode="after")
    def validate_quantities(self) -> GRNLineSchema:
        if self.quantity_accepted is not None:
            if self.quantity_accepted + self.quantity_rejected != self.quantity_received:
                raise ValueError("Accepted + rejected must equal received quantity")
        return self


class GoodsReceiptCreateSchema(BaseModel):
    """Schema untuk membuat Goods Receipt Note."""

    model_config = ConfigDict(from_attributes=True)

    grn_number: str = Field(..., max_length=50, description="Nomor GRN")
    grn_date: date = Field(default_factory=date.today, description="Tanggal GRN")
    purchase_order_id: UUID = Field(..., description="PO ID")
    lines: list[GRNLineSchema] = Field(..., min_length=1, description="Line items")
    warehouse_id: UUID = Field(..., description="Gudang penerimaan")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("grn_number")
    @classmethod
    def validate_grn_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("GRN number is required")
        return v.strip()


class GoodsReceiptResponseSchema(BaseModel):
    """Response Goods Receipt Note."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    grn_number: str
    grn_date: date
    purchase_order_id: UUID
    po_number: str | None = None
    supplier_id: UUID
    supplier_name: str | None = None
    warehouse_id: UUID
    warehouse_name: str | None = None
    status: GoodsReceiptStatus
    lines: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    confirmed_at: datetime | None = None
    confirmed_by: UUID | None = None
    posted_at: datetime | None = None
    version: int = 1


# ---- DELIVERY ORDER ----


class DOLineSchema(BaseModel):
    """Line dalam Delivery Order."""

    model_config = ConfigDict(from_attributes=True)

    sales_order_line_id: UUID = Field(..., description="SO line ID")
    item_id: UUID = Field(..., description="Item ID")
    quantity_shipped: Decimal = Field(..., gt=0, decimal_places=2, description="Kuantitas dikirim")
    batch_number: str | None = Field(None, max_length=50, description="Batch number")
    serial_numbers: list[str] | None = Field(None, description="Serial numbers")


class DeliveryOrderCreateSchema(BaseModel):
    """Schema untuk membuat Delivery Order."""

    model_config = ConfigDict(from_attributes=True)

    do_number: str = Field(..., max_length=50, description="Nomor DO")
    do_date: date = Field(default_factory=date.today, description="Tanggal DO")
    sales_order_id: UUID = Field(..., description="SO ID")
    warehouse_id: UUID = Field(..., description="Gudang asal")
    shipping_address: str | None = Field(None, max_length=500, description="Alamat pengiriman")
    tracking_number: str | None = Field(None, max_length=50, description="Nomor tracking")
    carrier: str | None = Field(None, max_length=100, description="Kurir")
    lines: list[DOLineSchema] = Field(..., min_length=1, description="Line items")
    notes: str | None = Field(None, max_length=500, description="Catatan")

    @field_validator("do_number")
    @classmethod
    def validate_do_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DO number is required")
        return v.strip()


class DeliveryOrderResponseSchema(BaseModel):
    """Response Delivery Order."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    do_number: str
    do_date: date
    sales_order_id: UUID
    so_number: str | None = None
    customer_id: UUID
    customer_name: str | None = None
    warehouse_id: UUID
    warehouse_name: str | None = None
    shipping_address: str | None
    tracking_number: str | None
    carrier: str | None
    status: DeliveryOrderStatus
    lines: list[dict[str, Any]]
    notes: str | None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    confirmed_at: datetime | None = None
    confirmed_by: UUID | None = None
    shipped_at: datetime | None = None
    delivered_at: datetime | None = None
    version: int = 1


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_purchase_sales_service(request: Request) -> Any:
    """Get Purchase Sales Service instance."""
    from application.service_layer.service_purchase_sales import PurchaseSalesService

    container = request.app.state.container
    return await container.resolve_async(PurchaseSalesService)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/purchase-sales", tags=["Purchase & Sales"])


# ----------------------------------------------------------------------------
# PURCHASE ORDER CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/purchase-orders",
    response_model=PurchaseOrderResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Purchase Order",
    operation_id="create_purchase_order",
)
async def create_purchase_order(
    request: PurchaseOrderCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("purchase:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Create a new Purchase Order."""
    method_name = "create_purchase_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PurchaseOrderResponseSchema(**cached)

    try:
        result = await service.create_purchase_order(
            po_number=request.po_number,
            po_date=request.po_date,
            supplier_id=request.supplier_id,
            lines=[line.dict() for line in request.lines],
            expected_delivery_date=request.expected_delivery_date,
            delivery_term_days=request.delivery_term_days,
            payment_term_days=request.payment_term_days,
            incoterm=request.incoterm.value,
            order_type=request.order_type.value,
            reference_number=request.reference_number,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/purchase-orders/{po_id}",
    response_model=PurchaseOrderResponseSchema,
    summary="Get Purchase Order by ID",
    operation_id="get_purchase_order",
)
async def get_purchase_order(
    po_id: UUID,
    _permission: None = Depends(require_permission("purchase:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Get Purchase Order by ID."""
    try:
        po = await service.get_purchase_order_by_id(po_id, legal_entity_id)

        if not po:
            raise HTTPException(status_code=404, detail="Purchase order not found")

        return PurchaseOrderResponseSchema(
            id=po.id,
            po_number=po.po_number,
            po_date=po.po_date,
            supplier_id=po.supplier_id,
            supplier_name=po.supplier_name,
            supplier_code=po.supplier_code,
            total_amount=po.total_amount,
            received_amount=po.received_amount,
            invoiced_amount=po.invoiced_amount,
            paid_amount=po.paid_amount,
            outstanding_amount=po.outstanding_amount,
            status=PurchaseOrderStatus(po.status),
            expected_delivery_date=po.expected_delivery_date,
            actual_delivery_date=po.actual_delivery_date,
            delivery_term_days=po.delivery_term_days,
            payment_term_days=po.payment_term_days,
            incoterm=Incoterm(po.incoterm),
            order_type=OrderType(po.order_type),
            reference_number=po.reference_number,
            notes=po.notes,
            lines=po.lines,
            created_at=po.created_at,
            updated_at=po.updated_at,
            created_by=po.created_by,
            created_by_name=po.created_by_name,
            approved_at=po.approved_at,
            approved_by=po.approved_by,
            approved_by_name=po.approved_by_name,
            rejected_at=po.rejected_at,
            rejected_by=po.rejected_by,
            rejection_reason=po.rejection_reason,
            cancelled_at=po.cancelled_at,
            cancelled_by=po.cancelled_by,
            closed_at=po.closed_at,
            is_locked=po.is_locked,
            version=po.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/purchase-orders/by-number/{po_number}",
    response_model=PurchaseOrderResponseSchema,
    summary="Get Purchase Order by PO number",
    operation_id="get_purchase_order_by_number",
)
async def get_purchase_order_by_number(
    po_number: str,
    _permission: None = Depends(require_permission("purchase:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Get Purchase Order by PO number."""
    try:
        po = await service.get_purchase_order_by_number(po_number, legal_entity_id)

        if not po:
            raise HTTPException(
                status_code=404,
                detail=f"Purchase order {po_number} not found",
            )

        return PurchaseOrderResponseSchema(
            id=po.id,
            po_number=po.po_number,
            po_date=po.po_date,
            supplier_id=po.supplier_id,
            supplier_name=po.supplier_name,
            supplier_code=po.supplier_code,
            total_amount=po.total_amount,
            received_amount=po.received_amount,
            invoiced_amount=po.invoiced_amount,
            paid_amount=po.paid_amount,
            outstanding_amount=po.outstanding_amount,
            status=PurchaseOrderStatus(po.status),
            expected_delivery_date=po.expected_delivery_date,
            actual_delivery_date=po.actual_delivery_date,
            delivery_term_days=po.delivery_term_days,
            payment_term_days=po.payment_term_days,
            incoterm=Incoterm(po.incoterm),
            order_type=OrderType(po.order_type),
            reference_number=po.reference_number,
            notes=po.notes,
            lines=po.lines,
            created_at=po.created_at,
            updated_at=po.updated_at,
            created_by=po.created_by,
            created_by_name=po.created_by_name,
            approved_at=po.approved_at,
            approved_by=po.approved_by,
            approved_by_name=po.approved_by_name,
            rejected_at=po.rejected_at,
            rejected_by=po.rejected_by,
            rejection_reason=po.rejection_reason,
            cancelled_at=po.cancelled_at,
            cancelled_by=po.cancelled_by,
            closed_at=po.closed_at,
            is_locked=po.is_locked,
            version=po.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get purchase order by number: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/purchase-orders",
    response_model=list[PurchaseOrderResponseSchema],
    summary="List Purchase Orders",
    operation_id="list_purchase_orders",
)
async def list_purchase_orders(
    supplier_id: UUID | None = Query(None, description="Filter by supplier"),
    status: PurchaseOrderStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("purchase:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> list[PurchaseOrderResponseSchema]:
    """List Purchase Orders with pagination and filters."""
    try:
        result = await service.list_purchase_orders(
            legal_entity_id=legal_entity_id,
            supplier_id=supplier_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            PurchaseOrderResponseSchema(
                id=po.id,
                po_number=po.po_number,
                po_date=po.po_date,
                supplier_id=po.supplier_id,
                supplier_name=po.supplier_name,
                supplier_code=po.supplier_code,
                total_amount=po.total_amount,
                received_amount=po.received_amount,
                invoiced_amount=po.invoiced_amount,
                paid_amount=po.paid_amount,
                outstanding_amount=po.outstanding_amount,
                status=PurchaseOrderStatus(po.status),
                expected_delivery_date=po.expected_delivery_date,
                actual_delivery_date=po.actual_delivery_date,
                delivery_term_days=po.delivery_term_days,
                payment_term_days=po.payment_term_days,
                incoterm=Incoterm(po.incoterm),
                order_type=OrderType(po.order_type),
                reference_number=po.reference_number,
                notes=po.notes,
                lines=po.lines,
                created_at=po.created_at,
                updated_at=po.updated_at,
                created_by=po.created_by,
                created_by_name=po.created_by_name,
                approved_at=po.approved_at,
                approved_by=po.approved_by,
                approved_by_name=po.approved_by_name,
                rejected_at=po.rejected_at,
                rejected_by=po.rejected_by,
                rejection_reason=po.rejection_reason,
                cancelled_at=po.cancelled_at,
                cancelled_by=po.cancelled_by,
                closed_at=po.closed_at,
                is_locked=po.is_locked,
                version=po.version,
            )
            for po in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list purchase orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/purchase-orders/{po_id}",
    response_model=PurchaseOrderResponseSchema,
    summary="Update Purchase Order",
    operation_id="update_purchase_order",
)
async def update_purchase_order(
    po_id: UUID,
    request: PurchaseOrderUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("purchase:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Update Purchase Order (only DRAFT or REJECTED status)."""
    method_name = "update_purchase_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PurchaseOrderResponseSchema(**cached)

    try:
        result = await service.update_purchase_order(
            po_id=po_id,
            expected_delivery_date=request.expected_delivery_date,
            delivery_term_days=request.delivery_term_days,
            payment_term_days=request.payment_term_days,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be updated"
            )

        response = PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PURCHASE ORDER WORKFLOW
# ----------------------------------------------------------------------------


@router.post(
    "/purchase-orders/{po_id}/submit",
    response_model=PurchaseOrderResponseSchema,
    summary="Submit Purchase Order for approval",
    operation_id="submit_purchase_order",
)
async def submit_purchase_order(
    po_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("purchase:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Submit Purchase Order for approval workflow."""
    method_name = "submit_purchase_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return PurchaseOrderResponseSchema(**cached)

    try:
        result = await service.submit_purchase_order(po_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be submitted"
            )

        response = PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/purchase-orders/{po_id}/approve",
    response_model=PurchaseOrderResponseSchema,
    summary="Approve Purchase Order",
    operation_id="approve_purchase_order",
)
async def approve_purchase_order(
    po_id: UUID,
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("purchase:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Approve a submitted Purchase Order."""
    try:
        result = await service.approve_purchase_order(
            po_id, current_user.user_id, legal_entity_id, notes
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be approved"
            )

        return PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/purchase-orders/{po_id}/reject",
    response_model=PurchaseOrderResponseSchema,
    summary="Reject Purchase Order",
    operation_id="reject_purchase_order",
)
async def reject_purchase_order(
    po_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    _permission: None = Depends(require_permission("purchase:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Reject a submitted Purchase Order."""
    try:
        result = await service.reject_purchase_order(
            po_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be rejected"
            )

        return PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reject purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/purchase-orders/{po_id}",
    response_model=dict[str, Any],
    summary="Cancel Purchase Order",
    operation_id="cancel_purchase_order",
)
async def cancel_purchase_order(
    po_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("purchase:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> dict[str, Any]:
    """Cancel a Purchase Order (only DRAFT or APPROVED)."""
    try:
        result = await service.cancel_purchase_order(
            po_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be cancelled"
            )

        return {
            "po_id": str(po_id),
            "po_number": result.po_number,
            "status": result.status,
            "message": "Purchase order cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/purchase-orders/{po_id}/close",
    response_model=PurchaseOrderResponseSchema,
    summary="Close Purchase Order",
    operation_id="close_purchase_order",
)
async def close_purchase_order(
    po_id: UUID,
    _permission: None = Depends(require_permission("purchase:close")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> PurchaseOrderResponseSchema:
    """Close a fully received Purchase Order."""
    try:
        result = await service.close_purchase_order(po_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(
                status_code=404, detail="Purchase order not found or cannot be closed"
            )

        return PurchaseOrderResponseSchema(
            id=result.id,
            po_number=result.po_number,
            po_date=result.po_date,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            supplier_code=result.supplier_code,
            total_amount=result.total_amount,
            received_amount=result.received_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=PurchaseOrderStatus(result.status),
            expected_delivery_date=result.expected_delivery_date,
            actual_delivery_date=result.actual_delivery_date,
            delivery_term_days=result.delivery_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close purchase order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SALES ORDER CRUD
# ----------------------------------------------------------------------------


@router.post(
    "/sales-orders",
    response_model=SalesOrderResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Sales Order",
    operation_id="create_sales_order",
)
async def create_sales_order(
    request: SalesOrderCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("sales:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Create a new Sales Order."""
    method_name = "create_sales_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SalesOrderResponseSchema(**cached)

    try:
        result = await service.create_sales_order(
            so_number=request.so_number,
            so_date=request.so_date,
            customer_id=request.customer_id,
            lines=[line.dict() for line in request.lines],
            expected_ship_date=request.expected_ship_date,
            shipping_term_days=request.shipping_term_days,
            payment_term_days=request.payment_term_days,
            incoterm=request.incoterm.value,
            order_type=request.order_type.value,
            reference_number=request.reference_number,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sales-orders/{so_id}",
    response_model=SalesOrderResponseSchema,
    summary="Get Sales Order by ID",
    operation_id="get_sales_order",
)
async def get_sales_order(
    so_id: UUID,
    _permission: None = Depends(require_permission("sales:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Get Sales Order by ID."""
    try:
        so = await service.get_sales_order_by_id(so_id, legal_entity_id)

        if not so:
            raise HTTPException(status_code=404, detail="Sales order not found")

        return SalesOrderResponseSchema(
            id=so.id,
            so_number=so.so_number,
            so_date=so.so_date,
            customer_id=so.customer_id,
            customer_name=so.customer_name,
            customer_code=so.customer_code,
            total_amount=so.total_amount,
            shipped_amount=so.shipped_amount,
            invoiced_amount=so.invoiced_amount,
            paid_amount=so.paid_amount,
            outstanding_amount=so.outstanding_amount,
            status=SalesOrderStatus(so.status),
            expected_ship_date=so.expected_ship_date,
            actual_ship_date=so.actual_ship_date,
            shipping_term_days=so.shipping_term_days,
            payment_term_days=so.payment_term_days,
            incoterm=Incoterm(so.incoterm),
            order_type=OrderType(so.order_type),
            reference_number=so.reference_number,
            notes=so.notes,
            lines=so.lines,
            created_at=so.created_at,
            updated_at=so.updated_at,
            created_by=so.created_by,
            created_by_name=so.created_by_name,
            approved_at=so.approved_at,
            approved_by=so.approved_by,
            approved_by_name=so.approved_by_name,
            rejected_at=so.rejected_at,
            rejected_by=so.rejected_by,
            rejection_reason=so.rejection_reason,
            cancelled_at=so.cancelled_at,
            cancelled_by=so.cancelled_by,
            closed_at=so.closed_at,
            is_locked=so.is_locked,
            version=so.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sales-orders/by-number/{so_number}",
    response_model=SalesOrderResponseSchema,
    summary="Get Sales Order by SO number",
    operation_id="get_sales_order_by_number",
)
async def get_sales_order_by_number(
    so_number: str,
    _permission: None = Depends(require_permission("sales:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Get Sales Order by SO number."""
    try:
        so = await service.get_sales_order_by_number(so_number, legal_entity_id)

        if not so:
            raise HTTPException(
                status_code=404,
                detail=f"Sales order {so_number} not found",
            )

        return SalesOrderResponseSchema(
            id=so.id,
            so_number=so.so_number,
            so_date=so.so_date,
            customer_id=so.customer_id,
            customer_name=so.customer_name,
            customer_code=so.customer_code,
            total_amount=so.total_amount,
            shipped_amount=so.shipped_amount,
            invoiced_amount=so.invoiced_amount,
            paid_amount=so.paid_amount,
            outstanding_amount=so.outstanding_amount,
            status=SalesOrderStatus(so.status),
            expected_ship_date=so.expected_ship_date,
            actual_ship_date=so.actual_ship_date,
            shipping_term_days=so.shipping_term_days,
            payment_term_days=so.payment_term_days,
            incoterm=Incoterm(so.incoterm),
            order_type=OrderType(so.order_type),
            reference_number=so.reference_number,
            notes=so.notes,
            lines=so.lines,
            created_at=so.created_at,
            updated_at=so.updated_at,
            created_by=so.created_by,
            created_by_name=so.created_by_name,
            approved_at=so.approved_at,
            approved_by=so.approved_by,
            approved_by_name=so.approved_by_name,
            rejected_at=so.rejected_at,
            rejected_by=so.rejected_by,
            rejection_reason=so.rejection_reason,
            cancelled_at=so.cancelled_at,
            cancelled_by=so.cancelled_by,
            closed_at=so.closed_at,
            is_locked=so.is_locked,
            version=so.version,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get sales order by number: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sales-orders",
    response_model=list[SalesOrderResponseSchema],
    summary="List Sales Orders",
    operation_id="list_sales_orders",
)
async def list_sales_orders(
    customer_id: UUID | None = Query(None, description="Filter by customer"),
    status: SalesOrderStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Start date"),
    end_date: date | None = Query(None, description="End date"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("sales:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> list[SalesOrderResponseSchema]:
    """List Sales Orders with pagination and filters."""
    try:
        result = await service.list_sales_orders(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )

        return [
            SalesOrderResponseSchema(
                id=so.id,
                so_number=so.so_number,
                so_date=so.so_date,
                customer_id=so.customer_id,
                customer_name=so.customer_name,
                customer_code=so.customer_code,
                total_amount=so.total_amount,
                shipped_amount=so.shipped_amount,
                invoiced_amount=so.invoiced_amount,
                paid_amount=so.paid_amount,
                outstanding_amount=so.outstanding_amount,
                status=SalesOrderStatus(so.status),
                expected_ship_date=so.expected_ship_date,
                actual_ship_date=so.actual_ship_date,
                shipping_term_days=so.shipping_term_days,
                payment_term_days=so.payment_term_days,
                incoterm=Incoterm(so.incoterm),
                order_type=OrderType(so.order_type),
                reference_number=so.reference_number,
                notes=so.notes,
                lines=so.lines,
                created_at=so.created_at,
                updated_at=so.updated_at,
                created_by=so.created_by,
                created_by_name=so.created_by_name,
                approved_at=so.approved_at,
                approved_by=so.approved_by,
                approved_by_name=so.approved_by_name,
                rejected_at=so.rejected_at,
                rejected_by=so.rejected_by,
                rejection_reason=so.rejection_reason,
                cancelled_at=so.cancelled_at,
                cancelled_by=so.cancelled_by,
                closed_at=so.closed_at,
                is_locked=so.is_locked,
                version=so.version,
            )
            for so in result.items
        ]
    except Exception as e:
        logger.exception("Failed to list sales orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/sales-orders/{so_id}",
    response_model=SalesOrderResponseSchema,
    summary="Update Sales Order",
    operation_id="update_sales_order",
)
async def update_sales_order(
    so_id: UUID,
    request: SalesOrderUpdateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("sales:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Update Sales Order (only DRAFT or REJECTED status)."""
    method_name = "update_sales_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SalesOrderResponseSchema(**cached)

    try:
        result = await service.update_sales_order(
            so_id=so_id,
            expected_ship_date=request.expected_ship_date,
            shipping_term_days=request.shipping_term_days,
            payment_term_days=request.payment_term_days,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Sales order not found or cannot be updated"
            )

        response = SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# SALES ORDER WORKFLOW
# ----------------------------------------------------------------------------


@router.post(
    "/sales-orders/{so_id}/submit",
    response_model=SalesOrderResponseSchema,
    summary="Submit Sales Order for approval",
    operation_id="submit_sales_order",
)
async def submit_sales_order(
    so_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("sales:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Submit Sales Order for approval workflow."""
    method_name = "submit_sales_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return SalesOrderResponseSchema(**cached)

    try:
        result = await service.submit_sales_order(so_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(
                status_code=404, detail="Sales order not found or cannot be submitted"
            )

        response = SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/sales-orders/{so_id}/approve",
    response_model=SalesOrderResponseSchema,
    summary="Approve Sales Order",
    operation_id="approve_sales_order",
)
async def approve_sales_order(
    so_id: UUID,
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("sales:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Approve a submitted Sales Order."""
    try:
        result = await service.approve_sales_order(
            so_id, current_user.user_id, legal_entity_id, notes
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Sales order not found or cannot be approved"
            )

        return SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/sales-orders/{so_id}/reject",
    response_model=SalesOrderResponseSchema,
    summary="Reject Sales Order",
    operation_id="reject_sales_order",
)
async def reject_sales_order(
    so_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    _permission: None = Depends(require_permission("sales:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Reject a submitted Sales Order."""
    try:
        result = await service.reject_sales_order(
            so_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Sales order not found or cannot be rejected"
            )

        return SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reject sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/sales-orders/{so_id}",
    response_model=dict[str, Any],
    summary="Cancel Sales Order",
    operation_id="cancel_sales_order",
)
async def cancel_sales_order(
    so_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("sales:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> dict[str, Any]:
    """Cancel a Sales Order (only DRAFT or APPROVED)."""
    try:
        result = await service.cancel_sales_order(
            so_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Sales order not found or cannot be cancelled"
            )

        return {
            "so_id": str(so_id),
            "so_number": result.so_number,
            "status": result.status,
            "message": "Sales order cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/sales-orders/{so_id}/close",
    response_model=SalesOrderResponseSchema,
    summary="Close Sales Order",
    operation_id="close_sales_order",
)
async def close_sales_order(
    so_id: UUID,
    _permission: None = Depends(require_permission("sales:close")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> SalesOrderResponseSchema:
    """Close a fully shipped and paid Sales Order."""
    try:
        result = await service.close_sales_order(so_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Sales order not found or cannot be closed")

        return SalesOrderResponseSchema(
            id=result.id,
            so_number=result.so_number,
            so_date=result.so_date,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            total_amount=result.total_amount,
            shipped_amount=result.shipped_amount,
            invoiced_amount=result.invoiced_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            status=SalesOrderStatus(result.status),
            expected_ship_date=result.expected_ship_date,
            actual_ship_date=result.actual_ship_date,
            shipping_term_days=result.shipping_term_days,
            payment_term_days=result.payment_term_days,
            incoterm=Incoterm(result.incoterm),
            order_type=OrderType(result.order_type),
            reference_number=result.reference_number,
            notes=result.notes,
            lines=result.lines,
            created_at=result.created_at,
            updated_at=result.updated_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            approved_by_name=result.approved_by_name,
            rejected_at=result.rejected_at,
            rejected_by=result.rejected_by,
            rejection_reason=result.rejection_reason,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            closed_at=result.closed_at,
            is_locked=result.is_locked,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to close sales order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# GOODS RECEIPT NOTE
# ----------------------------------------------------------------------------


@router.post(
    "/goods-receipt",
    response_model=GoodsReceiptResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Goods Receipt Note",
    operation_id="create_goods_receipt",
)
async def create_goods_receipt(
    request: GoodsReceiptCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("purchase:receive")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> GoodsReceiptResponseSchema:
    """Create a Goods Receipt Note for a Purchase Order."""
    method_name = "create_goods_receipt"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return GoodsReceiptResponseSchema(**cached)

    try:
        result = await service.create_goods_receipt_note(
            grn_number=request.grn_number,
            grn_date=request.grn_date,
            purchase_order_id=request.purchase_order_id,
            lines=[line.dict() for line in request.lines],
            warehouse_id=request.warehouse_id,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = GoodsReceiptResponseSchema(
            id=result.id,
            grn_number=result.grn_number,
            grn_date=result.grn_date,
            purchase_order_id=result.purchase_order_id,
            po_number=result.po_number,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            status=GoodsReceiptStatus(result.status),
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            confirmed_at=result.confirmed_at,
            confirmed_by=result.confirmed_by,
            posted_at=result.posted_at,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create goods receipt: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/goods-receipt/{grn_id}/confirm",
    response_model=GoodsReceiptResponseSchema,
    summary="Confirm Goods Receipt Note",
    operation_id="confirm_goods_receipt",
)
async def confirm_goods_receipt(
    grn_id: UUID,
    _permission: None = Depends(require_permission("purchase:receive")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> GoodsReceiptResponseSchema:
    """Confirm a Goods Receipt Note (updates inventory)."""
    try:
        result = await service.confirm_goods_receipt_note(
            grn_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Goods receipt not found")

        return GoodsReceiptResponseSchema(
            id=result.id,
            grn_number=result.grn_number,
            grn_date=result.grn_date,
            purchase_order_id=result.purchase_order_id,
            po_number=result.po_number,
            supplier_id=result.supplier_id,
            supplier_name=result.supplier_name,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            status=GoodsReceiptStatus(result.status),
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            confirmed_at=result.confirmed_at,
            confirmed_by=result.confirmed_by,
            posted_at=result.posted_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to confirm goods receipt: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/goods-receipt/{grn_id}",
    response_model=dict[str, Any],
    summary="Cancel Goods Receipt Note",
    operation_id="cancel_goods_receipt",
)
async def cancel_goods_receipt(
    grn_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("purchase:cancel")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> dict[str, Any]:
    """Cancel a Goods Receipt Note (only DRAFT status)."""
    try:
        result = await service.cancel_goods_receipt_note(
            grn_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(
                status_code=404, detail="Goods receipt not found or cannot be cancelled"
            )

        return {
            "grn_id": str(grn_id),
            "grn_number": result.grn_number,
            "status": result.status,
            "message": "Goods receipt cancelled",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to cancel goods receipt: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DELIVERY ORDER
# ----------------------------------------------------------------------------


@router.post(
    "/delivery-orders",
    response_model=DeliveryOrderResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create Delivery Order",
    operation_id="create_delivery_order",
)
async def create_delivery_order(
    request: DeliveryOrderCreateSchema,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    _permission: None = Depends(require_permission("sales:deliver")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> DeliveryOrderResponseSchema:
    """Create a Delivery Order for a Sales Order."""
    method_name = "create_delivery_order"
    if idempotency_key:
        cached = _idempotency_manager.get_cached_result(idempotency_key, method_name)
        if cached is not None:
            logger.info(f"Idempotent cache hit: {method_name} key={idempotency_key[:8]}...")
            return DeliveryOrderResponseSchema(**cached)

    try:
        result = await service.create_delivery_order(
            do_number=request.do_number,
            do_date=request.do_date,
            sales_order_id=request.sales_order_id,
            warehouse_id=request.warehouse_id,
            shipping_address=request.shipping_address,
            tracking_number=request.tracking_number,
            carrier=request.carrier,
            lines=[line.dict() for line in request.lines],
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        response = DeliveryOrderResponseSchema(
            id=result.id,
            do_number=result.do_number,
            do_date=result.do_date,
            sales_order_id=result.sales_order_id,
            so_number=result.so_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            shipping_address=result.shipping_address,
            tracking_number=result.tracking_number,
            carrier=result.carrier,
            status=DeliveryOrderStatus(result.status),
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            confirmed_at=result.confirmed_at,
            confirmed_by=result.confirmed_by,
            shipped_at=result.shipped_at,
            delivered_at=result.delivered_at,
            version=result.version,
        )

        if idempotency_key:
            _idempotency_manager.cache_result(idempotency_key, method_name, response.model_dump())

        return response
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create delivery order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/delivery-orders/{do_id}/confirm",
    response_model=DeliveryOrderResponseSchema,
    summary="Confirm Delivery Order",
    operation_id="confirm_delivery_order",
)
async def confirm_delivery_order(
    do_id: UUID,
    _permission: None = Depends(require_permission("sales:deliver")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> DeliveryOrderResponseSchema:
    """Confirm a Delivery Order (reserve inventory)."""
    try:
        result = await service.confirm_delivery_order(do_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Delivery order not found")

        return DeliveryOrderResponseSchema(
            id=result.id,
            do_number=result.do_number,
            do_date=result.do_date,
            sales_order_id=result.sales_order_id,
            so_number=result.so_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            shipping_address=result.shipping_address,
            tracking_number=result.tracking_number,
            carrier=result.carrier,
            status=DeliveryOrderStatus(result.status),
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            confirmed_at=result.confirmed_at,
            confirmed_by=result.confirmed_by,
            shipped_at=result.shipped_at,
            delivered_at=result.delivered_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to confirm delivery order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/delivery-orders/{do_id}/ship",
    response_model=DeliveryOrderResponseSchema,
    summary="Mark as Shipped",
    operation_id="ship_delivery_order",
)
async def ship_delivery_order(
    do_id: UUID,
    tracking_number: str | None = Query(None, description="Tracking number"),
    _permission: None = Depends(require_permission("sales:deliver")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> DeliveryOrderResponseSchema:
    """Mark Delivery Order as Shipped."""
    try:
        result = await service.ship_delivery_order(
            do_id=do_id,
            tracking_number=tracking_number,
            shipped_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Delivery order not found")

        return DeliveryOrderResponseSchema(
            id=result.id,
            do_number=result.do_number,
            do_date=result.do_date,
            sales_order_id=result.sales_order_id,
            so_number=result.so_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            warehouse_id=result.warehouse_id,
            warehouse_name=result.warehouse_name,
            shipping_address=result.shipping_address,
            tracking_number=result.tracking_number,
            carrier=result.carrier,
            status=DeliveryOrderStatus(result.status),
            lines=result.lines,
            notes=result.notes,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            confirmed_at=result.confirmed_at,
            confirmed_by=result.confirmed_by,
            shipped_at=result.shipped_at,
            delivered_at=result.delivered_at,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to ship delivery order: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# ORDER STATUS & HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/purchase-orders/{po_id}/status",
    response_model=dict[str, Any],
    summary="Get Purchase Order status",
    operation_id="get_purchase_order_status",
)
async def get_purchase_order_status(
    po_id: UUID,
    _permission: None = Depends(require_permission("purchase:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> dict[str, Any]:
    """Get detailed Purchase Order status including workflow state."""
    try:
        status_info = await service.get_purchase_order_status(po_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Purchase order not found")

        return {
            "po_id": str(po_id),
            "po_number": status_info.po_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_submit": status_info.can_submit,
            "can_approve": status_info.can_approve,
            "can_reject": status_info.can_reject,
            "can_cancel": status_info.can_cancel,
            "can_close": status_info.can_close,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "submitted_at": status_info.submitted_at.isoformat()
            if status_info.submitted_at
            else None,
            "approved_at": status_info.approved_at.isoformat() if status_info.approved_at else None,
            "received_percent": status_info.received_percent,
            "invoiced_percent": status_info.invoiced_percent,
            "paid_percent": status_info.paid_percent,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get purchase order status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sales-orders/{so_id}/status",
    response_model=dict[str, Any],
    summary="Get Sales Order status",
    operation_id="get_sales_order_status",
)
async def get_sales_order_status(
    so_id: UUID,
    _permission: None = Depends(require_permission("sales:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> dict[str, Any]:
    """Get detailed Sales Order status including workflow state."""
    try:
        status_info = await service.get_sales_order_status(so_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Sales order not found")

        return {
            "so_id": str(so_id),
            "so_number": status_info.so_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_submit": status_info.can_submit,
            "can_approve": status_info.can_approve,
            "can_reject": status_info.can_reject,
            "can_cancel": status_info.can_cancel,
            "can_close": status_info.can_close,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "submitted_at": status_info.submitted_at.isoformat()
            if status_info.submitted_at
            else None,
            "approved_at": status_info.approved_at.isoformat() if status_info.approved_at else None,
            "shipped_percent": status_info.shipped_percent,
            "invoiced_percent": status_info.invoiced_percent,
            "paid_percent": status_info.paid_percent,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get sales order status: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/purchase-orders/{po_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get Purchase Order history",
    operation_id="get_purchase_order_history",
)
async def get_purchase_order_history(
    po_id: UUID,
    _permission: None = Depends(require_permission("purchase:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> list[dict[str, Any]]:
    """Get Purchase Order change history (audit trail)."""
    try:
        history = await service.get_purchase_order_history(po_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "from_status": h.from_status,
                "to_status": h.to_status,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
                "notes": h.notes,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get purchase order history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/sales-orders/{so_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get Sales Order history",
    operation_id="get_sales_order_history",
)
async def get_sales_order_history(
    so_id: UUID,
    _permission: None = Depends(require_permission("sales:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> list[dict[str, Any]]:
    """Get Sales Order change history (audit trail)."""
    try:
        history = await service.get_sales_order_history(so_id, legal_entity_id)

        return [
            {
                "timestamp": h.timestamp.isoformat(),
                "action": h.action,
                "from_status": h.from_status,
                "to_status": h.to_status,
                "actor_id": str(h.actor_id),
                "actor_name": h.actor_name,
                "reason": h.reason,
                "notes": h.notes,
            }
            for h in history
        ]
    except Exception as e:
        logger.exception("Failed to get sales order history: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------


@router.get(
    "/export/purchase-orders",
    summary="Export Purchase Orders",
    operation_id="export_purchase_orders",
)
async def export_purchase_orders(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: PurchaseOrderStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("purchase:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> Response:
    """Export Purchase Orders to CSV or Excel."""
    try:
        data = await service.export_purchase_orders(
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
        filename = f"purchase_orders_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export purchase orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/export/sales-orders",
    summary="Export Sales Orders",
    operation_id="export_sales_orders",
)
async def export_sales_orders(
    start_date: date = Query(..., description="Start date"),
    end_date: date = Query(..., description="End date"),
    format: str = Query("csv", pattern="^(csv|excel)$", description="Export format"),
    status: SalesOrderStatus | None = Query(None, description="Filter by status"),
    _permission: None = Depends(require_permission("sales:export")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    service: Any = Depends(get_purchase_sales_service),
) -> Response:
    """Export Sales Orders to CSV or Excel."""
    try:
        data = await service.export_sales_orders(
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
        filename = f"sales_orders_{legal_entity_id}_{start_date}_{end_date}.{format}"

        return Response(
            content=data,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception("Failed to export sales orders: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]
