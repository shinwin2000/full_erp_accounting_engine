# test_domain_events.py
# ======================
# Comprehensive tests for domain/subledger_ar/domain_events.py.
# Covers all enums, base event class, concrete events, publisher,
# serialization, aliases, and edge cases.

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.subledger_ar.credit_note_entity import (
    CreditNoteEntity,
    CreditNoteReason,
    CreditNoteStatus,
)
from domain.subledger_ar.debit_note_entity import DebitNoteEntity, DebitNoteReason, DebitNoteStatus
from domain.subledger_ar.domain_events import (
    ARCreditNoteIssued,
    ARDebitNoteIssued,
    ARInvoiceApproved,
    ARInvoiceCancelled,
    ARInvoiceCreated,
    ARInvoicePaid,
    ARInvoiceWrittenOff,
    ARPaymentApplied,
    ARPaymentReceived,
    ARPaymentVoided,
    BadDebtProvisionRecordedEvent,
    CreditNoteAppliedEvent,
    CreditNoteIssuedEvent,
    DebitNoteIssuedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    InvoiceApprovedEvent,
    InvoiceCancelledEvent,
    InvoiceIssuedEvent,
    InvoicePaidEvent,
    InvoicePartiallyPaidEvent,
    InvoiceWrittenOffEvent,
    PaymentAllocatedEvent,
    PaymentReceivedEvent,
    PaymentVoidedEvent,
)
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus, InvoiceType
from domain.subledger_ar.payment_entity import PaymentEntity, PaymentMethod, PaymentStatus


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_invoice() -> InvoiceEntity:
    return InvoiceEntity(
        invoice_id=uuid4(),
        invoice_number="INV-2025-001",
        legal_entity_id=uuid4(),
        customer_id=uuid4(),
        customer_name="PT Maju Jaya",
        invoice_date=date(2025, 1, 15),
        due_date=date(2025, 2, 15),
        amount=Decimal("1000.00"),
        currency="IDR",
        status=InvoiceStatus.DRAFT,
        invoice_type=InvoiceType.STANDARD,
        description="Test invoice",
        created_by=uuid4(),
    )


@pytest.fixture
def sample_payment() -> PaymentEntity:
    return PaymentEntity(
        payment_id=uuid4(),
        payment_number="PAY-2025-001",
        legal_entity_id=uuid4(),
        customer_id=uuid4(),
        customer_name="PT Maju Jaya",
        payment_date=date(2025, 1, 20),
        amount=Decimal("1000.00"),
        currency="IDR",
        payment_method=PaymentMethod.TRANSFER,
        status=PaymentStatus.RECEIVED,
        description="Test payment",
        created_by=uuid4(),
    )


@pytest.fixture
def sample_credit_note(sample_invoice) -> CreditNoteEntity:
    return CreditNoteEntity(
        credit_note_id=uuid4(),
        credit_note_number="CN-2025-001",
        invoice_id=sample_invoice.invoice_id,
        invoice_number=sample_invoice.invoice_number,
        customer_id=sample_invoice.customer_id,
        customer_name=sample_invoice.customer_name,
        issue_date=datetime.now(UTC),
        amount=Decimal("200.00"),
        currency="IDR",
        reason=CreditNoteReason.GOODS_RETURN,
        status=CreditNoteStatus.ISSUED,
        description="Return",
        created_by="alice",
    )


@pytest.fixture
def sample_debit_note(sample_invoice) -> DebitNoteEntity:
    return DebitNoteEntity(
        debit_note_id=uuid4(),
        debit_note_number="DN-2025-001",
        invoice_id=sample_invoice.invoice_id,
        invoice_number=sample_invoice.invoice_number,
        customer_id=sample_invoice.customer_id,
        customer_name=sample_invoice.customer_name,
        issue_date=datetime.now(UTC),
        amount=Decimal("150.00"),
        currency="IDR",
        reason=DebitNoteReason.ADDITIONAL_CHARGE,
        status=DebitNoteStatus.ISSUED,
        description="Additional charge",
        created_by="bob",
    )


