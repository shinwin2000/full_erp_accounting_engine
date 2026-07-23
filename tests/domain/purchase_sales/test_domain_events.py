# test_domain_events.py
# Comprehensive tests for domain/purchase_sales/domain_events.py

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.purchase_sales.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    CreditNoteReceivedEvent,
    DebitNoteAppliedEvent,
    DebitNoteIssuedEvent,
    DebitNoteIssuedServiceEvent,
    DeliveryNoteShippedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    GoodsReceiptCreatedEvent,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceCreatedEvent,
    InvoiceDisputedEvent,
    InvoiceIssuedEvent,
    InvoicePaidEvent,
    InvoicePartiallyPaidEvent,
    InvoiceReceivedEvent,
    InvoiceVerifiedEvent,
    InvoiceWrittenOffEvent,
    PurchaseInvoiceApprovedEvent,
    PurchaseInvoicePaidEvent,
    PurchaseInvoiceReceivedEvent,
    PurchaseOrderApprovedEvent,
    PurchaseOrderCreatedEvent,
    SalesInvoiceIssuedEvent,
    SalesInvoicePaidEvent,
    SalesOrderApprovedEvent,
    SalesOrderCreatedEvent,
)


# -------------------- Enum Tests --------------------
class TestDomainEventType:
    def test_members(self):
        assert DomainEventType.PURCHASE_ORDER_CREATED.value == "purchase_order_created"
        assert DomainEventType.PURCHASE_ORDER_APPROVED.value == "purchase_order_approved"
        assert DomainEventType.PURCHASE_ORDER_CANCELLED.value == "purchase_order_cancelled"
        assert DomainEventType.PURCHASE_ORDER_RECEIVED.value == "purchase_order_received"
        assert DomainEventType.SALES_ORDER_CREATED.value == "sales_order_created"
        assert DomainEventType.SALES_ORDER_APPROVED.value == "sales_order_approved"
        assert DomainEventType.SALES_ORDER_CANCELLED.value == "sales_order_cancelled"
        assert DomainEventType.SALES_ORDER_DELIVERED.value == "sales_order_delivered"
        assert DomainEventType.SALES_ORDER_INVOICED.value == "sales_order_invoiced"
        assert DomainEventType.GOODS_RECEIPT_CREATED.value == "goods_receipt_created"
        assert DomainEventType.GOODS_RECEIPT_CONFIRMED.value == "goods_receipt_confirmed"
        assert DomainEventType.DELIVERY_NOTE_CREATED.value == "delivery_note_created"
        assert DomainEventType.DELIVERY_NOTE_SHIPPED.value == "delivery_note_shipped"
        assert DomainEventType.DELIVERY_NOTE_DELIVERED.value == "delivery_note_delivered"
        assert DomainEventType.INVOICE_CREATED.value == "invoice_created"
        assert DomainEventType.INVOICE_ISSUED.value == "invoice_issued"
        assert DomainEventType.INVOICE_APPROVED.value == "invoice_approved"
        assert DomainEventType.INVOICE_CANCELLED.value == "invoice_cancelled"
        assert DomainEventType.INVOICE_PAID.value == "invoice_paid"
        assert DomainEventType.INVOICE_PARTIALLY_PAID.value == "invoice_partially_paid"
        assert DomainEventType.INVOICE_DISPUTED.value == "invoice_disputed"
        assert DomainEventType.INVOICE_VERIFIED.value == "invoice_verified"
        assert DomainEventType.INVOICE_RECEIVED.value == "invoice_received"
        assert DomainEventType.INVOICE_WRITTEN_OFF.value == "invoice_written_off"
        assert DomainEventType.PURCHASE_INVOICE_RECEIVED.value == "purchase_invoice_received"
        assert DomainEventType.PURCHASE_INVOICE_APPROVED.value == "purchase_invoice_approved"
        assert DomainEventType.PURCHASE_INVOICE_PAID.value == "purchase_invoice_paid"
        assert DomainEventType.SALES_INVOICE_ISSUED.value == "sales_invoice_issued"
        assert DomainEventType.SALES_INVOICE_PAID.value == "sales_invoice_paid"
        assert DomainEventType.CREDIT_NOTE_ISSUED.value == "credit_note_issued"
        assert DomainEventType.CREDIT_NOTE_RECEIVED.value == "credit_note_received"
        assert DomainEventType.CREDIT_NOTE_APPLIED.value == "credit_note_applied"
        assert DomainEventType.DEBIT_NOTE_ISSUED.value == "debit_note_issued"
        assert DomainEventType.DEBIT_NOTE_APPLIED.value == "debit_note_applied"
        assert DomainEventType.DEBIT_NOTE_ISSUED_SERVICE.value == "debit_note_issued_service"
        assert DomainEventType.PURCHASE_RETURN_CREATED.value == "purchase_return_created"
        assert DomainEventType.SALES_RETURN_CREATED.value == "sales_return_created"


