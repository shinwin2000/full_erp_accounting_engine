#!/usr/bin/env python3
"""
Unit: Accounts Receivable Service
Menguji service AR: invoice, aging, collection, bad debt provision.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from application.service_layer.service_ar import (
    ARService,
    BadDebtProvisionRequest,
    CreateARInvoiceRequest,
    RecordARPaymentRequest,
)
from domain.subledger_ar.aging_bucket_vo import AgingBucket, AgingBucketVO
from ports.primary.ar_repository_port import ARRepositoryPort
from ports.primary.customer_repository_port import CustomerRepositoryPort
from ports.primary.ledger_repository_port import LedgerRepositoryPort
from ports.primary.unit_of_work_port import UnitOfWorkPort

# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_ar_repo():
    repo = AsyncMock(spec=ARRepositoryPort)
    repo.save_invoice = AsyncMock()
    repo.get_invoice_by_id = AsyncMock()
    repo.save_payment = AsyncMock()
    repo.get_payment_by_id = AsyncMock()
    repo.get_payment_allocations = AsyncMock(return_value=[])
    repo.list_open_invoices = AsyncMock(return_value=[])
    repo.get_customer_outstanding = AsyncMock(return_value=Decimal(0))
    repo.get_total_receivables = AsyncMock(return_value=Decimal(0))
    repo.get_last_invoice_number = AsyncMock(return_value=None)
    repo.get_last_payment_number = AsyncMock(return_value=None)
    repo.get_last_credit_note_number = AsyncMock(return_value=None)
    repo.save_credit_note = AsyncMock()
    repo.list_invoices = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_customer_repo():
    repo = AsyncMock(spec=CustomerRepositoryPort)
    repo.get_customer_by_id = AsyncMock()
    customer_agg = MagicMock()
    customer_agg.customer = MagicMock()
    customer_agg.customer.id = uuid4()
    customer_agg.customer.name = "PT Customer"
    customer_agg.customer.is_active = True
    customer_agg.customer.credit_limit = Decimal(100_000_000)
    repo.get_customer_by_id.return_value = customer_agg
    return repo


@pytest.fixture
def mock_ledger_repo():
    repo = AsyncMock(spec=LedgerRepositoryPort)
    repo.post_journal = AsyncMock(return_value=uuid4())
    return repo


@pytest.fixture
def mock_uow():
    uow = MagicMock(spec=UnitOfWorkPort)
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    return uow


@pytest.fixture
def service(mock_ar_repo, mock_customer_repo, mock_ledger_repo, mock_uow):
    return ARService(
        ar_repo=mock_ar_repo,
        customer_repo=mock_customer_repo,
        ledger_repo=mock_ledger_repo,
        uow=mock_uow,
        event_publisher=None,
    )


# ============================================================================
# TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_create_invoice(service, mock_ar_repo, mock_customer_repo, mock_uow):
    """Test create invoice - patch ARInvoice dan ARAggregate."""
    customer_id = mock_customer_repo.get_customer_by_id.return_value.customer.id
    request = CreateARInvoiceRequest(
        legal_entity_id=uuid4(),
        customer_id=customer_id,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        amount=Decimal("10000000"),
    )
    user_id = uuid4()

    with (
        patch("application.service_layer.service_ar.ARInvoice") as MockInvoice,
        patch("application.service_layer.service_ar.ARAggregate") as MockAggregate,
    ):
        mock_invoice = MagicMock()
        mock_invoice.id = uuid4()
        MockInvoice.return_value = mock_invoice

        mock_aggregate = MagicMock()
        MockAggregate.return_value = mock_aggregate

        response = await service.create_invoice(request, user_id)

        assert response.id is not None
        mock_ar_repo.save_invoice.assert_called_once()
        mock_uow.commit.assert_called_once()


@pytest.mark.asyncio
async def test_aging_buckets_calculation(service, mock_ar_repo):
    """Test aging buckets dengan mock aging calculator."""
    today = date.today()

    class DummyInvoice:
        def __init__(self, amount, due_date, remaining_amount, customer_id):
            self.amount = amount
            self.due_date = due_date
            self.remaining_amount = remaining_amount
            self.customer_id = customer_id

    cid = uuid4()
    inv1 = DummyInvoice(
        Decimal("1000000"),
        today - timedelta(days=10),
        Decimal("1000000"),
        cid,
    )
    inv2 = DummyInvoice(
        Decimal("2000000"),
        today - timedelta(days=35),
        Decimal("2000000"),
        cid,
    )
    inv3 = DummyInvoice(
        Decimal("3000000"),
        today + timedelta(days=5),
        Decimal("3000000"),
        cid,
    )
    mock_ar_repo.list_open_invoices.return_value = [inv1, inv2, inv3]

    mock_calculator = MagicMock()
    mock_calculator.calculate.return_value = [
        AgingBucketVO(AgingBucket.DAYS_1_30, Decimal("1000000")),
        AgingBucketVO(AgingBucket.DAYS_31_60, Decimal("2000000")),
        AgingBucketVO(AgingBucket.CURRENT, Decimal("3000000")),
    ]
    service._aging_calculator = mock_calculator

    report = await service.get_aging_report(
        legal_entity_id=uuid4(), as_of_date=today
    )

    assert report.total_ar == Decimal("6000000")
    assert len(report.buckets) == 3
    mock_calculator.calculate.assert_called_once()


@pytest.mark.asyncio
async def test_record_collection(
    service, mock_ar_repo, mock_customer_repo
):
    """Test record payment - patch ARAggregate."""
    invoice_id = uuid4()
    customer_id = uuid4()

    customer_agg = MagicMock()
    customer_agg.customer.name = "Test Customer"
    mock_customer_repo.get_customer_by_id.return_value = customer_agg

    invoice_agg = MagicMock()
    invoice_agg.invoice = MagicMock()
    invoice_agg.invoice.remaining_amount = Decimal("1000000")
    invoice_agg.apply_payment = MagicMock()
    mock_ar_repo.get_invoice_by_id.return_value = invoice_agg

    with patch("application.service_layer.service_ar.ARAggregate") as MockAggregate:
        mock_agg = MagicMock()
        MockAggregate.return_value = mock_agg

        request = RecordARPaymentRequest(
            legal_entity_id=uuid4(),
            customer_id=customer_id,
            payment_date=date.today(),
            amount=Decimal("600000"),
            payment_method="bank_transfer",
            allocations=[
                {
                    "invoice_id": invoice_id,
                    "amount": Decimal("600000"),
                }
            ],
        )
        user_id = uuid4()

        responses = await service.record_payment(request, user_id)

        assert len(responses) == 1
        assert responses[0].amount == Decimal("600000")
        mock_ar_repo.save_invoice.assert_called()
        mock_ar_repo.save_payment.assert_called()


@pytest.mark.asyncio
async def test_bad_debt_provision(service, mock_ar_repo):
    """Test bad debt provision calculation."""
    mock_ar_repo.get_total_receivables = AsyncMock(
        return_value=Decimal("5000000")
    )
    request = BadDebtProvisionRequest(
        legal_entity_id=uuid4(),
        as_of_date=date.today(),
        provision_rate=Decimal("0.5"),
    )
    response = await service.calculate_bad_debt_provision(request, uuid4())
    assert response.total_receivables == Decimal("5000000")
    assert response.provision_amount == Decimal("2500000")
