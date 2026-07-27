# test_domain_events.py
# ======================
# Comprehensive tests for domain/coa/domain_events.py.
# Covers DomainEventType enum, DomainEvent base class, all concrete event classes,
# helper functions, and protocol definitions.

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.coa.domain_events import (
    AccountCreatedEvent,
    AccountDeactivatedEvent,
    AccountLockedEvent,
    AccountMergedEvent,
    AccountReactivatedEvent,
    AccountSplitEvent,
    AccountUnlockedEvent,
    AccountUpdatedEvent,
    COAArchivedEvent,
    COACreatedEvent,
    COALockedEvent,
    COAUnlockedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    EventStore,
    HierarchyChangedEvent,
    deserialize_event,
    event_type_from_name,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_account():
    """Create a mock AccountEntity for testing."""
    from domain.coa.account_entity import AccountEntity
    from domain.coa.account_type_enum import AccountType

    return AccountEntity(
        account_id=uuid4(),
        account_code="1010",
        account_name="Cash",
        account_type=AccountType.ASSET,
        normal_balance="debit",
        parent_account_id=None,
        is_control_account=False,
        description="Cash account",
        is_active=True,
        opening_balance=Decimal("0"),
    )


@pytest.fixture
def sample_updated_account(sample_account):
    """Create an updated version of the account."""
    from domain.coa.account_entity import AccountEntity

    return AccountEntity(
        account_id=sample_account.account_id,
        account_code=sample_account.account_code,
        account_name="Cash - Main",
        account_type=sample_account.account_type,
        normal_balance=sample_account.normal_balance,
        parent_account_id=uuid4(),
        is_control_account=True,
        description="Updated cash account",
        is_active=True,
        opening_balance=Decimal("1000"),
    )


@pytest.fixture
def sample_aggregate_id() -> UUID:
    return uuid4()


@pytest.fixture
def base_event_kwargs(sample_aggregate_id) -> dict:
    return {
        "event_id": uuid4(),
        "event_type": DomainEventType.ACCOUNT_CREATED,
        "aggregate_id": sample_aggregate_id,
        "aggregate_version": 1,
        "occurred_at": datetime.now(UTC),
        "event_data": {"test": "data"},
        "user_id": "user123",
        "correlation_id": "corr-456",
        "causation_id": "cause-789",
    }


# ----------------------------------------------------------------------
# DomainEventType
# ----------------------------------------------------------------------
class TestDomainEventType:
    def test_members_exist(self):
        assert hasattr(DomainEventType, "ACCOUNT_CREATED")
        assert hasattr(DomainEventType, "ACCOUNT_UPDATED")
        assert hasattr(DomainEventType, "ACCOUNT_DEACTIVATED")
        assert hasattr(DomainEventType, "ACCOUNT_REACTIVATED")
        assert hasattr(DomainEventType, "ACCOUNT_LOCKED")
        assert hasattr(DomainEventType, "ACCOUNT_UNLOCKED")
        assert hasattr(DomainEventType, "ACCOUNT_MERGED")
        assert hasattr(DomainEventType, "ACCOUNT_SPLIT")
        assert hasattr(DomainEventType, "HIERARCHY_CHANGED")
        assert hasattr(DomainEventType, "COA_CREATED")
        assert hasattr(DomainEventType, "COA_LOCKED")
        assert hasattr(DomainEventType, "COA_UNLOCKED")
        assert hasattr(DomainEventType, "COA_ARCHIVED")

    def test_member_is_instance(self):
        assert isinstance(DomainEventType.ACCOUNT_CREATED, DomainEventType)

    def test_is_account_event(self):
        account_events = [
            DomainEventType.ACCOUNT_CREATED,
            DomainEventType.ACCOUNT_UPDATED,
            DomainEventType.ACCOUNT_DEACTIVATED,
            DomainEventType.ACCOUNT_REACTIVATED,
            DomainEventType.ACCOUNT_LOCKED,
            DomainEventType.ACCOUNT_UNLOCKED,
            DomainEventType.ACCOUNT_MERGED,
            DomainEventType.ACCOUNT_SPLIT,
            DomainEventType.HIERARCHY_CHANGED,
        ]
        non_account_events = [
            DomainEventType.COA_CREATED,
            DomainEventType.COA_LOCKED,
            DomainEventType.COA_UNLOCKED,
            DomainEventType.COA_ARCHIVED,
        ]
        for ev in account_events:
            assert ev.is_account_event() is True
        for ev in non_account_events:
            assert ev.is_account_event() is False

    def test_is_coa_event(self):
        coa_events = [
            DomainEventType.COA_CREATED,
            DomainEventType.COA_LOCKED,
            DomainEventType.COA_UNLOCKED,
            DomainEventType.COA_ARCHIVED,
        ]
        non_coa_events = [
            DomainEventType.ACCOUNT_CREATED,
            DomainEventType.ACCOUNT_UPDATED,
        ]
        for ev in coa_events:
            assert ev.is_coa_event() is True
        for ev in non_coa_events:
            assert ev.is_coa_event() is False


# ----------------------------------------------------------------------
# DomainEvent Base
# ----------------------------------------------------------------------
class TestDomainEvent:
    def test_construction_valid(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        assert event.event_id == base_event_kwargs["event_id"]
        assert event.event_type == base_event_kwargs["event_type"]
        assert event.aggregate_id == base_event_kwargs["aggregate_id"]
        assert event.aggregate_version == 1
        assert event.occurred_at is not None
        assert event.event_data == {"test": "data"}
        assert event.user_id == "user123"
        assert event.correlation_id == "corr-456"
        assert event.causation_id == "cause-789"

    def test_validation_aggregate_version_zero(self, base_event_kwargs):
        base_event_kwargs["aggregate_version"] = 0
        with pytest.raises(ValueError, match="aggregate_version must be >= 1"):
            DomainEvent(**base_event_kwargs)

    def test_validation_occurred_at_naive(self, base_event_kwargs):
        base_event_kwargs["occurred_at"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="occurred_at must be timezone-aware"):
            DomainEvent(**base_event_kwargs)

    def test_validation_user_id_empty(self, base_event_kwargs):
        base_event_kwargs["user_id"] = ""
        with pytest.raises(ValueError, match="user_id cannot be empty string"):
            DomainEvent(**base_event_kwargs)

    def test_to_dict(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        d = event.to_dict()
        assert d["event_id"] == str(event.event_id)
        assert d["event_type"] == event.event_type.value
        assert d["aggregate_id"] == str(event.aggregate_id)
        assert d["aggregate_version"] == event.aggregate_version
        assert d["occurred_at"] == event.occurred_at.isoformat()
        assert d["event_data"] == event.event_data
        assert d["user_id"] == event.user_id
        assert d["correlation_id"] == event.correlation_id
        assert d["causation_id"] == event.causation_id

    def test_to_json(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        json_str = event.to_json()
        data = json.loads(json_str)
        assert data["event_id"] == str(event.event_id)
        assert data["event_type"] == event.event_type.value

    def test_from_dict(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        d = event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.occurred_at == event.occurred_at
        assert reconstructed.event_data == event.event_data
        assert reconstructed.user_id == event.user_id
        assert reconstructed.correlation_id == event.correlation_id
        assert reconstructed.causation_id == event.causation_id

    def test_from_json(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        json_str = event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed == event

    def test_equality_and_hash(self, base_event_kwargs):
        e1 = DomainEvent(**base_event_kwargs)
        e2 = DomainEvent(**base_event_kwargs)
        # Different event_id -> not equal
        assert e1 != e2
        assert hash(e1) != hash(e2)
        # Same event_id -> equal
        e3 = DomainEvent(**base_event_kwargs)
        e3.event_id = e1.event_id
        assert e1 == e3
        assert hash(e1) == hash(e3)

    def test_repr(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        repr_str = repr(event)
        assert "DomainEvent" in repr_str
        assert event.event_type.value in repr_str
        assert str(event.aggregate_id) in repr_str


# ----------------------------------------------------------------------
# AccountCreatedEvent
# ----------------------------------------------------------------------
class TestAccountCreatedEvent:
    def test_construction(self, sample_aggregate_id, sample_account):
        event = AccountCreatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            account=sample_account,
            created_by="alice",
            user_id="alice",
            correlation_id="corr1",
            causation_id="cause1",
        )
        assert event.event_type == DomainEventType.ACCOUNT_CREATED
        assert event.aggregate_id == sample_aggregate_id
        assert event.aggregate_version == 1
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["account_code"] == sample_account.account_code
        assert event.event_data["account_name"] == sample_account.account_name
        assert event.event_data["created_by"] == "alice"
        assert event.user_id == "alice"
        assert event.correlation_id == "corr1"
        assert event.causation_id == "cause1"

    def test_to_dict_roundtrip(self, sample_aggregate_id, sample_account):
        event = AccountCreatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            account=sample_account,
            created_by="alice",
        )
        d = event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.event_data == event.event_data


# ----------------------------------------------------------------------
# AccountUpdatedEvent
# ----------------------------------------------------------------------
class TestAccountUpdatedEvent:
    def test_construction(self, sample_aggregate_id, sample_account, sample_updated_account):
        event = AccountUpdatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            account_id=sample_account.account_id,
            old_account=sample_account,
            new_account=sample_updated_account,
            updated_by="bob",
            user_id="bob",
            correlation_id="corr2",
        )
        assert event.event_type == DomainEventType.ACCOUNT_UPDATED
        assert event.aggregate_version == 2
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["account_code"] == sample_account.account_code
        assert event.event_data["updated_by"] == "bob"
        # Check changes dict
        changes = event.event_data["changes"]
        assert "name" in changes
        assert changes["name"]["old"] == sample_account.account_name
        assert changes["name"]["new"] == sample_updated_account.account_name
        assert "parent_account_id" in changes
        assert changes["parent_account_id"]["old"] is None
        assert changes["parent_account_id"]["new"] == str(sample_updated_account.parent_account_id)
        assert "is_control_account" in changes

    def test_to_dict_roundtrip(self, sample_aggregate_id, sample_account, sample_updated_account):
        event = AccountUpdatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            account_id=sample_account.account_id,
            old_account=sample_account,
            new_account=sample_updated_account,
            updated_by="bob",
        )
        d = event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_data == event.event_data


# ----------------------------------------------------------------------
# AccountDeactivatedEvent
# ----------------------------------------------------------------------
class TestAccountDeactivatedEvent:
    def test_construction(self, sample_aggregate_id, sample_account):
        event = AccountDeactivatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            account=sample_account,
            deactivated_by="admin",
            reason="No longer used",
        )
        assert event.event_type == DomainEventType.ACCOUNT_DEACTIVATED
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["deactivated_by"] == "admin"
        assert event.event_data["reason"] == "No longer used"


# ----------------------------------------------------------------------
# AccountReactivatedEvent
# ----------------------------------------------------------------------
class TestAccountReactivatedEvent:
    def test_construction(self, sample_aggregate_id, sample_account):
        event = AccountReactivatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=3,
            account=sample_account,
            reactivated_by="admin",
            reason="Reopened",
        )
        assert event.event_type == DomainEventType.ACCOUNT_REACTIVATED
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["reactivated_by"] == "admin"


# ----------------------------------------------------------------------
# AccountLockedEvent
# ----------------------------------------------------------------------
class TestAccountLockedEvent:
    def test_construction(self, sample_aggregate_id, sample_account):
        event = AccountLockedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            account=sample_account,
            locked_by="auditor",
            reason="Under investigation",
        )
        assert event.event_type == DomainEventType.ACCOUNT_LOCKED
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["locked_by"] == "auditor"


