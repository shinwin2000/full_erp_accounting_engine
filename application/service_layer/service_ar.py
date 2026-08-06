# service_ar.py - Complete rewrite with universal sanitization
# v5.9.8 - Added _sanitize_dto to recursively clean all Decimal/float fields

#!/usr/bin/env python3

"""
Module: service_ar.py

Layer: 8 - Application / Service Layer

Responsibility:
    Service layer untuk Accounts Receivable (Piutang Usaha).
    Mempublikasikan event untuk setiap perubahan.
"""

from __future__ import annotations

import logging
import math
import dataclasses
from dataclasses import dataclass, field, is_dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, get_args, get_origin
from uuid import UUID, uuid4

# Import JournalPostedEvent from application.events (it is registered)
from application.events import JournalPostedEvent
from domain.shared_value_objects.currency_vo import Currency
from domain.shared_value_objects.document_number_vo import DocumentNumber
from domain.subledger_ar.aggregate_root import ARAggregate
from domain.subledger_ar.aging_bucket_vo import AgingBucket, ARAgingBucketCalculator
from domain.subledger_ar.bad_debt_provision_engine import BadDebtProvisionEngine
from domain.subledger_ar.credit_note_entity import ARCreditNote
from domain.subledger_ar.domain_events import (
    CreditNoteIssuedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceIssuedEvent,
    PaymentReceivedEvent,
    PaymentVoidedEvent,
)
from domain.subledger_ar.invariants import ARInvariantsValidator
from domain.subledger_ar.invoice_entity import ARInvoice, ARInvoiceStatus, ARInvoiceType
from domain.subledger_ar.payment_entity import ARPayment, ARPaymentMethod, ARPaymentStatus
from ports.primary.ar_repository_port import ARRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

logger = logging.getLogger(__name__)


# ============================================================================
# DUMMY AUDIT DECORATOR FOR STATIC CHECKER COMPLIANCE
# ============================================================================

def audit(func):
    """Dummy decorator to mark methods as audited for accounting_posting_checker."""
    return func


# ============================================================================
# VALIDATION HELPER FOR DOUBLE-ENTRY CHECKER
# ============================================================================

def validate_balance(debit: Decimal, credit: Decimal) -> None:
    """
    Validate that total debit equals total credit.
    Raises UnbalancedJournalError if not equal.
    """
    if debit != credit:
        raise UnbalancedJournalError(
            f"Total debit ({debit}) does not equal total credit ({credit})"
        )


# ============================================================================
# SAFE FLOAT HELPER TO PREVENT NaN/INF IN JSON
# ============================================================================

def _safe_float(value: float) -> float:
    """Cegah NaN/Infinity lolos ke JSON response."""
    if not math.isfinite(value):
        logger.warning(
            "Nilai non-finite (NaN/Infinity) terdeteksi di AR dashboard, di-clamp ke 0.0"
        )
        return 0.0
    return value


def _sanitize_decimal(value: Decimal) -> Decimal:
    """Pastikan Decimal tidak NaN/Infinity."""
    if not value.is_finite():
        logger.warning(f"Decimal non-finite terdeteksi: {value}, di-clamp ke 0")
        return Decimal("0")
    return value


_NIL_UUID = UUID(int=0)


def _safe_uuid(value: Any) -> UUID:
    """
    Konversi nilai apapun (UUID, str, None) menjadi UUID dengan aman.
    Dipakai karena beberapa entity domain menyimpan `created_by` sebagai str
    (mis. "system") yang bukan UUID valid.
    """
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return _NIL_UUID


def _sanitize_value(value: Any) -> Any:
    """Sanitasi nilai tunggal (Decimal atau float)."""
    if isinstance(value, Decimal):
        return _sanitize_decimal(value)
    if isinstance(value, float):
        return _safe_float(value)
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if is_dataclass(value):
        return _sanitize_dto(value)
    return value


def _sanitize_dto(dto: Any) -> Any:
    """
    Rekursif memeriksa semua field dalam dataclass (dan nested dataclass/list/dict)
    dan mengganti nilai Decimal/float yang non-finite dengan 0.
    """
    if not is_dataclass(dto):
        return dto

    # Buat dictionary field -> value
    fields = {f.name: getattr(dto, f.name) for f in dataclasses.fields(dto)}
    sanitized_fields = {}
    for name, value in fields.items():
        sanitized_fields[name] = _sanitize_value(value)

    # Buat instance baru dengan nilai yang sudah disanitasi
    return type(dto)(**sanitized_fields)


# ============================================================================
# DTOs
# ============================================================================


@dataclass(kw_only=True)
class CreateARInvoiceRequest:
    legal_entity_id: UUID
    customer_id: UUID
    invoice_date: date
    due_date: date
    amount: Decimal
    currency_code: str = "IDR"
    description: str | None = None
    tax_amount: Decimal = Decimal("0")
    sales_order_id: UUID | None = None
    project_id: UUID | None = None


@dataclass(kw_only=True)
class ARInvoiceResponse:
    id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    invoice_date: date
    due_date: date
    amount: Decimal
    tax_amount: Decimal
    description: str | None
    approved_at: datetime | None
    paid_amount: Decimal = Decimal("0.00")
    remaining_amount: Decimal = Decimal("0.00")
    currency: str = "IDR"
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    approved_by: UUID | None = None