# ----------------------------------------------------------------------
# DomainEventType Enum
# ----------------------------------------------------------------------
class TestDomainEventType:
    def test_members_exist(self):
        assert hasattr(DomainEventType, "INVOICE_ISSUED")
        assert hasattr(DomainEventType, "INVOICE_APPROVED")
        assert hasattr(DomainEventType, "INVOICE_PAID")
        assert hasattr(DomainEventType, "INVOICE_PARTIALLY_PAID")
        assert hasattr(DomainEventType, "INVOICE_OVERDUE")
        assert hasattr(DomainEventType, "INVOICE_WRITTEN_OFF")
        assert hasattr(DomainEventType, "INVOICE_CANCELLED")
        assert hasattr(DomainEventType, "PAYMENT_RECEIVED")
        assert hasattr(DomainEventType, "PAYMENT_ALLOCATED")
        assert hasattr(DomainEventType, "PAYMENT_REFUNDED")
        assert hasattr(DomainEventType, "CREDIT_NOTE_ISSUED")
        assert hasattr(DomainEventType, "CREDIT_NOTE_APPLIED")
        assert hasattr(DomainEventType, "DEBIT_NOTE_ISSUED")
        assert hasattr(DomainEventType, "DEBIT_NOTE_APPLIED")
        assert hasattr(DomainEventType, "CUSTOMER_CREDIT_LIMIT_CHANGED")
        assert hasattr(DomainEventType, "CUSTOMER_RISK_RATING_CHANGED")
        assert hasattr(DomainEventType, "BAD_DEBT_PROVISION_RECORDED")

    def test_member_is_instance(self):
        assert isinstance(DomainEventType.INVOICE_ISSUED, DomainEventType)

    def test_display_name(self):
        assert DomainEventType.INVOICE_ISSUED.display_name() == "Invoice Issued"
        assert DomainEventType.INVOICE_APPROVED.display_name() == "Invoice Approved"
        assert DomainEventType.INVOICE_PAID.display_name() == "Invoice Paid"
        assert DomainEventType.INVOICE_PARTIALLY_PAID.display_name() == "Invoice Partially Paid"
        assert DomainEventType.INVOICE_OVERDUE.display_name() == "Invoice Overdue"
        assert DomainEventType.INVOICE_WRITTEN_OFF.display_name() == "Invoice Written Off"
        assert DomainEventType.INVOICE_CANCELLED.display_name() == "Invoice Cancelled"
        assert DomainEventType.PAYMENT_RECEIVED.display_name() == "Payment Received"
        assert DomainEventType.PAYMENT_ALLOCATED.display_name() == "Payment Allocated"
        assert DomainEventType.PAYMENT_REFUNDED.display_name() == "Payment Refunded"
        assert DomainEventType.CREDIT_NOTE_ISSUED.display_name() == "Credit Note Issued"
        assert DomainEventType.CREDIT_NOTE_APPLIED.display_name() == "Credit Note Applied"
        assert DomainEventType.DEBIT_NOTE_ISSUED.display_name() == "Debit Note Issued"
        assert DomainEventType.DEBIT_NOTE_APPLIED.display_name() == "Debit Note Applied"
        assert DomainEventType.CUSTOMER_CREDIT_LIMIT_CHANGED.display_name() == "Customer Credit Limit Changed"
        assert DomainEventType.CUSTOMER_RISK_RATING_CHANGED.display_name() == "Customer Risk Rating Changed"
        assert DomainEventType.BAD_DEBT_PROVISION_RECORDED.display_name() == "Bad Debt Provision Recorded"