# -------------------- Base DomainEvent Tests --------------------
class TestDomainEvent:
    def test_construction(self):
        event_id = uuid4()
        agg_id = uuid4()
        now = datetime.now(UTC)
        event = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=agg_id,
            aggregate_version=1,
            occurred_at=now,
            event_data={"key": "value"},
            user_id="user1",
            correlation_id="corr1",
            causation_id="cause1",
        )
        assert event.event_id == event_id
        assert event.event_type == DomainEventType.INVOICE_CREATED
        assert event.aggregate_id == agg_id
        assert event.aggregate_version == 1
        assert event.occurred_at == now
        assert event.event_data == {"key": "value"}
        assert event.user_id == "user1"
        assert event.correlation_id == "corr1"
        assert event.causation_id == "cause1"

    def test_to_json(self):
        event_id = uuid4()
        agg_id = uuid4()
        now = datetime.now(UTC)
        event = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=agg_id,
            aggregate_version=2,
            occurred_at=now,
            event_data={"amount": "100.00"},
            user_id="userX",
        )
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_id"] == str(event_id)
        assert data["event_type"] == "invoice_created"
        assert data["aggregate_id"] == str(agg_id)
        assert data["aggregate_version"] == 2
        assert data["occurred_at"] == now.isoformat()
        assert data["event_data"] == {"amount": "100.00"}
        assert data["user_id"] == "userX"
        assert data["correlation_id"] is None
        assert data["causation_id"] is None

    def test_from_json(self):
        event_id = uuid4()
        agg_id = uuid4()
        now = datetime.now(UTC)
        original = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=agg_id,
            aggregate_version=3,
            occurred_at=now,
            event_data={"note": "test"},
            user_id="userY",
            correlation_id="corrY",
            causation_id="causeY",
        )
        json_str = original.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed.event_id == original.event_id
        assert reconstructed.event_type == original.event_type
        assert reconstructed.aggregate_id == original.aggregate_id
        assert reconstructed.aggregate_version == original.aggregate_version
        assert reconstructed.occurred_at == original.occurred_at
        assert reconstructed.event_data == original.event_data
        assert reconstructed.user_id == original.user_id
        assert reconstructed.correlation_id == original.correlation_id
        assert reconstructed.causation_id == original.causation_id


# -------------------- Helper: Entity Mocks --------------------
def make_mock_purchase_order():
    po = MagicMock()
    po.po_id = uuid4()
    po.po_number = "PO-001"
    po.supplier_id = uuid4()
    po.supplier_name = "Supplier ABC"
    po.total_amount = Decimal("1500.00")
    po.currency = "USD"
    return po

def make_mock_sales_order():
    so = MagicMock()
    so.so_id = uuid4()
    so.so_number = "SO-001"
    so.customer_id = uuid4()
    so.customer_name = "Customer XYZ"
    so.total_amount = Decimal("2000.00")
    so.currency = "EUR"
    return so

def make_mock_grn():
    grn = MagicMock()
    grn.grn_id = uuid4()
    grn.grn_number = "GRN-001"
    grn.po_id = uuid4()
    grn.po_number = "PO-001"
    grn.supplier_id = uuid4()
    grn.supplier_name = "Supplier ABC"
    grn.receipt_date = date.today()
    grn.total_amount = Decimal("1500.00")
    return grn

def make_mock_delivery():
    delivery = MagicMock()
    delivery.delivery_id = uuid4()
    delivery.delivery_number = "DN-001"
    delivery.so_id = uuid4()
    delivery.so_number = "SO-001"
    delivery.customer_id = uuid4()
    delivery.customer_name = "Customer XYZ"
    delivery.tracking_number = "TRK123"
    return delivery