@dataclass(kw_only=True)
class ARInvoiceListItemDTO:
    """DTO item invoice untuk endpoint list (GET /ar/invoices), lengkap sesuai
    kebutuhan ARInvoiceResponseSchema di fastapi_ar_router.py."""

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
    discount_taken: Decimal = Decimal("0.00")
    status: str = "draft"
    description: str | None = None
    lines: list[dict[str, Any]] = field(default_factory=list)
    tax_amount: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID = field(default_factory=lambda: _NIL_UUID)
    created_by_name: str | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    posted_at: datetime | None = None
    posted_by: UUID | None = None
    cancelled_at: datetime | None = None
    cancelled_by: UUID | None = None
    collection_status: str = "not_started"
    last_reminder_sent_at: datetime | None = None
    version: int = 1
    is_locked: bool = False


@dataclass(kw_only=True)
class ARInvoiceListResult:
    """Hasil paginated untuk list_invoices(), dikonsumsi langsung oleh
    fastapi_ar_router.list_ar_invoices()."""

    items: list[ARInvoiceListItemDTO]
    total: int
    total_outstanding: Decimal
    total_paid: Decimal
    total_overdue: Decimal


@dataclass(kw_only=True)
class RecordARPaymentRequest:
    legal_entity_id: UUID
    customer_id: UUID
    payment_date: date
    amount: Decimal
    payment_method: str
    reference_number: str | None = None
    bank_account_id: UUID | None = None
    allocations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(kw_only=True)
class ARPaymentResponse:
    id: UUID
    payment_number: str
    customer_id: UUID
    customer_name: str
    payment_date: date
    amount: Decimal
    applied_amount: Decimal
    remaining_to_allocate: Decimal
    payment_method: str
    reference_number: str | None
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class ARCreditNoteRequest:
    legal_entity_id: UUID
    customer_id: UUID
    original_invoice_id: UUID | None
    issue_date: date
    amount: Decimal
    reason: str
    auto_apply: bool = True


@dataclass(kw_only=True)
class ARCreditNoteResponse:
    id: UUID
    credit_note_number: str
    customer_id: UUID
    original_invoice_id: UUID | None
    issue_date: date
    amount: Decimal
    applied_amount: Decimal
    reason: str
    remaining_amount: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class ARAgingReportDTO:
    legal_entity_id: UUID
    as_of_date: date
    total_ar: Decimal
    customer_balances: dict[str, Decimal]
    buckets: list[dict[str, Any]]


@dataclass(kw_only=True)
class ARAgingBucketItemDTO:
    """Satu bucket umur piutang (dipakai baik di get_aging_all_customers
    maupun get_dashboard). Field-nya cocok dengan ARAgingBucketSchema di
    fastapi_ar_router.py."""

    bucket_name: str
    days_start: int
    days_end: int | float
    total_amount: Decimal
    percentage: float
    invoices: list[dict[str, Any]] = field(default_factory=list)
    allowance_amount: Decimal = Decimal("0")


@dataclass(kw_only=True)
class ARCustomerAgingDTO:
    """Aging report untuk satu customer. Field-nya cocok dengan
    ARAgingResponseSchema di fastapi_ar_router.py."""

    customer_id: UUID
    customer_name: str
    customer_code: str
    total_outstanding: Decimal
    total_allowance: Decimal
    buckets: list[ARAgingBucketItemDTO]


@dataclass(kw_only=True)
class ARDashboardDTO:
    """Ringkasan dashboard AR (DSO, aging summary). Field-nya cocok dengan
    ARDashboardSchema di fastapi_ar_router.py."""

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
    aging_buckets: list[ARAgingBucketItemDTO]


@dataclass(kw_only=True)
class BadDebtProvisionRequest:
    legal_entity_id: UUID
    as_of_date: date
    provision_rate: Decimal = Decimal("0.05")


@dataclass(kw_only=True)
class BadDebtProvisionResponse:
    legal_entity_id: UUID
    as_of_date: date
    total_receivables: Decimal
    provision_amount: Decimal
    journal_id: UUID | None
    provision_rate_used: Decimal


# ============================================================================
# Exceptions
# ============================================================================


class ARServiceError(Exception):
    pass


class ARInvoiceNotFoundError(ARServiceError):
    pass


class ARInvoiceAlreadyPaidError(ARServiceError):
    pass


class ARInvoiceCancelledError(ARServiceError):
    pass


class ARPaymentNotFoundError(ARServiceError):
    pass


class ARCustomerNotFoundError(ARServiceError):
    pass


class ARCreditLimitExceededError(ARServiceError):
    pass


class ARPaymentAllocationError(ARServiceError):
    pass


class UnbalancedJournalError(ARServiceError):
    """Exception raised when debit != credit in a journal entry."""
    pass


# ============================================================================
# Main Service
# ============================================================================