# ----------------------------------------------------------------------
# DomainEvent Base Class
# ----------------------------------------------------------------------
class TestDomainEvent:
    @pytest.fixture
    def base_event(self) -> DomainEvent:
        return DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
            event_id=uuid4(),
            occurred_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
            event_data={"key": "value"},
            user_id="alice",
            correlation_id="corr-123",
        )

    def test_construction_valid(self, base_event):
        assert base_event.event_type == DomainEventType.INVOICE_ISSUED
        assert base_event.aggregate_version == 1
        assert base_event.occurred_at.tzinfo == UTC
        assert base_event.event_data == {"key": "value"}
        assert base_event.user_id == "alice"
        assert base_event.correlation_id == "corr-123"

    def test_construction_invalid_version(self):
        with pytest.raises(ValueError, match="aggregate_version must be >= 1"):
            DomainEvent(
                event_type=DomainEventType.INVOICE_ISSUED,
                aggregate_id=uuid4(),
                aggregate_type="ARSubledger",
                aggregate_version=0,
            )

    def test_construction_naive_datetime_auto_utc(self):
        naive = datetime(2025, 1, 15, 10, 0)
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
            occurred_at=naive,
        )
        assert event.occurred_at.tzinfo == UTC
        assert event.occurred_at == naive.replace(tzinfo=UTC)

    def test_validate_valid(self, base_event):
        result = base_event.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=0,
        )
        result = event.validate()
        assert result["is_valid"] is False
        assert "aggregate_version must be >= 1" in result["errors"]

    def test_to_dict(self, base_event):
        d = base_event.to_dict()
        assert d["event_id"] == str(base_event.event_id)
        assert d["event_type"] == "invoice_issued"
        assert d["aggregate_id"] == str(base_event.aggregate_id)
        assert d["aggregate_version"] == 1
        assert d["occurred_at"] == base_event.occurred_at.isoformat()
        assert d["event_data"] == {"key": "value"}
        assert d["user_id"] == "alice"
        assert d["correlation_id"] == "corr-123"

    def test_from_dict(self, base_event):
        d = base_event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_id == base_event.event_id
        assert reconstructed.event_type == base_event.event_type
        assert reconstructed.aggregate_id == base_event.aggregate_id
        assert reconstructed.aggregate_version == base_event.aggregate_version
        assert reconstructed.occurred_at == base_event.occurred_at
        assert reconstructed.event_data == base_event.event_data
        assert reconstructed.user_id == base_event.user_id
        assert reconstructed.correlation_id == base_event.correlation_id

    def test_to_json_roundtrip(self, base_event):
        json_str = base_event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed == base_event

    def test_serialize_roundtrip(self, base_event):
        data = base_event.serialize()
        reconstructed = DomainEvent.deserialize(data)
        assert reconstructed == base_event

    def test_clone(self, base_event):
        cloned = base_event.clone()
        assert cloned.event_id != base_event.event_id
        assert cloned.event_type == base_event.event_type
        assert cloned.aggregate_id == base_event.aggregate_id
        assert cloned.aggregate_version == base_event.aggregate_version
        assert cloned.occurred_at != base_event.occurred_at
        assert cloned.event_data == base_event.event_data
        assert cloned.user_id == base_event.user_id
        assert cloned.correlation_id == base_event.correlation_id

    def test_snapshot(self, base_event):
        snap = base_event.snapshot()
        assert snap["event_id"] == str(base_event.event_id)
        assert snap["event_type"] == "invoice_issued"
        assert snap["aggregate_id"] == str(base_event.aggregate_id)
        assert snap["aggregate_version"] == 1
        assert "occurred_at" in snap

    def test_version(self, base_event):
        assert base_event.version() == 1

    def test_audit_trail(self, base_event):
        # Class variable shared; we'll just check it's a list
        assert isinstance(base_event.audit_trail(), list)
        # We can append something to the class variable to test limit? Better not mutate.
        # Just check the method exists and returns a list.
        trail = base_event.audit_trail(limit=5)
        assert isinstance(trail, list)

    def test_touch(self, base_event):
        touched = base_event.touch("system")
        assert touched.event_id != base_event.event_id
        assert touched.occurred_at != base_event.occurred_at
        assert touched.event_type == base_event.event_type
        assert touched.aggregate_id == base_event.aggregate_id

    def test_equality(self, base_event):
        other = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=base_event.aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=1,
            event_id=base_event.event_id,
        )
        assert base_event == other
        different = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        assert base_event != different


# ----------------------------------------------------------------------
# Concrete Event Classes
# ----------------------------------------------------------------------
class TestInvoiceIssuedEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        event = InvoiceIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=2,
            invoice=sample_invoice,
            issued_by="alice",
            user_id="user1",
            correlation_id="corr",
        )
        assert event.event_type == DomainEventType.INVOICE_ISSUED
        assert event.aggregate_id == agg_id
        assert event.aggregate_version == 2
        assert event.event_data["invoice_id"] == str(sample_invoice.invoice_id)
        assert event.event_data["invoice_number"] == sample_invoice.invoice_number
        assert event.event_data["customer_id"] == str(sample_invoice.customer_id)
        assert event.event_data["amount"] == str(sample_invoice.amount)
        assert event.event_data["issued_by"] == "alice"
        assert event.user_id == "user1"


class TestInvoiceApprovedEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        event = InvoiceApprovedEvent(
            aggregate_id=agg_id,
            aggregate_version=3,
            invoice=sample_invoice,
            approved_by="bob",
        )
        assert event.event_type == DomainEventType.INVOICE_APPROVED
        assert event.aggregate_version == 3
        assert event.event_data["approved_by"] == "bob"


class TestInvoicePaidEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        payment_id = uuid4()
        event = InvoicePaidEvent(
            aggregate_id=agg_id,
            aggregate_version=4,
            invoice=sample_invoice,
            payment_id=payment_id,
            payment_amount=Decimal("1000.00"),
        )
        assert event.event_type == DomainEventType.INVOICE_PAID
        assert event.event_data["payment_id"] == str(payment_id)
        assert event.event_data["payment_amount"] == "1000.00"
        assert event.event_data["final_status"] == "fully_paid"


class TestInvoicePartiallyPaidEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        payment_id = uuid4()
        event = InvoicePartiallyPaidEvent(
            aggregate_id=agg_id,
            aggregate_version=5,
            invoice=sample_invoice,
            payment_id=payment_id,
            payment_amount=Decimal("300.00"),
            remaining_amount=Decimal("700.00"),
        )
        assert event.event_type == DomainEventType.INVOICE_PARTIALLY_PAID
        assert event.event_data["payment_amount"] == "300.00"
        assert event.event_data["remaining_amount"] == "700.00"


class TestInvoiceCancelledEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        event = InvoiceCancelledEvent(
            aggregate_id=agg_id,
            aggregate_version=6,
            invoice=sample_invoice,
            reason="Duplicate",
            cancelled_by="carol",
        )
        assert event.event_type == DomainEventType.INVOICE_CANCELLED
        assert event.event_data["reason"] == "Duplicate"
        assert event.event_data["cancelled_by"] == "carol"


class TestInvoiceWrittenOffEvent:
    def test_construction(self, sample_invoice):
        agg_id = uuid4()
        event = InvoiceWrittenOffEvent(
            aggregate_id=agg_id,
            aggregate_version=7,
            invoice=sample_invoice,
            reason="Uncollectible",
            amount=Decimal("500.00"),
            written_off_by="dave",
        )
        assert event.event_type == DomainEventType.INVOICE_WRITTEN_OFF
        assert event.event_data["amount"] == "500.00"
        assert event.event_data["written_off_by"] == "dave"


class TestPaymentReceivedEvent:
    def test_construction(self, sample_payment):
        agg_id = uuid4()
        event = PaymentReceivedEvent(
            aggregate_id=agg_id,
            aggregate_version=8,
            payment=sample_payment,
            received_by="eve",
        )
        assert event.event_type == DomainEventType.PAYMENT_RECEIVED
        assert event.event_data["payment_id"] == str(sample_payment.payment_id)
        assert event.event_data["amount"] == str(sample_payment.amount)
        assert event.event_data["received_by"] == "eve"


class TestPaymentAllocatedEvent:
    def test_construction(self, sample_payment):
        agg_id = uuid4()
        invoice_id = uuid4()
        event = PaymentAllocatedEvent(
            aggregate_id=agg_id,
            aggregate_version=9,
            payment=sample_payment,
            invoice_id=invoice_id,
            allocated_amount=Decimal("500.00"),
        )
        assert event.event_type == DomainEventType.PAYMENT_ALLOCATED
        assert event.event_data["invoice_id"] == str(invoice_id)
        assert event.event_data["allocated_amount"] == "500.00"


class TestCreditNoteIssuedEvent:
    def test_construction(self, sample_credit_note):
        agg_id = uuid4()
        event = CreditNoteIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=10,
            credit_note=sample_credit_note,
            issued_by="frank",
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_ISSUED
        assert event.event_data["credit_note_id"] == str(sample_credit_note.credit_note_id)
        assert event.event_data["amount"] == str(sample_credit_note.amount)
        assert event.event_data["issued_by"] == "frank"


class TestCreditNoteAppliedEvent:
    def test_construction(self, sample_credit_note):
        agg_id = uuid4()
        invoice_id = uuid4()
        event = CreditNoteAppliedEvent(
            aggregate_id=agg_id,
            aggregate_version=11,
            credit_note=sample_credit_note,
            invoice_id=invoice_id,
            applied_amount=Decimal("200.00"),
            applied_by="grace",
        )
        assert event.event_type == DomainEventType.CREDIT_NOTE_APPLIED
        assert event.event_data["invoice_id"] == str(invoice_id)
        assert event.event_data["applied_amount"] == "200.00"
        assert event.event_data["applied_by"] == "grace"