def make_mock_sales_invoice():
    inv = MagicMock()
    inv.invoice_id = uuid4()
    inv.invoice_number = "INV-001"
    inv.customer_id = uuid4()
    inv.customer_name = "Customer XYZ"
    inv.invoice_date = date.today()
    inv.due_date = date.today() + timedelta(days=30)
    inv.total_amount = Decimal("2000.00")
    inv.currency = "USD"
    inv.paid_amount = Decimal("0")
    return inv

def make_mock_purchase_invoice():
    inv = MagicMock()
    inv.invoice_id = uuid4()
    inv.invoice_number = "PINV-001"
    inv.supplier_id = uuid4()
    inv.supplier_name = "Supplier ABC"
    inv.invoice_date = date.today()
    inv.due_date = date.today() + timedelta(days=30)
    inv.total_amount = Decimal("1500.00")
    inv.currency = "USD"
    return inv


# -------------------- Concrete Event Tests --------------------
class TestPurchaseOrderCreatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        po = make_mock_purchase_order()
        event = PurchaseOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            purchase_order=po,
            created_by="creator",
            user_id="user1",
            correlation_id="corr1",
            causation_id="cause1",
        )
        assert event.event_type == DomainEventType.PURCHASE_ORDER_CREATED
        assert event.aggregate_id == agg_id
        assert event.aggregate_version == 1
        assert event.user_id == "user1"
        assert event.correlation_id == "corr1"
        assert event.causation_id == "cause1"
        data = event.event_data
        assert data["po_id"] == str(po.po_id)
        assert data["po_number"] == "PO-001"
        assert data["supplier_id"] == str(po.supplier_id)
        assert data["supplier_name"] == "Supplier ABC"
        assert data["total_amount"] == "1500.00"
        assert data["currency"] == "USD"
        assert data["created_by"] == "creator"
        # to_json works
        json_str = event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed.event_type == event.event_type

class TestPurchaseOrderApprovedEvent:
    def test_construction(self):
        agg_id = uuid4()
        po = make_mock_purchase_order()
        event = PurchaseOrderApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            purchase_order=po,
            approved_by="approver",
        )
        assert event.event_type == DomainEventType.PURCHASE_ORDER_APPROVED
        data = event.event_data
        assert data["po_id"] == str(po.po_id)
        assert data["po_number"] == "PO-001"
        assert data["approved_by"] == "approver"

class TestSalesOrderCreatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        so = make_mock_sales_order()
        event = SalesOrderCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            sales_order=so,
            created_by="creator",
        )
        assert event.event_type == DomainEventType.SALES_ORDER_CREATED
        data = event.event_data
        assert data["so_id"] == str(so.so_id)
        assert data["so_number"] == "SO-001"
        assert data["customer_id"] == str(so.customer_id)
        assert data["customer_name"] == "Customer XYZ"
        assert data["total_amount"] == "2000.00"
        assert data["currency"] == "EUR"
        assert data["created_by"] == "creator"

class TestSalesOrderApprovedEvent:
    def test_construction(self):
        agg_id = uuid4()
        so = make_mock_sales_order()
        event = SalesOrderApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            sales_order=so,
            approved_by="approver",
        )
        assert event.event_type == DomainEventType.SALES_ORDER_APPROVED
        data = event.event_data
        assert data["so_id"] == str(so.so_id)
        assert data["so_number"] == "SO-001"
        assert data["approved_by"] == "approver"

class TestGoodsReceiptCreatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        grn = make_mock_grn()
        event = GoodsReceiptCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            grn=grn,
            created_by="creator",
        )
        assert event.event_type == DomainEventType.GOODS_RECEIPT_CREATED
        data = event.event_data
        assert data["grn_id"] == str(grn.grn_id)
        assert data["grn_number"] == "GRN-001"
        assert data["po_id"] == str(grn.po_id)
        assert data["po_number"] == "PO-001"
        assert data["supplier_id"] == str(grn.supplier_id)
        assert data["supplier_name"] == "Supplier ABC"
        assert data["receipt_date"] == date.today().isoformat()
        assert data["total_amount"] == "1500.00"
        assert data["created_by"] == "creator"

