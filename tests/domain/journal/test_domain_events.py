"""
Tests for domain/journal/domain_events.py

Covers:
- DomainEventType.from_string (incl. fallback)
- DomainEvent: to_json/from_json round trip, serialize/deserialize
- Concrete events: JournalCreatedEvent, JournalSubmittedEvent, JournalApprovedEvent,
  JournalRejectedEvent, JournalPostedEvent (incl. balance validation),
  JournalReversedEvent, JournalVoidedEvent, JournalAdjustedEvent,
  JournalArchivedEvent, JournalUnarchivedEvent, JournalCancelledEvent
- Backwards-compatible aliases
- DomainEventPublisher: publish (abstract), publish_many, publish_with_retry
  (success / transient retry / exhausted retries / immediate custom-error
  propagation / unexpected-error wrapping)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    EventPublishError,
    EventPublishTimeoutError,
    EventPublishUnexpectedError,
    JournalAdjusted,
    JournalAdjustedEvent,
    JournalApproved,
    JournalApprovedEvent,
    JournalArchived,
    JournalArchivedEvent,
    JournalCancelled,
    JournalCancelledEvent,
    JournalCreated,
    JournalCreatedEvent,
    JournalPosted,
    JournalPostedEvent,
    JournalRejected,
    JournalRejectedEvent,
    JournalReversed,
    JournalReversedEvent,
    JournalSubmitted,
    JournalSubmittedEvent,
    JournalUnarchived,
    JournalUnarchivedEvent,
    JournalVoided,
    JournalVoidedEvent,
)
from domain.journal.journal_entity import JournalEntity, JournalStatus, JournalType

# ============================================================================
# DomainEventType
# ============================================================================


class TestDomainEventType:
    def test_from_string_valid(self):
        assert DomainEventType.from_string("journal_posted") == DomainEventType.JOURNAL_POSTED

    def test_from_string_case_insensitive(self):
        assert DomainEventType.from_string("JOURNAL_POSTED") == DomainEventType.JOURNAL_POSTED

    def test_from_string_unknown_falls_back_to_created(self):
        assert DomainEventType.from_string("bogus_event") == DomainEventType.JOURNAL_CREATED


# ============================================================================
# DomainEvent (base)
# ============================================================================


class TestDomainEventBase:
    def test_construction_generates_id_and_timestamp(self):
        event = DomainEvent(
            event_type=DomainEventType.JOURNAL_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
        )
        assert event.event_id is not None
        assert event.occurred_at is not None

    def test_to_json_and_from_json_round_trip(self):
        event = DomainEvent(
            event_type=DomainEventType.JOURNAL_POSTED,
            aggregate_id=uuid4(),
            aggregate_version=2,
            event_data={"foo": "bar"},
            user_id="user_x",
            correlation_id="corr-1",
        )
        json_str = event.to_json()
        restored = DomainEvent.from_json(json_str)
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type
        assert restored.aggregate_id == event.aggregate_id
        assert restored.aggregate_version == event.aggregate_version
        assert restored.event_data == {"foo": "bar"}
        assert restored.user_id == "user_x"
        assert restored.correlation_id == "corr-1"

    def test_serialize_and_deserialize_round_trip(self):
        event = DomainEvent(
            event_type=DomainEventType.JOURNAL_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
        )
        raw = event.serialize()
        assert isinstance(raw, bytes)
        restored = DomainEvent.deserialize(raw)
        assert restored.event_id == event.event_id

    def test_event_is_immutable(self):
        event = DomainEvent(
            event_type=DomainEventType.JOURNAL_CREATED, aggregate_id=uuid4(), aggregate_version=1,
        )
        with pytest.raises(Exception):
            event.aggregate_version = 99


# ============================================================================
# Fixture: a real balanced JournalEntity for concrete events
# ============================================================================


@pytest.fixture
def journal():
    now = datetime.now(UTC)
    return JournalEntity(
        journal_id=uuid4(),
        journal_number="JRN-500",
        journal_type=JournalType.GENERAL,
        transaction_date=now,
        description="Event fixture journal",
        legal_entity_id=uuid4(),
        status=JournalStatus.DRAFT,
        created_by="user_a",
        created_at=now,
        updated_at=now,
        total_debit=Decimal("100"),
        total_credit=Decimal("100"),
    )


# ============================================================================
# Concrete events
# ============================================================================


class TestJournalCreatedEvent:
    def test_event_data_fields(self, journal):
        event = JournalCreatedEvent(
            aggregate_id=journal.journal_id, aggregate_version=1, journal=journal,
            lines_count=2, created_by="user_a",
        )
        assert event.event_type == DomainEventType.JOURNAL_CREATED
        assert event.event_data["journal_number"] == "JRN-500"
        assert event.event_data["lines_count"] == 2
        assert event.event_data["total_debit"] == "100"

    def test_alias_is_same_class(self):
        assert JournalCreated is JournalCreatedEvent


class TestJournalSubmittedEvent:
    def test_event_data_fields(self, journal):
        event = JournalSubmittedEvent(
            aggregate_id=journal.journal_id, aggregate_version=2, journal=journal, submitted_by="user_b",
        )
        assert event.event_type == DomainEventType.JOURNAL_SUBMITTED
        assert event.event_data["submitted_by"] == "user_b"

    def test_alias_is_same_class(self):
        assert JournalSubmitted is JournalSubmittedEvent


class TestJournalApprovedEvent:
    def test_event_data_fields(self, journal):
        event = JournalApprovedEvent(
            aggregate_id=journal.journal_id, aggregate_version=3, journal=journal, approved_by="user_c",
        )
        assert event.event_type == DomainEventType.JOURNAL_APPROVED
        assert event.event_data["approved_by"] == "user_c"

    def test_alias_is_same_class(self):
        assert JournalApproved is JournalApprovedEvent


class TestJournalRejectedEvent:
    def test_event_data_fields(self, journal):
        event = JournalRejectedEvent(
            aggregate_id=journal.journal_id, aggregate_version=3, journal=journal,
            rejected_by="user_c", reason="incomplete documentation",
        )
        assert event.event_data["reason"] == "incomplete documentation"

    def test_alias_is_same_class(self):
        assert JournalRejected is JournalRejectedEvent


class TestJournalPostedEvent:
    def test_valid_balanced_event(self, journal):
        event = JournalPostedEvent(
            aggregate_id=journal.journal_id, aggregate_version=4, journal=journal,
            total_debit=Decimal("100"), total_credit=Decimal("100"), posted_by="user_d",
        )
        assert event.event_data["total_debit"] == "100"
        assert event.event_data["posted_by"] == "user_d"

    def test_unbalanced_totals_raise(self, journal):
        with pytest.raises(ValueError, match="Unbalanced journal"):
            JournalPostedEvent(
                aggregate_id=journal.journal_id, aggregate_version=4, journal=journal,
                total_debit=Decimal("100"), total_credit=Decimal("50"), posted_by="user_d",
            )

    def test_negative_totals_raise(self, journal):
        with pytest.raises(ValueError, match="non-negative"):
            JournalPostedEvent(
                aggregate_id=journal.journal_id, aggregate_version=4, journal=journal,
                total_debit=Decimal("-1"), total_credit=Decimal("-1"), posted_by="user_d",
            )

    def test_lines_count_defaults_to_zero_when_entity_has_no_lines_attr(self, journal):
        # JournalEntity has no `.lines` attribute; getattr(journal, "lines", []) -> []
        event = JournalPostedEvent(
            aggregate_id=journal.journal_id, aggregate_version=4, journal=journal,
            total_debit=Decimal("100"), total_credit=Decimal("100"), posted_by="user_d",
        )
        assert event.event_data["lines_count"] == 0

    def test_alias_is_same_class(self):
        assert JournalPosted is JournalPostedEvent


class TestJournalReversedEvent:
    def test_event_data_fields(self, journal):
        original_id = uuid4()
        reversal_id = uuid4()
        event = JournalReversedEvent(
            aggregate_id=journal.journal_id, aggregate_version=5,
            original_journal_id=original_id, reversal_journal_id=reversal_id,
            journal=journal, reversed_by="user_e", reason="correction needed",
        )
        assert event.event_data["original_journal_id"] == str(original_id)
        assert event.event_data["reversal_journal_id"] == str(reversal_id)
        assert event.event_data["reason"] == "correction needed"

    def test_alias_is_same_class(self):
        assert JournalReversed is JournalReversedEvent


class TestJournalVoidedEvent:
    def test_event_data_fields(self, journal):
        event = JournalVoidedEvent(
            aggregate_id=journal.journal_id, aggregate_version=1, journal=journal,
            voided_by="user_f", reason="duplicate entry",
        )
        assert event.event_data["voided_by"] == "user_f"
        assert event.event_data["reason"] == "duplicate entry"

    def test_alias_is_same_class(self):
        assert JournalVoided is JournalVoidedEvent


class TestJournalAdjustedEvent:
    def test_event_data_fields(self, journal):
        event = JournalAdjustedEvent(
            aggregate_id=journal.journal_id, aggregate_version=6, journal=journal,
            adjusted_by="user_g", adjustment_reason="year-end accrual",
        )
        assert event.event_data["adjustment_reason"] == "year-end accrual"

    def test_alias_is_same_class(self):
        assert JournalAdjusted is JournalAdjustedEvent


class TestJournalArchivedEvent:
    def test_event_data_fields(self, journal):
        event = JournalArchivedEvent(
            aggregate_id=journal.journal_id, aggregate_version=7, journal=journal, archived_by="user_h",
        )
        assert event.event_data["archived_by"] == "user_h"

    def test_alias_is_same_class(self):
        assert JournalArchived is JournalArchivedEvent


class TestJournalUnarchivedEvent:
    def test_event_data_fields(self, journal):
        event = JournalUnarchivedEvent(
            aggregate_id=journal.journal_id, aggregate_version=8, journal=journal, unarchived_by="user_i",
        )
        assert event.event_data["unarchived_by"] == "user_i"

    def test_alias_is_same_class(self):
        assert JournalUnarchived is JournalUnarchivedEvent


class TestJournalCancelledEvent:
    def test_event_data_fields(self, journal):
        event = JournalCancelledEvent(
            aggregate_id=journal.journal_id, aggregate_version=1, journal=journal,
            cancelled_by="user_j", reason="created in error",
        )
        assert event.event_data["cancelled_by"] == "user_j"
        assert event.event_data["reason"] == "created in error"

    def test_alias_is_same_class(self):
        assert JournalCancelled is JournalCancelledEvent


# ============================================================================
# DomainEventPublisher
# ============================================================================


class RecordingPublisher(DomainEventPublisher):
    """Concrete publisher used to test the base class's default behaviour."""

    def __init__(self, fail_times=0, error_factory=None):
        self.published = []
        self.fail_times = fail_times
        self.error_factory = error_factory or (lambda: ConnectionError("transient"))
        self._attempts = 0

    async def publish(self, event):
        self._attempts += 1
        if self._attempts <= self.fail_times:
            raise self.error_factory()
        self.published.append(event)


