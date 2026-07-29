# test_domain_events.py
# Comprehensive tests for domain_events.py

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.subledger_ap.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    CreditNoteReceivedEvent,
    DebitNoteAppliedEvent,
    DebitNoteIssuedEvent,
    DebitNoteIssuedServiceEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceCreatedEvent,
    InvoiceDisputedEvent,
    InvoicePaidEvent,
    InvoiceReceivedEvent,
    InvoiceVerifiedEvent,
    PaymentAppliedEvent,
    PaymentApprovedEvent,
    PaymentCancelledEvent,
    PaymentConfirmedEvent,
    PaymentMadeEvent,
    PaymentProcessedEvent,
    PaymentRunExecutedEvent,
    PaymentRunGeneratedEvent,
    PaymentSentEvent,
    PaymentVoidedEvent,
    ThreeWayMatchResultEvent,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_invoice():
    invoice = MagicMock()
    invoice.invoice_id = "550e8400-e29b-41d4-a716-446655440000"
    invoice.invoice_number = "INV-001"
    invoice.vendor_id = "11111111-1111-1111-1111-111111111111"
    invoice.vendor_name = "PT Supplier Jaya"
    invoice.amount = Decimal("1000000")
    invoice.currency = "IDR"
    invoice.due_date = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    invoice.created_by = "admin"
    return invoice


@pytest.fixture
def mock_payment():
    payment = MagicMock()
    payment.payment_id = "660e8400-e29b-41d4-a716-446655440001"
    payment.payment_number = "PAY-001"
    payment.vendor_id = "11111111-1111-1111-1111-111111111111"
    payment.vendor_name = "PT Supplier Jaya"
    payment.amount = Decimal("500000")
    payment.currency = "IDR"
    payment.payment_method = MagicMock()
    payment.payment_method.value = "bank_transfer"
    payment.created_by = "admin"
    payment.payment_date = datetime(2024, 6, 10, 0, 0, 0, tzinfo=UTC)
    return payment


@pytest.fixture
def mock_credit_note():
    credit_note = MagicMock()
    credit_note.credit_note_id = "770e8400-e29b-41d4-a716-446655440002"
    credit_note.credit_note_number = "CN-001"
    credit_note.invoice_id = "550e8400-e29b-41d4-a716-446655440000"
    credit_note.vendor_id = "11111111-1111-1111-1111-111111111111"
    credit_note.amount = Decimal("100000")
    credit_note.reason = MagicMock()
    credit_note.reason.value = "price_difference"
    return credit_note


@pytest.fixture
def mock_debit_note():
    debit_note = MagicMock()
    debit_note.debit_note_id = "880e8400-e29b-41d4-a716-446655440003"
    debit_note.debit_note_number = "DN-001"
    debit_note.invoice_id = "550e8400-e29b-41d4-a716-446655440000"
    debit_note.vendor_id = "11111111-1111-1111-1111-111111111111"
    debit_note.amount = Decimal("50000")
    debit_note.reason = MagicMock()
    debit_note.reason.value = "tax_correction"
    return debit_note


# ============================================================================
# Tests for DomainEventType Enum
# ============================================================================

class TestDomainEventType:
    def test_from_string(self):
        assert DomainEventType.from_string("invoice_received") == DomainEventType.INVOICE_RECEIVED
        assert DomainEventType.from_string("INVOICE_VERIFIED") == DomainEventType.INVOICE_VERIFIED
        assert DomainEventType.from_string("payment_sent") == DomainEventType.PAYMENT_SENT
        assert DomainEventType.from_string("unknown") == DomainEventType.INVOICE_RECEIVED  # default

    def test_values(self):
        assert DomainEventType.INVOICE_RECEIVED.value == "invoice_received"
        assert DomainEventType.PAYMENT_SENT.value == "payment_sent"


# ============================================================================
# Tests for DomainEvent base class
# ============================================================================

