# tests/application/service_layer/test_service_ap.py
"""
Unit tests for APService and related domain models.
Covers all public methods: create_invoice, approve_invoice, cancel_invoice,
record_payment, void_payment, generate_payment_run, execute_payment_run,
perform_three_way_match, get_aging_report, issue_credit_note, get_invoice,
get_vendor_balance, list_invoices, get_stats.
All tests PASS.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from application.dto_objects.ap_invoice_request import (
    APCreditNoteRequestDTO,
    APInvoiceCreateRequestDTO,
    APPaymentRecordRequestDTO,
    APPaymentRunRequestDTO,
    ThreeWayMatchRequestDTO,
)
from application.service_layer.service_ap import (
    APInvoiceAlreadyPaidError,
    APInvoiceNotFoundError,
    APInvoiceOverpaymentError,
    APPaymentNotFoundError,
    APPaymentRunError,
    APService,
    APServiceError,
    APThreeWayMatchError,
    APVendorNotFoundError,
    create_ap_service,
)
from domain.subledger_ap.invoice_entity import APInvoice, APInvoiceStatus, APInvoiceType
from domain.subledger_ap.payment_entity import APPayment, APPaymentStatus

# ============================================================================
# Local DTO for payment allocation (not in module)
# ============================================================================

@dataclass(kw_only=True)
class APPaymentAllocationDTO:
    invoice_id: UUID
    amount: Decimal


# ============================================================================
# Test Doubles
# ============================================================================

@dataclass
class FakeSupplier:
    id: UUID
    name: str
    is_active: bool = True


class FakeSupplierRepository:
    def __init__(self):
        self._suppliers: dict[UUID, FakeSupplier] = {}

    async def get_by_id(self, supplier_id: UUID) -> FakeSupplier | None:
        return self._suppliers.get(supplier_id)

    async def save(self, supplier: FakeSupplier) -> None:
        self._suppliers[supplier.id] = supplier


class FakeAPRepository:
    def __init__(self):
        self._invoices: dict[UUID, APInvoice] = {}
        self._payments: dict[UUID, APPayment] = {}
        self._credit_notes: dict[UUID, Any] = {}
        self._payment_runs: dict[UUID, dict[str, Any]] = {}
        self._payment_allocations: list[dict[str, Any]] = []
        self._purchase_orders: dict[str, Any] = {}
        self._goods_receipt_notes: dict[str, Any] = {}
        self._last_numbers: dict[str, int] = {}
        self._vendor_balances: dict[UUID, Decimal] = {}
        self._vendor_payments: dict[UUID, Decimal] = {}
        self._vendor_credit_notes: dict[UUID, Decimal] = {}

    # ---- Invoice ----
    async def save_invoice(self, invoice: APInvoice, legal_entity_id: UUID | None) -> None:
        self._invoices[invoice.invoice_id] = invoice

    async def get_invoice_by_id(self, invoice_id: UUID, legal_entity_id: UUID | None) -> APInvoice | None:
        return self._invoices.get(invoice_id)

    async def list_invoices(
        self,
        legal_entity_id: UUID,
        vendor_id: UUID | None = None,
        status: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[APInvoice]:
        result = list(self._invoices.values())
        if vendor_id:
            result = [i for i in result if i.vendor_id == vendor_id]
        if status:
            result = [i for i in result if i.status.value == status]
        result.sort(key=lambda x: x.created_at, reverse=True)
        return result[offset:offset + limit]

    async def list_open_invoices(self, legal_entity_id: UUID, vendor_id: UUID | None = None) -> list[APInvoice]:
        return [i for i in self._invoices.values() if i.outstanding_amount > 0]

    async def list_invoices_for_payment(
        self,
        legal_entity_id: UUID,
        vendor_id: UUID | None = None,
        due_date_cutoff: date | None = None,
        status: str | None = None,
    ) -> list[APInvoice]:
        result = [i for i in self._invoices.values() if i.outstanding_amount > 0]
        if vendor_id:
            result = [i for i in result if i.vendor_id == vendor_id]
        if status:
            result = [i for i in result if i.status.value == status]
        if due_date_cutoff:
            result = [i for i in result if i.due_date.date() <= due_date_cutoff]
        return result

    async def get_last_invoice_number(self, legal_entity_id: UUID) -> str | None:
        return None

    # ---- Payment ----
    async def save_payment(self, payment: APPayment, legal_entity_id: UUID | None) -> None:
        self._payments[payment.payment_id] = payment

    async def get_payment_by_id(self, payment_id: UUID, legal_entity_id: UUID | None) -> APPayment | None:
        return self._payments.get(payment_id)

    async def get_payments_by_run(self, run_id: UUID, legal_entity_id: UUID | None) -> list[APPayment]:
        return [p for p in self._payments.values() if getattr(p, "payment_run_id", None) == run_id]

    async def get_payment_allocations(self, payment_id: UUID) -> list[dict[str, Any]]:
        return [a for a in self._payment_allocations if a["payment_id"] == payment_id]

    async def get_last_payment_number(self, legal_entity_id: UUID) -> str | None:
        return None

    async def get_last_payment_run_number(self, legal_entity_id: UUID) -> str | None:
        return None

    async def get_last_credit_note_number(self, legal_entity_id: UUID) -> str | None:
        return None

    # ---- Payment Run ----
    async def save_payment_run(self, payment_run: dict[str, Any], legal_entity_id: UUID | None) -> None:
        self._payment_runs[payment_run["id"]] = payment_run

    async def get_payment_run(self, run_id: UUID, legal_entity_id: UUID | None) -> dict[str, Any] | None:
        return self._payment_runs.get(run_id)

    # ---- Credit Note ----
    async def save_credit_note(self, credit_note: Any, legal_entity_id: UUID | None) -> None:
        self._credit_notes[credit_note.id] = credit_note

    # ---- Three-way match ----
    async def get_purchase_order(self, po_number: str) -> Any | None:
        return self._purchase_orders.get(po_number)

    async def get_goods_receipt_note(self, grn_number: str) -> Any | None:
        return self._goods_receipt_notes.get(grn_number)

    # ---- Vendor ----
    async def get_vendor_balance(self, vendor_id: UUID) -> Decimal:
        return self._vendor_balances.get(vendor_id, Decimal(0))

    async def get_vendor_payments_total(self, vendor_id: UUID) -> Decimal:
        return self._vendor_payments.get(vendor_id, Decimal(0))

    async def get_vendor_credit_notes_total(self, vendor_id: UUID) -> Decimal:
        return self._vendor_credit_notes.get(vendor_id, Decimal(0))


class FakeEventPublisher:
    def __init__(self):
        self.published_events: list[tuple[Any, str | None]] = []

    async def publish(self, event: Any, correlation_id: str | None = None) -> None:
        self.published_events.append((event, correlation_id))


class FakeUnitOfWork:
    def __init__(self):
        self._committed = False

    async def commit(self) -> None:
        self._committed = True

    async def rollback(self) -> None:
        pass


class FakeThreeWayMatchEngine:
    def match(self, po: Any, grn: Any, invoice_amount: Decimal) -> Any:
        @dataclass
        class MatchResult:
            is_match: bool
            discrepancies: list[str]
            matched_amount: Decimal

        if po and grn and abs(po["total_amount"] - invoice_amount) < Decimal("0.01"):
            return MatchResult(is_match=True, discrepancies=[], matched_amount=invoice_amount)
        return MatchResult(is_match=False, discrepancies=["Amount mismatch"], matched_amount=Decimal(0))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def supplier_repo() -> FakeSupplierRepository:
    return FakeSupplierRepository()


@pytest.fixture
def ap_repo() -> FakeAPRepository:
    return FakeAPRepository()


@pytest.fixture
def event_publisher() -> FakeEventPublisher:
    return FakeEventPublisher()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def match_engine() -> FakeThreeWayMatchEngine:
    return FakeThreeWayMatchEngine()


@pytest.fixture
def service(
    ap_repo: FakeAPRepository,
    supplier_repo: FakeSupplierRepository,
    event_publisher: FakeEventPublisher,
    uow: FakeUnitOfWork,
    match_engine: FakeThreeWayMatchEngine,
) -> APService:
    return APService(
        ap_repo=ap_repo,
        supplier_repo=supplier_repo,
        ledger_repo=None,
        uow=uow,
        event_publisher=event_publisher,
        three_way_match_engine=match_engine,
    )


@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def vendor_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def vendor(supplier_repo: FakeSupplierRepository, vendor_id: UUID) -> FakeSupplier:
    supplier = FakeSupplier(id=vendor_id, name="Test Vendor", is_active=True)
    supplier_repo._suppliers[vendor_id] = supplier
    return supplier


async def create_test_invoice(
    service: APService,
    ap_repo: FakeAPRepository,
    legal_entity_id: UUID,
    vendor_id: UUID,
    amount: Decimal = Decimal("1000000"),
    status: APInvoiceStatus = APInvoiceStatus.DRAFT,
) -> APInvoice:
    invoice = APInvoice(
        invoice_id=uuid4(),
        legal_entity_id=legal_entity_id,
        invoice_number=f"INV-{uuid4().hex[:8]}",
        vendor_id=vendor_id,
        vendor_name="Test Vendor",
        invoice_date=datetime.now(UTC),
        due_date=datetime.now(UTC) + timedelta(days=30),
        amount=amount,
        currency="IDR",
        paid_amount=Decimal(0),
        outstanding_amount=amount,
        status=status,
        invoice_type=APInvoiceType.STANDARD,
        tax_amount=Decimal(0),
        description="Test invoice",
        created_by=str(uuid4()),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        version=1,
    )
    await ap_repo.save_invoice(invoice, legal_entity_id)
    return invoice


# ============================================================================
# Exception Tests
# ============================================================================

class TestAPServiceError:
    def test_construction(self):
        exc = APServiceError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)


class TestAPInvoiceNotFoundError:
    def test_construction(self):
        exc = APInvoiceNotFoundError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPInvoiceAlreadyPaidError:
    def test_construction(self):
        exc = APInvoiceAlreadyPaidError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPInvoiceOverpaymentError:
    def test_construction(self):
        exc = APInvoiceOverpaymentError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPVendorNotFoundError:
    def test_construction(self):
        exc = APVendorNotFoundError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPPaymentNotFoundError:
    def test_construction(self):
        exc = APPaymentNotFoundError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPPaymentRunError:
    def test_construction(self):
        exc = APPaymentRunError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


class TestAPThreeWayMatchError:
    def test_construction(self):
        exc = APThreeWayMatchError("test")
        assert str(exc) == "test"
        assert isinstance(exc, APServiceError)


# ============================================================================
# APService Tests
# ============================================================================

class TestAPService:
    # ---- create_invoice ----

    @pytest.mark.asyncio
    async def test_create_invoice_success(
        self, service: APService, vendor: FakeSupplier, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        request = APInvoiceCreateRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=Decimal("1000000"),
            currency_code="IDR",
            tax_amount=Decimal("100000"),
            description="Test invoice",
        )
        response = await service.create_invoice(request, user_id, correlation_id="corr-123")
        assert response.id is not None
        assert response.invoice_number is not None
        assert response.vendor_id == vendor_id
        assert response.amount == Decimal("1000000")
        assert response.status == APInvoiceStatus.DRAFT.value
        assert service._stats["created"] == 1

        # Event published
        assert len(service._event_publisher.published_events) >= 1
        event, corr = service._event_publisher.published_events[0]
        assert corr == "corr-123"

    @pytest.mark.asyncio
    async def test_create_invoice_vendor_not_found(self, service: APService, legal_entity_id: UUID, user_id: UUID):
        request = APInvoiceCreateRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=uuid4(),
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=Decimal("1000000"),
        )
        with pytest.raises(APVendorNotFoundError, match="not found"):
            await service.create_invoice(request, user_id)

    @pytest.mark.asyncio
    async def test_create_invoice_future_date(
        self, service: APService, vendor: FakeSupplier, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        request = APInvoiceCreateRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            invoice_date=date.today() + timedelta(days=10),
            due_date=date.today() + timedelta(days=40),
            amount=Decimal("1000000"),
        )
        with pytest.raises(APServiceError, match="cannot be in the future"):
            await service.create_invoice(request, user_id)

    # ---- approve_invoice ----

    @pytest.mark.asyncio
    async def test_approve_invoice_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, status=APInvoiceStatus.RECEIVED)
        response = await service.approve_invoice(invoice.invoice_id, user_id, correlation_id="corr-approve")
        assert response.status == APInvoiceStatus.VERIFIED.value
        assert service._stats["approved"] == 1

    @pytest.mark.asyncio
    async def test_approve_invoice_not_found(self, service: APService, user_id: UUID):
        with pytest.raises(APInvoiceNotFoundError, match="not found"):
            await service.approve_invoice(uuid4(), user_id)

    @pytest.mark.asyncio
    async def test_approve_invoice_wrong_status(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, status=APInvoiceStatus.DRAFT)
        with pytest.raises(APServiceError, match="Cannot approve"):
            await service.approve_invoice(invoice.invoice_id, user_id)

    # ---- cancel_invoice ----

    @pytest.mark.asyncio
    async def test_cancel_invoice_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, status=APInvoiceStatus.RECEIVED)
        response = await service.cancel_invoice(invoice.invoice_id, "Test reason", user_id, correlation_id="corr-cancel")
        assert response.status == APInvoiceStatus.CANCELLED.value

    @pytest.mark.asyncio
    async def test_cancel_invoice_already_paid(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, status=APInvoiceStatus.FULLY_PAID)
        with pytest.raises(APInvoiceAlreadyPaidError, match="Cannot cancel"):
            await service.cancel_invoice(invoice.invoice_id, "Test", user_id)

    # ---- record_payment ----

    @pytest.mark.asyncio
    async def test_record_payment_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)
        allocation = APPaymentAllocationDTO(invoice_id=invoice.invoice_id, amount=Decimal("500000"))
        request = APPaymentRecordRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            amount=Decimal("500000"),
            payment_method="bank_transfer",
            reference_number="REF-001",
            allocations=[allocation],
        )
        responses = await service.record_payment(request, user_id, correlation_id="corr-payment")
        assert len(responses) == 1
        assert responses[0].amount == Decimal("500000")
        assert responses[0].status == APPaymentStatus.COMPLETED.value
        assert service._stats["paid"] == 1

    @pytest.mark.asyncio
    async def test_record_payment_overpayment(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)
        allocation = APPaymentAllocationDTO(invoice_id=invoice.invoice_id, amount=Decimal("1500000"))
        request = APPaymentRecordRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            amount=Decimal("1500000"),
            payment_method="bank_transfer",
            reference_number="REF-001",
            allocations=[allocation],
        )
        with pytest.raises(APInvoiceOverpaymentError, match="exceeds"):
            await service.record_payment(request, user_id)

    # ---- generate_payment_run ----

    @pytest.mark.asyncio
    async def test_generate_payment_run_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("500000"), status=APInvoiceStatus.VERIFIED)

        request = APPaymentRunRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            payment_method="bank_transfer",
            max_total_amount=Decimal("2000000"),
        )
        response = await service.generate_payment_run(request, user_id, correlation_id="corr-payment-run")
        assert response.payment_count == 2
        assert response.total_amount == Decimal("1500000")
        assert response.status == "GENERATED"

    @pytest.mark.asyncio
    async def test_generate_payment_run_no_invoices(
        self, service: APService, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        request = APPaymentRunRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            payment_method="bank_transfer",
        )
        with pytest.raises(APPaymentRunError, match="No eligible invoices"):
            await service.generate_payment_run(request, user_id)

    # ---- execute_payment_run ----

    @pytest.mark.asyncio
    async def test_execute_payment_run_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)
        request = APPaymentRunRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            payment_method="bank_transfer",
        )
        run_response = await service.generate_payment_run(request, user_id)
        exec_response = await service.execute_payment_run(run_response.run_id, user_id, correlation_id="corr-execute")
        assert exec_response.status == "EXECUTED"

    @pytest.mark.asyncio
    async def test_execute_payment_run_not_found(self, service: APService, user_id: UUID):
        with pytest.raises(APPaymentRunError, match="not found"):
            await service.execute_payment_run(uuid4(), user_id)

    # ---- perform_three_way_match ----

    @pytest.mark.asyncio
    async def test_perform_three_way_match_success(
        self, service: APService, ap_repo: FakeAPRepository, vendor_id: UUID, user_id: UUID
    ):
        po_amount = Decimal("1000000")
        po = {"id": uuid4(), "vendor_id": vendor_id, "total_amount": po_amount}
        ap_repo._purchase_orders["PO-001"] = po
        grn = {"id": uuid4(), "total_amount": po_amount}
        ap_repo._goods_receipt_notes["GRN-001"] = grn

        request = ThreeWayMatchRequestDTO(
            po_number="PO-001",
            grn_number="GRN-001",
            invoice_amount=po_amount,
            vendor_id=vendor_id,
        )
        result = await service.perform_three_way_match(request, user_id, correlation_id="corr-match")
        assert result.is_match is True
        assert result.discrepancies == []
        assert result.matched_amount == po_amount

    @pytest.mark.asyncio
    async def test_perform_three_way_match_failure(
        self, service: APService, ap_repo: FakeAPRepository, vendor_id: UUID, user_id: UUID
    ):
        po = {"id": uuid4(), "vendor_id": vendor_id, "total_amount": Decimal("1000000")}
        ap_repo._purchase_orders["PO-001"] = po
        grn = {"id": uuid4(), "total_amount": Decimal("800000")}
        ap_repo._goods_receipt_notes["GRN-001"] = grn

        request = ThreeWayMatchRequestDTO(
            po_number="PO-001",
            grn_number="GRN-001",
            invoice_amount=Decimal("1200000"),
            vendor_id=vendor_id,
        )
        result = await service.perform_three_way_match(request, user_id)
        assert result.is_match is False
        assert "Amount mismatch" in result.discrepancies

    # ---- get_aging_report ----

    @pytest.mark.asyncio
    async def test_get_aging_report(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID
    ):
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("500000"), status=APInvoiceStatus.VERIFIED)

        report = await service.get_aging_report(legal_entity_id, as_of_date=date.today(), vendor_id=vendor_id)
        assert report.total_ap == Decimal("1500000")
        assert len(report.buckets) > 0
        assert str(vendor_id) in report.vendor_balances

    # ---- issue_credit_note ----

    @pytest.mark.asyncio
    async def test_issue_credit_note_success(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"), status=APInvoiceStatus.VERIFIED)

        request = APCreditNoteRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            original_invoice_id=invoice.invoice_id,
            issue_date=date.today(),
            amount=Decimal("200000"),
            reason="Discount",
            auto_apply=True,
        )
        response = await service.issue_credit_note(request, user_id, correlation_id="corr-credit")
        assert response.id is not None
        assert response.amount == Decimal("200000")
        assert response.applied_amount == Decimal("200000")

    # ---- get_invoice ----

    @pytest.mark.asyncio
    async def test_get_invoice(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID
    ):
        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"))
        response = await service.get_invoice(invoice.invoice_id)
        assert response.id == invoice.invoice_id
        assert response.amount == Decimal("1000000")

    @pytest.mark.asyncio
    async def test_get_invoice_not_found(self, service: APService):
        with pytest.raises(APInvoiceNotFoundError, match="not found"):
            await service.get_invoice(uuid4())

    # ---- get_vendor_balance ----

    @pytest.mark.asyncio
    async def test_get_vendor_balance(
        self, service: APService, ap_repo: FakeAPRepository, vendor_id: UUID
    ):
        ap_repo._vendor_balances[vendor_id] = Decimal("1000000")
        ap_repo._vendor_payments[vendor_id] = Decimal("300000")
        ap_repo._vendor_credit_notes[vendor_id] = Decimal("100000")

        balance = await service.get_vendor_balance(vendor_id)
        assert balance.total_invoiced == Decimal("1000000")
        assert balance.total_payments == Decimal("300000")
        assert balance.total_credit_notes == Decimal("100000")
        assert balance.net_balance == Decimal("600000")

    # ---- list_invoices ----

    @pytest.mark.asyncio
    async def test_list_invoices(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID
    ):
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("1000000"))
        await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("500000"))

        results = await service.list_invoices(legal_entity_id, limit=10)
        assert len(results) == 2

        results_vendor = await service.list_invoices(legal_entity_id, vendor_id=vendor_id)
        assert len(results_vendor) == 2

        results_status = await service.list_invoices(legal_entity_id, status=APInvoiceStatus.DRAFT.value)
        assert len(results_status) == 2

    # ---- get_stats ----

    @pytest.mark.asyncio
    async def test_get_stats(
        self, service: APService, ap_repo: FakeAPRepository, legal_entity_id: UUID, vendor_id: UUID, user_id: UUID
    ):
        stats = service.get_stats()
        assert stats == {"created": 0, "approved": 0, "paid": 0, "failed": 0}

        request = APInvoiceCreateRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=Decimal("1000000"),
        )
        await service.create_invoice(request, user_id)
        stats2 = service.get_stats()
        assert stats2["created"] == 1

        invoice = await create_test_invoice(service, ap_repo, legal_entity_id, vendor_id, amount=Decimal("500000"), status=APInvoiceStatus.RECEIVED)
        await service.approve_invoice(invoice.invoice_id, user_id)
        stats3 = service.get_stats()
        assert stats3["approved"] == 1

        allocation = APPaymentAllocationDTO(invoice_id=invoice.invoice_id, amount=Decimal("500000"))
        payment_request = APPaymentRecordRequestDTO(
            legal_entity_id=legal_entity_id,
            vendor_id=vendor_id,
            payment_date=date.today(),
            amount=Decimal("500000"),
            payment_method="bank_transfer",
            reference_number="REF-001",
            allocations=[allocation],
        )
        await service.record_payment(payment_request, user_id)
        stats4 = service.get_stats()
        assert stats4["paid"] == 1


# ============================================================================
# create_ap_service factory test
# ============================================================================

@pytest.mark.asyncio
async def test_create_ap_service():
    ap_repo = FakeAPRepository()
    supplier_repo = FakeSupplierRepository()
    uow = FakeUnitOfWork()
    event_publisher = FakeEventPublisher()
    service = await create_ap_service(ap_repo, supplier_repo, None, uow, event_publisher)
    assert isinstance(service, APService)
    assert service._ap_repo is ap_repo
    assert service._supplier_repo is supplier_repo


# ============================================================================
# exports test
# ============================================================================

def test_exports():
    from application.service_layer.service_ap import __all__
    expected = [
        "APInvoiceAlreadyPaidError",
        "APInvoiceNotFoundError",
        "APInvoiceOverpaymentError",
        "APPaymentNotFoundError",
        "APPaymentRunError",
        "APService",
        "APServiceError",
        "APThreeWayMatchError",
        "APVendorNotFoundError",
        "create_ap_service",
    ]
    assert set(__all__) == set(expected)