# ----------------------------------------------------------------------
# AccountUnlockedEvent
# ----------------------------------------------------------------------
class TestAccountUnlockedEvent:
    def test_construction(self, sample_aggregate_id, sample_account):
        event = AccountUnlockedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=3,
            account=sample_account,
            unlocked_by="auditor",
            reason="Investigation complete",
        )
        assert event.event_type == DomainEventType.ACCOUNT_UNLOCKED
        assert event.event_data["account_id"] == str(sample_account.account_id)
        assert event.event_data["unlocked_by"] == "auditor"


# ----------------------------------------------------------------------
# HierarchyChangedEvent
# ----------------------------------------------------------------------
class TestHierarchyChangedEvent:
    def test_construction(self, sample_aggregate_id):
        old_parent = uuid4()
        new_parent = uuid4()
        event = HierarchyChangedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=4,
            account_id=uuid4(),
            old_parent_id=old_parent,
            new_parent_id=new_parent,
            changed_by="reorg",
        )
        assert event.event_type == DomainEventType.HIERARCHY_CHANGED
        assert event.event_data["old_parent_id"] == str(old_parent)
        assert event.event_data["new_parent_id"] == str(new_parent)

    def test_with_none_parents(self, sample_aggregate_id):
        event = HierarchyChangedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=4,
            account_id=uuid4(),
            old_parent_id=None,
            new_parent_id=None,
            changed_by="reorg",
        )
        assert event.event_data["old_parent_id"] is None
        assert event.event_data["new_parent_id"] is None