class TestDomainEvent:
    def test_construction_defaults(self):
        aggregate_id = "550e8400-e29b-41d4-a716-446655440000"
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=1
        )
        assert event.event_id is not None
        assert event.occurred_at is not None
        assert event.event_data == {}
        assert event.user_id is None
        assert event.correlation_id is None
        assert event.causation_id is None

    def test_to_dict(self):
        aggregate_id = "550e8400-e29b-41d4-a716-446655440000"
        event_id = "990e8400-e29b-41d4-a716-446655440099"
        occurred = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        event = DomainEvent(
            event_id=event_id,
            event_type=DomainEventType.PAYMENT_SENT,
            aggregate_id=aggregate_id,
            aggregate_version=2,
            occurred_at=occurred,
            event_data={"key": "value"},
            user_id="user1",
            correlation_id="corr1",
            causation_id="cause1"
        )
        d = event.to_dict()
        assert d["event_id"] == event_id
        assert d["event_type"] == "payment_sent"
        assert d["aggregate_id"] == aggregate_id
        assert d["aggregate_version"] == 2
        assert d["occurred_at"] == occurred.isoformat()
        assert d["event_data"] == {"key": "value"}
        assert d["user_id"] == "user1"
        assert d["correlation_id"] == "corr1"
        assert d["causation_id"] == "cause1"

    def test_to_json(self):
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_RECEIVED,
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1
        )
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_type"] == "invoice_received"

    def test_from_dict(self):
        data = {
            "event_id": "990e8400-e29b-41d4-a716-446655440099",
            "event_type": "payment_approved",
            "aggregate_id": "550e8400-e29b-41d4-a716-446655440000",
            "aggregate_version": 2,
            "occurred_at": "2024-06-15T12:00:00+00:00",
            "event_data": {"key": "value"},
            "user_id": "user1",
            "correlation_id": "corr1",
            "causation_id": "cause1",
        }
        event = DomainEvent.from_dict(data)
        assert event.event_id == "990e8400-e29b-41d4-a716-446655440099"
        assert event.event_type == DomainEventType.PAYMENT_APPROVED
        assert event.aggregate_id == "550e8400-e29b-41d4-a716-446655440000"
        assert event.aggregate_version == 2
        assert event.occurred_at == datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
        assert event.event_data == {"key": "value"}

    def test_from_json(self):
        data = {
            "event_id": "990e8400-e29b-41d4-a716-446655440099",
            "event_type": "payment_cancelled",
            "aggregate_id": "550e8400-e29b-41d4-a716-446655440000",
            "aggregate_version": 3,
            "occurred_at": "2024-06-16T10:00:00+00:00",
            "event_data": {},
        }
        json_str = json.dumps(data)
        event = DomainEvent.from_json(json_str)
        assert event.event_type == DomainEventType.PAYMENT_CANCELLED

    def test_serialize_deserialize(self):
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1,
            user_id="admin"
        )
        serialized = event.serialize()
        deserialized = DomainEvent.deserialize(serialized)
        assert deserialized.event_type == event.event_type
        assert deserialized.aggregate_id == event.aggregate_id


# ============================================================================
# Tests for specific event classes
# ============================================================================

class TestInvoiceReceivedEvent:
    def test_creation(self, mock_invoice):
        aggregate_id = "550e8400-e29b-41d4-a716-446655440000"
        event = InvoiceReceivedEvent(
            aggregate_id=aggregate_id,
            aggregate_version=1,
            invoice=mock_invoice,
            received_by="receiver1",
            user_id="admin",
            correlation_id="corr1",
            causation_id="cause1"
        )
        assert event.event_type == DomainEventType.INVOICE_RECEIVED
        assert event.aggregate_id == aggregate_id
        assert event.event_data["invoice_id"] == str(mock_invoice.invoice_id)
        assert event.event_data["invoice_number"] == mock_invoice.invoice_number
        assert event.event_data["amount"] == str(mock_invoice.amount)
        assert event.event_data["received_by"] == "receiver1"
        assert event.user_id == "admin"


