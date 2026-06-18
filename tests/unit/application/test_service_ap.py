#!/usr/bin/env python3
"""
Unit: Accounts Payable Service - FULLY FIXED FINAL
Semua test lulus dengan mock yang tepat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from uuid import UUID, uuid4

import pytest

# ============================================================================
# DTOs (dipindahkan ke level modul)
# ============================================================================


@dataclass(kw_only=True)
class APInvoiceCreateRequestDTO:
    legal_entity_id: UUID
    vendor_id: UUID
    invoice_date: date
    due_date: date
    amount: Decimal
    tax_amount: Decimal = Decimal(0)
    description: str = ""
    currency_code: str = "IDR"
    po_number: str | None = None
    grn_number: str | None = None


@dataclass(kw_only=True)
class APPaymentRecordAllocationDTO:
    invoice_id: UUID
    amount: Decimal


@dataclass(kw_only=True)
class APPaymentRecordRequestDTO:
    legal_entity_id: UUID
    vendor_id: UUID
    payment_date: date
    amount: Decimal
    payment_method: str
    reference_number: str
    bank_account_id: UUID
    allocations: list[APPaymentRecordAllocationDTO]


@dataclass(kw_only=True)
class APPaymentRunRequestDTO:
    legal_entity_id: UUID
    payment_date: date
    payment_method: str
    bank_account_id: UUID
    max_total_amount: Decimal | None = None
    vendor_id: UUID | None = None


@dataclass(kw_only=True)
class ThreeWayMatchRequestDTO:
    po_number: str
    grn_number: str
    invoice_amount: Decimal
    vendor_id: UUID


@dataclass(kw_only=True)
class APCreditNoteRequestDTO:
    legal_entity_id: UUID
    vendor_id: UUID
    original_invoice_id: UUID | None
    issue_date: date
    amount: Decimal
    reason: str
    auto_apply: bool = True


# ============================================================================
# Imports dari aplikasi (diletakkan setelah DTO untuk menghindari circular)
# ============================================================================

from application.service_layer.service_ap import (
    APInvoiceAlreadyPaidError,
    APInvoiceNotFoundError,
    APInvoiceOverpaymentError,
    APPaymentRunError,
    APService,
    APThreeWayMatchError,
    APVendorNotFoundError,
)
from domain.subledger_ap.invoice_entity import APInvoiceStatus
from domain.subledger_ap.payment_entity import APPaymentStatus

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def mock_ap_repo():
    repo = AsyncMock()
    repo.save_invoice = AsyncMock()
    repo.get_invoice_by_id = AsyncMock()
    repo.save_payment = AsyncMock()
    repo.get_payment_by_id = AsyncMock()
    repo.get_payment_allocations = AsyncMock(return_value=[])
    repo.save_payment_run = AsyncMock()
    repo.get_payment_run = AsyncMock()
    repo.get_payments_by_run = AsyncMock(return_value=[])
    repo.list_invoices_for_payment = AsyncMock(return_value=[])
    repo.list_open_invoices = AsyncMock(return_value=[])
    repo.list_invoices = AsyncMock(return_value=[])
    repo.get_vendor_balance = AsyncMock(return_value=Decimal(0))
    repo.get_vendor_payments_total = AsyncMock(return_value=Decimal(0))
    repo.get_vendor_credit_notes_total = AsyncMock(return_value=Decimal(0))
    repo.save_credit_note = AsyncMock()
    repo.get_purchase_order = AsyncMock()
    repo.get_goods_receipt_note = AsyncMock()
    repo.get_last_invoice_number = AsyncMock(return_value=None)
    repo.get_last_payment_number = AsyncMock(return_value=None)
    repo.get_last_payment_run_number = AsyncMock(return_value=None)
    repo.get_last_credit_note_number = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_supplier_repo():
    repo = AsyncMock()
    supplier_agg = Mock()
    supplier_agg.supplier = Mock()
    supplier_agg.supplier.id = uuid4()
    supplier_agg.supplier.name = "PT Test Supplier"
    supplier_agg.supplier.is_active = True
    repo.get_by_id.return_value = supplier_agg
    return repo


@pytest.fixture
def mock_ledger_repo():
    return AsyncMock()


@pytest.fixture
def mock_uow():
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    return uow


@pytest.fixture
def service(mock_ap_repo, mock_supplier_repo, mock_ledger_repo, mock_uow):
    return APService(
        ap_repo=mock_ap_repo,
        supplier_repo=mock_supplier_repo,
        ledger_repo=mock_ledger_repo,
        uow=mock_uow,
        event_publisher=None,
    )


# ============================================================================
# TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_create_invoice_success(service, mock_ap_repo, mock_uow):
    request = APInvoiceCreateRequestDTO(
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        amount=Decimal("5000000"),
        tax_amount=Decimal("550000"),
        description="Test invoice",
        currency_code="IDR",
        po_number=None,
        grn_number=None,
    )
    user_id = uuid4()
    response = await service.create_invoice(request, user_id)
    assert response.id is not None
    assert response.invoice_number.startswith("AP-")
    mock_ap_repo.save_invoice.assert_called_once()
    mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_create_invoice_vendor_not_found(service, mock_supplier_repo):
    mock_supplier_repo.get_by_id.return_value = None
    request = APInvoiceCreateRequestDTO(
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        amount=Decimal("5000000"),
        tax_amount=Decimal("550000"),
        description="Test",
        currency_code="IDR",
        po_number=None,
        grn_number=None,
    )
    with pytest.raises(APVendorNotFoundError):
        await service.create_invoice(request, uuid4())


@pytest.mark.asyncio
async def test_create_invoice_inactive_vendor(service, mock_supplier_repo):
    supplier_agg = Mock()
    supplier_agg.supplier.is_active = False
    mock_supplier_repo.get_by_id.return_value = supplier_agg
    request = APInvoiceCreateRequestDTO(
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        amount=Decimal("5000000"),
        tax_amount=Decimal("550000"),
        description="Test",
        currency_code="IDR",
        po_number=None,
        grn_number=None,
    )
    with pytest.raises(APVendorNotFoundError):
        await service.create_invoice(request, uuid4())


@pytest.mark.asyncio
async def test_create_invoice_three_way_match_success(service, mock_ap_repo, mock_uow):
    po_mock = Mock()
    po_mock.total_amount = Decimal("5000000")
    po_mock.vendor_id = uuid4()
    grn_mock = Mock()
    grn_mock.total_amount = Decimal("5000000")
    mock_ap_repo.get_purchase_order = AsyncMock(return_value=po_mock)
    mock_ap_repo.get_goods_receipt_note = AsyncMock(return_value=grn_mock)

    with patch.object(service._match_engine, "match") as mock_match:
        mock_match.return_value = Mock(is_match=True, discrepancies=[])
        request = APInvoiceCreateRequestDTO(
            legal_entity_id=uuid4(),
            vendor_id=po_mock.vendor_id,
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=Decimal("5000000"),
            tax_amount=Decimal("550000"),
            description="Test",
            currency_code="IDR",
            po_number="PO-001",
            grn_number="GRN-001",
        )
        response = await service.create_invoice(request, uuid4())
        assert response.id is not None
        mock_uow.commit.assert_called_once()
        mock_match.assert_called_once()


@pytest.mark.asyncio
async def test_create_invoice_three_way_match_fails(service, mock_ap_repo):
    po_mock = Mock()
    po_mock.total_amount = Decimal("5000000")
    po_mock.vendor_id = uuid4()
    grn_mock = Mock()
    grn_mock.total_amount = Decimal("5000000")
    mock_ap_repo.get_purchase_order = AsyncMock(return_value=po_mock)
    mock_ap_repo.get_goods_receipt_note = AsyncMock(return_value=grn_mock)

    with patch.object(service._match_engine, "match") as mock_match:
        mock_match.return_value = Mock(is_match=False, discrepancies=["Vendor mismatch"])
        request = APInvoiceCreateRequestDTO(
            legal_entity_id=uuid4(),
            vendor_id=uuid4(),
            invoice_date=date.today(),
            due_date=date.today() + timedelta(days=30),
            amount=Decimal("5000000"),
            tax_amount=Decimal("550000"),
            description="Test",
            currency_code="IDR",
            po_number="PO-001",
            grn_number="GRN-001",
        )
        with pytest.raises(APThreeWayMatchError):
            await service.create_invoice(request, uuid4())


@pytest.mark.asyncio
async def test_approve_invoice_success(service, mock_ap_repo, mock_uow):
    invoice_mock = Mock()
    invoice_mock.status = APInvoiceStatus.RECEIVED
    invoice_mock.verify = Mock(return_value=Mock(status=APInvoiceStatus.VERIFIED))
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)

    response = await service.approve_invoice(uuid4(), uuid4())
    assert response.status == APInvoiceStatus.VERIFIED.value
    mock_ap_repo.save_invoice.assert_called_once()
    mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_approve_invoice_not_found(service, mock_ap_repo):
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=None)
    with pytest.raises(APInvoiceNotFoundError):
        await service.approve_invoice(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_cancel_invoice_success(service, mock_ap_repo, mock_uow):
    invoice_mock = Mock()
    invoice_mock.paid_amount = Decimal(0)
    invoice_mock.status = APInvoiceStatus.DRAFT
    invoice_mock.cancel = Mock(return_value=Mock(status=APInvoiceStatus.CANCELLED))
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)

    response = await service.cancel_invoice(uuid4(), "Testing", uuid4())
    assert response.status == APInvoiceStatus.CANCELLED.value
    mock_ap_repo.save_invoice.assert_called_once()
    mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_invoice_already_paid(service, mock_ap_repo):
    invoice_mock = Mock()
    invoice_mock.paid_amount = Decimal("500000")
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)
    with pytest.raises(APInvoiceAlreadyPaidError):
        await service.cancel_invoice(uuid4(), "Test", uuid4())


@pytest.mark.asyncio
async def test_record_payment_success(service, mock_ap_repo, mock_uow):
    invoice_mock = Mock()
    invoice_mock.outstanding_amount = Decimal("10000000")
    invoice_mock.record_payment = Mock(return_value=invoice_mock)
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)

    request = APPaymentRecordRequestDTO(
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        payment_date=date.today(),
        amount=Decimal("10000000"),
        payment_method="bank_transfer",
        reference_number="REF-001",
        bank_account_id=uuid4(),
        allocations=[
            APPaymentRecordAllocationDTO(
                invoice_id=uuid4(),
                amount=Decimal("10000000"),
            )
        ],
    )

    supplier_agg = Mock()
    supplier_agg.supplier.name = "Test Supplier"
    service._supplier_repo.get_by_id = AsyncMock(return_value=supplier_agg)

    with patch("application.service_layer.service_ap.APPaymentMethod"):
        responses = await service.record_payment(request, uuid4())
        assert len(responses) == 1
        assert responses[0].amount == Decimal("10000000")
        mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_record_payment_overpayment(service, mock_ap_repo):
    invoice_mock = Mock()
    invoice_mock.outstanding_amount = Decimal("200000")
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)

    request = APPaymentRecordRequestDTO(
        legal_entity_id=uuid4(),
        vendor_id=uuid4(),
        payment_date=date.today(),
        amount=Decimal("500000"),
        payment_method="bank_transfer",
        reference_number="REF-001",
        bank_account_id=uuid4(),
        allocations=[
            APPaymentRecordAllocationDTO(
                invoice_id=uuid4(),
                amount=Decimal("500000"),
            )
        ],
    )
    supplier_agg = Mock()
    supplier_agg.supplier.name = "Test Supplier"
    service._supplier_repo.get_by_id = AsyncMock(return_value=supplier_agg)

    with patch("application.service_layer.service_ap.APPaymentMethod"):
        with pytest.raises(APInvoiceOverpaymentError):
            await service.record_payment(request, uuid4())


@pytest.mark.asyncio
async def test_void_payment_success(service, mock_ap_repo, mock_uow):
    payment_mock = Mock()
    payment_mock.status = APPaymentStatus.PENDING
    payment_mock.payment_number = "PYMT-001"
    mock_ap_repo.get_payment_by_id = AsyncMock(return_value=payment_mock)
    mock_ap_repo.get_payment_allocations = AsyncMock(return_value=[])

    response = await service.void_payment(uuid4(), "Wrong amount", uuid4())
    assert response.status == APPaymentStatus.VOIDED.value
    mock_ap_repo.save_payment.assert_called()
    mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_generate_payment_run_success(service, mock_ap_repo, mock_uow):
    invoice_mock = Mock()
    invoice_mock.outstanding_amount = Decimal("5000000")
    invoice_mock.vendor_id = uuid4()
    mock_ap_repo.list_invoices_for_payment = AsyncMock(return_value=[invoice_mock])
    mock_ap_repo.save_payment = AsyncMock()
    mock_ap_repo.save_payment_run = AsyncMock()

    request = APPaymentRunRequestDTO(
        legal_entity_id=uuid4(),
        payment_date=date.today(),
        payment_method="bank_transfer",
        bank_account_id=uuid4(),
        max_total_amount=None,
        vendor_id=None,
    )
    with patch("application.service_layer.service_ap.APPaymentMethod"):
        response = await service.generate_payment_run(request, uuid4())
        assert response.total_amount == Decimal("5000000")
        assert response.payment_count == 1
        mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_generate_payment_run_no_invoices(service, mock_ap_repo):
    mock_ap_repo.list_invoices_for_payment = AsyncMock(return_value=[])
    request = APPaymentRunRequestDTO(
        legal_entity_id=uuid4(),
        payment_date=date.today(),
        payment_method="bank_transfer",
        bank_account_id=uuid4(),
        max_total_amount=None,
        vendor_id=None,
    )
    with pytest.raises(APPaymentRunError):
        await service.generate_payment_run(request, uuid4())


@pytest.mark.asyncio
async def test_execute_payment_run_success(service, mock_ap_repo, mock_uow):
    payment_run = {
        "id": uuid4(),
        "run_number": "PR-2025-00001",
        "run_date": date.today(),
        "total_amount": Decimal("5000000"),
        "payment_count": 1,
        "status": "GENERATED",
        "created_by": uuid4(),
        "created_at": datetime.now(),
    }
    payment_mock = Mock()
    payment_mock.status = APPaymentStatus.SCHEDULED
    mock_ap_repo.get_payment_run = AsyncMock(return_value=payment_run)
    mock_ap_repo.get_payments_by_run = AsyncMock(return_value=[payment_mock])
    mock_ap_repo.save_payment = AsyncMock()
    mock_ap_repo.save_payment_run = AsyncMock()

    response = await service.execute_payment_run(payment_run["id"], uuid4())
    assert response.status == "EXECUTED"
    mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_execute_payment_run_not_found(service, mock_ap_repo):
    mock_ap_repo.get_payment_run = AsyncMock(return_value=None)
    with pytest.raises(APPaymentRunError):
        await service.execute_payment_run(uuid4(), uuid4())


@pytest.mark.asyncio
async def test_perform_three_way_match(service, mock_ap_repo):
    po_mock = Mock()
    po_mock.total_amount = Decimal("10000000")
    po_mock.vendor_id = uuid4()
    grn_mock = Mock()
    grn_mock.total_amount = Decimal("10000000")
    mock_ap_repo.get_purchase_order = AsyncMock(return_value=po_mock)
    mock_ap_repo.get_goods_receipt_note = AsyncMock(return_value=grn_mock)

    with patch.object(service._match_engine, "match") as mock_match:
        mock_match.return_value = Mock(is_match=True, discrepancies=[])
        request = ThreeWayMatchRequestDTO(
            po_number="PO-001",
            grn_number="GRN-001",
            invoice_amount=Decimal("10000000"),
            vendor_id=po_mock.vendor_id,
        )
        result = await service.perform_three_way_match(request)
        assert result.is_match is True
        mock_match.assert_called_once()


@pytest.mark.asyncio
async def test_get_aging_report(service, mock_ap_repo):
    now = datetime.now()
    vendor_id_1 = uuid4()
    vendor_id_2 = uuid4()

    class DummyInvoice:
        def __init__(self, due_date, amount, vendor_id):
            self.due_date = due_date
            self.outstanding_amount = amount
            self.vendor_id = vendor_id

    inv1 = DummyInvoice(now - timedelta(days=10), Decimal("5000000"), vendor_id_1)
    inv2 = DummyInvoice(now - timedelta(days=45), Decimal("3000000"), vendor_id_2)

    mock_ap_repo.list_open_invoices = AsyncMock(return_value=[inv1, inv2])

    report = await service.get_aging_report(uuid4(), as_of_date=date.today())

    assert report.total_ap == Decimal("8000000")
    bucket_dict = {b.bucket.value: b.amount for b in report.buckets}
    assert bucket_dict.get("1_30_days") == Decimal("5000000")
    assert bucket_dict.get("31_60_days") == Decimal("3000000")
    assert len(report.vendor_balances) == 2


@pytest.mark.asyncio
async def test_issue_credit_note_success(service, mock_ap_repo, mock_uow):
    invoice_mock = Mock()
    invoice_mock.outstanding_amount = Decimal("10000000")
    invoice_mock.updated_at = datetime.now()
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)

    with patch("application.service_layer.service_ap.APCreditNote") as MockCreditNote:
        mock_credit_note = Mock()
        mock_credit_note.id = uuid4()
        mock_credit_note.credit_note_number = Mock()
        mock_credit_note.credit_note_number.value = "APCN-2025-00001"
        mock_credit_note.vendor_id = uuid4()
        mock_credit_note.original_invoice_id = uuid4()
        mock_credit_note.issue_date = date.today()
        mock_credit_note.amount = Decimal("5000000")
        mock_credit_note.applied_amount = Decimal("0")
        mock_credit_note.remaining_amount = Decimal("5000000")
        mock_credit_note.reason = "Product return"
        mock_credit_note.created_at = datetime.now()
        MockCreditNote.return_value = mock_credit_note

        request = APCreditNoteRequestDTO(
            legal_entity_id=uuid4(),
            vendor_id=uuid4(),
            original_invoice_id=uuid4(),
            issue_date=date.today(),
            amount=Decimal("5000000"),
            reason="Product return",
            auto_apply=True,
        )
        response = await service.issue_credit_note(request, uuid4())
        assert response.credit_note_number.startswith("APCN-")
        assert response.amount == Decimal("5000000")
        mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_get_vendor_balance(service, mock_ap_repo):
    mock_ap_repo.get_vendor_balance = AsyncMock(return_value=Decimal("10000000"))
    mock_ap_repo.get_vendor_payments_total = AsyncMock(return_value=Decimal("3000000"))
    mock_ap_repo.get_vendor_credit_notes_total = AsyncMock(return_value=Decimal("1000000"))
    balance = await service.get_vendor_balance(uuid4())
    assert balance.total_invoiced == Decimal("10000000")
    assert balance.total_payments == Decimal("3000000")
    assert balance.total_credit_notes == Decimal("1000000")
    assert balance.net_balance == Decimal("6000000")


@pytest.mark.asyncio
async def test_list_invoices(service, mock_ap_repo):
    invoice_mock = Mock()
    invoice_mock.invoice_number = "INV-001"
    invoice_mock.amount = Decimal("5000000")
    invoice_mock.status = APInvoiceStatus.VERIFIED
    mock_ap_repo.list_invoices = AsyncMock(return_value=[invoice_mock])
    invoices = await service.list_invoices(uuid4(), limit=10, offset=0)
    assert len(invoices) == 1
    assert invoices[0].invoice_number == "INV-001"


@pytest.mark.asyncio
async def test_get_invoice(service, mock_ap_repo):
    invoice_mock = Mock()
    invoice_mock.invoice_number = "INV-001"
    invoice_mock.amount = Decimal("5000000")
    invoice_mock.status = APInvoiceStatus.VERIFIED
    mock_ap_repo.get_invoice_by_id = AsyncMock(return_value=invoice_mock)
    response = await service.get_invoice(uuid4())
    assert response.invoice_number == "INV-001"
    assert response.amount == Decimal("5000000")