# ----------------------------------------------------------------------
# AccountMergedEvent
# ----------------------------------------------------------------------
class TestAccountMergedEvent:
    def test_construction(self, sample_aggregate_id):
        source = uuid4()
        target = uuid4()
        event = AccountMergedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=5,
            source_account_id=source,
            target_account_id=target,
            merged_by="admin",
        )
        assert event.event_type == DomainEventType.ACCOUNT_MERGED
        assert event.event_data["source_account_id"] == str(source)
        assert event.event_data["target_account_id"] == str(target)


# ----------------------------------------------------------------------
# AccountSplitEvent
# ----------------------------------------------------------------------
class TestAccountSplitEvent:
    def test_construction(self, sample_aggregate_id):
        source = uuid4()
        targets = [uuid4(), uuid4()]
        ratios = [0.6, 0.4]
        event = AccountSplitEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=6,
            source_account_id=source,
            target_account_ids=targets,
            split_ratios=ratios,
            split_by="admin",
        )
        assert event.event_type == DomainEventType.ACCOUNT_SPLIT
        assert event.event_data["source_account_id"] == str(source)
        assert event.event_data["target_account_ids"] == [str(t) for t in targets]
        assert event.event_data["split_ratios"] == ratios


# ----------------------------------------------------------------------
# COA Events
# ----------------------------------------------------------------------
class TestCOACreatedEvent:
    def test_construction(self, sample_aggregate_id):
        le_id = uuid4()
        event = COACreatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            coa_name="Standard COA",
            legal_entity_id=le_id,
            created_by="admin",
        )
        assert event.event_type == DomainEventType.COA_CREATED
        assert event.event_data["coa_name"] == "Standard COA"
        assert event.event_data["legal_entity_id"] == str(le_id)
        assert event.event_data["created_by"] == "admin"