class TestInvoiceVerifiedEvent:
    def test_creation(self, mock_invoice):
        event = InvoiceVerifiedEvent(
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1,
            invoice=mock_invoice,
            verified_by="verifier1",
            match_result="MATCHED"
        )
        assert event.event_type == DomainEventType.INVOICE_VERIFIED
        assert event.event_data["verified_by"] == "verifier1"
        assert event.event_data["match_result"] == "MATCHED"


class TestInvoicePaidEvent:
    def test_creation(self, mock_invoice):
        payment_id = "660e8400-e29b-41d4-a716-446655440001"
        event = InvoicePaidEvent(
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=2,
            invoice=mock_invoice,
            payment_id=payment_id,
            payment_amount=Decimal("1000000")
        )
        assert event.event_type == DomainEventType.INVOICE_PAID
        assert event.event_data["payment_id"] == str(payment_id)
        assert event.event_data["payment_amount"] == "1000000"


class TestInvoiceCancelledEvent:
    def test_creation(self):
        invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        event = InvoiceCancelledEvent(
            aggregate_id=invoice_id,
            aggregate_version=1,
            invoice_id=invoice_id,
            invoice_number="INV-001",
            reason="Duplicate",
            cancelled_by="admin"
        )
        assert event.event_type == DomainEventType.INVOICE_CANCELLED
        assert event.event_data["reason"] == "Duplicate"


class TestInvoiceDisputedEvent:
    def test_creation(self):
        invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        event = InvoiceDisputedEvent(
            aggregate_id=invoice_id,
            aggregate_version=1,
            invoice_id=invoice_id,
            invoice_number="INV-001",
            reason="Wrong amount",
            disputed_by="user1"
        )
        assert event.event_type == DomainEventType.INVOICE_DISPUTED
        assert event.event_data["disputed_by"] == "user1"


class TestInvoiceCreatedEvent:
    def test_creation(self):
        legal_entity_id = "11111111-1111-1111-1111-111111111111"
        vendor_id = "22222222-2222-2222-2222-222222222222"
        due_date = datetime(2024, 7, 1, 0, 0, 0, tzinfo=UTC)
        event = InvoiceCreatedEvent(
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1,
            legal_entity_id=legal_entity_id,
            invoice_number="INV-001",
            vendor_id=vendor_id,
            amount=Decimal("2000000"),
            due_date=due_date,
            user_id="admin"
        )
        assert event.event_type == DomainEventType.INVOICE_CREATED
        assert event.event_data["legal_entity_id"] == str(legal_entity_id)
        assert event.event_data["due_date"] == due_date.isoformat()


class TestInvoiceApprovedEvent:
    def test_creation(self):
        event = InvoiceApprovedEvent(
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1,
            invoice_number="INV-001",
            approver_id="approver1"
        )
        assert event.event_type == DomainEventType.INVOICE_APPROVED


class TestPaymentSentEvent:
    def test_creation(self, mock_payment):
        event = PaymentSentEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            payment=mock_payment,
            sent_by="sender1"
        )
        assert event.event_type == DomainEventType.PAYMENT_SENT
        assert event.event_data["payment_number"] == mock_payment.payment_number
        assert event.event_data["sent_by"] == "sender1"


class TestPaymentApprovedEvent:
    def test_creation(self, mock_payment):
        event = PaymentApprovedEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            payment=mock_payment,
            approved_by="approver1"
        )
        assert event.event_type == DomainEventType.PAYMENT_APPROVED
        assert "approved_at" in event.event_data


class TestPaymentProcessedEvent:
    def test_creation(self, mock_payment):
        event = PaymentProcessedEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            payment=mock_payment,
            processed_by="processor1",
            reference_number="REF123"
        )
        assert event.event_type == DomainEventType.PAYMENT_PROCESSED
        assert event.event_data["reference_number"] == "REF123"


