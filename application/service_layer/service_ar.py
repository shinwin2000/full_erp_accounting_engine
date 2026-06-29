# service_ar.py - Complete rewrite with fixes (replace BadDebtProvisionRecordedEvent with JournalPostedEvent)

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
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.currency_vo import Currency
from domain.shared_value_objects.document_number_vo import DocumentNumber
from domain.subledger_ar.aggregate_root import ARAggregate
from domain.subledger_ar.aging_bucket_vo import ARAgingBucketCalculator
from domain.subledger_ar.bad_debt_provision_engine import BadDebtProvisionEngine
from domain.subledger_ar.credit_note_entity import ARCreditNote
from domain.subledger_ar.domain_events import (
    InvoiceIssuedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    PaymentReceivedEvent,
    PaymentVoidedEvent,
    CreditNoteIssuedEvent,
)
from domain.subledger_ar.invariants import ARInvariantsValidator
from domain.subledger_ar.invoice_entity import ARInvoice, ARInvoiceStatus, ARInvoiceType
from domain.subledger_ar.payment_entity import ARPayment, ARPaymentMethod, ARPaymentStatus
from ports.primary.ar_repository_port import ARRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort
from ports.primary.event_publisher_port import EventPublisherPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# Import JournalPostedEvent from application.events (it is registered)
from application.events import JournalPostedEvent

logger = logging.getLogger(__name__)


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

        logger.info("ARService initialized")

    # ========================================================================
    # Invoice Management
    # ========================================================================

    async def create_invoice(
        self, request: CreateARInvoiceRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Create a new AR invoice."""
        # Validate customer
        customer_agg = await self._customer_repo.get_customer_by_id(request.customer_id)
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

        logger.info(f"AR invoice {invoice_number} created for customer {customer.name}")
        return self._to_invoice_response(invoice)

    async def approve_invoice(
        self, invoice_id: UUID, approver_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Approve AR invoice."""
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

        return self._to_invoice_response(aggregate.invoice)

    async def cancel_invoice(
        self, invoice_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> ARInvoiceResponse:
        """Cancel an invoice."""
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

        return self._to_invoice_response(aggregate.invoice)

    # ========================================================================
    # Payment Management
    # ========================================================================

    async def record_payment(
        self, request: RecordARPaymentRequest, user_id: UUID, correlation_id: str | None = None
    ) -> list[ARPaymentResponse]:
        """Record customer payment."""
        customer_agg = await self._customer_repo.get_customer_by_id(request.customer_id)
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

        logger.info(f"Payment {payment_number} recorded for customer {customer_agg.customer.name}")
        return [self._to_payment_response(payment)]

    async def void_payment(
        self, payment_id: UUID, reason: str, user_id: UUID, correlation_id: str | None = None
    ) -> ARPaymentResponse:
        """Void a payment."""
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

        return self._to_payment_response(payment_agg.payment)

    # ========================================================================
    # Credit Notes
    # ========================================================================

    async def issue_credit_note(
        self, request: ARCreditNoteRequest, user_id: UUID, correlation_id: str | None = None
    ) -> ARCreditNoteResponse:
        """Issue a credit note to customer."""
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

        return self._to_credit_note_response(credit_note)

    # ========================================================================
    # Bad Debt Provision
    # ========================================================================

    async def calculate_bad_debt_provision(
        self, request: BadDebtProvisionRequest, user_id: UUID, correlation_id: str | None = None
    ) -> BadDebtProvisionResponse:
        """Calculate bad debt provision."""
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
        """Post bad debt expense journal."""
        expense_account = "5-5500"
        allowance_account = "1-1205"
        journal_id = await self._ledger_repo.post_journal(
            legal_entity_id=legal_entity_id,
            journal_date=as_of_date,
            period=f"{as_of_date.year}-{as_of_date.month:02d}",
            description="Bad debt provision",
            lines=[
                {"account_code": expense_account, "debit": amount, "credit": Decimal("0")},
                {"account_code": allowance_account, "debit": Decimal("0"), "credit": amount},
            ],
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
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ARInvoiceResponse]:
        """List invoices with filters."""
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
    "create_ar_service",
]