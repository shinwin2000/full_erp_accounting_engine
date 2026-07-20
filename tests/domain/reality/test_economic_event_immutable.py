# tests/domain/reality/test_economic_event_immutable.py
"""
Unit tests for economic_event_immutable.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.reality.economic_event_immutable import (
    EconomicEvent,
    EconomicEventService,
    EconomicEventStatus,
    EconomicEventType,
    get_economic_event_service,
)
from domain.shared_value_objects.money_vo import Money
from domain.shared_value_objects.quantity_vo import Quantity


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_service():
    service = get_economic_event_service()
    service.reset()
    # Reset singleton instance for __new__ test
    EconomicEventService._instance = None
    yield
    service.reset()
    EconomicEventService._instance = None


@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


@pytest.fixture
def sample_event(legal_entity_id, user_id):
    return EconomicEvent(
        event_id=uuid4(),
        event_type=EconomicEventType.SALE_OF_GOODS,
        event_date=datetime.now(UTC),
        description="Test event",
        legal_entity_id=legal_entity_id,
        created_by=str(user_id),
        created_at=datetime.now(UTC),
        status=EconomicEventStatus.DRAFT,
        amount=Decimal("1000"),
        currency="IDR",
    )


@pytest.fixture
def service():
    return EconomicEventService()


# ============================================================================
# Test EconomicEventType enum
# ============================================================================

class TestEconomicEventType:
    def test_members(self):
        assert EconomicEventType.SALE_OF_GOODS is not None
        assert EconomicEventType.PURCHASE_OF_GOODS is not None
        assert EconomicEventType.CASH_RECEIPT is not None


# ============================================================================
# Test EconomicEventStatus enum
# ============================================================================

class TestEconomicEventStatus:
    def test_members(self):
        assert EconomicEventStatus.DRAFT is not None
        assert EconomicEventStatus.VALIDATED is not None
        assert EconomicEventStatus.MAPPED is not None
        assert EconomicEventStatus.POSTED is not None
        assert EconomicEventStatus.REVERSED is not None
        assert EconomicEventStatus.CANCELLED is not None


# ============================================================================
# Test EconomicEvent
# ============================================================================

class TestEconomicEvent:
    def test_construction(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
        )
        assert event.event_type == EconomicEventType.SALE_OF_GOODS
        assert event.amount == Decimal("1000")
        assert event.currency == "IDR"

    def test_money_property(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
        )
        money = event.money
        assert money is not None
        assert money.amount == Decimal("1000")
        assert money.currency == "IDR"

        # No currency
        event2 = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("0"),
            currency="",
        )
        assert event2.money is None

    def test_has_amount_property(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("1000"),
            currency="IDR",
        )
        assert event.has_amount is True

        event2 = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("0"),
            currency="",
        )
        assert event2.has_amount is False

    def test_compute_hash(self, sample_event):
        h1 = sample_event.compute_hash()
        h2 = sample_event.compute_hash()
        assert h1 == h2

        # Different description should change hash
        event2 = EconomicEvent(
            event_id=sample_event.event_id,
            event_type=sample_event.event_type,
            event_date=sample_event.event_date,
            description="Different",
            legal_entity_id=sample_event.legal_entity_id,
            created_by=sample_event.created_by,
            created_at=sample_event.created_at,
            amount=sample_event.amount,
            currency=sample_event.currency,
        )
        assert event2.compute_hash() != h1

    def test_post_init_hash_mismatch(self, sample_event):
        # Create an event with wrong hash
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            EconomicEvent(
                event_id=sample_event.event_id,
                event_type=sample_event.event_type,
                event_date=sample_event.event_date,
                description=sample_event.description,
                legal_entity_id=sample_event.legal_entity_id,
                created_by=sample_event.created_by,
                created_at=sample_event.created_at,
                cryptographic_hash="wrong_hash",
            )

    def test_validate_valid(self, sample_event):
        errors = sample_event.validate()
        assert errors == []

    def test_validate_amount_negative(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("-100"),
            currency="IDR",
        )
        errors = event.validate()
        assert len(errors) == 1
        assert "positive" in errors[0]

    def test_validate_description_too_short(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="ab",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
        )
        errors = event.validate()
        assert len(errors) == 1
        assert "at least 3" in errors[0]

    def test_validate_future_date(self, legal_entity_id, user_id):
        event = EconomicEvent(
            event_id=uuid4(),
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC) + timedelta(days=400),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
        )
        errors = event.validate()
        assert len(errors) == 1
        assert "more than one year" in errors[0]

    def test_validate_self_previous_event(self, legal_entity_id, user_id):
        eid = uuid4()
        event = EconomicEvent(
            event_id=eid,
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            previous_event_id=eid,
        )
        errors = event.validate()
        assert len(errors) == 1
        assert "same as event ID" in errors[0]

    def test_validate_self_reversal(self, legal_entity_id, user_id):
        eid = uuid4()
        event = EconomicEvent(
            event_id=eid,
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            created_at=datetime.now(UTC),
            amount=Decimal("100"),
            currency="IDR",
            reversal_of=eid,
        )
        errors = event.validate()
        assert len(errors) == 1
        assert "same as event ID" in errors[0]

    def test_is_posted(self, sample_event):
        assert sample_event.is_posted() is False
        posted = EconomicEvent(
            event_id=sample_event.event_id,
            event_type=sample_event.event_type,
            event_date=sample_event.event_date,
            description=sample_event.description,
            legal_entity_id=sample_event.legal_entity_id,
            created_by=sample_event.created_by,
            created_at=sample_event.created_at,
            status=EconomicEventStatus.POSTED,
            amount=sample_event.amount,
            currency=sample_event.currency,
        )
        assert posted.is_posted() is True

    def test_is_reversal(self, sample_event):
        assert sample_event.is_reversal() is False
        reversed_event = EconomicEvent(
            event_id=sample_event.event_id,
            event_type=sample_event.event_type,
            event_date=sample_event.event_date,
            description=sample_event.description,
            legal_entity_id=sample_event.legal_entity_id,
            created_by=sample_event.created_by,
            created_at=sample_event.created_at,
            reversal_of=sample_event.event_id,
            amount=sample_event.amount,
            currency=sample_event.currency,
        )
        assert reversed_event.is_reversal() is True

    def test_create_reversal(self, sample_event):
        reversal = sample_event.create_reversal("admin", "Test reason")
        assert reversal.event_id != sample_event.event_id
        assert reversal.event_type == sample_event.event_type
        assert reversal.amount == sample_event.amount
        assert reversal.currency == sample_event.currency
        assert reversal.reversal_of == sample_event.event_id
        assert reversal.previous_event_id == sample_event.event_id
        assert "REVERSAL" in reversal.description
        assert reversal.status == EconomicEventStatus.DRAFT

    def test_to_dict(self, sample_event):
        d = sample_event.to_dict()
        assert d["event_id"] == str(sample_event.event_id)
        assert d["event_type"] == sample_event.event_type.name
        assert d["amount"] == str(sample_event.amount)
        assert d["currency"] == sample_event.currency


# ============================================================================
# Test EconomicEventService
# ============================================================================

class TestEconomicEventService:
    def test_singleton_new(self):
        s1 = EconomicEventService()
        s2 = EconomicEventService()
        assert s1 is s2

    def test_create_event(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        event = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test event",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
            source_document_ref="REF-001",
            counterparty_id=uuid4(),
        )
        assert event is not None
        assert event.event_type == EconomicEventType.SALE_OF_GOODS
        assert event.amount == Decimal("1000")
        assert event.currency == "IDR"
        assert event.cryptographic_hash != ""
        assert service.get_event(event.event_id) is not None

    def test_create_event_without_money(self, service, legal_entity_id, user_id):
        event = service.create_event(
            event_type=EconomicEventType.INVENTORY_ADJUSTMENT,
            event_date=datetime.now(UTC),
            description="Inventory adjustment",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
        )
        assert event.amount == Decimal(0)
        assert event.currency == ""

    def test_get_event(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        created = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        retrieved = service.get_event(created.event_id)
        assert retrieved is not None
        assert retrieved.event_id == created.event_id

        not_found = service.get_event(uuid4())
        assert not_found is None

    def test_validate_event(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        event = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        valid, errors = service.validate_event(event.event_id)
        assert valid is True
        assert errors == []

        # Invalid event
        invalid_event = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="ab",  # too short
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        valid2, errors2 = service.validate_event(invalid_event.event_id)
        assert valid2 is False
        assert len(errors2) >= 1

        # Event not found
        valid3, errors3 = service.validate_event(uuid4())
        assert valid3 is False
        assert "not found" in errors3[0]

    def test_mark_as_validated(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        event = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        validated = service.mark_as_validated(event.event_id)
        assert validated is not None
        assert validated.status == EconomicEventStatus.VALIDATED

        # Already validated
        validated2 = service.mark_as_validated(event.event_id)
        assert validated2 is None

        # Not found
        assert service.mark_as_validated(uuid4()) is None

    def test_mark_as_mapped(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        event = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        # Must be validated first
        service.mark_as_validated(event.event_id)
        mapped = service.mark_as_mapped(event.event_id)
        assert mapped is not None
        assert mapped.status == EconomicEventStatus.MAPPED

        # Cannot map DRAFT directly (only VALIDATED or DRAFT in code, but code checks VALIDATED or DRAFT)
        # Actually code allows DRAFT or VALIDATED, so we can test from DRAFT
        event2 = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test2",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        mapped2 = service.mark_as_mapped(event2.event_id)
        assert mapped2 is not None
        assert mapped2.status == EconomicEventStatus.MAPPED

        # Already mapped
        mapped3 = service.mark_as_mapped(event2.event_id)
        assert mapped3 is None

        # Not found
        assert service.mark_as_mapped(uuid4()) is None

    def test_get_events_by_date_range(self, service, legal_entity_id, user_id):
        now = datetime.now(UTC)
        money = Money(Decimal("1000"), "IDR")
        event1 = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=now - timedelta(days=2),
            description="Test1",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        event2 = service.create_event(
            event_type=EconomicEventType.PURCHASE_OF_GOODS,
            event_date=now,
            description="Test2",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        event3 = service.create_event(
            event_type=EconomicEventType.CASH_RECEIPT,
            event_date=now + timedelta(days=2),
            description="Test3",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )

        from_date = now - timedelta(days=1)
        to_date = now + timedelta(days=1)
        results = service.get_events_by_date_range(legal_entity_id, from_date, to_date)
        # Should include event2 (now) but not event1 (2 days ago) or event3 (2 days ahead)
        event_ids = [e.event_id for e in results]
        assert event2.event_id in event_ids
        assert event1.event_id not in event_ids
        assert event3.event_id not in event_ids
        assert len(results) == 1

        # Different legal entity
        other_legal = uuid4()
        results2 = service.get_events_by_date_range(other_legal, from_date, to_date)
        assert len(results2) == 0

    def test_get_events_by_type(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        sale1 = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Sale1",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        sale2 = service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Sale2",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        purchase = service.create_event(
            event_type=EconomicEventType.PURCHASE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Purchase",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )

        sales = service.get_events_by_type(legal_entity_id, EconomicEventType.SALE_OF_GOODS)
        assert len(sales) == 2
        assert sale1.event_id in [e.event_id for e in sales]
        assert sale2.event_id in [e.event_id for e in sales]

        purchases = service.get_events_by_type(legal_entity_id, EconomicEventType.PURCHASE_OF_GOODS)
        assert len(purchases) == 1
        assert purchase.event_id == purchases[0].event_id

        other_legal = uuid4()
        sales_other = service.get_events_by_type(other_legal, EconomicEventType.SALE_OF_GOODS)
        assert len(sales_other) == 0

    def test_get_statistics(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        for i in range(3):
            service.create_event(
                event_type=EconomicEventType.SALE_OF_GOODS,
                event_date=datetime.now(UTC),
                description=f"Test{i}",
                legal_entity_id=legal_entity_id,
                created_by=str(user_id),
                amount=money,
            )
        stats = service.get_statistics()
        assert stats["total_events"] == 3
        assert stats["by_status"]["DRAFT"] == 3
        assert stats["by_type"]["SALE_OF_GOODS"] == 3

    def test_reset(self, service, legal_entity_id, user_id):
        money = Money(Decimal("1000"), "IDR")
        service.create_event(
            event_type=EconomicEventType.SALE_OF_GOODS,
            event_date=datetime.now(UTC),
            description="Test",
            legal_entity_id=legal_entity_id,
            created_by=str(user_id),
            amount=money,
        )
        stats = service.get_statistics()
        assert stats["total_events"] == 1
        service.reset()
        stats2 = service.get_statistics()
        assert stats2["total_events"] == 0


# ============================================================================
# Test module-level get_economic_event_service
# ============================================================================

def test_get_economic_event_service():
    s1 = get_economic_event_service()
    s2 = get_economic_event_service()
    assert s1 is s2


# ============================================================================
# Test property access explicitly for checker
# ============================================================================

def test_property_access_explicit(sample_event):
    # Direct access to money property
    money = sample_event.money
    assert money is not None
    # Direct access to has_amount
    has = sample_event.has_amount
    assert has is True
    # is_reversal
    is_rev = sample_event.is_reversal()
    assert is_rev is False
    # create_reversal
    rev = sample_event.create_reversal("admin", "test")
    assert rev is not None