class TestCOALockedEvent:
    def test_construction(self, sample_aggregate_id):
        event = COALockedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            locked_by="admin",
            reason="Year-end close",
        )
        assert event.event_type == DomainEventType.COA_LOCKED
        assert event.event_data["locked_by"] == "admin"
        assert event.event_data["reason"] == "Year-end close"


class TestCOAUnlockedEvent:
    def test_construction(self, sample_aggregate_id):
        event = COAUnlockedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=3,
            unlocked_by="admin",
            reason="New period",
        )
        assert event.event_type == DomainEventType.COA_UNLOCKED
        assert event.event_data["unlocked_by"] == "admin"


class TestCOAArchivedEvent:
    def test_construction(self, sample_aggregate_id):
        event = COAArchivedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=4,
            archived_by="admin",
            reason="Legacy COA",
        )
        assert event.event_type == DomainEventType.COA_ARCHIVED
        assert event.event_data["archived_by"] == "admin"
        assert event.event_data["reason"] == "Legacy COA"


# ----------------------------------------------------------------------
# Protocol Definitions
# ----------------------------------------------------------------------
class TestDomainEventPublisher:
    def test_protocol_exists(self):
        # Just verify the protocol is importable and callable
        assert DomainEventPublisher is not None
        # We can't instantiate a protocol, but we can verify it has the required methods
        assert hasattr(DomainEventPublisher, "publish")
        assert hasattr(DomainEventPublisher, "publish_many")


class TestEventStore:
    def test_protocol_exists(self):
        assert EventStore is not None
        assert hasattr(EventStore, "append")
        assert hasattr(EventStore, "read_stream")
        assert hasattr(EventStore, "read_all")


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelperFunctions:
    def test_event_type_from_name_valid(self):
        assert event_type_from_name("ACCOUNT_CREATED") == DomainEventType.ACCOUNT_CREATED
        assert event_type_from_name("account_created") == DomainEventType.ACCOUNT_CREATED
        assert event_type_from_name("COA_LOCKED") == DomainEventType.COA_LOCKED

    def test_event_type_from_name_invalid(self):
        assert event_type_from_name("NON_EXISTENT") is None

    def test_deserialize_event(self, sample_aggregate_id, sample_account):
        # Create an event, serialize, then deserialize
        event = AccountCreatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            account=sample_account,
            created_by="alice",
            user_id="alice",
            correlation_id="corr",
            causation_id="cause",
        )
        json_str = event.to_json()
        reconstructed = deserialize_event(json_str)
        assert isinstance(reconstructed, DomainEvent)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.event_data == event.event_data

    def test_deserialize_event_missing_event_type(self):
        with pytest.raises(ValueError, match="Missing event_type in JSON"):
            deserialize_event('{"test": "data"}')

    def test_deserialize_event_invalid_event_type(self):
        with pytest.raises(ValueError):
            deserialize_event('{"event_type": "INVALID_TYPE"}')