class TestDeliveryNoteShippedEvent:
    def test_construction(self):
        agg_id = uuid4()
        delivery = make_mock_delivery()
        event = DeliveryNoteShippedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            delivery=delivery,
            shipped_by="shipper",
        )
        assert event.event_type == DomainEventType.DELIVERY_NOTE_SHIPPED
        data = event.event_data
        assert data["delivery_id"] == str(delivery.delivery_id)
        assert data["delivery_number"] == "DN-001"
        assert data["so_id"] == str(delivery.so_id)
        assert data["so_number"] == "SO-001"
        assert data["customer_id"] == str(delivery.customer_id)
        assert data["customer_name"] == "Customer XYZ"
        assert data["shipped_by"] == "shipper"
        assert data["tracking_number"] == "TRK123"

class TestSalesInvoiceIssuedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv = make_mock_sales_invoice()
        event = SalesInvoiceIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            invoice=inv,
            issued_by="issuer",
        )
        assert event.event_type == DomainEventType.SALES_INVOICE_ISSUED
        data = event.event_data
        assert data["invoice_id"] == str(inv.invoice_id)
        assert data["invoice_number"] == "INV-001"
        assert data["customer_id"] == str(inv.customer_id)
        assert data["customer_name"] == "Customer XYZ"
        assert data["invoice_date"] == inv.invoice_date.isoformat()
        assert data["due_date"] == inv.due_date.isoformat()
        assert data["total_amount"] == "2000.00"
        assert data["currency"] == "USD"
        assert data["issued_by"] == "issuer"

class TestSalesInvoicePaidEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv = make_mock_sales_invoice()
        inv.paid_amount = Decimal("2000.00")
        event = SalesInvoicePaidEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            invoice=inv,
            payment_amount=Decimal("2000.00"),
            paid_by="payer",
        )
        assert event.event_type == DomainEventType.SALES_INVOICE_PAID
        data = event.event_data
        assert data["invoice_id"] == str(inv.invoice_id)
        assert data["invoice_number"] == "INV-001"
        assert data["payment_amount"] == "2000.00"
        assert data["total_paid"] == "2000.00"
        assert data["paid_by"] == "payer"

class TestPurchaseInvoiceReceivedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv = make_mock_purchase_invoice()
        event = PurchaseInvoiceReceivedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            invoice=inv,
            received_by="receiver",
        )
        assert event.event_type == DomainEventType.PURCHASE_INVOICE_RECEIVED
        data = event.event_data
        assert data["invoice_id"] == str(inv.invoice_id)
        assert data["invoice_number"] == "PINV-001"
        assert data["supplier_id"] == str(inv.supplier_id)
        assert data["supplier_name"] == "Supplier ABC"
        assert data["invoice_date"] == inv.invoice_date.isoformat()
        assert data["due_date"] == inv.due_date.isoformat()
        assert data["total_amount"] == "1500.00"
        assert data["currency"] == "USD"
        assert data["received_by"] == "receiver"

class TestPurchaseInvoiceApprovedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv = make_mock_purchase_invoice()
        event = PurchaseInvoiceApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            invoice=inv,
            approved_by="approver",
        )
        assert event.event_type == DomainEventType.PURCHASE_INVOICE_APPROVED
        data = event.event_data
        assert data["invoice_id"] == str(inv.invoice_id)
        assert data["invoice_number"] == "PINV-001"
        assert data["supplier_id"] == str(inv.supplier_id)
        assert data["supplier_name"] == "Supplier ABC"
        assert data["total_amount"] == "1500.00"
        assert data["approved_by"] == "approver"

class TestPurchaseInvoicePaidEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv = make_mock_purchase_invoice()
        event = PurchaseInvoicePaidEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            invoice=inv,
            payment_amount=Decimal("1500.00"),
            paid_by="payer",
        )
        assert event.event_type == DomainEventType.PURCHASE_INVOICE_PAID
        data = event.event_data
        assert data["invoice_id"] == str(inv.invoice_id)
        assert data["invoice_number"] == "PINV-001"
        assert data["supplier_id"] == str(inv.supplier_id)
        assert data["supplier_name"] == "Supplier ABC"
        assert data["payment_amount"] == "1500.00"
        assert data["paid_by"] == "payer"

