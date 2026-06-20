
#!/usr/bin/env python3
"""
Module: fastapi_ar_router.py
Layer: Adapters (Primary API - v1)
Responsibility: Menyediakan REST API endpoint untuk mengelola Account Receivable (AR):
               invoice penjualan, pembayaran piutang, credit note, aging customer,
               dashboard piutang, collection workflow.

Method Standards (ERP):
- create_invoice() / update_invoice() / delete_invoice() / get_invoice()
- approve_invoice() / reject_invoice() / cancel_invoice() / void_invoice()
- submit_invoice() / post_invoice() / reverse_invoice()
- record_payment() / reverse_payment()
- create_credit_note() / approve_credit_note() / cancel_credit_note()
- get_aging_report() / get_dashboard() / get_dso()
- start_collection() / send_reminder() / escalate_collection()
- calculate_outstanding() / calculate_dso()
- lock_invoice() / unlock_invoice() / archive_invoice() / restore_invoice()
- get_invoice_status() / get_invoice_history() / get_invoice_snapshot()
- audit_trail_invoice() / can_transition_invoice()
- register_invoice_event() / get_invoice_events() / clear_invoice_events()
- version_invoice()
"""


from __future__ import annotations
from fastapi import Request

import logging
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from adapters.dependency_provider import get_service
from fastapi import APIRouter, Depends, HTTPException, Query, status
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


class ARInvoiceStatus(str, Enum):
    """Status invoice AR sesuai standar ERP."""

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
    OVERDUE = "overdue"
    IN_COLLECTION = "in_collection"
    WRITTEN_OFF = "written_off"
    ERROR = "error"


class ARPaymentStatus(str, Enum):
    """Status payment AR."""

    DRAFT = "draft"
    PENDING = "pending"
    PROCESSED = "processed"
    CLEARED = "cleared"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    VOID = "void"
    REVERSED = "reversed"


class ARCreditNoteStatus(str, Enum):
    """Status credit note AR."""

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
    CREDIT_CARD = "credit_card"
    GIRO = "giro"
    DEBIT_CARD = "debit_card"


class CollectionStatus(str, Enum):
    NOT_STARTED = "not_started"
    REMINDER_SENT = "reminder_sent"
    ESCALATED = "escalated"
    LEGAL_ACTION = "legal_action"
    RESOLVED = "resolved"


# Aging buckets (sesuai standar)
AGING_BUCKETS = [
    {"name": "0-30 days", "days_start": 0, "days_end": 30},
    {"name": "31-60 days", "days_start": 31, "days_end": 60},
    {"name": "61-90 days", "days_start": 61, "days_end": 90},
    {"name": "Over 90 days", "days_start": 91, "days_end": float("inf")},
]

# DSO calculation constants
DSO_DAYS = 365  # Days per year for DSO calculation

# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================