class TestDebitNoteIssuedEvent:
    def test_construction(self, sample_debit_note):
        agg_id = uuid4()
        event = DebitNoteIssuedEvent(
            aggregate_id=agg_id,
            aggregate_version=12,
            debit_note=sample_debit_note,
            issued_by="hank",
        )
        assert event.event_type == DomainEventType.DEBIT_NOTE_ISSUED
        assert event.event_data["debit_note_id"] == str(sample_debit_note.debit_note_id)
        assert event.event_data["amount"] == str(sample_debit_note.amount)
        assert event.event_data["issued_by"] == "hank"


class TestPaymentVoidedEvent:
    def test_construction(self):
        agg_id = uuid4()
        event = PaymentVoidedEvent(
            aggregate_id=agg_id,
            aggregate_version=13,
            payment_number="PAY-001",
            reason="Duplicate",
        )
        assert event.event_type == DomainEventType.PAYMENT_REFUNDED
        assert event.event_data["payment_number"] == "PAY-001"
        assert event.event_data["reason"] == "Duplicate"


class TestBadDebtProvisionRecordedEvent:
    def test_construction(self):
        agg_id = uuid4()
        legal_entity_id = uuid4()
        as_of_date = date(2025, 1, 31)
        event = BadDebtProvisionRecordedEvent(
            aggregate_id=agg_id,
            aggregate_version=14,
            legal_entity_id=legal_entity_id,
            as_of_date=as_of_date,
            total_receivables=Decimal("10000.00"),
            provision_amount=Decimal("500.00"),
            user_id="auditor",
        )
        assert event.event_type == DomainEventType.BAD_DEBT_PROVISION_RECORDED
        assert event.event_data["legal_entity_id"] == str(legal_entity_id)
        assert event.event_data["as_of_date"] == "2025-01-31"
        assert event.event_data["total_receivables"] == "10000.00"
        assert event.event_data["provision_amount"] == "500.00"
        assert event.user_id == "auditor"