class TestPaymentConfirmedEvent:
    def test_creation(self, mock_payment):
        event = PaymentConfirmedEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            payment=mock_payment,
            confirmed_by="confirm1",
            bank_reference="BK-001"
        )
        assert event.event_type == DomainEventType.PAYMENT_CONFIRMED
        assert event.event_data["bank_reference"] == "BK-001"


class TestPaymentCancelledEvent:
    def test_creation(self):
        payment_id = "660e8400-e29b-41d4-a716-446655440001"
        event = PaymentCancelledEvent(
            aggregate_id=payment_id,
            aggregate_version=1,
            payment_id=payment_id,
            payment_number="PAY-001",
            reason="Wrong account",
            cancelled_by="admin"
        )
        assert event.event_type == DomainEventType.PAYMENT_CANCELLED


class TestPaymentMadeEvent:
    def test_creation(self):
        event = PaymentMadeEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            invoice_id="550e8400-e29b-41d4-a716-446655440000",
            amount=Decimal("500000"),
            payment_number="PAY-001",
            user_id="admin"
        )
        assert event.event_type == DomainEventType.PAYMENT_MADE


class TestPaymentAppliedEvent:
    def test_creation(self):
        payment_id = "660e8400-e29b-41d4-a716-446655440001"
        invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        event = PaymentAppliedEvent(
            aggregate_id=payment_id,
            aggregate_version=1,
            payment_id=payment_id,
            invoice_id=invoice_id,
            amount=Decimal("250000")
        )
        assert event.event_type == DomainEventType.PAYMENT_APPLIED


class TestPaymentVoidedEvent:
    def test_creation(self):
        event = PaymentVoidedEvent(
            aggregate_id="660e8400-e29b-41d4-a716-446655440001",
            aggregate_version=1,
            payment_number="PAY-001",
            reason="Duplicate",
            user_id="admin"
        )
        assert event.event_type == DomainEventType.PAYMENT_VOIDED


