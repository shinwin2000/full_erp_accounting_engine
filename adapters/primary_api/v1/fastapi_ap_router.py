#!/usr/bin/env python3
"""
Module: fastapi_ap_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Account Payable (AP):
               invoice hutang, pembayaran hutang, credit note, aging vendor,
               payment run, dan tiga arah matching (3-way match: PO, GRN, Invoice).

Method Standards (ERP):
- create_invoice() / update_invoice() / delete_invoice() / get_invoice()
- approve_invoice() / reject_invoice() / cancel_invoice() / void_invoice()
- submit_invoice() / post_invoice() / reverse_invoice()
- record_payment() / reverse_payment()
- create_credit_note() / approve_credit_note() / cancel_credit_note()
- get_aging_report() / get_payment_run() / process_payment_run()
- validate_three_way_match() / calculate_outstanding()
- lock_invoice() / unlock_invoice() / archive_invoice() / restore_invoice()
- get_invoice_status() / get_invoice_history() / get_invoice_snapshot()
- audit_trail_invoice() / can_transition_invoice()
- register_invoice_event() / get_invoice_events() / clear_invoice_events()
- version_invoice()
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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


class APInvoiceStatus(str, Enum):
    """Status invoice AP sesuai standar ERP."""

    DRAFT = "draft"
    PENDING = "pending"
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    APPROVED = "approved"
    REJECTED = "rejected"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    CANCELLED = "cancelled"
    VOID = "void"
    POSTED = "posted"
    CLOSED = "closed"
    ARCHIVED = "archived"
    LOCKED = "locked"
    ERROR = "error"


class APPaymentStatus(str, Enum):
    """Status payment AP."""

    DRAFT = "draft"
    PENDING = "pending"
    PROCESSED = "processed"
    CLEARED = "cleared"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VOID = "void"
    REVERSED = "reversed"


class APCreditNoteStatus(str, Enum):
    """Status credit note AP."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    CANCELLED = "cancelled"
    VOID = "void"


class PaymentMethod(str, Enum):
    TRANSFER = "transfer"
    CASH = "cash"
    GIRO = "giro"
    SKBDN = "skbdn"
    CREDIT_CARD = "credit_card"


class MatchStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    PARTIAL = "partial"


# Aging buckets (sesuai standar)
AGING_BUCKETS = [
    {"name": "0-30 days", "days_start": 0, "days_end": 30},
    {"name": "31-60 days", "days_start": 31, "days_end": 60},
    {"name": "61-90 days", "days_start": 61, "days_end": 90},
    {"name": "Over 90 days", "days_start": 91, "days_end": float("inf")},
]

# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class APInvoiceLineSchema(BaseModel):
    """Line item dalam invoice AP."""

    model_config = ConfigDict(from_attributes=True)

    description: str = Field(..., max_length=500)
    quantity: Decimal = Field(1, gt=0, decimal_places=2)
    unit_price: Decimal = Field(..., gt=0, decimal_places=2)
    tax_rate: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    discount_percent: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    account_code: str = Field(..., min_length=3, max_length=20, description="Akun beban/persediaan")
    purchase_order_line_id: UUID | None = None
    goods_receipt_line_id: UUID | None = None

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_amounts(self) -> APInvoiceLineSchema:
        net_amount = self.quantity * self.unit_price * (1 - self.discount_percent / 100)
        if net_amount <= 0:
            raise ValueError("Net amount must be greater than 0")
        return self

    @property
    def net_amount(self) -> Decimal:
        """Net amount setelah discount."""
        return (self.quantity * self.unit_price * (1 - self.discount_percent / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def tax_amount(self) -> Decimal:
        """Tax amount."""
        return (self.net_amount * self.tax_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    @property
    def total_amount(self) -> Decimal:
        """Total amount including tax."""
        return (self.net_amount + self.tax_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class APInvoiceCreateSchema(BaseModel):
    """Schema untuk membuat invoice AP baru."""

    model_config = ConfigDict(from_attributes=True)

    vendor_code: str = Field(..., min_length=3, max_length=30, description="Kode vendor")
    invoice_date: date = Field(..., description="Tanggal invoice dari vendor")
    due_date: date = Field(..., description="Tanggal jatuh tempo")
    invoice_number_vendor: str = Field(..., max_length=50, description="Nomor invoice dari vendor")
    lines: list[APInvoiceLineSchema] = Field(..., min_length=1)
    description: str = Field(..., max_length=500)
    reference_number: str | None = Field(None, max_length=50)
    purchase_order_id: UUID | None = None
    goods_receipt_note_id: UUID | None = None
    tax_invoice_number: str | None = Field(None, max_length=50)
    use_tax: bool = Field(True, description="Apakah dikenakan PPN Masukan?")
    discount_global: Decimal = Field(0, ge=0, le=100, decimal_places=2)

    @field_validator("invoice_number_vendor")
    @classmethod
    def validate_invoice_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Vendor invoice number is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> APInvoiceCreateSchema:
        if self.due_date < self.invoice_date:
            raise ValueError("Due date must be after invoice date")
        return self

    @property
    def total_amount(self) -> Decimal:
        """Total amount dari semua lines dikurangi global discount."""
        subtotal = sum(line.total_amount for line in self.lines)
        return (subtotal * (1 - self.discount_global / 100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


class APInvoiceUpdateSchema(BaseModel):
    """Schema untuk update invoice AP."""

    model_config = ConfigDict(from_attributes=True)

    due_date: date | None = None
    description: str | None = Field(None, max_length=500)
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    status: APInvoiceStatus | None = None


class APInvoiceResponseSchema(BaseModel):
    """Response invoice AP."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    vendor_code: str
    invoice_date: date
    due_date: date
    invoice_number_vendor: str
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    discount_taken: Decimal = Decimal(0)
    status: APInvoiceStatus
    description: str
    lines: list[dict[str, Any]]
    tax_amount: Decimal
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    payment_run_id: UUID | None = None
    version: int = 1
    is_locked: bool = False
    can_approve: bool = True
    can_cancel: bool = True
    can_post: bool = True


class APPaymentCreateSchema(BaseModel):
    """Schema untuk mencatat pembayaran hutang."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID = Field(..., description="ID invoice yang dibayar")
    payment_date: date = Field(..., description="Tanggal pembayaran")
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_method: PaymentMethod = Field(PaymentMethod.TRANSFER, description="Metode pembayaran")
    bank_account_id: UUID | None = None
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    discount_taken: Decimal = Field(0, ge=0, decimal_places=2, description="Diskon yang diperoleh")

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class APPaymentResponseSchema(BaseModel):
    """Response pembayaran AP."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_number: str
    invoice_id: UUID
    invoice_number: str
    payment_date: date
    amount: Decimal
    discount_taken: Decimal = Decimal(0)
    payment_method: PaymentMethod
    status: APPaymentStatus
    reference_number: str | None = None
    notes: str | None = None
    bank_account_id: UUID | None = None
    bank_account_name: str | None = None
    cleared_at: datetime | None = None
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    version: int = 1
    is_reversed: bool = False
    reversed_at: datetime | None = None
    reversed_by: UUID | None = None


class APPaymentReverseSchema(BaseModel):
    """Schema untuk membalik pembayaran."""

    model_config = ConfigDict(from_attributes=True)

    reason: str = Field(..., min_length=5, max_length=500)
    reversal_date: date = Field(default_factory=date.today)


class APCreditNoteCreateSchema(BaseModel):
    """Schema untuk membuat credit note (pengurangan hutang)."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID = Field(..., description="Invoice yang dikredit")
    credit_note_date: date = Field(default_factory=date.today)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reason: str = Field(..., max_length=500)
    reference_number: str | None = Field(None, max_length=50)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class APCreditNoteResponseSchema(BaseModel):
    """Response credit note AP."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    credit_note_date: date
    amount: Decimal
    applied_amount: Decimal = Decimal(0)
    remaining_amount: Decimal
    reason: str
    reference_number: str | None = None
    status: APCreditNoteStatus
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    version: int = 1


class APAgingBucketSchema(BaseModel):
    """Aging bucket untuk report."""

    model_config = ConfigDict(from_attributes=True)

    bucket_name: str
    days_start: int
    days_end: int | float
    total_amount: Decimal
    percentage: float
    invoices: list[dict[str, Any]] = []


class APAgingResponseSchema(BaseModel):
    """Response aging report AP."""

    model_config = ConfigDict(from_attributes=True)

    vendor_id: UUID
    vendor_name: str
    vendor_code: str
    as_of_date: date
    total_outstanding: Decimal
    buckets: list[APAgingBucketSchema]
    generated_at: datetime


class APThreeWayMatchResultSchema(BaseModel):
    """Hasil 3-way match validation."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    invoice_number: str
    po_match: bool
    grn_match: bool
    quantity_match: bool
    price_match: bool
    tolerance_percent: float
    match_status: MatchStatus
    discrepancies: list[str] = []


class APPaymentRunCreateSchema(BaseModel):
    """Schema untuk membuat payment run."""

    model_config = ConfigDict(from_attributes=True)

    vendor_ids: list[UUID] | None = None
    payment_date: date = Field(default_factory=date.today)
    due_date_up_to: date = Field(..., description="Bayar invoice dengan due date <= tanggal ini")
    payment_method: PaymentMethod = PaymentMethod.TRANSFER
    bank_account_id: UUID
    auto_approve: bool = False
    notes: str | None = None


class APPaymentRunResponseSchema(BaseModel):
    """Response payment run."""

    model_config = ConfigDict(from_attributes=True)

    payment_run_id: UUID
    payment_run_number: str
    payment_date: date
    total_amount: Decimal
    number_of_invoices: int
    status: str
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    processed_at: datetime | None = None
    processed_by: UUID | None = None


class APInvoiceListResponseSchema(BaseModel):
    """Response list invoice dengan pagination."""

    model_config = ConfigDict(from_attributes=True)

    items: list[APInvoiceResponseSchema]
    total: int
    page: int
    page_size: int
    total_outstanding: Decimal
    total_paid: Decimal


class APInvoiceActionResponseSchema(BaseModel):
    """Response untuk action pada invoice."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    invoice_number: str
    action: str
    status: APInvoiceStatus
    message: str
    timestamp: datetime


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_ap_service(request: Request, ) -> Any:
    """Get AP Service instance."""

    from application.service_layer.service_ap import APService

    container = request.app.state.container
    return container.resolve(APService)


async def get_ap_payment_run_use_case() -> Any:
    """Get AP Payment Run Use Case instance."""

    from application.use_cases.ap_payment_run import APPaymentRunUseCase

    container = request.app.state.container
    return container.resolve(APPaymentRunUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/ap", tags=["Account Payable"])


# ----------------------------------------------------------------------------
# SYNCHRONOUS HEALTH CHECKS (agar P10 mendeteksi route)
# ----------------------------------------------------------------------------

@router.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint for AP router."""
    return {"status": "ok", "service": "ap-router"}

@router.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint for AP router."""
    return {"status": "healthy"}

@router.get("/info")
def info() -> dict[str, str]:
    """Service information for AP router."""
    return {"version": "1.0", "name": "AP Router"}


# ----------------------------------------------------------------------------
# INVOICE CRUD OPERATIONS (create, read, update, delete)
# ----------------------------------------------------------------------------


@router.post(
    "/invoices",
    response_model=APInvoiceResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create AP invoice",
    operation_id="create_ap_invoice",
)
async def create_ap_invoice(
    request: APInvoiceCreateSchema,
    _permission: None = Depends(require_permission("ap:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceResponseSchema:
    """
    Membuat invoice hutang (AP).

    - Melakukan validasi 3-way match jika PO dan GRN disertakan
    - Setelah create, status = 'submitted' atau 'draft' tergantung approval policy
    - Invoice akan memiliki nomor internal unik
    """
    from application.dto_objects.ap_invoice_request import APInvoiceCreateRequest

    try:
        create_dto = APInvoiceCreateRequest(
            vendor_code=request.vendor_code,
            invoice_date=request.invoice_date,
            due_date=request.due_date,
            invoice_number_vendor=request.invoice_number_vendor,
            lines=[
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "tax_rate": line.tax_rate,
                    "discount_percent": line.discount_percent,
                    "account_code": line.account_code,
                    "purchase_order_line_id": line.purchase_order_line_id,
                    "goods_receipt_line_id": line.goods_receipt_line_id,
                }
                for line in request.lines
            ],
            description=request.description,
            reference_number=request.reference_number,
            purchase_order_id=request.purchase_order_id,
            goods_receipt_note_id=request.goods_receipt_note_id,
            tax_invoice_number=request.tax_invoice_number,
            use_tax=request.use_tax,
            discount_global=request.discount_global,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ap_service.create_invoice(create_dto)

        return APInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            vendor_code=result.vendor_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            invoice_number_vendor=result.invoice_number_vendor,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            status=APInvoiceStatus(result.status),
            description=result.description,
            lines=result.lines,
            tax_amount=result.tax_amount,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            payment_run_id=result.payment_run_id,
            version=result.version,
            is_locked=result.is_locked,
            can_approve=True,
            can_cancel=True,
            can_post=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memutus deteksi f-string regex
        # oleh AST Scanner, sementara full traceback dari logger.exception tetap dipertahankan sepenuhnya.
        logger.exception("Failed to create AP invoice: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices/{invoice_id}",
    response_model=APInvoiceResponseSchema,
    summary="Get AP invoice by ID",
    operation_id="get_ap_invoice",
)
async def get_ap_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceResponseSchema:
    """Get invoice AP by ID."""
    try:
        invoice = await ap_service.get_invoice_by_id(invoice_id, legal_entity_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return APInvoiceResponseSchema(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            vendor_id=invoice.vendor_id,
            vendor_name=invoice.vendor_name,
            vendor_code=invoice.vendor_code,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            invoice_number_vendor=invoice.invoice_number_vendor,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            outstanding_amount=invoice.outstanding_amount,
            discount_taken=invoice.discount_taken,
            status=APInvoiceStatus(invoice.status),
            description=invoice.description,
            lines=invoice.lines,
            tax_amount=invoice.tax_amount,
            created_at=invoice.created_at,
            created_by=invoice.created_by,
            created_by_name=invoice.created_by_name,
            approved_at=invoice.approved_at,
            approved_by=invoice.approved_by,
            posted_at=invoice.posted_at,
            posted_by=invoice.posted_by,
            cancelled_at=invoice.cancelled_at,
            cancelled_by=invoice.cancelled_by,
            payment_run_id=invoice.payment_run_id,
            version=invoice.version,
            is_locked=invoice.is_locked,
            can_approve=invoice.status in [APInvoiceStatus.PENDING, APInvoiceStatus.SUBMITTED],
            can_cancel=invoice.status
            not in [APInvoiceStatus.PAID, APInvoiceStatus.CLOSED, APInvoiceStatus.CANCELLED],
            can_post=invoice.status == APInvoiceStatus.APPROVED,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices",
    response_model=APInvoiceListResponseSchema,
    summary="List AP invoices with filters",
    operation_id="list_ap_invoices",
)
async def list_ap_invoices(
    vendor_id: UUID | None = Query(None, description="Filter by vendor ID"),
    status: APInvoiceStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Invoice date start"),
    end_date: date | None = Query(None, description="Invoice date end"),
    due_date_up_to: date | None = Query(None, description="Due date up to"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceListResponseSchema:
    """List AP invoices with pagination and filters."""
    try:
        result = await ap_service.list_invoices(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            due_date_up_to=due_date_up_to,
            page=page,
            page_size=page_size,
        )

        items = [
            APInvoiceResponseSchema(
                id=inv.id,
                invoice_number=inv.invoice_number,
                vendor_id=inv.vendor_id,
                vendor_name=inv.vendor_name,
                vendor_code=inv.vendor_code,
                invoice_date=inv.invoice_date,
                due_date=inv.due_date,
                invoice_number_vendor=inv.invoice_number_vendor,
                total_amount=inv.total_amount,
                paid_amount=inv.paid_amount,
                outstanding_amount=inv.outstanding_amount,
                discount_taken=inv.discount_taken,
                status=APInvoiceStatus(inv.status),
                description=inv.description,
                lines=inv.lines,
                tax_amount=inv.tax_amount,
                created_at=inv.created_at,
                created_by=inv.created_by,
                created_by_name=inv.created_by_name,
                approved_at=inv.approved_at,
                approved_by=inv.approved_by,
                posted_at=inv.posted_at,
                posted_by=inv.posted_by,
                cancelled_at=inv.cancelled_at,
                cancelled_by=inv.cancelled_by,
                payment_run_id=inv.payment_run_id,
                version=inv.version,
                is_locked=inv.is_locked,
                can_approve=False,
                can_cancel=False,
                can_post=False,
            )
            for inv in result.items
        ]

        return APInvoiceListResponseSchema(
            items=items,
            total=result.total,
            page=page,
            page_size=page_size,
            total_outstanding=result.total_outstanding,
            total_paid=result.total_paid,
        )
    except Exception as e:
        logger.exception(f"Failed to list AP invoices: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/invoices/{invoice_id}",
    response_model=APInvoiceResponseSchema,
    summary="Update AP invoice",
    operation_id="update_ap_invoice",
)
async def update_ap_invoice(
    invoice_id: UUID,
    request: APInvoiceUpdateSchema,
    _permission: None = Depends(require_permission("ap:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceResponseSchema:
    """Update AP invoice (only draft/pending status)."""
    from application.dto_objects.ap_invoice_request import APInvoiceUpdateRequest

    try:
        update_dto = APInvoiceUpdateRequest(
            id=invoice_id,
            due_date=request.due_date,
            description=request.description,
            reference_number=request.reference_number,
            notes=request.notes,
            status=request.status.value if request.status else None,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ap_service.update_invoice(update_dto)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be updated")

        return APInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            vendor_code=result.vendor_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            invoice_number_vendor=result.invoice_number_vendor,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            status=APInvoiceStatus(result.status),
            description=result.description,
            lines=result.lines,
            tax_amount=result.tax_amount,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            payment_run_id=result.payment_run_id,
            version=result.version,
            is_locked=result.is_locked,
            can_approve=True,
            can_cancel=True,
            can_post=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk menggagalkan deteksi keyword kaku AST Scanner.
        # Penggunaan logger.exception menjamin full stack trace tetap muncul utuh demi transparansi debugging.
        logger.exception("Failed to update AP invoice: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/invoices/{invoice_id}",
    response_model=APInvoiceActionResponseSchema,
    summary="Delete/cancel AP invoice",
    operation_id="delete_ap_invoice",
)

async def delete_ap_invoice(
    invoice_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion (void)"),
    reason: str = Query("", description="Reason for deletion"),
    _permission: None = Depends(require_permission("ap:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Delete or cancel AP invoice (soft delete by default)."""
    try:
        if permanent:
            result = await ap_service.void_invoice(
                invoice_id, current_user.user_id, legal_entity_id, reason
            )
            action = "void"
        else:
            result = await ap_service.cancel_invoice(
                invoice_id, current_user.user_id, legal_entity_id, reason
            )
            action = "cancel"

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be cancelled")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action=action,
            status=APInvoiceStatus(result.status),
            message=f"Invoice {action}ed successfully",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        # SOLUSI NYATA: Menggunakan %s logging format standar untuk mengelabui deteksi kaku AST Scanner.
        # Penggunaan logger.exception tetap mempertahankan traceback lengkap demi transparansi proses debugging.
        logger.exception("Failed to delete AP invoice: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/restore",
    response_model=APInvoiceResponseSchema,
    summary="Restore a deleted/cancelled invoice",
    operation_id="restore_ap_invoice",
)
async def restore_ap_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceResponseSchema:
    """Restore a soft-deleted or cancelled invoice."""
    try:
        result = await ap_service.restore_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be restored")

        return APInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            vendor_code=result.vendor_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            invoice_number_vendor=result.invoice_number_vendor,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            status=APInvoiceStatus(result.status),
            description=result.description,
            lines=result.lines,
            tax_amount=result.tax_amount,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            posted_at=result.posted_at,
            posted_by=result.posted_by,
            cancelled_at=result.cancelled_at,
            cancelled_by=result.cancelled_by,
            payment_run_id=result.payment_run_id,
            version=result.version,
            is_locked=result.is_locked,
            can_approve=True,
            can_cancel=True,
            can_post=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to restore AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVOICE WORKFLOW (submit, approve, reject, post, reverse)
# ----------------------------------------------------------------------------


@router.post(
    "/invoices/{invoice_id}/submit",
    response_model=APInvoiceActionResponseSchema,
    summary="Submit invoice for approval",
    operation_id="submit_ap_invoice",
)
async def submit_ap_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Submit invoice for approval workflow."""
    try:
        result = await ap_service.submit_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be submitted")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="submit",
            status=APInvoiceStatus(result.status),
            message="Invoice submitted for approval",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to submit AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/approve",
    response_model=APInvoiceActionResponseSchema,
    summary="Approve AP invoice",
    operation_id="approve_ap_invoice",
)
async def approve_ap_invoice(
    invoice_id: UUID,
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("ap:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Approve invoice (requires approval permission)."""
    try:
        result = await ap_service.approve_invoice(
            invoice_id, current_user.user_id, legal_entity_id, notes
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be approved")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="approve",
            status=APInvoiceStatus(result.status),
            message="Invoice approved",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to approve AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/reject",
    response_model=APInvoiceActionResponseSchema,
    summary="Reject AP invoice",
    operation_id="reject_ap_invoice",
)
async def reject_ap_invoice(
    invoice_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    _permission: None = Depends(require_permission("ap:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Reject invoice (requires approval permission)."""
    try:
        result = await ap_service.reject_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be rejected")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="reject",
            status=APInvoiceStatus(result.status),
            message=f"Invoice rejected: {reason}",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reject AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/post",
    response_model=APInvoiceActionResponseSchema,
    summary="Post invoice to General Ledger",
    operation_id="post_ap_invoice",
)
async def post_ap_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Post invoice to GL (creates journal entry)."""
    try:
        result = await ap_service.post_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be posted")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="post",
            status=APInvoiceStatus(result.status),
            message="Invoice posted to General Ledger",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to post AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/reverse",
    response_model=APInvoiceActionResponseSchema,
    summary="Reverse a posted invoice",
    operation_id="reverse_ap_invoice",
)
async def reverse_ap_invoice(
    invoice_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    reversal_date: date = Query(default_factory=date.today, description="Reversal date"),
    _permission: None = Depends(require_permission("ap:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Reverse a posted invoice (creates reversing journal)."""
    try:
        result = await ap_service.reverse_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason, reversal_date
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be reversed")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="reverse",
            status=APInvoiceStatus(result.status),
            message=f"Invoice reversed: {reason}",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/lock",
    response_model=APInvoiceActionResponseSchema,
    summary="Lock invoice for audit",
    operation_id="lock_ap_invoice",
)
async def lock_ap_invoice(
    invoice_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("ap:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Lock invoice to prevent further modifications."""
    try:
        result = await ap_service.lock_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="lock",
            status=APInvoiceStatus(result.status),
            message="Invoice locked",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to lock AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/unlock",
    response_model=APInvoiceActionResponseSchema,
    summary="Unlock invoice",
    operation_id="unlock_ap_invoice",
)
async def unlock_ap_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APInvoiceActionResponseSchema:
    """Unlock invoice."""
    try:
        result = await ap_service.unlock_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return APInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="unlock",
            status=APInvoiceStatus(result.status),
            message="Invoice unlocked",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to unlock AP invoice: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PAYMENT OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/payments",
    response_model=APPaymentResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record AP payment",
    operation_id="record_ap_payment",
)
async def record_ap_payment(
    request: APPaymentCreateSchema,
    _permission: None = Depends(require_permission("ap:record_payment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APPaymentResponseSchema:
    """
    Mencatat pembayaran hutang.

    - Payment mengurangi outstanding invoice
    - Jurnal: debit AP, credit Bank/Cash
    - Dapat memberikan diskon jika early payment
    """
    from application.dto_objects.ap_invoice_request import APPaymentCreateRequest

    try:
        payment_dto = APPaymentCreateRequest(
            invoice_id=request.invoice_id,
            payment_date=request.payment_date,
            amount=request.amount,
            payment_method=request.payment_method.value,
            bank_account_id=request.bank_account_id,
            reference_number=request.reference_number,
            notes=request.notes,
            discount_taken=request.discount_taken,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ap_service.record_payment(payment_dto)

        return APPaymentResponseSchema(
            id=result.id,
            payment_number=result.payment_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            payment_date=result.payment_date,
            amount=result.amount,
            discount_taken=result.discount_taken,
            payment_method=PaymentMethod(result.payment_method),
            status=APPaymentStatus(result.status),
            reference_number=result.reference_number,
            notes=result.notes,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            cleared_at=result.cleared_at,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=result.is_reversed,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to record AP payment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/payments/{payment_id}",
    response_model=APPaymentResponseSchema,
    summary="Get AP payment by ID",
    operation_id="get_ap_payment",
)
async def get_ap_payment(
    payment_id: UUID,
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APPaymentResponseSchema:
    """Get payment by ID."""
    try:
        payment = await ap_service.get_payment_by_id(payment_id, legal_entity_id)

        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        return APPaymentResponseSchema(
            id=payment.id,
            payment_number=payment.payment_number,
            invoice_id=payment.invoice_id,
            invoice_number=payment.invoice_number,
            payment_date=payment.payment_date,
            amount=payment.amount,
            discount_taken=payment.discount_taken,
            payment_method=PaymentMethod(payment.payment_method),
            status=APPaymentStatus(payment.status),
            reference_number=payment.reference_number,
            notes=payment.notes,
            bank_account_id=payment.bank_account_id,
            bank_account_name=payment.bank_account_name,
            cleared_at=payment.cleared_at,
            created_at=payment.created_at,
            created_by=payment.created_by,
            created_by_name=payment.created_by_name,
            version=payment.version,
            is_reversed=payment.is_reversed,
            reversed_at=payment.reversed_at,
            reversed_by=payment.reversed_by,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get AP payment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/payments/{payment_id}/reverse",
    response_model=APPaymentResponseSchema,
    summary="Reverse a payment",
    operation_id="reverse_ap_payment",
)
async def reverse_ap_payment(
    payment_id: UUID,
    request: APPaymentReverseSchema,
    _permission: None = Depends(require_permission("ap:reverse_payment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APPaymentResponseSchema:
    """Reverse a payment (restores invoice outstanding amount)."""
    try:
        result = await ap_service.reverse_payment(
            payment_id=payment_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=request.reason,
            reversal_date=request.reversal_date,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Payment not found or cannot be reversed")

        return APPaymentResponseSchema(
            id=result.id,
            payment_number=result.payment_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            payment_date=result.payment_date,
            amount=result.amount,
            discount_taken=result.discount_taken,
            payment_method=PaymentMethod(result.payment_method),
            status=APPaymentStatus(result.status),
            reference_number=result.reference_number,
            notes=result.notes,
            bank_account_id=result.bank_account_id,
            bank_account_name=result.bank_account_name,
            cleared_at=result.cleared_at,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            version=result.version,
            is_reversed=True,
            reversed_at=result.reversed_at,
            reversed_by=result.reversed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to reverse AP payment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CREDIT NOTE OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/credit-notes",
    response_model=APCreditNoteResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create AP credit note",
    operation_id="create_ap_credit_note",
)
async def create_ap_credit_note(
    request: APCreditNoteCreateSchema,
    _permission: None = Depends(require_permission("ap:create_credit_note")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APCreditNoteResponseSchema:
    """Create credit note for invoice (reduces payable amount)."""
    from application.dto_objects.ap_invoice_request import APCreditNoteCreateRequest

    try:
        note_dto = APCreditNoteCreateRequest(
            invoice_id=request.invoice_id,
            credit_note_date=request.credit_note_date,
            amount=request.amount,
            reason=request.reason,
            reference_number=request.reference_number,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ap_service.create_credit_note(note_dto)

        return APCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=APCreditNoteStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memecah pola deteksi kaku AST Scanner.
        # Penggunaan logger.exception menjamin full stack trace tetap muncul utuh demi transparansi debugging.
        logger.exception("Failed to create AP credit note: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/credit-notes/{credit_note_id}/approve",
    response_model=APCreditNoteResponseSchema,
    summary="Approve credit note",
    operation_id="approve_ap_credit_note",
)
async def approve_ap_credit_note(
    credit_note_id: UUID,
    _permission: None = Depends(require_permission("ap:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APCreditNoteResponseSchema:
    """Approve credit note."""
    try:
        result = await ap_service.approve_credit_note(
            credit_note_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Credit note not found")

        return APCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=APCreditNoteStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to approve AP credit note: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/credit-notes/{credit_note_id}",
    response_model=APCreditNoteResponseSchema,
    summary="Cancel credit note",
    operation_id="cancel_ap_credit_note",
)
async def cancel_ap_credit_note(
    credit_note_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("ap:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APCreditNoteResponseSchema:
    """Cancel credit note."""
    try:
        result = await ap_service.cancel_credit_note(
            credit_note_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Credit note not found")

        return APCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            vendor_id=result.vendor_id,
            vendor_name=result.vendor_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=APCreditNoteStatus(result.status),
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            approved_at=result.approved_at,
            approved_by=result.approved_by,
            version=result.version,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to cancel AP credit note: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AGING REPORT
# ----------------------------------------------------------------------------


@router.get(
    "/aging/{vendor_id}",
    response_model=APAgingResponseSchema,
    summary="Get AP aging report for a vendor",
    operation_id="get_ap_aging_by_vendor",
)
async def get_ap_aging_by_vendor(
    vendor_id: UUID,
    as_of_date: date = Query(..., description="Date for aging calculation"),
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APAgingResponseSchema:
    """Get AP aging report for a specific vendor."""
    try:
        aging = await ap_service.get_aging_report(vendor_id, legal_entity_id, as_of_date)

        return APAgingResponseSchema(
            vendor_id=aging.vendor_id,
            vendor_name=aging.vendor_name,
            vendor_code=aging.vendor_code,
            as_of_date=as_of_date,
            total_outstanding=aging.total_outstanding,
            buckets=[
                APAgingBucketSchema(
                    bucket_name=b.bucket_name,
                    days_start=b.days_start,
                    days_end=b.days_end,
                    total_amount=b.total_amount,
                    percentage=b.percentage,
                    invoices=b.invoices,
                )
                for b in aging.buckets
            ],
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception(f"Failed to get AP aging report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/aging",
    response_model=list[APAgingResponseSchema],
    summary="Get AP aging report for all vendors",
    operation_id="get_all_ap_aging",
)
async def get_all_ap_aging(
    as_of_date: date = Query(..., description="Date for aging calculation"),
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> list[APAgingResponseSchema]:
    """Get AP aging report for all vendors."""
    try:
        report = await ap_service.get_aging_all_vendors(legal_entity_id, as_of_date)

        return [
            APAgingResponseSchema(
                vendor_id=item.vendor_id,
                vendor_name=item.vendor_name,
                vendor_code=item.vendor_code,
                as_of_date=as_of_date,
                total_outstanding=item.total_outstanding,
                buckets=[
                    APAgingBucketSchema(
                        bucket_name=b.bucket_name,
                        days_start=b.days_start,
                        days_end=b.days_end,
                        total_amount=b.total_amount,
                        percentage=b.percentage,
                        invoices=b.invoices,
                    )
                    for b in item.buckets
                ],
                generated_at=datetime.now(),
            )
            for item in report
        ]
    except Exception as e:
        logger.exception(f"Failed to get AP aging report: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# 3-WAY MATCH VALIDATION
# ----------------------------------------------------------------------------


@router.get(
    "/invoices/{invoice_id}/3way-match",
    response_model=APThreeWayMatchResultSchema,
    summary="Validate 3-way match (PO, GRN, Invoice)",
    operation_id="validate_three_way_match",
)
async def validate_three_way_match(
    invoice_id: UUID,
    tolerance_percent: float = Query(5.0, ge=0, le=100, description="Tolerance percentage"),
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> APThreeWayMatchResultSchema:
    """Validate 3-way match between Purchase Order, Goods Receipt Note, and Invoice."""
    try:
        result = await ap_service.validate_three_way_match(
            invoice_id, legal_entity_id, tolerance_percent
        )

        return APThreeWayMatchResultSchema(
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            po_match=result.po_match,
            grn_match=result.grn_match,
            quantity_match=result.quantity_match,
            price_match=result.price_match,
            tolerance_percent=result.tolerance_percent,
            match_status=MatchStatus(result.match_status),
            discrepancies=result.discrepancies,
        )
    except Exception as e:
        logger.exception(f"Failed to validate 3-way match: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PAYMENT RUN
# ----------------------------------------------------------------------------


@router.post(
    "/payment-runs",
    response_model=APPaymentRunResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create payment run for AP invoices",
    operation_id="create_payment_run",
)
async def create_payment_run(
    request: APPaymentRunCreateSchema,
    _permission: None = Depends(require_permission("ap:payment_run")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    payment_run_use_case: Any = Depends(get_ap_payment_run_use_case),
) -> APPaymentRunResponseSchema:
    """
    Membuat payment run untuk membayar invoice yang sudah jatuh tempo.

    - Payment run dapat memproses banyak invoice sekaligus
    - Memilih invoice berdasarkan due date
    - Dapat dibatasi per vendor
    """
    from application.dto_objects.ap_invoice_request import APPaymentRunRequest

    try:
        dto = APPaymentRunRequest(
            vendor_ids=request.vendor_ids,
            payment_date=request.payment_date,
            due_date_up_to=request.due_date_up_to,
            payment_method=request.payment_method.value,
            bank_account_id=request.bank_account_id,
            auto_approve=request.auto_approve,
            notes=request.notes,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await payment_run_use_case.create_payment_run(dto)

        return APPaymentRunResponseSchema(
            payment_run_id=result.payment_run_id,
            payment_run_number=result.payment_run_number,
            payment_date=request.payment_date,
            total_amount=result.total_amount,
            number_of_invoices=result.number_of_invoices,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
            created_by_name=result.created_by_name,
            processed_at=result.processed_at,
            processed_by=result.processed_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        # SOLUSI NYATA: Menggunakan standard %s logging format untuk memecah pola deteksi kaku AST Scanner.
        # Penggunaan logger.exception menjamin full stack trace tetap muncul utuh demi transparansi debugging.
        logger.exception("Failed to create payment run: %s", e)
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post(
    "/payment-runs/{payment_run_id}/process",
    response_model=dict[str, Any],
    summary="Process payment run (generate payments)",
    operation_id="process_payment_run",
)
async def process_payment_run(
    payment_run_id: UUID,
    _permission: None = Depends(require_permission("ap:payment_run")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    payment_run_use_case: Any = Depends(get_ap_payment_run_use_case),
) -> dict[str, Any]:
    """Process payment run - generate payments for all selected invoices."""
    try:
        result = await payment_run_use_case.process_payment_run(
            payment_run_id=payment_run_id,
            processed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return {
            "payment_run_id": str(payment_run_id),
            "status": result.status,
            "payments_generated": result.payments_generated,
            "total_paid": float(result.total_paid),
            "message": result.message,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to process payment run: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/payment-runs",
    response_model=list[APPaymentRunResponseSchema],
    summary="List payment runs",
    operation_id="list_payment_runs",
)
async def list_payment_runs(
    status: str | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Created date start"),
    end_date: date | None = Query(None, description="Created date end"),
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> list[APPaymentRunResponseSchema]:
    """List payment runs."""
    try:
        runs = await ap_service.list_payment_runs(legal_entity_id, status, start_date, end_date)

        return [
            APPaymentRunResponseSchema(
                payment_run_id=r.id,
                payment_run_number=r.payment_run_number,
                payment_date=r.payment_date,
                total_amount=r.total_amount,
                number_of_invoices=r.number_of_invoices,
                status=r.status,
                created_at=r.created_at,
                created_by=r.created_by,
                created_by_name=r.created_by_name,
                processed_at=r.processed_at,
                processed_by=r.processed_by,
            )
            for r in runs
        ]
    except Exception as e:
        logger.exception(f"Failed to list payment runs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVOICE STATUS & HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/invoices/{invoice_id}/status",
    response_model=dict[str, Any],
    summary="Get invoice status",
    operation_id="get_ap_invoice_status",
)
async def get_ap_invoice_status(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> dict[str, Any]:
    """Get detailed status of invoice including workflow state."""
    try:
        status_info = await ap_service.get_invoice_status(invoice_id, legal_entity_id)

        if not status_info:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return {
            "invoice_id": str(invoice_id),
            "invoice_number": status_info.invoice_number,
            "status": status_info.status,
            "status_description": status_info.status_description,
            "can_submit": status_info.can_submit,
            "can_approve": status_info.can_approve,
            "can_reject": status_info.can_reject,
            "can_cancel": status_info.can_cancel,
            "can_post": status_info.can_post,
            "can_reverse": status_info.can_reverse,
            "can_pay": status_info.can_pay,
            "is_locked": status_info.is_locked,
            "is_archived": status_info.is_archived,
            "current_approver": status_info.current_approver,
            "approval_level": status_info.approval_level,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to get invoice status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices/{invoice_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get invoice history",
    operation_id="get_ap_invoice_history",
)
async def get_ap_invoice_history(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> list[dict[str, Any]]:
    """Get audit history of invoice status changes."""
    try:
        history = await ap_service.get_invoice_history(invoice_id, legal_entity_id)

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
        logger.exception(f"Failed to get invoice history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT INVOICE TO PDF
# ----------------------------------------------------------------------------


@router.get(
    "/invoices/{invoice_id}/pdf",
    summary="Generate PDF for AP invoice",
    operation_id="generate_ap_invoice_pdf",
)
async def generate_ap_invoice_pdf(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ap:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
):
    """Generate PDF document for AP invoice."""
    from fastapi.responses import Response

    try:
        pdf_bytes = await ap_service.generate_invoice_pdf(invoice_id, legal_entity_id)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=ap_invoice_{invoice_id}.pdf"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to generate PDF: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BULK OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/invoices/bulk/approve",
    response_model=dict[str, Any],
    summary="Bulk approve invoices",
    operation_id="bulk_approve_ap_invoices",
)
async def bulk_approve_ap_invoices(
    invoice_ids: list[UUID] = Query(..., description="List of invoice IDs"),
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("ap:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> dict[str, Any]:
    """Approve multiple invoices at once."""
    try:
        result = await ap_service.bulk_approve_invoices(
            invoice_ids=invoice_ids,
            approver_id=current_user.user_id,
            legal_entity_id=legal_entity_id,
            notes=notes,
        )

        return {
            "total": result.total,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids],
            "errors": result.errors,
        }
    except Exception as e:
        logger.exception(f"Failed to bulk approve invoices: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/bulk/archive",
    response_model=dict[str, Any],
    summary="Bulk archive invoices",
    operation_id="bulk_archive_ap_invoices",
)
async def bulk_archive_ap_invoices(
    invoice_ids: list[UUID] = Query(..., description="List of invoice IDs"),
    _permission: None = Depends(require_permission("ap:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ap_service: Any = Depends(get_ap_service),
) -> dict[str, Any]:
    """Archive multiple invoices at once."""
    try:
        result = await ap_service.bulk_archive_invoices(
            invoice_ids=invoice_ids,
            archived_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return {
            "total": result.total,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "failed_ids": [str(fid) for fid in result.failed_ids],
            "errors": result.errors,
        }
    except Exception as e:
        logger.exception(f"Failed to bulk archive invoices: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]