def make_event():
    return DomainEvent(
        event_type=DomainEventType.JOURNAL_CREATED, aggregate_id=uuid4(), aggregate_version=1,
    )


class TestDomainEventPublisher:
    async def test_base_publish_is_not_implemented(self):
        publisher = DomainEventPublisher()
        with pytest.raises(NotImplementedError):
            await publisher.publish(make_event())

    async def test_publish_many_calls_publish_for_each_event(self):
        publisher = RecordingPublisher()
        events = [make_event(), make_event(), make_event()]
        await publisher.publish_many(events)
        assert len(publisher.published) == 3

    async def test_publish_with_retry_succeeds_immediately(self):
        publisher = RecordingPublisher(fail_times=0)
        event = make_event()
        await publisher.publish_with_retry(event, max_retries=3)
        assert publisher.published == [event]

    async def test_publish_with_retry_recovers_after_transient_errors(self):
        publisher = RecordingPublisher(fail_times=2, error_factory=lambda: TimeoutError("slow"))
        event = make_event()
        await publisher.publish_with_retry(event, max_retries=5)
        assert publisher.published == [event]

    async def test_publish_with_retry_exhausts_and_raises_timeout_error(self):
        publisher = RecordingPublisher(fail_times=10, error_factory=lambda: OSError("down"))
        event = make_event()
        with pytest.raises(EventPublishTimeoutError):
            await publisher.publish_with_retry(event, max_retries=2)

    async def test_publish_with_retry_reraises_event_publish_error_immediately(self):
        class CustomPublishError(EventPublishError):
            pass

        publisher = RecordingPublisher(fail_times=10, error_factory=lambda: CustomPublishError("nope"))
        event = make_event()
        with pytest.raises(CustomPublishError):
            await publisher.publish_with_retry(event, max_retries=5)
        # only tried once: EventPublishError is not retried
        assert publisher._attempts == 1

    async def test_publish_with_retry_wraps_unexpected_errors(self):
        publisher = RecordingPublisher(fail_times=10, error_factory=lambda: KeyError("weird"))
        event = make_event()
        with pytest.raises(EventPublishUnexpectedError):
            await publisher.publish_with_retry(event, max_retries=5)
        assert publisher._attempts == 1  # unexpected errors are not retried either