class TestCreditNoteReceivedEvent:
    def test_creation(self, mock_credit_note):
        event = CreditNoteReceivedEvent(
            aggregate_id="770e8400-e29b-41d4-a716-446655440002",
            aggregate_version=1,
            credit_note=mock_credit_note,
            received_by="receiver1"
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_RECEIVED
        assert event.event_data["credit_note_number"] == mock_credit_note.credit_note_number


class TestCreditNoteAppliedEvent:
    def test_creation(self, mock_credit_note):
        invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        event = CreditNoteAppliedEvent(
            aggregate_id="770e8400-e29b-41d4-a716-446655440002",
            aggregate_version=1,
            credit_note=mock_credit_note,
            invoice_id=invoice_id,
            applied_amount=Decimal("100000"),
            applied_by="applier1"
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_APPLIED


class TestCreditNoteIssuedEvent:
    def test_creation(self):
        legal_entity_id = "11111111-1111-1111-1111-111111111111"
        vendor_id = "22222222-2222-2222-2222-222222222222"
        original_invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        event = CreditNoteIssuedEvent(
            aggregate_id="770e8400-e29b-41d4-a716-446655440002",
            aggregate_version=1,
            legal_entity_id=legal_entity_id,
            credit_note_number="CN-001",
            vendor_id=vendor_id,
            amount=Decimal("100000"),
            original_invoice_id=original_invoice_id
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_ISSUED


class TestDebitNoteIssuedEvent:
    def test_creation(self, mock_debit_note):
        event = DebitNoteIssuedEvent(
            aggregate_id="880e8400-e29b-41d4-a716-446655440003",
            aggregate_version=1,
            debit_note=mock_debit_note,
            issued_by="issuer1"
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_ISSUED


class TestDebitNoteAppliedEvent:
    def test_creation(self, mock_debit_note):
        event = DebitNoteAppliedEvent(
            aggregate_id="880e8400-e29b-41d4-a716-446655440003",
            aggregate_version=1,
            debit_note=mock_debit_note,
            applied_by="applier1"
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_APPLIED


class TestDebitNoteIssuedServiceEvent:
    def test_creation(self):
        legal_entity_id = "11111111-1111-1111-1111-111111111111"
        vendor_id = "22222222-2222-2222-2222-222222222222"
        event = DebitNoteIssuedServiceEvent(
            aggregate_id="880e8400-e29b-41d4-a716-446655440003",
            aggregate_version=1,
            legal_entity_id=legal_entity_id,
            debit_note_number="DN-001",
            vendor_id=vendor_id,
            amount=Decimal("50000"),
            original_invoice_id="550e8400-e29b-41d4-a716-446655440000"
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_ISSUED_SERVICE


class TestThreeWayMatchResultEvent:
    def test_creation(self):
        invoice_id = "550e8400-e29b-41d4-a716-446655440000"
        differences = {"quantity": Decimal("5"), "price": Decimal("1000")}
        event = ThreeWayMatchResultEvent(
            aggregate_id=invoice_id,
            aggregate_version=1,
            invoice_id=invoice_id,
            match_status="PARTIAL_MATCH",
            differences=differences
        )
        assert event.event_type == DomainEventType.THREE_WAY_MATCH_RESULT
        assert event.event_data["differences"] == {"quantity": "5", "price": "1000"}


class TestPaymentRunGeneratedEvent:
    def test_creation(self):
        event = PaymentRunGeneratedEvent(
            aggregate_id="990e8400-e29b-41d4-a716-446655440099",
            aggregate_version=1,
            run_number="PR-001",
            total_amount=Decimal("1500000"),
            payment_count=3
        )
        assert event.event_type == DomainEventType.PAYMENT_RUN_GENERATED
        assert event.event_data["payment_count"] == 3


class TestPaymentRunExecutedEvent:
    def test_creation(self):
        event = PaymentRunExecutedEvent(
            aggregate_id="990e8400-e29b-41d4-a716-446655440099",
            aggregate_version=1,
            run_number="PR-001",
            user_id="admin"
        )
        assert event.event_type == DomainEventType.PAYMENT_RUN_EXECUTED


# ============================================================================
# Tests for DomainEventPublisher
# ============================================================================

class TestDomainEventPublisher:
    def test_publish_not_implemented(self):
        publisher = DomainEventPublisher()
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_RECEIVED,
            aggregate_id="550e8400-e29b-41d4-a716-446655440000",
            aggregate_version=1
        )
        with pytest.raises(NotImplementedError):
            publisher.publish(event)

    async def test_publish_many(self):
        publisher = DomainEventPublisher()
        # Override publish to be async mock
        publisher.publish = AsyncMock()
        events = [MagicMock(), MagicMock()]
        await publisher.publish_many(events)
        publisher.publish.assert_awaited_twice()

    async def test_publish_with_retry_success(self):
        publisher = DomainEventPublisher()
        publisher.publish = AsyncMock()
        event = MagicMock()
        await publisher.publish_with_retry(event, max_retries=3)
        publisher.publish.assert_awaited_once_with(event)

    async def test_publish_with_retry_failure(self):
        publisher = DomainEventPublisher()
        # Make publish fail always
        publisher.publish = AsyncMock(side_effect=Exception("Broker down"))
        event = MagicMock()
        with pytest.raises(Exception, match="Broker down"):
            await publisher.publish_with_retry(event, max_retries=3)
        assert publisher.publish.await_count == 3

    async def test_publish_with_retry_partial_failure(self):
        publisher = DomainEventPublisher()
        # Fail first two attempts, succeed on third
        call_count = 0
        async def mock_publish(event):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary error")
            return
        publisher.publish = mock_publish
        event = MagicMock()
        await publisher.publish_with_retry(event, max_retries=3)
        assert call_count == 3
