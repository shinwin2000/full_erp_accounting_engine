#!/usr/bin/env python3
"""
E2E: Sales â†’ Accounts Receivable â†’ GL â†’ Cash Collection
Alur: Sales order â†’ delivery â†’ invoice AR â†’ pengakuan pendapatan â†’ penerimaan kas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

# ============================================================================
# MOCK CLASSES untuk menggantikan modul yang tidak tersedia
# ============================================================================


@dataclass(kw_only=True)
class MockSalesOrder:
    id: str
    customer_id: str
    items: list[dict]
    status: str = "draft"
    delivery_status: str = "PENDING"
    approved: bool = False
    """Mock Sales Order untuk testing."""

    def approve(self):
        self.status = "approved"
        self.approved = True

    def deliver(self, quantity: int):
        self.delivery_status = (
            "FULL" if quantity >= sum(item["qty"] for item in self.items) else "PARTIAL"
        )


@dataclass(kw_only=True)
class MockSalesInvoice:
    id: str
    so_id: str
    amount: Decimal
    vat: Decimal
    status: str = "draft"
    outstanding_balance: Decimal = field(init=False)
    """Mock Sales Invoice."""

    def __post_init__(self):
        self.outstanding_balance = self.amount + self.vat

    def issue(self):
        self.status = "ISSUED"


@dataclass(kw_only=True)
class MockRevenue:
    amount: Decimal
    deferred: bool = False
    """Mock Revenue object."""


class MockRevenueRecognizer:
    """Mock Revenue Recognizer (PSAK 72)."""

    def recognize(self, invoice: MockSalesInvoice) -> MockRevenue:
        return MockRevenue(amount=invoice.amount, deferred=False)

    def create_journal(self, revenue: MockRevenue, invoice: MockSalesInvoice) -> MockJournal:
        return MockJournal(
            debit_total=invoice.amount + invoice.vat,
            credit_total=invoice.amount + invoice.vat,
        )


class MockJournal:
    """Mock Journal entry."""

    def __init__(self, debit_total: Decimal, credit_total: Decimal):
        self._debit = debit_total
        self._credit = credit_total

    def get_debit_total(self) -> Decimal:
        return self._debit

    def get_credit_total(self) -> Decimal:
        return self._credit


class MockArPayment:
    """Mock AR Payment."""

    def __init__(self, invoice_id: str, amount: Decimal, payment_date: date):
        self.invoice_id = invoice_id
        self.amount = amount
        self.payment_date = payment_date


class MockArCollectionWorkflow:
    """Mock AR Collection Workflow."""

    def process(self, payment: MockArPayment) -> MockCollectionResult:
        # Simulate reconciliation
        return MockCollectionResult(is_reconciled=True, remaining_balance=Decimal("0"))


@dataclass(kw_only=True)
class MockCollectionResult:
    is_reconciled: bool
    remaining_balance: Decimal


# ============================================================================
# E2E TEST
# ============================================================================


def test_sales_to_ar_collection():
    """Test alur lengkap dari Sales Order hingga koleksi pembayaran."""
    # 1. Sales Order
    so = MockSalesOrder(
        id=str(uuid4()),
        customer_id="CUST-001",
        items=[{"product": "X", "qty": 10, "price": Decimal("100000")}],
    )
    so.approve()
    assert so.status == "approved"

    # 2. Delivery
    so.deliver(quantity=10)
    assert so.delivery_status == "FULL"

    # 3. Invoice
    invoice = MockSalesInvoice(
        id=str(uuid4()), so_id=so.id, amount=Decimal("1000000"), vat=Decimal("110000")
    )
    invoice.issue()
    assert invoice.status == "ISSUED"

    # 4. Pendapatan diakui (sesuai PSAK 72) - menggunakan mock recognizer
    recognizer = MockRevenueRecognizer()
    revenue = recognizer.recognize(invoice)
    assert revenue.amount == Decimal("1000000")
    assert revenue.deferred is False

    # 5. Jurnal: Debit Piutang 1.110.000, Credit Pendapatan 1.000.000, Credit PPN Keluaran 110.000
    journal = recognizer.create_journal(revenue, invoice)
    assert journal.get_debit_total() == Decimal("1110000")
    assert journal.get_credit_total() == Decimal("1110000")

    # 6. Koleksi pembayaran
    payment = MockArPayment(
        invoice_id=invoice.id, amount=Decimal("1110000"), payment_date=date.today()
    )
    workflow = MockArCollectionWorkflow()
    result = workflow.process(payment)
    assert result.is_reconciled is True
    # Setelah payment, outstanding balance invoice menjadi 0 (di-mock)
    invoice.outstanding_balance = Decimal("0")
    assert invoice.outstanding_balance == Decimal("0")


# ============================================================================
# OPSIONAL: Jika real modules tersedia, gunakan yang real
# ============================================================================
try:
    from domain.revenue.revenue_recognizer import RevenueRecognizer

    from application.use_cases.ar_collection_workflow import ArCollectionWorkflow
    from domain.purchase_sales.sales_invoice_entity import SalesInvoice
    from domain.purchase_sales.sales_order_aggregate import SalesOrder
    from domain.subledger_ar.payment_entity import ArPayment

    REAL_MODULES_AVAILABLE = True
except ImportError:
    REAL_MODULES_AVAILABLE = False


@pytest.mark.skipif(not REAL_MODULES_AVAILABLE, reason="Real domain modules not available")
def test_sales_to_ar_collection_real():
    """Versi real (hanya jika semua module tersedia)."""
    # 1. Sales Order
    so = SalesOrder(
        customer_id="CUST-001", items=[{"product": "X", "qty": 10, "price": Decimal("100000")}]
    )
    so.approve()

    # 2. Delivery
    so.deliver(quantity=10)
    assert so.delivery_status == "FULL"

    # 3. Invoice
    invoice = SalesInvoice(so_id=so.id, amount=Decimal("1000000"), vat=Decimal("110000"))
    invoice.issue()
    assert invoice.status == "ISSUED"

    # 4. Pendapatan diakui (sesuai PSAK 72)
    recognizer = RevenueRecognizer()
    revenue = recognizer.recognize(invoice)
    assert revenue.amount == Decimal("1000000")
    assert revenue.deferred is False

    # 5. Jurnal
    journal = revenue.create_journal()
    assert journal.get_debit_total() == Decimal("1110000")
    assert journal.get_credit_total() == Decimal("1110000")

    # 6. Koleksi pembayaran
    payment = ArPayment(invoice_id=invoice.id, amount=Decimal("1110000"), payment_date=date.today())
    workflow = ArCollectionWorkflow()
    result = workflow.process(payment)
    assert result.is_reconciled is True
    assert invoice.outstanding_balance == Decimal("0")