# --- Generic Invoice Events ---
class TestInvoiceCreatedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceCreatedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            total_amount=Decimal("1000.00"),
            created_by="creator",
        )
        assert event.event_type == DomainEventType.INVOICE_CREATED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["total_amount"] == "1000.00"
        assert data["created_by"] == "creator"
        assert event.user_id == "creator"  # fallback

class TestInvoiceIssuedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            total_amount=Decimal("1000.00"),
            issued_by="issuer",
        )
        assert event.event_type == DomainEventType.INVOICE_ISSUED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["total_amount"] == "1000.00"
        assert data["issued_by"] == "issuer"

class TestInvoiceApprovedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="purchase",
            approved_by="approver",
        )
        assert event.event_type == DomainEventType.INVOICE_APPROVED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "purchase"
        assert data["approved_by"] == "approver"

class TestInvoiceCancelledEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceCancelledEvent(
            aggregate_id=agg_id,
            aggregate_version=4,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            reason="customer request",
            cancelled_by="canceller",
        )
        assert event.event_type == DomainEventType.INVOICE_CANCELLED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["reason"] == "customer request"
        assert data["cancelled_by"] == "canceller"

class TestInvoicePaidEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoicePaidEvent(
            aggregate_id=agg_id,
            aggregate_version=5,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            payment_amount=Decimal("500.00"),
            paid_by="payer",
        )
        assert event.event_type == DomainEventType.INVOICE_PAID
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["payment_amount"] == "500.00"
        assert data["paid_by"] == "payer"

class TestInvoicePartiallyPaidEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoicePartiallyPaidEvent(
            aggregate_id=agg_id,
            aggregate_version=6,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            paid_amount=Decimal("300.00"),
            total_amount=Decimal("1000.00"),
            paid_by="payer",
        )
        assert event.event_type == DomainEventType.INVOICE_PARTIALLY_PAID
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["paid_amount"] == "300.00"
        assert data["total_amount"] == "1000.00"
        assert data["paid_by"] == "payer"

class TestInvoiceDisputedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceDisputedEvent(
            aggregate_id=agg_id,
            aggregate_version=7,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="purchase",
            reason="quantity mismatch",
            disputed_by="disputer",
        )
        assert event.event_type == DomainEventType.INVOICE_DISPUTED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "purchase"
        assert data["reason"] == "quantity mismatch"
        assert data["disputed_by"] == "disputer"

class TestInvoiceVerifiedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceVerifiedEvent(
            aggregate_id=agg_id,
            aggregate_version=8,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="purchase",
            verified_by="verifier",
        )
        assert event.event_type == DomainEventType.INVOICE_VERIFIED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "purchase"
        assert data["verified_by"] == "verifier"

class TestInvoiceReceivedEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceReceivedEvent(
            aggregate_id=agg_id,
            aggregate_version=9,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="purchase",
            received_by="receiver",
        )
        assert event.event_type == DomainEventType.INVOICE_RECEIVED
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "purchase"
        assert data["received_by"] == "receiver"

class TestInvoiceWrittenOffEvent:
    def test_construction(self):
        agg_id = uuid4()
        inv_id = uuid4()
        event = InvoiceWrittenOffEvent(
            aggregate_id=agg_id,
            aggregate_version=10,
            invoice_id=inv_id,
            invoice_number="INV-GEN-001",
            invoice_type="sales",
            reason="uncollectible",
            written_off_by="writer",
        )
        assert event.event_type == DomainEventType.INVOICE_WRITTEN_OFF
        data = event.event_data
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_number"] == "INV-GEN-001"
        assert data["invoice_type"] == "sales"
        assert data["reason"] == "uncollectible"
        assert data["written_off_by"] == "writer"

# --- Credit Note Events ---
class TestCreditNoteIssuedEvent:
    def test_construction(self):
        agg_id = uuid4()
        cn_id = uuid4()
        inv_id = uuid4()
        event = CreditNoteIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            credit_note_id=cn_id,
            credit_note_number="CN-001",
            invoice_id=inv_id,
            invoice_type="sales",
            amount=Decimal("200.00"),
            reason="price adjustment",
            issued_by="issuer",
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_ISSUED
        data = event.event_data
        assert data["credit_note_id"] == str(cn_id)
        assert data["credit_note_number"] == "CN-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "sales"
        assert data["amount"] == "200.00"
        assert data["reason"] == "price adjustment"
        assert data["issued_by"] == "issuer"

