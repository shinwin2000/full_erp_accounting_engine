# tests/domain/bank_cash/test_domain_events.py
"""
Comprehensive unit tests for domain_events.py.

Covers:
- DomainEventType enum (members, values)
- DomainEvent base class (construction, to_json, from_json, to_dict)
- All concrete event classes (20+ events) with parametrized tests
- DomainEventPublisher (publish, publish_many, get_published_events, clear)
- Shim classes for backward compatibility (BankAccountCreated, etc.)
- Negative path: missing required args, invalid types, etc.
- Mock datetime to avoid flaky tests
"""

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from domain.bank_cash.domain_events import (
    BankAccountBlockedEvent,
    BankAccountClosedEvent,
    BankAccountCreated,
    BankAccountCreatedEvent,
    BankAccountUpdated,
    BankAccountUpdatedEvent,
    BankReconciliationCompleted,
    BankReconciliationCompletedEvent,
    BankTransactionClearedEvent,
    BankTransactionReconciledEvent,
    BankTransactionRecorded,
    BankTransactionRecordedEvent,
    BankTransferCancelledEvent,
    BankTransferCompletedEvent,
    BankTransferExecuted,
    BankTransferFailedEvent,
    BankTransferInitiatedEvent,
    CashBookClosedEvent,
    CashBookUpdatedEvent,
    CashDisbursementApprovedEvent,
    CashDisbursementCancelledEvent,
    CashDisbursementIssued,
    CashDisbursementPaidEvent,
    CashReceiptCancelledEvent,
    CashReceiptConfirmedEvent,
    CashReceiptIssued,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    PettyCashActivatedEvent,
    PettyCashAdjustedEvent,
    PettyCashClosedEvent,
    PettyCashDisbursementEvent,
    PettyCashFundCreated,
    PettyCashReplenished,
    PettyCashReplenishedEvent,
    PettyCashSuspendedEvent,
)