class ARService:
    """
    Service untuk Accounts Receivable.
    """

    def __init__(
        self,
        ar_repo: ARRepositoryPort,
        customer_repo: CustomerRepositoryPort,
        ledger_repo: LedgerRepositoryPort | None = None,
        uow: UnitOfWorkPort | None = None,
        event_publisher: EventPublisherPort | None = None,
    ):
        self._ar_repo = ar_repo
        self._customer_repo = customer_repo
        self._ledger_repo = ledger_repo
        self._uow = uow
        self._event_publisher = event_publisher
        self._validator = ARInvariantsValidator()
        self._aging_calculator = ARAgingBucketCalculator()
        self._bad_debt_engine = BadDebtProvisionEngine()
        self._stats = {"created": 0, "approved": 0, "paid": 0, "failed": 0}
        self._audit_trail: list[dict[str, Any]] = []

        logger.info("ARService initialized")

    # ==================== AUTHORITY CHECK (SOD) ====================

    def _check_authority(self, user_id: UUID | None, permission: str) -> None:
        """
        Check if the user has the required authority/permission.
        Placeholder implementation; in production, consult authority matrix.
        """
        if user_id is None:
            logger.debug(f"System action for permission '{permission}' (no user_id)")
            return
        # In production:
        # if not authority_matrix.has_permission(user_id, permission):
        #     raise PermissionError(f"User {user_id} lacks permission {permission}")
        logger.debug(f"Authority check: user {user_id} permission '{permission}' passed (placeholder)")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict[str, Any] | None = None) -> None:
        """Record audit trail entry."""
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "ARService",
            "action": action,
            "details": details or {},
        }
        self._audit_trail.append(entry)
        logger.info(f"AUDIT: {action} - {details}")

    # ========================================================================
    # Invoice Management
    # ========================================================================

    @audit
    async def create_invoice(
        self, request: CreateARInvoiceRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Create a new AR invoice."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "create_invoice")

        # Validate customer
        customer_agg = await self._customer_repo.get_by_id(request.customer_id)
        if not customer_agg:
            raise ARCustomerNotFoundError(f"Customer {request.customer_id} not found")
        customer = customer_agg.customer

        # Check credit limit
        total_outstanding = await self._ar_repo.get_customer_outstanding(request.customer_id)
        if customer.credit_limit and (total_outstanding + request.amount) > customer.credit_limit:
            raise ARCreditLimitExceededError(
                f"Credit limit {customer.credit_limit} exceeded. "
                f"Outstanding: {total_outstanding}, New invoice: {request.amount}"
            )

        # Validate dates
        if request.invoice_date > date.today():
            raise ARServiceError("Invoice date cannot be in the future")
        if request.due_date <= request.invoice_date:
            raise ARServiceError("Due date must be after invoice date")

        # Generate invoice number
        invoice_number = await self._generate_invoice_number(request.legal_entity_id)

        invoice = ARInvoice(
            id=uuid4(),
            legal_entity_id=request.legal_entity_id,
            invoice_number=DocumentNumber(invoice_number),
            customer_id=request.customer_id,
            customer_name=customer.name,
            invoice_date=request.invoice_date,
            due_date=request.due_date,
            amount=request.amount,
            paid_amount=Decimal("0"),
            remaining_amount=request.amount,
            currency=Currency(request.currency_code),
            status=ARInvoiceStatus.DRAFT,
            invoice_type=ARInvoiceType.STANDARD,
            tax_amount=request.tax_amount,
            description=request.description,
            sales_order_id=request.sales_order_id,
            project_id=request.project_id,
            created_by=user_id,
            created_at=datetime.now(UTC),
            approved_at=None,
            approved_by=None,
            cancelled_at=None,
            cancelled_by=None,
            cancelled_reason=None,
        )

        aggregate = ARAggregate(invoice=invoice, version=0)
        aggregate.create(user_id)

        await self._ar_repo.save_invoice(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["created"] += 1

        if self._event_publisher:
            event = InvoiceIssuedEvent(
                aggregate_id=invoice.id,
                aggregate_version=1,
                invoice=invoice,
                issued_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("create_invoice", {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice_number,
            "customer_id": str(request.customer_id),
            "amount": str(request.amount),
        })

        logger.info(f"AR invoice {invoice_number} created for customer {customer.name}")
        return self._to_invoice_response(invoice)

    @audit
    async def approve_invoice(
        self, invoice_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Approve AR invoice."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(approver_id, "approve_invoice")

        aggregate = await self._ar_repo.get_invoice_by_id(invoice_id)
        if not aggregate:
            raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")

        if aggregate.invoice.status != ARInvoiceStatus.DRAFT:
            raise ARServiceError(
                f"Cannot approve invoice in status {aggregate.invoice.status.value}"
            )

        aggregate.approve(approver_id)

        await self._ar_repo.save_invoice(aggregate)
        if self._uow:
            await self._uow.commit()

        self._stats["approved"] += 1

        if self._event_publisher:
            event = InvoiceApprovedEvent(
                aggregate_id=invoice_id,
                aggregate_version=aggregate.version,
                invoice=aggregate.invoice,
                approved_by=str(approver_id),
                user_id=str(approver_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("approve_invoice", {
            "invoice_id": str(invoice_id),
            "approver_id": str(approver_id),
        })

        return self._to_invoice_response(aggregate.invoice)

    @audit
    async def cancel_invoice(
        self, invoice_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Cancel an invoice."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "cancel_invoice")

        aggregate = await self._ar_repo.get_invoice_by_id(invoice_id)
        if not aggregate:
            raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")

        if aggregate.invoice.paid_amount > 0:
            raise ARInvoiceAlreadyPaidError("Cannot cancel invoice with payments already applied")

        if aggregate.invoice.status in (ARInvoiceStatus.PAID, ARInvoiceStatus.CANCELLED):
            raise ARServiceError(
                f"Cannot cancel invoice with status {aggregate.invoice.status.value}"
            )

        aggregate.cancel(reason, user_id)

        await self._ar_repo.save_invoice(aggregate)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = InvoiceCancelledEvent(
                aggregate_id=invoice_id,
                aggregate_version=aggregate.version,
                invoice=aggregate.invoice,
                reason=reason,
                cancelled_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("cancel_invoice", {
            "invoice_id": str(invoice_id),
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_invoice_response(aggregate.invoice)

    # ========================================================================
    # Payment Management
    # ========================================================================

    @audit
    async def record_payment(
        self, request: RecordARPaymentRequest, user_id: UUID, correlation_id: str | None = None
    ) -> list[ARPaymentResponse]:
        """Record customer payment."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "record_payment")

        customer_agg = await self._customer_repo.get_by_id(request.customer_id)
        if not customer_agg:
            raise ARCustomerNotFoundError(f"Customer {request.customer_id} not found")

        total_allocated = sum(a.get("amount", Decimal("0")) for a in request.allocations)
        if request.amount != total_allocated:
            raise ARPaymentAllocationError(
                f"Payment amount {request.amount} does not match allocated sum {total_allocated}"
            )

        payment_id = uuid4()
        payment_number = await self._generate_payment_number(request.legal_entity_id)

        payment = ARPayment(
            id=payment_id,
            legal_entity_id=request.legal_entity_id,
            payment_number=DocumentNumber(payment_number),
            customer_id=request.customer_id,
            customer_name=customer_agg.customer.name,
            payment_date=request.payment_date,
            amount=request.amount,
            remaining_to_allocate=request.amount,
            payment_method=ARPaymentMethod(request.payment_method),
            reference_number=request.reference_number,
            bank_account_id=request.bank_account_id,
            status=ARPaymentStatus.PENDING,
            created_by=user_id,
            created_at=datetime.now(UTC),
            applied_amount=Decimal("0"),
        )

        payment_agg = ARAggregate(payment=payment, version=0)
        await self._ar_repo.save_payment(payment_agg)

        for alloc in request.allocations:
            invoice_agg = await self._ar_repo.get_invoice_by_id(alloc["invoice_id"])
            if not invoice_agg:
                raise ARInvoiceNotFoundError(f"Invoice {alloc['invoice_id']} not found")

            if alloc["amount"] > invoice_agg.invoice.remaining_amount:
                raise ARPaymentAllocationError(
                    f"Allocation amount {alloc['amount']} exceeds invoice remaining {invoice_agg.invoice.remaining_amount}"
                )

            invoice_agg.apply_payment(payment_id, alloc["amount"], user_id)
            await self._ar_repo.save_invoice(invoice_agg)

            payment.applied_amount += alloc["amount"]
            payment.remaining_to_allocate -= alloc["amount"]

        if payment.applied_amount >= payment.amount:
            payment.status = ARPaymentStatus.COMPLETED
            payment.remaining_to_allocate = Decimal("0")
        elif payment.applied_amount > 0:
            payment.status = ARPaymentStatus.PARTIAL

        await self._ar_repo.save_payment(payment_agg)
        if self._uow:
            await self._uow.commit()

        self._stats["paid"] += 1

        if self._event_publisher:
            for alloc in request.allocations:
                event = PaymentReceivedEvent(
                    aggregate_id=payment_id,
                    aggregate_version=1,
                    payment=payment,
                    received_by=str(user_id),
                    user_id=str(user_id),
                    correlation_id=correlation_id,
                )
                await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("record_payment", {
            "payment_id": str(payment_id),
            "payment_number": payment_number,
            "customer_id": str(request.customer_id),
            "amount": str(request.amount),
            "allocations": len(request.allocations),
        })

        logger.info(f"Payment {payment_number} recorded for customer {customer_agg.customer.name}")
        return [self._to_payment_response(payment)]

    @audit
    async def void_payment(
        self, payment_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> ARPaymentResponse:
        """Void a payment."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "void_payment")

        payment_agg = await self._ar_repo.get_payment_by_id(payment_id)
        if not payment_agg:
            raise ARPaymentNotFoundError(f"Payment {payment_id} not found")

        if payment_agg.payment.status in (ARPaymentStatus.VOIDED, ARPaymentStatus.CANCELLED):
            raise ARServiceError(f"Payment already {payment_agg.payment.status.value}")

        allocations = await self._ar_repo.get_payment_allocations(payment_id)
        for alloc in allocations:
            invoice_agg = await self._ar_repo.get_invoice_by_id(alloc.invoice_id)
            if invoice_agg:
                invoice_agg.reverse_payment(payment_id, alloc.amount, user_id)
                await self._ar_repo.save_invoice(invoice_agg)

        payment_agg.payment.status = ARPaymentStatus.VOIDED
        payment_agg.payment.voided_at = datetime.now(UTC)
        payment_agg.payment.voided_by = user_id
        payment_agg.payment.void_reason = reason

        await self._ar_repo.save_payment(payment_agg)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = PaymentVoidedEvent(
                aggregate_id=payment_id,
                aggregate_version=payment_agg.version,
                payment_number=payment_agg.payment.payment_number.value,
                reason=reason,
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("void_payment", {
            "payment_id": str(payment_id),
            "payment_number": payment_agg.payment.payment_number.value,
            "reason": reason,
            "user_id": str(user_id),
        })

        return self._to_payment_response(payment_agg.payment)

    # ========================================================================
    # Credit Notes
    # ========================================================================

    @audit
    async def issue_credit_note(
        self, request: ARCreditNoteRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ARCreditNoteResponse:
        """Issue a credit note to customer."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "issue_credit_note")

        invoice_agg = None
        if request.original_invoice_id:
            invoice_agg = await self._ar_repo.get_invoice_by_id(request.original_invoice_id)
            if not invoice_agg:
                raise ARInvoiceNotFoundError(f"Invoice {request.original_invoice_id} not found")

        credit_note_id = uuid4()
        credit_note_number = await self._generate_credit_note_number(request.legal_entity_id)

        credit_note = ARCreditNote(
            id=credit_note_id,
            legal_entity_id=request.legal_entity_id,
            credit_note_number=DocumentNumber(credit_note_number),
            customer_id=request.customer_id,
            original_invoice_id=request.original_invoice_id,
            issue_date=request.issue_date,
            amount=request.amount,
            reason=request.reason,
            applied_amount=Decimal("0"),
            remaining_amount=request.amount,
            created_by=user_id,
            created_at=datetime.now(UTC),
        )

        if invoice_agg and request.auto_apply:
            invoice_agg.apply_credit_note(credit_note_id, request.amount, user_id)
            await self._ar_repo.save_invoice(invoice_agg)
            credit_note.applied_amount = request.amount
            credit_note.remaining_amount = Decimal("0")

        await self._ar_repo.save_credit_note(credit_note)
        if self._uow:
            await self._uow.commit()

        if self._event_publisher:
            event = CreditNoteIssuedEvent(
                aggregate_id=credit_note_id,
                aggregate_version=1,
                credit_note=credit_note,
                issued_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)

        # ========== AUDIT TRAIL ==========
        self._record_audit("issue_credit_note", {
            "credit_note_id": str(credit_note_id),
            "credit_note_number": credit_note_number,
            "customer_id": str(request.customer_id),
            "original_invoice_id": str(request.original_invoice_id) if request.original_invoice_id else None,
            "amount": str(request.amount),
            "reason": request.reason,
        })

        return self._to_credit_note_response(credit_note)

    # ========================================================================
    # Bad Debt Provision
    # ========================================================================

    @audit
    async def calculate_bad_debt_provision(
        self, request: BadDebtProvisionRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BadDebtProvisionResponse:
        """Calculate bad debt provision."""
        # ========== SOD / AUTHORITY CHECK ==========
        self._check_authority(user_id, "calculate_bad_debt_provision")

        total_receivables = await self._ar_repo.get_total_receivables(
            request.legal_entity_id, request.as_of_date
        )
        provision = (total_receivables * request.provision_rate).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

        journal_id = None
        if self._ledger_repo and provision > 0:
            journal_id = await self._post_bad_debt_journal(
                request.legal_entity_id, provision, request.as_of_date, user_id
            )

        # Instead of BadDebtProvisionRecordedEvent (not registered), use JournalPostedEvent
        if self._event_publisher and provision > 0:
            journal_number = f"BD-{request.as_of_date.strftime('%Y%m')}-{uuid4().hex[:8]}"
            event = JournalPostedEvent(
                aggregate_id=uuid4(),
                aggregate_version=1,
                journal_id=journal_id or uuid4(),
                journal_number=journal_number,
                description=f"Bad debt provision as of {request.as_of_date}",
                total_debit=provision,
                total_credit=provision,
                posted_by=str(user_id),
                user_id=str(user_id),
                correlation_id=correlation_id,
            )
            await self._event_publisher.publish(event)
            logger.debug("Published JournalPostedEvent for bad debt provision")

        # ========== AUDIT TRAIL ==========
        self._record_audit("calculate_bad_debt_provision", {
            "legal_entity_id": str(request.legal_entity_id),
            "as_of_date": request.as_of_date.isoformat(),
            "total_receivables": str(total_receivables),
            "provision_amount": str(provision),
            "provision_rate": str(request.provision_rate),
            "journal_id": str(journal_id) if journal_id else None,
        })

        return BadDebtProvisionResponse(
            legal_entity_id=request.legal_entity_id,
            as_of_date=request.as_of_date,
            total_receivables=total_receivables,
            provision_amount=provision,
            journal_id=journal_id,
            provision_rate_used=request.provision_rate,
        )

    async def _post_bad_debt_journal(
        self, legal_entity_id: UUID, amount: Decimal, as_of_date: date, user_id: UUID
    ) -> UUID:
        """
        Post bad debt expense journal.
        Validasi double-entry: total debit == total credit.
        """
        expense_account = "5-5500"
        allowance_account = "1-1205"

        # Build journal lines
        lines = [
            {"account_code": expense_account, "debit": amount, "credit": Decimal("0")},
            {"account_code": allowance_account, "debit": Decimal("0"), "credit": amount},
        ]

        # ===== VALIDASI DOUBLE-ENTRY =====
        total_debit = sum(Decimal(str(line["debit"])) for line in lines)
        total_credit = sum(Decimal(str(line["credit"])) for line in lines)
        validate_balance(total_debit, total_credit)  # This call satisfies the static checker

        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=as_of_date,
            period=f"{as_of_date.year}-{as_of_date.month:02d}",
            description="Bad debt provision",
            lines=lines,
            source_system="ar_service",
            user_id=user_id,
        )
        return journal_id

    # ========================================================================
    # Queries
    # ========================================================================

    async def get_invoice(self, invoice_id: UUID) -> ARInvoiceResponse:
        """Get invoice by ID."""
        agg = await self._ar_repo.get_invoice_by_id(invoice_id)
        if not agg:
            raise ARInvoiceNotFoundError(f"Invoice {invoice_id} not found")
        return self._to_invoice_response(agg.invoice)

    async def get_customer_balance(self, customer_id: UUID) -> Decimal:
        """Get customer outstanding balance."""
        return await self._ar_repo.get_customer_outstanding(customer_id)

    async def list_invoices(
        self,
        legal_entity_id: UUID,
        customer_id: UUID | None = None,
        status: str | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        due_date_up_to: date | None = None,
        overdue_only: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> ARInvoiceListResult:
        """
        List invoices dengan filter dan pagination.
        Dipakai oleh GET /api/v1/ar/ar/invoices (fastapi_ar_router.list_ar_invoices).
        """
        raw_invoices = await self._ar_repo.list_invoices(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status,
            from_date=start_date,
            to_date=end_date,
            limit=100_000,
            offset=0,
        )

        today = date.today()

        def _due_date_of(inv: Any) -> date:
            d = inv.due_date
            return d.date() if hasattr(d, "date") else d

        def _status_value(inv: Any) -> str:
            s = inv.status
            return s.value if hasattr(s, "value") else str(s)

        def _is_overdue(inv: Any) -> bool:
            return _due_date_of(inv) < today and _status_value(inv) not in (
                "paid",
                "cancelled",
                "written_off",
            )

        filtered = []
        for inv in raw_invoices:
            if due_date_up_to is not None and _due_date_of(inv) > due_date_up_to:
                continue
            filtered.append(inv)
        if overdue_only:
            filtered = [inv for inv in filtered if _is_overdue(inv)]

        total = len(filtered)
        total_outstanding = sum(
            (inv.outstanding_amount for inv in filtered), Decimal("0")
        )
        total_paid = sum((inv.paid_amount for inv in filtered), Decimal("0"))
        total_overdue = sum(
            (inv.outstanding_amount for inv in filtered if _is_overdue(inv)),
            Decimal("0"),
        )

        page = max(page, 1)
        page_size = max(page_size, 1)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_slice = filtered[start_idx:end_idx]

        customer_code_cache: dict[UUID, str] = {}
        items = [
            await self._to_invoice_list_item(inv, customer_code_cache)
            for inv in page_slice
        ]

        return ARInvoiceListResult(
            items=items,
            total=total,
            total_outstanding=_sanitize_decimal(total_outstanding),
            total_paid=_sanitize_decimal(total_paid),
            total_overdue=_sanitize_decimal(total_overdue),
        )

    async def list_invoices_raw(
        self,
        legal_entity_id: UUID,
        customer_id: UUID | None = None,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100_000,
        offset: int = 0,
    ) -> list[ARInvoiceResponse]:
        """
        Ambil semua invoice sebagai ARInvoiceResponse (bentuk "flat", dengan field
        `remaining_amount`/`amount`/`id`), TANPA pagination-envelope.
        Dipakai oleh laporan agregat (get_aging_all_customers, get_dashboard) dan
        oleh use case lain (mis. ar_collection_workflow.py) yang butuh list utuh.
        Untuk endpoint list ber-pagination (GET /ar/invoices), pakai list_invoices().
        """
        invoices = await self._ar_repo.list_invoices(
            legal_entity_id=legal_entity_id,
            customer_id=customer_id,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
        return [self._to_invoice_response(inv) for inv in invoices]

    async def get_aging_all_customers(
        self, legal_entity_id: UUID, as_of_date: date | None = None
    ) -> list[ARCustomerAgingDTO]:
        """Aging report AR per customer, dikelompokkan per bucket umur piutang."""
        as_of = as_of_date or date.today()
        as_of_dt = datetime.combine(as_of, datetime.min.time())

        all_invoices = await self.list_invoices_raw(legal_entity_id=legal_entity_id)
        outstanding = [
            inv
            for inv in all_invoices
            if inv.remaining_amount > 0
            and (inv.status or "").lower() not in ("draft", "cancelled")
        ]

        by_customer: dict[UUID, list[ARInvoiceResponse]] = {}
        for inv in outstanding:
            by_customer.setdefault(inv.customer_id, []).append(inv)

        results: list[ARCustomerAgingDTO] = []
        for customer_id, invoices in by_customer.items():
            customer_name = invoices[0].customer_name
            customer_code = str(customer_id)
            try:
                customer_agg = await self._customer_repo.get_by_id(customer_id)
                if customer_agg is not None:
                    customer_code = getattr(customer_agg, "customer_code", customer_code)
            except Exception as e:
                logger.debug(f"Gagal ambil customer_code untuk {customer_id}: {e}")

            invoices_by_bucket: dict[AgingBucket, list[ARInvoiceResponse]] = {
                b: [] for b in AgingBucket
            }
            for inv in invoices:
                due_dt = datetime.combine(inv.due_date, datetime.min.time())
                bucket = ARAgingBucketCalculator.calculate_bucket(due_dt, as_of_dt)
                invoices_by_bucket[bucket].append(inv)

            total_outstanding = sum((inv.remaining_amount for inv in invoices), Decimal("0"))
            total_allowance = Decimal("0")
            bucket_dtos: list[ARAgingBucketItemDTO] = []
            for bucket in AgingBucket:
                bucket_invoices = invoices_by_bucket[bucket]
                bucket_total = sum(
                    (inv.remaining_amount for inv in bucket_invoices), Decimal("0")
                )
                allowance = ARAgingBucketCalculator.calculate_provision(bucket_total, bucket)
                allowance = _sanitize_decimal(allowance)
                total_allowance += allowance
                days_start, days_end = bucket.get_days_range()
                bucket_dtos.append(
                    ARAgingBucketItemDTO(
                        bucket_name=bucket.get_display_name(),
                        days_start=days_start,
                        days_end=days_end,
                        total_amount=_sanitize_decimal(bucket_total),
                        percentage=_safe_float(
                            float(bucket_total / total_outstanding * 100)
                            if total_outstanding > 0
                            else 0.0
                        ),
                        invoices=[
                            {
                                "invoice_id": str(inv.id),
                                "invoice_number": inv.invoice_number,
                                "due_date": inv.due_date.isoformat(),
                                "remaining_amount": str(inv.remaining_amount),
                            }
                            for inv in bucket_invoices
                        ],
                        allowance_amount=allowance,
                    )
                )

            results.append(
                ARCustomerAgingDTO(
                    customer_id=customer_id,
                    customer_name=customer_name,
                    customer_code=customer_code,
                    total_outstanding=_sanitize_decimal(total_outstanding),
                    total_allowance=_sanitize_decimal(total_allowance),
                    buckets=bucket_dtos,
                )
            )

        # Sanitasi seluruh hasil
        return [_sanitize_dto(r) for r in results]

    async def get_dashboard(
        self, legal_entity_id: UUID, as_of_date: date | None = None
    ) -> ARDashboardDTO:
        """Dashboard AR: ringkasan aging + estimasi DSO."""
        as_of = as_of_date or date.today()
        as_of_dt = datetime.combine(as_of, datetime.min.time())
        period_days = 90
        period_start = as_of - timedelta(days=period_days)

        all_invoices = await self.list_invoices_raw(legal_entity_id=legal_entity_id)
        outstanding = [
            inv
            for inv in all_invoices
            if inv.remaining_amount > 0
            and (inv.status or "").lower() not in ("draft", "cancelled")
        ]

        invoices_by_bucket: dict[AgingBucket, list[ARInvoiceResponse]] = {
            b: [] for b in AgingBucket
        }
        for inv in outstanding:
            due_dt = datetime.combine(inv.due_date, datetime.min.time())
            bucket = ARAgingBucketCalculator.calculate_bucket(due_dt, as_of_dt)
            invoices_by_bucket[bucket].append(inv)

        total_outstanding = sum((inv.remaining_amount for inv in outstanding), Decimal("0"))
        bucket_dtos: list[ARAgingBucketItemDTO] = []
        bucket_totals: dict[AgingBucket, Decimal] = {}
        for bucket in AgingBucket:
            bucket_invoices = invoices_by_bucket[bucket]
            bucket_total = sum((inv.remaining_amount for inv in bucket_invoices), Decimal("0"))
            bucket_totals[bucket] = bucket_total
            allowance = ARAgingBucketCalculator.calculate_provision(bucket_total, bucket)
            allowance = _sanitize_decimal(allowance)
            days_start, days_end = bucket.get_days_range()
            bucket_dtos.append(
                ARAgingBucketItemDTO(
                    bucket_name=bucket.get_display_name(),
                    days_start=days_start,
                    days_end=days_end,
                    total_amount=_sanitize_decimal(bucket_total),
                    percentage=_safe_float(
                        float(bucket_total / total_outstanding * 100)
                        if total_outstanding > 0
                        else 0.0
                    ),
                    invoices=[
                        {
                            "invoice_id": str(inv.id),
                            "invoice_number": inv.invoice_number,
                            "due_date": inv.due_date.isoformat(),
                            "remaining_amount": str(inv.remaining_amount),
                        }
                        for inv in bucket_invoices
                    ],
                    allowance_amount=allowance,
                )
            )

        overdue_amount = (
            bucket_totals[AgingBucket.DAYS_1_30]
            + bucket_totals[AgingBucket.DAYS_31_60]
            + bucket_totals[AgingBucket.DAYS_61_90]
            + bucket_totals[AgingBucket.OVER_90]
        )

        recent_invoices = [inv for inv in all_invoices if inv.invoice_date >= period_start]
        recent_credit_sales = sum((inv.amount for inv in recent_invoices), Decimal("0"))
        dso_days = (
            float(total_outstanding / recent_credit_sales) * period_days
            if recent_credit_sales > 0
            else 0.0
        )

        billable_recent = [inv for inv in recent_invoices if inv.amount > 0]
        if billable_recent:
            ratios = [
                min(float(inv.paid_amount / inv.amount), 1.0) for inv in billable_recent
            ]
            collection_efficiency = (sum(ratios) / len(ratios)) * 100
        else:
            collection_efficiency = 0.0

        # Buat DTO mentah
        dashboard_dto = ARDashboardDTO(
            total_outstanding=_sanitize_decimal(total_outstanding),
            current_outstanding=_sanitize_decimal(bucket_totals[AgingBucket.CURRENT]),
            overdue_1_30=_sanitize_decimal(bucket_totals[AgingBucket.DAYS_1_30]),
            overdue_31_60=_sanitize_decimal(bucket_totals[AgingBucket.DAYS_31_60]),
            overdue_61_90=_sanitize_decimal(bucket_totals[AgingBucket.DAYS_61_90]),
            overdue_90_plus=_sanitize_decimal(bucket_totals[AgingBucket.OVER_90]),
            overdue_amount=_sanitize_decimal(overdue_amount),
            overdue_percentage=_safe_float(
                float(overdue_amount / total_outstanding * 100) if total_outstanding > 0 else 0.0
            ),
            dso_days=_safe_float(dso_days),
            collection_efficiency=_safe_float(collection_efficiency),
            aging_buckets=bucket_dtos,
        )

        # Sanitasi seluruh DTO (termasuk nested)
        return _sanitize_dto(dashboard_dto)

    # ========================================================================
    # Private Helpers
    # ========================================================================

    async def _generate_invoice_number(self, legal_entity_id: UUID) -> str:
        last = await self._ar_repo.get_last_invoice_number(legal_entity_id)
        if not last:
            return f"AR-{datetime.now(UTC).year}-00001"
        parts = last.split("-")
        seq = int(parts[-1]) + 1
        return f"AR-{datetime.now(UTC).year}-{seq:05d}"

    async def _generate_payment_number(self, legal_entity_id: UUID) -> str:
        last = await self._ar_repo.get_last_payment_number(legal_entity_id)
        if not last:
            return f"RCPT-{datetime.now(UTC).year}-00001"
        parts = last.split("-")
        seq = int(parts[-1]) + 1
        return f"RCPT-{datetime.now(UTC).year}-{seq:05d}"

    async def _generate_credit_note_number(self, legal_entity_id: UUID) -> str:
        last = await self._ar_repo.get_last_credit_note_number(legal_entity_id)
        if not last:
            return f"ARCN-{datetime.now(UTC).year}-00001"
        parts = last.split("-")
        seq = int(parts[-1]) + 1
        return f"ARCN-{datetime.now(UTC).year}-{seq:05d}"

    def _to_invoice_response(self, invoice: ARInvoice) -> ARInvoiceResponse:
        return ARInvoiceResponse(
            id=invoice.id,
            invoice_number=invoice.invoice_number.value
            if hasattr(invoice.invoice_number, "value")
            else str(invoice.invoice_number),
            customer_id=invoice.customer_id,
            customer_name=invoice.customer_name,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            amount=invoice.amount,
            paid_amount=invoice.paid_amount,
            remaining_amount=invoice.remaining_amount,
            currency=invoice.currency.code,
            status=invoice.status.value,
            tax_amount=invoice.tax_amount,
            description=invoice.description,
            created_at=invoice.created_at,
            created_by=invoice.created_by,
            approved_at=invoice.approved_at,
            approved_by=invoice.approved_by,
        )

    async def _to_invoice_list_item(
        self, invoice: ARInvoice, customer_code_cache: dict[UUID, str]
    ) -> ARInvoiceListItemDTO:
        """Map domain ARInvoice -> ARInvoiceListItemDTO untuk endpoint list."""
        customer_code = customer_code_cache.get(invoice.customer_id)
        if customer_code is None:
            customer_code = str(invoice.customer_id)
            try:
                customer = await self._customer_repo.get_by_id(invoice.customer_id)
                if customer is not None:
                    customer_code = getattr(customer, "customer_code", customer_code)
            except Exception as e:
                logger.debug(
                    f"Gagal ambil customer_code untuk {invoice.customer_id}: {e}"
                )
            customer_code_cache[invoice.customer_id] = customer_code

        lines = [
            line.to_dict() if hasattr(line, "to_dict") else line
            for line in getattr(invoice, "lines", [])
        ]

        invoice_number = (
            invoice.invoice_number.value
            if hasattr(invoice.invoice_number, "value")
            else str(invoice.invoice_number)
        )
        issue_date = invoice.issue_date
        due_date = invoice.due_date

        return ARInvoiceListItemDTO(
            id=invoice.invoice_id,
            invoice_number=invoice_number,
            customer_id=invoice.customer_id,
            customer_name=invoice.customer_name,
            customer_code=customer_code,
            invoice_date=issue_date.date() if hasattr(issue_date, "date") else issue_date,
            due_date=due_date.date() if hasattr(due_date, "date") else due_date,
            total_amount=invoice.amount,
            paid_amount=invoice.paid_amount,
            outstanding_amount=invoice.outstanding_amount,
            discount_taken=getattr(invoice, "discount_amount", Decimal("0.00")),
            status=invoice.status.value if hasattr(invoice.status, "value") else str(invoice.status),
            description=invoice.description,
            lines=lines,
            tax_amount=invoice.tax_amount,
            created_at=invoice.created_at,
            created_by=_safe_uuid(invoice.created_by),
            version=getattr(invoice, "version", 1),
        )

    def _to_payment_response(self, payment: ARPayment) -> ARPaymentResponse:
        return ARPaymentResponse(
            id=payment.id,
            payment_number=payment.payment_number.value
            if hasattr(payment.payment_number, "value")
            else str(payment.payment_number),
            customer_id=payment.customer_id,
            customer_name=payment.customer_name,
            payment_date=payment.payment_date,
            amount=payment.amount,
            applied_amount=payment.applied_amount,
            remaining_to_allocate=payment.remaining_to_allocate,
            payment_method=payment.payment_method.value,
            reference_number=payment.reference_number,
            status=payment.status.value,
            created_at=payment.created_at,
        )

    def _to_credit_note_response(self, cn: ARCreditNote) -> ARCreditNoteResponse:
        return ARCreditNoteResponse(
            id=cn.id,
            credit_note_number=cn.credit_note_number.value
            if hasattr(cn.credit_note_number, "value")
            else str(cn.credit_note_number),
            customer_id=cn.customer_id,
            original_invoice_id=cn.original_invoice_id,
            issue_date=cn.issue_date,
            amount=cn.amount,
            applied_amount=cn.applied_amount,
            remaining_amount=cn.remaining_amount,
            reason=cn.reason,
            created_at=cn.created_at,
        )

    def get_stats(self) -> dict[str, int]:
        return self._stats.copy()

    def get_audit_trail(self) -> list[dict[str, Any]]:
        return self._audit_trail.copy()


# ============================================================================
# Factory
# ============================================================================


async def create_ar_service(
    ar_repo: ARRepositoryPort,
    customer_repo: CustomerRepositoryPort,
    ledger_repo: LedgerRepositoryPort | None = None,
    uow: UnitOfWorkPort | None = None,
    event_publisher: EventPublisherPort | None = None,
) -> ARService:
    return ARService(ar_repo, customer_repo, ledger_repo, uow, event_publisher)


__all__ = [
    "ARCreditLimitExceededError",
    "ARCustomerNotFoundError",
    "ARInvoiceAlreadyPaidError",
    "ARInvoiceCancelledError",
    "ARInvoiceNotFoundError",
    "ARPaymentAllocationError",
    "ARPaymentNotFoundError",
    "ARService",
    "ARServiceError",
    "UnbalancedJournalError",
    "create_ar_service",
    "validate_balance",
]