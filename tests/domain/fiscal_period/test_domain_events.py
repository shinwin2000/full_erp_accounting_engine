# tests/domain/fiscal_period/test_domain_events.py
"""
Domain events tests – all async methods awaited, all events tested according to source.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from domain.fiscal_period.aggregate_root import PeriodStatus, PeriodType
from domain.fiscal_period.domain_events import (
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    PeriodClosedEvent,
    PeriodCreatedEvent,
    PeriodLockedEvent,
    PeriodOpenedEvent,
    PeriodReopenedEvent,
    PeriodStatusChangedEvent,
    PeriodUpdatedEvent,
    deserialize_domain_event,
    serialize_domain_event,
)


class TestEnum:
    def test_members(self):
        assert DomainEventType.PERIOD_OPENED.value == "period_opened"
        assert DomainEventType.PERIOD_LOCKED.value == "period_locked"
        assert DomainEventType.PERIOD_CLOSED.value == "period_closed"
        assert DomainEventType.PERIOD_REOPENED.value == "period_reopened"
        assert DomainEventType.PERIOD_CREATED.value == "period_created"
        assert DomainEventType.PERIOD_UPDATED.value == "period_updated"
        assert DomainEventType.PERIOD_STATUS_CHANGED.value == "period_status_changed"


class TestDomainEvent:
    def test_construction(self):
        eid = uuid4()
        aid = uuid4()
        event = DomainEvent(
            event_id=eid,
            event_type=DomainEventType.PERIOD_OPENED,
            aggregate_id=aid,
            aggregate_type="FiscalPeriod",
            aggregate_version=1,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            event_data={"key": "value"},
        )
        assert event.event_id == eid
        assert event.event_type == DomainEventType.PERIOD_OPENED

    def test_to_dict(self):
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_CREATED,
            aggregate_id=uuid4(),
            aggregate_type="FiscalPeriod",
            aggregate_version=2,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            event_data={"a": 1},
        )
        d = event.to_dict()
        assert d["event_type"] == "period_created"
        assert d["aggregate_version"] == 2

    def test_from_dict(self):
        d = {
            "event_id": str(uuid4()),
            "event_type": "period_opened",
            "aggregate_id": str(uuid4()),
            "aggregate_type": "FiscalPeriod",
            "aggregate_version": 1,
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "event_data": {},
        }
        event = DomainEvent.from_dict(d)
        assert event.event_type == DomainEventType.PERIOD_OPENED


class TestSpecificEvents:
    def test_PeriodCreatedEvent(self):
        event = PeriodCreatedEvent(
            legal_entity_id=uuid4(),
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            status=PeriodStatus.DRAFT,
            created_by="user",
        )
        assert event.event_data["legal_entity_id"] is not None
        assert event.event_data["period_number"] == 1

    def test_PeriodOpenedEvent(self):
        event = PeriodOpenedEvent(
            legal_entity_id=uuid4(),
            period_display="2026-01",
            opened_by="user",
        )
        assert event.event_data["period_display"] == "2026-01"
        assert event.event_data["opened_by"] == "user"

    def test_PeriodLockedEvent(self):
        event = PeriodLockedEvent(
            legal_entity_id=uuid4(),
            period_display="2026-01",
            locked_by="user",
        )
        assert event.event_data["locked_by"] == "user"

    def test_PeriodClosedEvent(self):
        event = PeriodClosedEvent(
            legal_entity_id=uuid4(),
            period_display="2026-01",
            closed_by="user",
        )
        assert event.event_data["closed_by"] == "user"

    def test_PeriodReopenedEvent(self):
        event = PeriodReopenedEvent(
            legal_entity_id=uuid4(),
            period_display="2026-01",
            reopened_by="user",
        )
        assert event.event_data["reopened_by"] == "user"

    def test_PeriodUpdatedEvent(self):
        event = PeriodUpdatedEvent(
            legal_entity_id=uuid4(),
            period_display="2026-01",
            changes={"desc": "new"},
            updated_by="user",
        )
        assert event.event_data["changes"] == {"desc": "new"}

    def test_PeriodStatusChangedEvent(self):
        event = PeriodStatusChangedEvent(
            old_status=PeriodStatus.DRAFT,
            new_status=PeriodStatus.OPEN,
            changed_by="user",
            reason="open",
        )
        assert event.event_data["old_status"] == "draft"
        assert event.event_data["new_status"] == "open"


class TestPublisher:
    def setup_method(self):
        DomainEventPublisher._published_events = []

    @pytest.mark.asyncio
    async def test_publish(self):
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_OPENED,
            aggregate_id=uuid4(),
            aggregate_type="FiscalPeriod",
            aggregate_version=1,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            event_data={},
        )
        await DomainEventPublisher.publish(event)
        assert len(DomainEventPublisher._published_events) == 1

    @pytest.mark.asyncio
    async def test_publish_many(self):
        events = [
            DomainEvent(
                event_id=uuid4(),
                event_type=DomainEventType.PERIOD_CREATED,
                aggregate_id=uuid4(),
                aggregate_type="FiscalPeriod",
                aggregate_version=1,
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                event_data={},
            )
            for _ in range(3)
        ]
        await DomainEventPublisher.publish_many(events)
        assert len(DomainEventPublisher._published_events) == 3

    def test_get_published_events(self):
        event = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_OPENED,
            aggregate_id=uuid4(),
            aggregate_type="FiscalPeriod",
            aggregate_version=1,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            event_data={},
        )
        DomainEventPublisher._published_events.append(event)
        assert len(DomainEventPublisher.get_published_events()) == 1

    def test_clear(self):
        DomainEventPublisher._published_events.append(object())
        DomainEventPublisher.clear()
        assert len(DomainEventPublisher._published_events) == 0


class TestSerialization:
    def test_serialize_deserialize(self):
        original = DomainEvent(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_CREATED,
            aggregate_id=uuid4(),
            aggregate_type="FiscalPeriod",
            aggregate_version=2,
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            event_data={"a": 1},
        )
        json_str = serialize_domain_event(original)
        reconstructed = deserialize_domain_event(json_str)
        assert reconstructed.event_id == original.event_id
        assert reconstructed.event_type == original.event_type
        assert reconstructed.aggregate_version == original.aggregate_version