# ----------------------------------------------------------------------
# DomainEventPublisher
# ----------------------------------------------------------------------
class TestDomainEventPublisher:
    @pytest.fixture(autouse=True)
    def clear_published_events(self):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher._max_history = 10000
        yield
        DomainEventPublisher._published_events.clear()

    def test_publish_single(self, base_event):
        DomainEventPublisher._published_events.clear()
        assert len(DomainEventPublisher._published_events) == 0
        DomainEventPublisher.publish(base_event)
        assert len(DomainEventPublisher._published_events) == 1
        assert DomainEventPublisher._published_events[0] == base_event

    def test_publish_many(self, base_event):
        e2 = base_event.clone()
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2])
        assert len(DomainEventPublisher._published_events) == 2
        assert DomainEventPublisher._published_events[0] == base_event
        assert DomainEventPublisher._published_events[1] == e2

    def test_add_alias(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.add(base_event)
        assert len(DomainEventPublisher._published_events) == 1

    def test_save_alias(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.save(base_event)
        assert len(DomainEventPublisher._published_events) == 1

    def test_get_events_default(self, base_event):
        e2 = base_event.clone()
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2])
        events = DomainEventPublisher.get_events()
        assert len(events) == 2
        assert events[0] == base_event
        assert events[1] == e2

    def test_get_events_with_limit(self, base_event):
        e2 = base_event.clone()
        e3 = base_event.clone()
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2, e3])
        events = DomainEventPublisher.get_events(limit=2)
        # Should get the last 2 (since list order is append order)
        assert len(events) == 2
        assert events[0] == e2
        assert events[1] == e3

    def test_get_events_with_type_filter(self, base_event):
        # Create another event of different type
        e2 = DomainEvent(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2])
        filtered = DomainEventPublisher.get_events(event_type=DomainEventType.INVOICE_APPROVED)
        assert len(filtered) == 1
        assert filtered[0].event_type == DomainEventType.INVOICE_APPROVED

    def test_get_events_with_type_and_limit(self, base_event):
        e2 = DomainEvent(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        e3 = DomainEvent(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2, e3])
        filtered = DomainEventPublisher.get_events(limit=1, event_type=DomainEventType.INVOICE_APPROVED)
        assert len(filtered) == 1
        assert filtered[0] == e3

    def test_clear(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish(base_event)
        assert len(DomainEventPublisher._published_events) == 1
        DomainEventPublisher.clear()
        assert len(DomainEventPublisher._published_events) == 0

    def test_get_statistics_empty(self):
        DomainEventPublisher._published_events.clear()
        stats = DomainEventPublisher.get_statistics()
        assert stats["total_events"] == 0
        assert stats["by_event_type"] == {}
        assert stats["max_history"] == 10000

    def test_get_statistics_with_events(self, base_event):
        e2 = DomainEvent(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish_many([base_event, e2, base_event])
        stats = DomainEventPublisher.get_statistics()
        assert stats["total_events"] == 3
        assert stats["by_event_type"] == {
            "invoice_issued": 2,
            "invoice_approved": 1,
        }
        assert stats["max_history"] == 10000

    def test_reset(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish(base_event)
        assert len(DomainEventPublisher._published_events) == 1
        DomainEventPublisher.reset()
        assert len(DomainEventPublisher._published_events) == 0

    def test_set_max_history_truncates(self, base_event):
        DomainEventPublisher._published_events.clear()
        # Publish 5 events
        for _i in range(5):
            ev = DomainEvent(
                event_type=DomainEventType.INVOICE_ISSUED,
                aggregate_id=uuid4(),
                aggregate_type="ARSubledger",
                aggregate_version=1,
            )
            DomainEventPublisher.publish(ev)
        assert len(DomainEventPublisher._published_events) == 5
        DomainEventPublisher.set_max_history(3)
        assert len(DomainEventPublisher._published_events) == 3
        assert DomainEventPublisher._max_history == 3

    def test_set_max_history_no_truncate_when_less(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.publish(base_event)
        DomainEventPublisher.set_max_history(10)
        assert len(DomainEventPublisher._published_events) == 1
        assert DomainEventPublisher._max_history == 10

    def test_publish_async(self, base_event):
        # Test async methods using pytest-asyncio if needed, but we can just call them
        # without awaiting since they are async but don't do IO in tests.
        # For synchronous tests we can just call them normally with await.
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        DomainEventPublisher._published_events.clear()
        loop.run_until_complete(DomainEventPublisher.publish(base_event))
        assert len(DomainEventPublisher._published_events) == 1


# ----------------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------------
class TestAliases:
    def test_aliases_exist(self):
        assert ARInvoiceCreated is InvoiceIssuedEvent
        assert ARInvoiceApproved is InvoiceApprovedEvent
        assert ARInvoicePaid is InvoicePaidEvent
        assert ARInvoiceCancelled is InvoiceCancelledEvent
        assert ARInvoiceWrittenOff is InvoiceWrittenOffEvent
        assert ARPaymentReceived is PaymentReceivedEvent
        assert ARPaymentApplied is PaymentAllocatedEvent
        assert ARPaymentVoided is PaymentVoidedEvent
        assert ARCreditNoteIssued is CreditNoteIssuedEvent
        assert ARDebitNoteIssued is DebitNoteIssuedEvent

    def test_alias_usage(self, sample_invoice):
        # Just ensure they can be instantiated
        event = ARInvoiceCreated(
            aggregate_id=uuid4(),
            aggregate_version=1,
            invoice=sample_invoice,
            issued_by="alice",
        )
        assert event.event_type == DomainEventType.INVOICE_ISSUED

# ----------------------------------------------------------------------
# Edge Cases
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_base_event_with_empty_event_data(self):
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        assert event.event_data == {}

    def test_deserialize_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            DomainEvent.from_json("invalid json")

    def test_to_dict_with_none_user_id(self):
        event = DomainEvent(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=uuid4(),
            aggregate_type="ARSubledger",
            aggregate_version=1,
        )
        d = event.to_dict()
        assert d["user_id"] is None
        assert d["correlation_id"] is None

    def test_serialize_deserialize_binary(self, base_event):
        data = base_event.serialize()
        reconstructed = DomainEvent.deserialize(data)
        assert reconstructed == base_event

    def test_publisher_limit_behavior(self, base_event):
        DomainEventPublisher._published_events.clear()
        DomainEventPublisher.set_max_history(2)
        ev1 = base_event
        ev2 = base_event.clone()
        ev3 = base_event.clone()
        DomainEventPublisher.publish(ev1)
        DomainEventPublisher.publish(ev2)
        DomainEventPublisher.publish(ev3)
        assert len(DomainEventPublisher._published_events) == 2
        # The oldest (ev1) should be dropped, so the remaining are ev2 and ev3
        assert DomainEventPublisher._published_events[0] == ev2
        assert DomainEventPublisher._published_events[1] == ev3