# =============================================================================
# FIXED DATETIME (untuk menghindari flaky)
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now(UTC) to return fixed datetime."""
    with patch("domain.bank_cash.domain_events.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Helper: create a valid DomainEvent for testing
# =============================================================================

def create_domain_event(
    event_id=None,
    event_type=DomainEventType.BANK_ACCOUNT_CREATED,
    aggregate_id=None,
    aggregate_version=1,
    occurred_at=FIXED_DATETIME,
    event_data=None,
    user_id="user123",
    correlation_id="corr-123",
    causation_id="cause-123",
):
    if event_id is None:
        event_id = uuid4()
    if aggregate_id is None:
        aggregate_id = uuid4()
    if event_data is None:
        event_data = {"key": "value"}
    return DomainEvent(
        event_id=event_id,
        event_type=event_type,
        aggregate_id=aggregate_id,
        aggregate_version=aggregate_version,
        occurred_at=occurred_at,
        event_data=event_data,
        user_id=user_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


# =============================================================================
# Tests for DomainEventType Enum
# =============================================================================

class TestDomainEventType:
    def test_members(self):
        assert DomainEventType.BANK_ACCOUNT_CREATED.value == "bank_account_created"
        assert DomainEventType.BANK_ACCOUNT_UPDATED.value == "bank_account_updated"
        assert DomainEventType.BANK_ACCOUNT_BLOCKED.value == "bank_account_blocked"
        assert DomainEventType.BANK_ACCOUNT_CLOSED.value == "bank_account_closed"
        assert DomainEventType.BANK_TRANSACTION_RECORDED.value == "bank_transaction_recorded"
        assert DomainEventType.BANK_TRANSACTION_CLEARED.value == "bank_transaction_cleared"
        assert DomainEventType.BANK_TRANSACTION_RECONCILED.value == "bank_transaction_reconciled"
        assert DomainEventType.BANK_TRANSFER_INITIATED.value == "bank_transfer_initiated"
        assert DomainEventType.BANK_TRANSFER_COMPLETED.value == "bank_transfer_completed"
        assert DomainEventType.BANK_TRANSFER_FAILED.value == "bank_transfer_failed"
        assert DomainEventType.BANK_TRANSFER_CANCELLED.value == "bank_transfer_cancelled"
        assert DomainEventType.CASH_RECEIPT_CONFIRMED.value == "cash_receipt_confirmed"
        assert DomainEventType.CASH_RECEIPT_CANCELLED.value == "cash_receipt_cancelled"
        assert DomainEventType.CASH_DISBURSEMENT_APPROVED.value == "cash_disbursement_approved"
        assert DomainEventType.CASH_DISBURSEMENT_PAID.value == "cash_disbursement_paid"
        assert DomainEventType.CASH_DISBURSEMENT_CANCELLED.value == "cash_disbursement_cancelled"
        assert DomainEventType.PETTY_CASH_DISBURSEMENT.value == "petty_cash_disbursement"
        assert DomainEventType.PETTY_CASH_REPLENISHED.value == "petty_cash_replenished"
        assert DomainEventType.PETTY_CASH_ADJUSTED.value == "petty_cash_adjusted"
        assert DomainEventType.PETTY_CASH_SUSPENDED.value == "petty_cash_suspended"
        assert DomainEventType.PETTY_CASH_ACTIVATED.value == "petty_cash_activated"
        assert DomainEventType.PETTY_CASH_CLOSED.value == "petty_cash_closed"
        assert DomainEventType.BANK_RECONCILIATION_COMPLETED.value == "bank_reconciliation_completed"
        assert DomainEventType.CASH_BOOK_UPDATED.value == "cash_book_updated"
        assert DomainEventType.CASH_BOOK_CLOSED.value == "cash_book_closed"


# =============================================================================
# Tests for DomainEvent Base Class
# =============================================================================

class TestDomainEvent:
    def test_construction(self):
        event = create_domain_event()
        assert event.event_id is not None
        assert event.event_type == DomainEventType.BANK_ACCOUNT_CREATED
        assert event.aggregate_version == 1
        assert event.occurred_at == FIXED_DATETIME
        assert event.event_data == {"key": "value"}
        assert event.user_id == "user123"

    def test_to_json(self):
        event = create_domain_event()
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_id"] == str(event.event_id)
        assert data["event_type"] == event.event_type.value
        assert data["aggregate_id"] == str(event.aggregate_id)
        assert data["aggregate_version"] == event.aggregate_version
        assert data["occurred_at"] == event.occurred_at.isoformat()
        assert data["user_id"] == event.user_id
        assert data["correlation_id"] == event.correlation_id
        assert data["causation_id"] == event.causation_id
        assert data["event_data"] == event.event_data

    def test_from_json(self):
        event = create_domain_event()
        json_str = event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.occurred_at == event.occurred_at
        assert reconstructed.user_id == event.user_id
        assert reconstructed.correlation_id == event.correlation_id
        assert reconstructed.causation_id == event.causation_id
        assert reconstructed.event_data == event.event_data

    def test_to_dict(self):
        event = create_domain_event()
        d = event.to_dict()
        assert d["event_id"] == str(event.event_id)
        assert d["event_type"] == event.event_type.value
        assert d["aggregate_id"] == str(event.aggregate_id)
        assert d["aggregate_version"] == event.aggregate_version
        assert d["occurred_at"] == event.occurred_at.isoformat()
        assert d["user_id"] == event.user_id
        assert d["correlation_id"] == event.correlation_id
        assert d["causation_id"] == event.causation_id
        assert d["event_data"] == event.event_data


# =============================================================================
# Tests for DomainEventPublisher
# =============================================================================

@pytest.mark.asyncio
class TestDomainEventPublisher:
    def test_construction(self):
        publisher = DomainEventPublisher()
        assert publisher._published_events == []

    async def test_publish_single(self):
        publisher = DomainEventPublisher()
        event = create_domain_event()
        await publisher.publish(event)
        published = publisher.get_published_events()
        assert len(published) == 1
        assert published[0] is event

    async def test_publish_many(self):
        publisher = DomainEventPublisher()
        events = [create_domain_event(), create_domain_event()]
        await publisher.publish_many(events)
        published = publisher.get_published_events()
        assert len(published) == 2
        assert published == events

    async def test_clear(self):
        publisher = DomainEventPublisher()
        event = create_domain_event()
        await publisher.publish(event)
        publisher.clear()
        published = publisher.get_published_events()
        assert published == []

    def test_get_published_events_returns_copy(self):
        publisher = DomainEventPublisher()
        event = create_domain_event()
        publisher._published_events = [event]
        result = publisher.get_published_events()
        assert result == [event]
        result.append("extra")
        assert publisher._published_events == [event]  # original unchanged


# =============================================================================
# Parametrized Tests for Concrete Event Classes
# =============================================================================

# All concrete event classes (dataclass-based) with their required arguments
EVENT_CLASSES = [
    (BankAccountCreatedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 1,
        "account_id": uuid4(),
        "account_number": "123456",
        "account_name": "Current Account",
        "account_type": "checking",
        "bank_name": "BNI",
        "currency": "IDR",
        "initial_balance": Decimal("1000000"),
        "created_by": "admin",
    }),
    (BankAccountUpdatedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 2,
        "account_id": uuid4(),
        "changes": {"account_name": "New Name"},
        "updated_by": "admin",
    }),
    (BankAccountBlockedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 3,
        "account_id": uuid4(),
        "reason": "Fraud",
        "blocked_by": "admin",
    }),
    (BankAccountClosedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 4,
        "account_id": uuid4(),
        "closed_by": "admin",
    }),
    (BankTransactionRecordedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 5,
        "transaction_id": uuid4(),
        "account_id": uuid4(),
        "amount": Decimal("500000"),
        "currency": "IDR",
        "transaction_type": "debit",
        "recorded_by": "admin",
        "reference_number": "REF-001",
    }),
    (BankTransactionClearedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 6,
        "transaction_id": uuid4(),
        "cleared_by": "admin",
    }),
    (BankTransactionReconciledEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 7,
        "transaction_id": uuid4(),
        "reconciled_by": "admin",
    }),
    (BankTransferInitiatedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 8,
        "transfer_id": uuid4(),
        "from_account_id": uuid4(),
        "to_account_id": uuid4(),
        "amount": Decimal("2000000"),
        "currency": "IDR",
        "initiated_by": "admin",
    }),
    (BankTransferCompletedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 9,
        "transfer_id": uuid4(),
        "completed_by": "admin",
        "reference": "BANK-REF",
    }),
    (BankTransferFailedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 10,
        "transfer_id": uuid4(),
        "reason": "Insufficient funds",
        "failed_by": "admin",
    }),
    (BankTransferCancelledEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 11,
        "transfer_id": uuid4(),
        "reason": "Cancelled by user",
        "cancelled_by": "admin",
    }),
    (CashReceiptConfirmedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 12,
        "receipt_id": uuid4(),
        "receipt_number": "REC-001",
        "amount": Decimal("500000"),
        "currency": "IDR",
        "confirmed_by": "admin",
    }),
    (CashReceiptCancelledEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 13,
        "receipt_id": uuid4(),
        "reason": "Duplicate",
        "cancelled_by": "admin",
    }),
    (CashDisbursementApprovedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 14,
        "disbursement_id": uuid4(),
        "amount": Decimal("300000"),
        "currency": "IDR",
        "approved_by": "admin",
    }),
    (CashDisbursementPaidEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 15,
        "disbursement_id": uuid4(),
        "paid_by": "admin",
    }),
    (CashDisbursementCancelledEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 16,
        "disbursement_id": uuid4(),
        "reason": "Void",
        "cancelled_by": "admin",
    }),
    (PettyCashDisbursementEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 17,
        "petty_cash_id": uuid4(),
        "amount": Decimal("50000"),
        "description": "Office supplies",
        "approved_by": "admin",
    }),
    (PettyCashReplenishedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 18,
        "petty_cash_id": uuid4(),
        "amount": Decimal("1000000"),
        "replenished_by": "admin",
    }),
    (PettyCashAdjustedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 19,
        "petty_cash_id": uuid4(),
        "adjustment_amount": Decimal("50000"),
        "reason": "Correction",
        "adjusted_by": "admin",
    }),
    (PettyCashSuspendedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 20,
        "petty_cash_id": uuid4(),
        "reason": "Audit",
        "suspended_by": "admin",
    }),
    (PettyCashActivatedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 21,
        "petty_cash_id": uuid4(),
        "activated_by": "admin",
    }),
    (PettyCashClosedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 22,
        "petty_cash_id": uuid4(),
        "final_balance": Decimal("100000"),
        "closed_by": "admin",
    }),
    (BankReconciliationCompletedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 23,
        "account_id": uuid4(),
        "statement_date": FIXED_DATETIME,
        "statement_balance": Decimal("1000000"),
        "book_balance": Decimal("1000000"),
        "difference": Decimal("0"),
        "reconciled_by": "admin",
    }),
    (CashBookUpdatedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 24,
        "cash_book_id": uuid4(),
        "new_balance": Decimal("1500000"),
        "transaction_type": "credit",
        "amount": Decimal("500000"),
        "updated_by": "admin",
    }),
    (CashBookClosedEvent, {
        "aggregate_id": uuid4(),
        "aggregate_version": 25,
        "cash_book_id": uuid4(),
        "closed_by": "admin",
    }),
]


class TestConcreteEvents:
    @pytest.mark.parametrize("event_class, kwargs", EVENT_CLASSES)
    def test_construction_success(self, event_class, kwargs):
        event = event_class(**kwargs)
        assert isinstance(event, DomainEvent)
        assert event.event_type is not None
        assert event.aggregate_id == kwargs["aggregate_id"]
        assert event.aggregate_version == kwargs["aggregate_version"]
        assert event.occurred_at == FIXED_DATETIME
        # Check that event_data contains the expected fields
        for key in kwargs:
            if key not in ("aggregate_id", "aggregate_version"):
                value = kwargs[key]
                if isinstance(value, uuid4().__class__ | Decimal):
                    assert str(value) == event.event_data.get(key)
                elif isinstance(value, datetime):
                    assert value.isoformat() == event.event_data.get(key)
                else:
                    assert event.event_data.get(key) == value

    @pytest.mark.parametrize("event_class, kwargs", EVENT_CLASSES)
    def test_event_id_generated(self, event_class, kwargs):
        """Ensure event_id is automatically generated."""
        event = event_class(**kwargs)
        assert event.event_id is not None
        assert isinstance(event.event_id, UUID)

    @pytest.mark.parametrize("event_class, kwargs", EVENT_CLASSES)
    def test_to_dict_includes_event_data(self, event_class, kwargs):
        event = event_class(**kwargs)
        d = event.to_dict()
        assert d["event_type"] == event.event_type.value
        assert d["event_data"] is not None
        # Check that event_data contains the kwargs (except aggregate_id/version)
        for key in kwargs:
            if key not in ("aggregate_id", "aggregate_version"):
                value = kwargs[key]
                if isinstance(value, uuid4().__class__ | Decimal):
                    assert d["event_data"][key] == str(value)
                elif isinstance(value, datetime):
                    assert d["event_data"][key] == value.isoformat()
                else:
                    assert d["event_data"].get(key) == value


# =============================================================================
# Tests for Shim Classes (Backward Compatibility)
# =============================================================================

SHIM_CLASSES = [
    BankAccountCreated,
    BankAccountUpdated,
    BankTransactionRecorded,
    BankReconciliationCompleted,
    BankTransferExecuted,
    CashReceiptIssued,
    CashDisbursementIssued,
    PettyCashFundCreated,
    PettyCashReplenished,
]


class TestShimClasses:
    @pytest.mark.parametrize("shim_class", SHIM_CLASSES)
    def test_shim_construction_with_kwargs(self, shim_class):
        """Shim classes should accept arbitrary kwargs."""
        event = shim_class(
            aggregate_id=uuid4(),
            aggregate_version=1,
            some_field="value",
            another=123,
        )
        assert isinstance(event, DomainEvent)
        assert event.event_id is not None
        assert event.event_type is not None
        assert event.occurred_at == FIXED_DATETIME
        # Check that kwargs are stored in event_data
        if hasattr(event, "event_data"):
            assert event.event_data.get("some_field") == "value"
            assert event.event_data.get("another") == 123

    @pytest.mark.parametrize("shim_class", SHIM_CLASSES)
    def test_shim_event_type_inferred(self, shim_class):
        event = shim_class()
        # All shim classes should have a default event_type
        assert event.event_type is not None

    def test_bank_account_created_shim_with_specific_args(self):
        event = BankAccountCreated(
            aggregate_id=uuid4(),
            aggregate_version=1,
            account_id=uuid4(),
            account_name="Test",
            initial_balance=Decimal("1000"),
        )
        assert event.event_data["account_name"] == "Test"
        assert event.event_data["initial_balance"] == "1000"

    def test_bank_account_updated_shim(self):
        event = BankAccountUpdated(
            aggregate_id=uuid4(),
            aggregate_version=2,
            changes={"name": "New"},
            updated_by="admin",
        )
        assert event.event_data["changes"] == {"name": "New"}


# =============================================================================
# Tests for Aliases (BankTransferExecutedEvent, etc.)
# =============================================================================

class TestAliases:
    def test_bank_transfer_executed_event_alias(self):
        from domain.bank_cash.domain_events import BankTransferExecutedEvent
        event = BankTransferExecutedEvent(
            aggregate_id=uuid4(),
            aggregate_version=1,
            transfer_id=uuid4(),
            completed_by="admin",
        )
        assert isinstance(event, DomainEvent)
        assert event.event_type == DomainEventType.BANK_TRANSFER_COMPLETED

    def test_cash_receipt_issued_event_alias(self):
        from domain.bank_cash.domain_events import CashReceiptIssuedEvent
        event = CashReceiptIssuedEvent(
            aggregate_id=uuid4(),
            aggregate_version=1,
            receipt_id=uuid4(),
            confirmed_by="admin",
        )
        assert event.event_type == DomainEventType.CASH_RECEIPT_CONFIRMED

    def test_cash_disbursement_issued_event_alias(self):
        from domain.bank_cash.domain_events import CashDisbursementIssuedEvent
        event = CashDisbursementIssuedEvent(
            aggregate_id=uuid4(),
            aggregate_version=1,
            disbursement_id=uuid4(),
            paid_by="admin",
        )
        assert event.event_type == DomainEventType.CASH_DISBURSEMENT_PAID

    def test_petty_cash_fund_created_event_alias(self):
        from domain.bank_cash.domain_events import PettyCashFundCreatedEvent
        event = PettyCashFundCreatedEvent(
            aggregate_id=uuid4(),
            aggregate_version=1,
            petty_cash_id=uuid4(),
            replenished_by="admin",
        )
        assert event.event_type == DomainEventType.PETTY_CASH_REPLENISHED

    def test_petty_cash_replenished_event_alias(self):
        from domain.bank_cash.domain_events import PettyCashReplenishedEvent
        event = PettyCashReplenishedEvent(
            aggregate_id=uuid4(),
            aggregate_version=1,
            petty_cash_id=uuid4(),
            replenished_by="admin",
        )
        assert event.event_type == DomainEventType.PETTY_CASH_REPLENISHED


# =============================================================================
# Negative Path Tests (Missing Required Arguments, Invalid Types)
# =============================================================================

class TestNegativePaths:
    def test_domain_event_missing_required(self):
        with pytest.raises(TypeError):
            DomainEvent()  # missing required args

    def test_concrete_event_missing_required(self):
        with pytest.raises(TypeError):
            BankAccountCreatedEvent()  # missing required args

    def test_shim_class_handles_missing_optional(self):
        # Shim classes have default values, so they should not raise
        event = BankAccountCreated()
        assert event.event_id is not None

    def test_from_json_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            DomainEvent.from_json("invalid json")

    def test_from_json_missing_fields(self):
        # JSON missing required fields should raise KeyError
        with pytest.raises(KeyError):
            DomainEvent.from_json('{"event_id": "123"}')

    def test_to_json_with_decimal(self):
        event = create_domain_event()
        event.event_data["decimal"] = Decimal("10.50")
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_data"]["decimal"] == "10.50"

    def test_to_json_with_uuid(self):
        event = create_domain_event()
        u = uuid4()
        event.event_data["uuid"] = u
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_data"]["uuid"] == str(u)