class ARInvoiceLineSchema(BaseModel):
    """Line item dalam invoice AR."""

    model_config = ConfigDict(from_attributes=True)

    description: str = Field(..., max_length=500)
    quantity: Decimal = Field(1, gt=0, decimal_places=2)
    unit_price: Decimal = Field(..., gt=0, decimal_places=2)
    tax_rate: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    discount_percent: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    account_code: str = Field(
        ..., min_length=3, max_length=20, description="Akun pendapatan (misal: 4-1100)"
    )
    sales_order_line_id: UUID | None = None

    @field_validator("account_code")
    @classmethod
    def validate_account_code(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Account code is required")
        return v.upper()

    @model_validator(mode="after")
    def validate_amounts(self) -> ARInvoiceLineSchema:
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


class ARInvoiceCreateSchema(BaseModel):
    """Schema untuk membuat invoice AR baru."""

    model_config = ConfigDict(from_attributes=True)

    customer_code: str = Field(..., min_length=3, max_length=30, description="Kode customer")
    invoice_date: date = Field(..., description="Tanggal invoice")
    due_date: date = Field(..., description="Tanggal jatuh tempo")
    invoice_number: str = Field(..., max_length=50, description="Nomor invoice internal")
    lines: list[ARInvoiceLineSchema] = Field(..., min_length=1)
    description: str = Field(..., max_length=500)
    reference_number: str | None = Field(None, max_length=50)
    sales_order_id: UUID | None = None
    tax_invoice_number: str | None = Field(None, max_length=50)
    use_tax: bool = Field(True, description="Apakah dikenakan PPN Keluaran?")
    discount_global: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    early_payment_discount_percent: Decimal = Field(0, ge=0, le=100, decimal_places=2)
    early_payment_discount_days: int = Field(0, ge=0, description="Days for early payment discount")

    @field_validator("invoice_number")
    @classmethod
    def validate_invoice_number(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Invoice number is required")
        return v.strip()

    @model_validator(mode="after")
    def validate_dates(self) -> ARInvoiceCreateSchema:
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


class ARInvoiceUpdateSchema(BaseModel):
    """Schema untuk update invoice AR."""

    model_config = ConfigDict(from_attributes=True)

    due_date: date | None = None
    description: str | None = Field(None, max_length=500)
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    status: ARInvoiceStatus | None = None
    early_payment_discount_percent: Decimal | None = Field(None, ge=0, le=100, decimal_places=2)
    early_payment_discount_days: int | None = Field(None, ge=0)


class ARInvoiceResponseSchema(BaseModel):
    """Response invoice AR."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    customer_code: str
    invoice_date: date
    due_date: date
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    discount_taken: Decimal = Decimal(0)
    early_payment_discount_eligible: bool = False
    early_payment_discount_amount: Decimal = Decimal(0)
    status: ARInvoiceStatus
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
    collection_status: CollectionStatus = CollectionStatus.NOT_STARTED
    last_reminder_sent_at: datetime | None = None
    days_overdue: int = 0
    version: int = 1
    is_locked: bool = False
    can_approve: bool = True
    can_cancel: bool = True
    can_post: bool = True


class ARPaymentCreateSchema(BaseModel):
    """Schema untuk mencatat pembayaran piutang."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID = Field(..., description="ID invoice yang dibayar")
    payment_date: date = Field(..., description="Tanggal pembayaran")
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    payment_method: PaymentMethod = Field(PaymentMethod.TRANSFER, description="Metode pembayaran")
    bank_account_id: UUID | None = None
    reference_number: str | None = Field(None, max_length=50)
    notes: str | None = Field(None, max_length=500)
    discount_taken: Decimal = Field(0, ge=0, decimal_places=2, description="Diskon yang diperoleh")
    apply_early_payment_discount: bool = False

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class ARPaymentResponseSchema(BaseModel):
    """Response pembayaran AR."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_number: str
    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    payment_date: date
    amount: Decimal
    discount_taken: Decimal = Decimal(0)
    payment_method: PaymentMethod
    status: ARPaymentStatus
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


class ARPaymentReverseSchema(BaseModel):
    """Schema untuk membalik pembayaran."""

    model_config = ConfigDict(from_attributes=True)

    reason: str = Field(..., min_length=5, max_length=500)
    reversal_date: date = Field(default_factory=date.today)


class ARCreditNoteCreateSchema(BaseModel):
    """Schema untuk membuat credit note (pengurangan piutang)."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID = Field(..., description="Invoice yang dikredit")
    credit_note_date: date = Field(default_factory=date.today)
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    reason: str = Field(..., max_length=500)
    reference_number: str | None = Field(None, max_length=50)
    apply_to_future_invoices: bool = False

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("Amount must be greater than 0")
        return v


class ARCreditNoteResponseSchema(BaseModel):
    """Response credit note AR."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    credit_note_date: date
    amount: Decimal
    applied_amount: Decimal = Decimal(0)
    remaining_amount: Decimal
    reason: str
    reference_number: str | None = None
    status: ARCreditNoteStatus
    created_at: datetime
    created_by: UUID
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    version: int = 1


class ARAgingBucketSchema(BaseModel):
    """Aging bucket untuk report."""

    model_config = ConfigDict(from_attributes=True)

    bucket_name: str
    days_start: int
    days_end: int | float
    total_amount: Decimal
    percentage: float
    invoices: list[dict[str, Any]] = []
    allowance_amount: Decimal = Decimal(0)


class ARAgingResponseSchema(BaseModel):
    """Response aging report AR."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: UUID
    customer_name: str
    customer_code: str
    as_of_date: date
    total_outstanding: Decimal
    total_allowance: Decimal = Decimal(0)
    buckets: list[ARAgingBucketSchema]
    generated_at: datetime


class ARDashboardSchema(BaseModel):
    """Dashboard AR metrics."""

    model_config = ConfigDict(from_attributes=True)

    total_outstanding: Decimal
    current_outstanding: Decimal
    overdue_1_30: Decimal
    overdue_31_60: Decimal
    overdue_61_90: Decimal
    overdue_90_plus: Decimal
    overdue_amount: Decimal
    overdue_percentage: float
    dso_days: float
    collection_efficiency: float
    aging_buckets: list[ARAgingBucketSchema]
    as_of_date: date


class ARCollectionReminderSchema(BaseModel):
    """Schema untuk mengirim reminder collection."""

    model_config = ConfigDict(from_attributes=True)

    invoice_ids: list[UUID] | None = None
    reminder_type: str = Field("gentle", description="gentle, firm, final, legal")
    message: str | None = None
    send_email: bool = True
    send_sms: bool = False


class ARCollectionReminderResponseSchema(BaseModel):
    """Response collection reminder."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    reminders_sent: int
    invoices_processed: list[UUID]
    errors: list[dict[str, Any]] = []


class ARInvoiceListResponseSchema(BaseModel):
    """Response list invoice dengan pagination."""

    model_config = ConfigDict(from_attributes=True)

    items: list[ARInvoiceResponseSchema]
    total: int
    page: int
    page_size: int
    total_outstanding: Decimal
    total_paid: Decimal
    total_overdue: Decimal


class ARInvoiceActionResponseSchema(BaseModel):
    """Response untuk action pada invoice."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    invoice_number: str
    action: str
    status: ARInvoiceStatus
    message: str
    timestamp: datetime


class ARWriteOffSchema(BaseModel):
    """Schema untuk write-off piutang."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: UUID
    write_off_amount: Decimal = Field(..., gt=0, decimal_places=2)
    reason: str = Field(..., min_length=5, max_length=500)
    account_code: str = Field(
        ..., min_length=3, max_length=20, description="Akun beban piutang tak tertagih"
    )

    @field_validator("write_off_amount")
    @classmethod
    def validate_amount(cls, v: Decimal, info) -> Decimal:
        if v <= 0:
            raise ValueError("Write-off amount must be greater than 0")
        return v


class ARWriteOffResponseSchema(BaseModel):
    """Response write-off piutang."""

    model_config = ConfigDict(from_attributes=True)

    write_off_id: UUID
    invoice_id: UUID
    invoice_number: str
    write_off_amount: Decimal
    remaining_outstanding: Decimal
    journal_id: UUID
    status: str
    created_at: datetime
    created_by: UUID


# ============================================================================
# DEPENDENCY INJECTION
# ============================================================================


async def get_ar_service(request: Request, ) -> Any:
    """Get AR Service instance."""
    from application.service_layer.service_ar import ARService
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(ARService)


async def get_ar_collection_workflow() -> Any:
    """Get AR Collection Workflow Use Case instance."""
    from application.use_cases.ar_collection_workflow import ARCollectionWorkflowUseCase
    from fastapi import Request

    container = request.app.state.container
    return container.resolve(ARCollectionWorkflowUseCase)


# ============================================================================
# ROUTER
# ============================================================================

router = APIRouter(prefix="/ar", tags=["Accounts Receivable"])


# ----------------------------------------------------------------------------
# INVOICE CRUD OPERATIONS (create, read, update, delete)
# ----------------------------------------------------------------------------


@router.post(
    "/invoices",
    response_model=ARInvoiceResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create AR invoice",
    operation_id="create_ar_invoice",
)
async def create_ar_invoice(
    request: ARInvoiceCreateSchema,
    _permission: None = Depends(require_permission("ar:create")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceResponseSchema:
    """
    Membuat invoice piutang (AR).

    - Invoice bisa berasal dari sales order atau langsung
    - Setelah create, status = 'submitted' atau 'draft' tergantung approval policy
    - Invoice akan memiliki nomor internal unik
    - Dapat memberikan diskon early payment
    """
    from application.dto_objects.ar_invoice_request import ARInvoiceCreateRequest

    try:
        create_dto = ARInvoiceCreateRequest(
            customer_code=request.customer_code,
            invoice_date=request.invoice_date,
            due_date=request.due_date,
            invoice_number=request.invoice_number,
            lines=[
                {
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_price": line.unit_price,
                    "tax_rate": line.tax_rate,
                    "discount_percent": line.discount_percent,
                    "account_code": line.account_code,
                    "sales_order_line_id": line.sales_order_line_id,
                }
                for line in request.lines
            ],
            description=request.description,
            reference_number=request.reference_number,
            sales_order_id=request.sales_order_id,
            tax_invoice_number=request.tax_invoice_number,
            use_tax=request.use_tax,
            discount_global=request.discount_global,
            early_payment_discount_percent=request.early_payment_discount_percent,
            early_payment_discount_days=request.early_payment_discount_days,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ar_service.create_invoice(create_dto)

        # Calculate early payment discount eligibility
        early_discount_eligible = False
        early_discount_amount = Decimal(0)
        if request.early_payment_discount_percent > 0 and request.early_payment_discount_days > 0:
            today = date.today()
            if today <= request.invoice_date + timedelta(days=request.early_payment_discount_days):
                early_discount_eligible = True
                early_discount_amount = (
                    result.total_amount * request.early_payment_discount_percent / 100
                ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return ARInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            early_payment_discount_eligible=early_discount_eligible,
            early_payment_discount_amount=early_discount_amount,
            status=ARInvoiceStatus(result.status),
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
            collection_status=CollectionStatus.NOT_STARTED,
            last_reminder_sent_at=result.last_reminder_sent_at,
            days_overdue=max(0, (date.today() - request.due_date).days),
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
        logger.exception("Failed to create AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices/{invoice_id}",
    response_model=ARInvoiceResponseSchema,
    summary="Get AR invoice by ID",
    operation_id="get_ar_invoice",
)
async def get_ar_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceResponseSchema:
    """Get invoice AR by ID."""
    try:
        invoice = await ar_service.get_invoice_by_id(invoice_id, legal_entity_id)
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")

        # Calculate days overdue
        days_overdue = (
            max(0, (date.today() - invoice.due_date).days)
            if invoice.status not in [ARInvoiceStatus.PAID, ARInvoiceStatus.CANCELLED]
            else 0
        )

        return ARInvoiceResponseSchema(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            customer_id=invoice.customer_id,
            customer_name=invoice.customer_name,
            customer_code=invoice.customer_code,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            outstanding_amount=invoice.outstanding_amount,
            discount_taken=invoice.discount_taken,
            early_payment_discount_eligible=False,
            early_payment_discount_amount=Decimal(0),
            status=ARInvoiceStatus(invoice.status),
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
            collection_status=CollectionStatus(invoice.collection_status)
            if invoice.collection_status
            else CollectionStatus.NOT_STARTED,
            last_reminder_sent_at=invoice.last_reminder_sent_at,
            days_overdue=days_overdue,
            version=invoice.version,
            is_locked=invoice.is_locked,
            can_approve=invoice.status in [ARInvoiceStatus.PENDING, ARInvoiceStatus.SUBMITTED],
            can_cancel=invoice.status
            not in [ARInvoiceStatus.PAID, ARInvoiceStatus.CLOSED, ARInvoiceStatus.CANCELLED],
            can_post=invoice.status == ARInvoiceStatus.APPROVED,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices",
    response_model=ARInvoiceListResponseSchema,
    summary="List AR invoices with filters",
    operation_id="list_ar_invoices",
)
async def list_ar_invoices(
    customer_id: UUID | None = Query(None, description="Filter by customer ID"),
    status: ARInvoiceStatus | None = Query(None, description="Filter by status"),
    start_date: date | None = Query(None, description="Invoice date start"),
    end_date: date | None = Query(None, description="Invoice date end"),
    due_date_up_to: date | None = Query(None, description="Due date up to"),
    overdue_only: bool = Query(False, description="Show only overdue invoices"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceListResponseSchema:
    """List AR invoices with pagination and filters."""
    try:
        result = await ar_service.list_invoices(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status.value if status else None,
            start_date=start_date,
            end_date=end_date,
            due_date_up_to=due_date_up_to,
            overdue_only=overdue_only,
            page=page,
            page_size=page_size,
        )

        items = []
        for inv in result.items:
            days_overdue = (
                max(0, (date.today() - inv.due_date).days)
                if inv.status not in ["paid", "cancelled"]
                else 0
            )

            items.append(
                ARInvoiceResponseSchema(
                    id=inv.id,
                    invoice_number=inv.invoice_number,
                    customer_id=inv.customer_id,
                    customer_name=inv.customer_name,
                    customer_code=inv.customer_code,
                    invoice_date=inv.invoice_date,
                    due_date=inv.due_date,
                    total_amount=inv.total_amount,
                    paid_amount=inv.paid_amount,
                    outstanding_amount=inv.outstanding_amount,
                    discount_taken=inv.discount_taken,
                    early_payment_discount_eligible=False,
                    early_payment_discount_amount=Decimal(0),
                    status=ARInvoiceStatus(inv.status),
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
                    collection_status=CollectionStatus(inv.collection_status)
                    if inv.collection_status
                    else CollectionStatus.NOT_STARTED,
                    last_reminder_sent_at=inv.last_reminder_sent_at,
                    days_overdue=days_overdue,
                    version=inv.version,
                    is_locked=inv.is_locked,
                    can_approve=False,
                    can_cancel=False,
                    can_post=False,
                )
            )

        return ARInvoiceListResponseSchema(
            items=items,
            total=result.total,
            page=page,
            page_size=page_size,
            total_outstanding=result.total_outstanding,
            total_paid=result.total_paid,
            total_overdue=result.total_overdue,
        )
    except Exception as e:
        logger.exception("Failed to list AR invoices: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put(
    "/invoices/{invoice_id}",
    response_model=ARInvoiceResponseSchema,
    summary="Update AR invoice",
    operation_id="update_ar_invoice",
)
async def update_ar_invoice(
    invoice_id: UUID,
    request: ARInvoiceUpdateSchema,
    _permission: None = Depends(require_permission("ar:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceResponseSchema:
    """Update AR invoice (only draft/pending status)."""
    from application.dto_objects.ar_invoice_request import ARInvoiceUpdateRequest

    try:
        update_dto = ARInvoiceUpdateRequest(
            id=invoice_id,
            due_date=request.due_date,
            description=request.description,
            reference_number=request.reference_number,
            notes=request.notes,
            status=request.status.value if request.status else None,
            early_payment_discount_percent=request.early_payment_discount_percent,
            early_payment_discount_days=request.early_payment_discount_days,
            updated_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ar_service.update_invoice(update_dto)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be updated")

        days_overdue = (
            max(0, (date.today() - result.due_date).days)
            if result.status not in ["paid", "cancelled"]
            else 0
        )

        return ARInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            early_payment_discount_eligible=False,
            early_payment_discount_amount=Decimal(0),
            status=ARInvoiceStatus(result.status),
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
            collection_status=CollectionStatus(result.collection_status)
            if result.collection_status
            else CollectionStatus.NOT_STARTED,
            last_reminder_sent_at=result.last_reminder_sent_at,
            days_overdue=days_overdue,
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
        logger.exception("Failed to update AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/invoices/{invoice_id}",
    response_model=ARInvoiceActionResponseSchema,
    summary="Delete/cancel AR invoice",
    operation_id="delete_ar_invoice",
)
async def delete_ar_invoice(
    invoice_id: UUID,
    permanent: bool = Query(False, description="Permanent deletion (void)"),
    reason: str = Query("", description="Reason for deletion"),
    _permission: None = Depends(require_permission("ar:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Delete or cancel AR invoice (soft delete by default)."""
    try:
        if permanent:
            result = await ar_service.void_invoice(
                invoice_id, current_user.user_id, legal_entity_id, reason
            )
            action = "void"
        else:
            result = await ar_service.cancel_invoice(
                invoice_id, current_user.user_id, legal_entity_id, reason
            )
            action = "cancel"

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be cancelled")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action=action,
            status=ARInvoiceStatus(result.status),
            message="{}ed successfully".format(action),
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/restore",
    response_model=ARInvoiceResponseSchema,
    summary="Restore a deleted/cancelled invoice",
    operation_id="restore_ar_invoice",
)
async def restore_ar_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:update")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceResponseSchema:
    """Restore a soft-deleted or cancelled invoice."""
    try:
        result = await ar_service.restore_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be restored")

        days_overdue = (
            max(0, (date.today() - result.due_date).days)
            if result.status not in ["paid", "cancelled"]
            else 0
        )

        return ARInvoiceResponseSchema(
            id=result.id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            customer_code=result.customer_code,
            invoice_date=result.invoice_date,
            due_date=result.due_date,
            total_amount=result.total_amount,
            paid_amount=result.paid_amount,
            outstanding_amount=result.outstanding_amount,
            discount_taken=result.discount_taken,
            early_payment_discount_eligible=False,
            early_payment_discount_amount=Decimal(0),
            status=ARInvoiceStatus(result.status),
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
            collection_status=CollectionStatus(result.collection_status)
            if result.collection_status
            else CollectionStatus.NOT_STARTED,
            last_reminder_sent_at=result.last_reminder_sent_at,
            days_overdue=days_overdue,
            version=result.version,
            is_locked=result.is_locked,
            can_approve=True,
            can_cancel=True,
            can_post=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to restore AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVOICE WORKFLOW (submit, approve, reject, post, reverse)
# ----------------------------------------------------------------------------


@router.post(
    "/invoices/{invoice_id}/submit",
    response_model=ARInvoiceActionResponseSchema,
    summary="Submit invoice for approval",
    operation_id="submit_ar_invoice",
)
async def submit_ar_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:submit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Submit invoice for approval workflow."""
    try:
        result = await ar_service.submit_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be submitted")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="submit",
            status=ARInvoiceStatus(result.status),
            message="Invoice submitted for approval",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to submit AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/approve",
    response_model=ARInvoiceActionResponseSchema,
    summary="Approve AR invoice",
    operation_id="approve_ar_invoice",
)
async def approve_ar_invoice(
    invoice_id: UUID,
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("ar:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Approve invoice (requires approval permission)."""
    try:
        result = await ar_service.approve_invoice(
            invoice_id, current_user.user_id, legal_entity_id, notes
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be approved")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="approve",
            status=ARInvoiceStatus(result.status),
            message="Invoice approved",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("Failed to approve AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/reject",
    response_model=ARInvoiceActionResponseSchema,
    summary="Reject AR invoice",
    operation_id="reject_ar_invoice",
)
async def reject_ar_invoice(
    invoice_id: UUID,
    reason: str = Query(..., min_length=5, description="Rejection reason"),
    _permission: None = Depends(require_permission("ar:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Reject invoice (requires approval permission)."""
    try:
        result = await ar_service.reject_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be rejected")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="reject",
            status=ARInvoiceStatus(result.status),
            message="Invoice rejected: {}".format(reason),
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reject AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/post",
    response_model=ARInvoiceActionResponseSchema,
    summary="Post invoice to General Ledger",
    operation_id="post_ar_invoice",
)
async def post_ar_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:post")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Post invoice to GL (creates journal entry)."""
    try:
        result = await ar_service.post_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be posted")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="post",
            status=ARInvoiceStatus(result.status),
            message="Invoice posted to General Ledger",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to post AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/reverse",
    response_model=ARInvoiceActionResponseSchema,
    summary="Reverse a posted invoice",
    operation_id="reverse_ar_invoice",
)
async def reverse_ar_invoice(
    invoice_id: UUID,
    reason: str = Query(..., min_length=5, description="Reversal reason"),
    reversal_date: date = Query(default_factory=date.today, description="Reversal date"),
    _permission: None = Depends(require_permission("ar:reverse")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Reverse a posted invoice (creates reversing journal)."""
    try:
        result = await ar_service.reverse_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason, reversal_date
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found or cannot be reversed")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="reverse",
            status=ARInvoiceStatus(result.status),
            message="Invoice reversed: {}".format(reason),
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to reverse AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/lock",
    response_model=ARInvoiceActionResponseSchema,
    summary="Lock invoice for audit",
    operation_id="lock_ar_invoice",
)
async def lock_ar_invoice(
    invoice_id: UUID,
    reason: str = Query("", description="Lock reason"),
    _permission: None = Depends(require_permission("ar:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Lock invoice to prevent further modifications."""
    try:
        result = await ar_service.lock_invoice(
            invoice_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="lock",
            status=ARInvoiceStatus(result.status),
            message="Invoice locked",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to lock AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/{invoice_id}/unlock",
    response_model=ARInvoiceActionResponseSchema,
    summary="Unlock invoice",
    operation_id="unlock_ar_invoice",
)
async def unlock_ar_invoice(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:audit")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARInvoiceActionResponseSchema:
    """Unlock invoice."""
    try:
        result = await ar_service.unlock_invoice(invoice_id, current_user.user_id, legal_entity_id)

        if not result:
            raise HTTPException(status_code=404, detail="Invoice not found")

        return ARInvoiceActionResponseSchema(
            invoice_id=result.id,
            invoice_number=result.invoice_number,
            action="unlock",
            status=ARInvoiceStatus(result.status),
            message="Invoice unlocked",
            timestamp=datetime.now(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to unlock AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# PAYMENT OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/payments",
    response_model=ARPaymentResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Record AR payment",
    operation_id="record_ar_payment",
)
async def record_ar_payment(
    request: ARPaymentCreateSchema,
    _permission: None = Depends(require_permission("ar:record_payment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARPaymentResponseSchema:
    """
    Mencatat pembayaran piutang.

    - Payment mengurangi outstanding invoice
    - Jurnal: debit Bank/Cash, credit AR
    - Dapat memberikan diskon jika early payment
    """
    from application.dto_objects.ar_invoice_request import ARPaymentCreateRequest

    try:
        payment_dto = ARPaymentCreateRequest(
            invoice_id=request.invoice_id,
            payment_date=request.payment_date,
            amount=request.amount,
            payment_method=request.payment_method.value,
            bank_account_id=request.bank_account_id,
            reference_number=request.reference_number,
            notes=request.notes,
            discount_taken=request.discount_taken,
            apply_early_payment_discount=request.apply_early_payment_discount,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ar_service.record_payment(payment_dto)

        return ARPaymentResponseSchema(
            id=result.id,
            payment_number=result.payment_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            payment_date=result.payment_date,
            amount=result.amount,
            discount_taken=result.discount_taken,
            payment_method=PaymentMethod(result.payment_method),
            status=ARPaymentStatus(result.status),
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
        logger.exception("Failed to record AR payment: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/payments/{payment_id}",
    response_model=ARPaymentResponseSchema,
    summary="Get AR payment by ID",
    operation_id="get_ar_payment",
)
async def get_ar_payment(
    payment_id: UUID,
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARPaymentResponseSchema:
    """Get payment by ID."""
    try:
        payment = await ar_service.get_payment_by_id(payment_id, legal_entity_id)

        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        return ARPaymentResponseSchema(
            id=payment.id,
            payment_number=payment.payment_number,
            invoice_id=payment.invoice_id,
            invoice_number=payment.invoice_number,
            customer_id=payment.customer_id,
            customer_name=payment.customer_name,
            payment_date=payment.payment_date,
            amount=payment.amount,
            discount_taken=payment.discount_taken,
            payment_method=PaymentMethod(payment.payment_method),
            status=ARPaymentStatus(payment.status),
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
        logger.exception("Failed to get AR payment: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/payments/{payment_id}/reverse",
    response_model=ARPaymentResponseSchema,
    summary="Reverse a payment",
    operation_id="reverse_ar_payment",
)
async def reverse_ar_payment(
    payment_id: UUID,
    request: ARPaymentReverseSchema,
    _permission: None = Depends(require_permission("ar:reverse_payment")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARPaymentResponseSchema:
    """Reverse a payment (restores invoice outstanding amount)."""
    try:
        result = await ar_service.reverse_payment(
            payment_id=payment_id,
            reversed_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
            reason=request.reason,
            reversal_date=request.reversal_date,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Payment not found or cannot be reversed")

        return ARPaymentResponseSchema(
            id=result.id,
            payment_number=result.payment_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            payment_date=result.payment_date,
            amount=result.amount,
            discount_taken=result.discount_taken,
            payment_method=PaymentMethod(result.payment_method),
            status=ARPaymentStatus(result.status),
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
        logger.exception("Failed to reverse AR payment: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# CREDIT NOTE OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/credit-notes",
    response_model=ARCreditNoteResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Create AR credit note",
    operation_id="create_ar_credit_note",
)
async def create_ar_credit_note(
    request: ARCreditNoteCreateSchema,
    _permission: None = Depends(require_permission("ar:create_credit_note")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARCreditNoteResponseSchema:
    """Create credit note for invoice (reduces receivable amount)."""
    from application.dto_objects.ar_invoice_request import ARCreditNoteCreateRequest

    try:
        note_dto = ARCreditNoteCreateRequest(
            invoice_id=request.invoice_id,
            credit_note_date=request.credit_note_date,
            amount=request.amount,
            reason=request.reason,
            reference_number=request.reference_number,
            apply_to_future_invoices=request.apply_to_future_invoices,
            created_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )
        result = await ar_service.create_credit_note(note_dto)

        return ARCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=ARCreditNoteStatus(result.status),
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
        logger.exception("Failed to create AR credit note: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/credit-notes/{credit_note_id}/approve",
    response_model=ARCreditNoteResponseSchema,
    summary="Approve credit note",
    operation_id="approve_ar_credit_note",
)
async def approve_ar_credit_note(
    credit_note_id: UUID,
    _permission: None = Depends(require_permission("ar:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARCreditNoteResponseSchema:
    """Approve credit note."""
    try:
        result = await ar_service.approve_credit_note(
            credit_note_id, current_user.user_id, legal_entity_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Credit note not found")

        return ARCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=ARCreditNoteStatus(result.status),
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
        logger.exception("Failed to approve AR credit note: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete(
    "/credit-notes/{credit_note_id}",
    response_model=ARCreditNoteResponseSchema,
    summary="Cancel credit note",
    operation_id="cancel_ar_credit_note",
)
async def cancel_ar_credit_note(
    credit_note_id: UUID,
    reason: str = Query("", description="Cancellation reason"),
    _permission: None = Depends(require_permission("ar:delete")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARCreditNoteResponseSchema:
    """Cancel credit note."""
    try:
        result = await ar_service.cancel_credit_note(
            credit_note_id, current_user.user_id, legal_entity_id, reason
        )

        if not result:
            raise HTTPException(status_code=404, detail="Credit note not found")

        return ARCreditNoteResponseSchema(
            id=result.id,
            credit_note_number=result.credit_note_number,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            customer_id=result.customer_id,
            customer_name=result.customer_name,
            credit_note_date=result.credit_note_date,
            amount=result.amount,
            applied_amount=result.applied_amount,
            remaining_amount=result.remaining_amount,
            reason=result.reason,
            reference_number=result.reference_number,
            status=ARCreditNoteStatus(result.status),
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
        logger.exception("Failed to cancel AR credit note: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# WRITE-OFF OPERATION
# ----------------------------------------------------------------------------


@router.post(
    "/write-off",
    response_model=ARWriteOffResponseSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Write off uncollectible receivable",
    operation_id="write_off_ar_invoice",
)
async def write_off_ar_invoice(
    request: ARWriteOffSchema,
    _permission: None = Depends(require_permission("ar:write_off")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARWriteOffResponseSchema:
    """
    Write off uncollectible receivable.

    - Menghapus piutang yang tidak tertagih
    - Membuat jurnal beban piutang tak tertagih
    - Invoice status menjadi WRITTEN_OFF
    """
    try:
        result = await ar_service.write_off_invoice(
            invoice_id=request.invoice_id,
            write_off_amount=request.write_off_amount,
            account_code=request.account_code,
            reason=request.reason,
            written_by=current_user.user_id,
            legal_entity_id=legal_entity_id,
        )

        return ARWriteOffResponseSchema(
            write_off_id=result.write_off_id,
            invoice_id=result.invoice_id,
            invoice_number=result.invoice_number,
            write_off_amount=result.write_off_amount,
            remaining_outstanding=result.remaining_outstanding,
            journal_id=result.journal_id,
            status=result.status,
            created_at=result.created_at,
            created_by=result.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to write off AR invoice: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# AGING REPORT
# ----------------------------------------------------------------------------


@router.get(
    "/aging/{customer_id}",
    response_model=ARAgingResponseSchema,
    summary="Get AR aging report for a customer",
    operation_id="get_ar_aging_by_customer",
)
async def get_ar_aging_by_customer(
    customer_id: UUID,
    as_of_date: date = Query(..., description="Date for aging calculation"),
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARAgingResponseSchema:
    """Get AR aging report for a specific customer."""
    try:
        aging = await ar_service.get_aging_report(customer_id, legal_entity_id, as_of_date)

        return ARAgingResponseSchema(
            customer_id=aging.customer_id,
            customer_name=aging.customer_name,
            customer_code=aging.customer_code,
            as_of_date=as_of_date,
            total_outstanding=aging.total_outstanding,
            total_allowance=aging.total_allowance,
            buckets=[
                ARAgingBucketSchema(
                    bucket_name=b.bucket_name,
                    days_start=b.days_start,
                    days_end=b.days_end,
                    total_amount=b.total_amount,
                    percentage=b.percentage,
                    invoices=b.invoices,
                    allowance_amount=b.allowance_amount,
                )
                for b in aging.buckets
            ],
            generated_at=datetime.now(),
        )
    except Exception as e:
        logger.exception("Failed to get AR aging report: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/aging",
    response_model=list[ARAgingResponseSchema],
    summary="Get AR aging report for all customers",
    operation_id="get_all_ar_aging",
)
async def get_all_ar_aging(
    as_of_date: date = Query(..., description="Date for aging calculation"),
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> list[ARAgingResponseSchema]:
    """Get AR aging report for all customers."""
    try:
        report = await ar_service.get_aging_all_customers(legal_entity_id, as_of_date)

        return [
            ARAgingResponseSchema(
                customer_id=item.customer_id,
                customer_name=item.customer_name,
                customer_code=item.customer_code,
                as_of_date=as_of_date,
                total_outstanding=item.total_outstanding,
                total_allowance=item.total_allowance,
                buckets=[
                    ARAgingBucketSchema(
                        bucket_name=b.bucket_name,
                        days_start=b.days_start,
                        days_end=b.days_end,
                        total_amount=b.total_amount,
                        percentage=b.percentage,
                        invoices=b.invoices,
                        allowance_amount=b.allowance_amount,
                    )
                    for b in item.buckets
                ],
                generated_at=datetime.now(),
            )
            for item in report
        ]
    except Exception as e:
        logger.exception("Failed to get AR aging report: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# DSO DASHBOARD
# ----------------------------------------------------------------------------


@router.get(
    "/dashboard",
    response_model=ARDashboardSchema,
    summary="Get AR dashboard metrics (DSO, aging summary)",
    operation_id="get_ar_dashboard",
)
async def get_ar_dashboard(
    as_of_date: date = Query(..., description="Date for dashboard calculation"),
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARDashboardSchema:
    """Get AR dashboard with DSO and aging summary."""
    try:
        dashboard = await ar_service.get_dashboard(legal_entity_id, as_of_date)

        return ARDashboardSchema(
            total_outstanding=dashboard.total_outstanding,
            current_outstanding=dashboard.current_outstanding,
            overdue_1_30=dashboard.overdue_1_30,
            overdue_31_60=dashboard.overdue_31_60,
            overdue_61_90=dashboard.overdue_61_90,
            overdue_90_plus=dashboard.overdue_90_plus,
            overdue_amount=dashboard.overdue_amount,
            overdue_percentage=dashboard.overdue_percentage,
            dso_days=dashboard.dso_days,
            collection_efficiency=dashboard.collection_efficiency,
            aging_buckets=[
                ARAgingBucketSchema(
                    bucket_name=b.bucket_name,
                    days_start=b.days_start,
                    days_end=b.days_end,
                    total_amount=b.total_amount,
                    percentage=b.percentage,
                    invoices=b.invoices,
                    allowance_amount=b.allowance_amount,
                )
                for b in dashboard.aging_buckets
            ],
            as_of_date=as_of_date,
        )
    except Exception as e:
        logger.exception("Failed to get AR dashboard: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# COLLECTION WORKFLOW
# ----------------------------------------------------------------------------


@router.post(
    "/collection/send-reminders",
    response_model=ARCollectionReminderResponseSchema,
    summary="Send collection reminders for overdue invoices",
    operation_id="send_collection_reminders",
)
async def send_collection_reminders(
    request: ARCollectionReminderSchema,
    _permission: None = Depends(require_permission("ar:collection")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> ARCollectionReminderResponseSchema:
    """Send collection reminders for overdue invoices."""
    try:
        result = await ar_service.send_collection_reminders(
            legal_entity_id=legal_entity_id,
            invoice_ids=request.invoice_ids,
            reminder_type=request.reminder_type,
            message=request.message,
            send_email=request.send_email,
            send_sms=request.send_sms,
            sent_by=current_user.user_id,
        )

        return ARCollectionReminderResponseSchema(
            success=result.success,
            reminders_sent=result.reminders_sent,
            invoices_processed=result.invoices_processed,
            errors=result.errors,
        )
    except Exception as e:
        logger.exception("Failed to send collection reminders: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/collection/start",
    response_model=dict[str, Any],
    summary="Start collection workflow for overdue invoices",
    operation_id="start_collection_workflow",
)
async def start_collection_workflow(
    _permission: None = Depends(require_permission("ar:collection")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    collection_workflow: Any = Depends(get_ar_collection_workflow),
) -> dict[str, Any]:
    """Start collection workflow for all overdue invoices."""
    try:
        result = await collection_workflow.start_collection_process(
            legal_entity_id=legal_entity_id,
            initiated_by=current_user.user_id,
        )

        return {
            "workflow_id": str(result.workflow_id),
            "invoices_processed": result.invoices_processed,
            "reminders_sent": result.reminders_sent,
            "escalated_to_collection": result.escalated_to_collection,
            "message": result.message,
        }
    except Exception as e:
        logger.exception("Failed to start collection workflow: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/collection/{invoice_id}/escalate",
    response_model=dict[str, Any],
    summary="Escalate invoice to legal/collection agency",
    operation_id="escalate_collection",
)
async def escalate_collection(
    invoice_id: UUID,
    reason: str = Query(..., min_length=5, description="Escalation reason"),
    _permission: None = Depends(require_permission("ar:collection")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> dict[str, Any]:
    """Escalate invoice to legal or collection agency."""
    try:
        result = await ar_service.escalate_collection(
            invoice_id=invoice_id,
            legal_entity_id=legal_entity_id,
            reason=reason,
            escalated_by=current_user.user_id,
        )

        return {
            "invoice_id": str(invoice_id),
            "invoice_number": result.invoice_number,
            "escalated": True,
            "collection_status": result.collection_status,
            "message": "Invoice escalated: {}".format(reason),
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Failed to escalate collection: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# INVOICE STATUS & HISTORY
# ----------------------------------------------------------------------------


@router.get(
    "/invoices/{invoice_id}/status",
    response_model=dict[str, Any],
    summary="Get invoice status",
    operation_id="get_ar_invoice_status",
)
async def get_ar_invoice_status(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> dict[str, Any]:
    """Get detailed status of invoice including workflow state."""
    try:
        status_info = await ar_service.get_invoice_status(invoice_id, legal_entity_id)

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
            "days_overdue": status_info.days_overdue,
            "collection_status": status_info.collection_status,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get invoice status: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/invoices/{invoice_id}/history",
    response_model=list[dict[str, Any]],
    summary="Get invoice history",
    operation_id="get_ar_invoice_history",
)
async def get_ar_invoice_history(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> list[dict[str, Any]]:
    """Get audit history of invoice status changes."""
    try:
        history = await ar_service.get_invoice_history(invoice_id, legal_entity_id)

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
        logger.exception("Failed to get invoice history: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORT INVOICE TO PDF
# ----------------------------------------------------------------------------


@router.get(
    "/invoices/{invoice_id}/pdf",
    summary="Generate PDF for AR invoice",
    operation_id="generate_ar_invoice_pdf",
)
async def generate_ar_invoice_pdf(
    invoice_id: UUID,
    _permission: None = Depends(require_permission("ar:read")),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
):
    """Generate PDF document for AR invoice."""
    from fastapi.responses import Response

    try:
        pdf_bytes = await ar_service.generate_invoice_pdf(invoice_id, legal_entity_id)

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=ar_invoice_{}.pdf".format(invoice_id)},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to generate PDF: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# BULK OPERATIONS
# ----------------------------------------------------------------------------


@router.post(
    "/invoices/bulk/approve",
    response_model=dict[str, Any],
    summary="Bulk approve invoices",
    operation_id="bulk_approve_ar_invoices",
)
async def bulk_approve_ar_invoices(
    invoice_ids: list[UUID] = Query(..., description="List of invoice IDs"),
    notes: str = Query("", description="Approval notes"),
    _permission: None = Depends(require_permission("ar:approve")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> dict[str, Any]:
    """Approve multiple invoices at once."""
    try:
        result = await ar_service.bulk_approve_invoices(
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
        logger.exception("Failed to bulk approve invoices: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post(
    "/invoices/bulk/send-reminders",
    response_model=dict[str, Any],
    summary="Bulk send payment reminders",
    operation_id="bulk_send_payment_reminders",
)
async def bulk_send_payment_reminders(
    invoice_ids: list[UUID] = Query(..., description="List of invoice IDs"),
    reminder_type: str = Query("gentle", description="gentle, firm, final"),
    _permission: None = Depends(require_permission("ar:collection")),
    current_user: TokenPayload = Depends(get_current_user),
    legal_entity_id: UUID = Depends(get_current_legal_entity),
    ar_service: Any = Depends(get_ar_service),
) -> dict[str, Any]:
    """Send payment reminders to multiple customers."""
    try:
        result = await ar_service.bulk_send_reminders(
            invoice_ids=invoice_ids,
            reminder_type=reminder_type,
            sent_by=current_user.user_id,
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
        logger.exception("Failed to bulk send reminders: {}".format(e))
        raise HTTPException(status_code=500, detail="Internal server error")


# ----------------------------------------------------------------------------
# EXPORTS
# ----------------------------------------------------------------------------

__all__ = ["router"]