class TestCreditNoteReceivedEvent:
    def test_construction(self):
        agg_id = uuid4()
        cn_id = uuid4()
        inv_id = uuid4()
        event = CreditNoteReceivedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            credit_note_id=cn_id,
            credit_note_number="CN-001",
            invoice_id=inv_id,
            invoice_type="sales",
            amount=Decimal("200.00"),
            received_by="receiver",
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_RECEIVED
        data = event.event_data
        assert data["credit_note_id"] == str(cn_id)
        assert data["credit_note_number"] == "CN-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "sales"
        assert data["amount"] == "200.00"
        assert data["received_by"] == "receiver"

class TestCreditNoteAppliedEvent:
    def test_construction(self):
        agg_id = uuid4()
        cn_id = uuid4()
        inv_id = uuid4()
        event = CreditNoteAppliedEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            credit_note_id=cn_id,
            credit_note_number="CN-001",
            invoice_id=inv_id,
            invoice_type="sales",
            amount=Decimal("200.00"),
            applied_by="applier",
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_APPLIED
        data = event.event_data
        assert data["credit_note_id"] == str(cn_id)
        assert data["credit_note_number"] == "CN-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "sales"
        assert data["amount"] == "200.00"
        assert data["applied_by"] == "applier"

# --- Debit Note Events ---
class TestDebitNoteIssuedEvent:
    def test_construction(self):
        agg_id = uuid4()
        dn_id = uuid4()
        inv_id = uuid4()
        event = DebitNoteIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            debit_note_id=dn_id,
            debit_note_number="DN-001",
            invoice_id=inv_id,
            invoice_type="purchase",
            amount=Decimal("150.00"),
            reason="freight charge",
            issued_by="issuer",
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_ISSUED
        data = event.event_data
        assert data["debit_note_id"] == str(dn_id)
        assert data["debit_note_number"] == "DN-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "purchase"
        assert data["amount"] == "150.00"
        assert data["reason"] == "freight charge"
        assert data["issued_by"] == "issuer"

class TestDebitNoteAppliedEvent:
    def test_construction(self):
        agg_id = uuid4()
        dn_id = uuid4()
        inv_id = uuid4()
        event = DebitNoteAppliedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            debit_note_id=dn_id,
            debit_note_number="DN-001",
            invoice_id=inv_id,
            invoice_type="purchase",
            amount=Decimal("150.00"),
            applied_by="applier",
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_APPLIED
        data = event.event_data
        assert data["debit_note_id"] == str(dn_id)
        assert data["debit_note_number"] == "DN-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "purchase"
        assert data["amount"] == "150.00"
        assert data["applied_by"] == "applier"

class TestDebitNoteIssuedServiceEvent:
    def test_construction(self):
        agg_id = uuid4()
        dn_id = uuid4()
        inv_id = uuid4()
        event = DebitNoteIssuedServiceEvent(
            aggregate_id=agg_id,
            aggregate_version=1,
            debit_note_id=dn_id,
            debit_note_number="DN-SVC-001",
            invoice_id=inv_id,
            invoice_type="purchase",
            amount=Decimal("300.00"),
            reason="consulting fee",
            service_type="consulting",
            issued_by="issuer",
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_ISSUED_SERVICE
        data = event.event_data
        assert data["debit_note_id"] == str(dn_id)
        assert data["debit_note_number"] == "DN-SVC-001"
        assert data["invoice_id"] == str(inv_id)
        assert data["invoice_type"] == "purchase"
        assert data["amount"] == "300.00"
        assert data["reason"] == "consulting fee"
        assert data["service_type"] == "consulting"
        assert data["issued_by"] == "issuer"


# -------------------- DomainEventPublisher Tests --------------------
class TestDomainEventPublisher:
    @pytest.mark.asyncio
    async def test_publish_raises_not_implemented(self):
        publisher = DomainEventPublisher()
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            occurred_at=datetime.now(UTC),
            event_data={},
        )
        with pytest.raises(NotImplementedError):
            await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_publish_many_raises_not_implemented(self):
        publisher = DomainEventPublisher()
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            occurred_at=datetime.now(UTC),
            event_data={},
        )
        with pytest.raises(NotImplementedError):
            await publisher.publish_many([event, event])