# test_domain_events.py
# ======================
# Comprehensive tests for domain/fixed_asset/domain_events.py.
# Covers all event types, serialization, validation, and helper functions.

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.fixed_asset.asset_entity import AssetStatus, AssetType, FixedAsset
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetDepreciationPostedEvent,
    AssetDisposedEvent,
    AssetFullyDepreciatedEvent,
    AssetGroupCreatedEvent,
    AssetGroupUpdatedEvent,
    AssetImpairedEvent,
    AssetImpairmentReversedEvent,
    AssetRevaluatedEvent,
    AssetTransferredEvent,
    AssetUpdatedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    deserialize_domain_event,
    serialize_domain_event,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_asset() -> FixedAsset:
    """Create a mock FixedAsset with required attributes."""
    asset = MagicMock(spec=FixedAsset)
    asset.id = uuid4()
    asset.asset_code = "ASSET-001"
    asset.name = "Test Asset"
    asset.asset_type = AssetType.LAND
    asset.status = AssetStatus.ACTIVE
    asset.acquisition_date = date(2025, 1, 1)
    asset.acquisition_cost = Decimal("10000")
    asset.salvage_value = Decimal("1000")
    asset.useful_life_years = 5
    asset.depreciation_method = "straight_line"
    asset.currency = "IDR"
    asset.location = "Warehouse A"
    asset.category = "Building"
    asset.accumulated_depreciation = Decimal("0")
    asset.accumulated_impairment = Decimal("0")
    asset.net_book_value = Decimal("10000")
    asset.is_fully_depreciated = False
    return asset


@pytest.fixture
def sample_aggregate_id() -> UUID:
    return uuid4()


@pytest.fixture
def base_event_kwargs(sample_aggregate_id) -> dict:
    return {
        "event_id": uuid4(),
        "event_type": DomainEventType.ASSET_ACQUIRED,
        "aggregate_id": sample_aggregate_id,
        "aggregate_version": 1,
        "occurred_at": datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
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
        assert hasattr(DomainEventType, "ASSET_ACQUIRED")
        assert hasattr(DomainEventType, "ASSET_UPDATED")
        assert hasattr(DomainEventType, "ASSET_DEPRECIATION_POSTED")
        assert hasattr(DomainEventType, "ASSET_REVALUATED")
        assert hasattr(DomainEventType, "ASSET_DISPOSED")
        assert hasattr(DomainEventType, "ASSET_TRANSFERRED")
        assert hasattr(DomainEventType, "ASSET_IMPAIRED")
        assert hasattr(DomainEventType, "ASSET_IMPAIRMENT_REVERSED")
        assert hasattr(DomainEventType, "ASSET_FULLY_DEPRECIATED")
        assert hasattr(DomainEventType, "ASSET_GROUP_CREATED")
        assert hasattr(DomainEventType, "ASSET_GROUP_UPDATED")

    def test_member_is_instance(self):
        assert isinstance(DomainEventType.ASSET_ACQUIRED, DomainEventType)

    def test_is_asset_event(self):
        asset_events = [
            DomainEventType.ASSET_ACQUIRED,
            DomainEventType.ASSET_UPDATED,
            DomainEventType.ASSET_DEPRECIATION_POSTED,
            DomainEventType.ASSET_REVALUATED,
            DomainEventType.ASSET_DISPOSED,
            DomainEventType.ASSET_TRANSFERRED,
            DomainEventType.ASSET_IMPAIRED,
            DomainEventType.ASSET_IMPAIRMENT_REVERSED,
            DomainEventType.ASSET_FULLY_DEPRECIATED,
        ]
        group_events = [
            DomainEventType.ASSET_GROUP_CREATED,
            DomainEventType.ASSET_GROUP_UPDATED,
        ]
        for ev in asset_events:
            assert ev.is_asset_event() is True
            assert ev.is_group_event() is False
        for ev in group_events:
            assert ev.is_asset_event() is False
            assert ev.is_group_event() is True


# ----------------------------------------------------------------------
# DomainEvent Base Class
# ----------------------------------------------------------------------
class TestDomainEvent:
    def test_construction_valid(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        assert event.event_id == base_event_kwargs["event_id"]
        assert event.event_type == base_event_kwargs["event_type"]
        assert event.aggregate_id == base_event_kwargs["aggregate_id"]
        assert event.aggregate_version == 1
        assert event.occurred_at == base_event_kwargs["occurred_at"]
        assert event.event_data == {"test": "data"}
        assert event.user_id == "user123"
        assert event.correlation_id == "corr-456"
        assert event.causation_id == "cause-789"

    def test_construction_invalid_version_zero(self, base_event_kwargs):
        base_event_kwargs["aggregate_version"] = 0
        with pytest.raises(ValueError, match="aggregate_version must be >= 1"):
            DomainEvent(**base_event_kwargs)

    def test_construction_naive_datetime_raises(self, base_event_kwargs):
        base_event_kwargs["occurred_at"] = datetime(2025, 1, 1, 10, 0)  # naive
        with pytest.raises(ValueError, match="occurred_at must be timezone-aware"):
            DomainEvent(**base_event_kwargs)

    def test_to_dict(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        d = event.to_dict()
        assert d["event_id"] == str(event.event_id)
        assert d["event_type"] == event.event_type.value
        assert d["aggregate_id"] == str(event.aggregate_id)
        assert d["aggregate_version"] == 1
        assert d["occurred_at"] == event.occurred_at.isoformat()
        assert d["event_data"] == {"test": "data"}
        assert d["user_id"] == "user123"
        assert d["correlation_id"] == "corr-456"
        assert d["causation_id"] == "cause-789"

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

    def test_to_json_roundtrip(self, base_event_kwargs):
        event = DomainEvent(**base_event_kwargs)
        json_str = event.to_json()
        reconstructed = DomainEvent.from_json(json_str)
        assert reconstructed == event


# ----------------------------------------------------------------------
# Concrete Event Classes
# ----------------------------------------------------------------------
class TestAssetAcquiredEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        event = AssetAcquiredEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            asset=sample_asset,
            acquired_by="alice",
            user_id="user1",
            correlation_id="corr1",
            causation_id="cause1",
        )
        assert event.event_type == DomainEventType.ASSET_ACQUIRED
        assert event.aggregate_id == sample_aggregate_id
        assert event.aggregate_version == 2
        assert event.user_id == "user1"
        assert event.correlation_id == "corr1"
        assert event.causation_id == "cause1"
        # Check event_data
        data = event.event_data
        assert data["asset_id"] == str(sample_asset.id)
        assert data["asset_code"] == sample_asset.asset_code
        assert data["asset_name"] == sample_asset.name
        assert data["acquisition_cost"] == str(sample_asset.acquisition_cost)
        assert data["acquired_by"] == "alice"

    def test_to_dict_roundtrip(self, sample_asset, sample_aggregate_id):
        event = AssetAcquiredEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=2,
            asset=sample_asset,
            acquired_by="alice",
        )
        d = event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.event_data == event.event_data


class TestAssetUpdatedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        changes = {"name": "Updated Asset", "location": "Warehouse B"}
        event = AssetUpdatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=3,
            asset=sample_asset,
            changes=changes,
            updated_by="bob",
        )
        assert event.event_type == DomainEventType.ASSET_UPDATED
        assert event.event_data["asset_id"] == str(sample_asset.id)
        assert event.event_data["changes"] == changes
        assert event.event_data["updated_by"] == "bob"

    def test_to_dict_roundtrip(self, sample_asset, sample_aggregate_id):
        event = AssetUpdatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=3,
            asset=sample_asset,
            changes={"name": "New Name"},
            updated_by="bob",
        )
        d = event.to_dict()
        reconstructed = DomainEvent.from_dict(d)
        assert reconstructed.event_data == event.event_data


class TestAssetDepreciationPostedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        amount = Decimal("1800")
        # Set asset attributes for the event
        sample_asset.accumulated_depreciation = amount
        sample_asset.net_book_value = Decimal("8200")
        sample_asset.is_fully_depreciated = False
        event = AssetDepreciationPostedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=4,
            asset=sample_asset,
            period="2025-01",
            amount=amount,
            posted_by="carol",
        )
        assert event.event_type == DomainEventType.ASSET_DEPRECIATION_POSTED
        data = event.event_data
        assert data["period"] == "2025-01"
        assert data["depreciation_amount"] == "1800"
        assert data["posted_by"] == "carol"
        assert data["accumulated_depreciation_before"] == "0"
        assert data["accumulated_depreciation_after"] == "1800"
        assert data["nbv_before"] == "10000"
        assert data["nbv_after"] == "8200"


class TestAssetRevaluatedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        old_value = Decimal("10000")
        new_value = Decimal("12000")
        surplus = Decimal("2000")
        event = AssetRevaluatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=5,
            asset=sample_asset,
            old_value=old_value,
            new_value=new_value,
            revaluation_surplus=surplus,
            revaluation_method="fair_value",
            approved_by="dave",
        )
        assert event.event_type == DomainEventType.ASSET_REVALUATED
        data = event.event_data
        assert data["old_value"] == "10000"
        assert data["new_value"] == "12000"
        assert data["revaluation_surplus"] == "2000"
        assert data["revaluation_method"] == "fair_value"
        assert data["approved_by"] == "dave"


class TestAssetDisposedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        disposal_date = date(2025, 6, 30)
        proceeds = Decimal("5000")
        nbv_at_disposal = Decimal("8200")
        gain_loss = proceeds - nbv_at_disposal  # -3200
        sample_asset.net_book_value = nbv_at_disposal
        event = AssetDisposedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=6,
            asset=sample_asset,
            disposal_date=disposal_date,
            disposal_type="sold",
            proceeds=proceeds,
            gain_loss=gain_loss,
            disposed_by="eve",
        )
        assert event.event_type == DomainEventType.ASSET_DISPOSED
        data = event.event_data
        assert data["disposal_date"] == "2025-06-30"
        assert data["disposal_type"] == "sold"
        assert data["proceeds"] == "5000"
        assert data["gain_loss"] == "-3200"
        assert data["is_gain"] is False
        assert data["is_loss"] is True


class TestAssetTransferredEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        event = AssetTransferredEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=7,
            asset=sample_asset,
            transfer_type="department",
            source="Finance",
            destination="Operations",
            transferred_by="frank",
        )
        assert event.event_type == DomainEventType.ASSET_TRANSFERRED
        data = event.event_data
        assert data["transfer_type"] == "department"
        assert data["source"] == "Finance"
        assert data["destination"] == "Operations"
        assert data["transferred_by"] == "frank"


class TestAssetImpairedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        carrying = Decimal("10000")
        recoverable = Decimal("8000")
        loss = Decimal("2000")
        indicators = ["market_decline", "economic_downturn"]
        event = AssetImpairedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=8,
            asset=sample_asset,
            carrying_amount=carrying,
            recoverable_amount=recoverable,
            impairment_loss=loss,
            indicators=indicators,
            tested_by="grace",
        )
        assert event.event_type == DomainEventType.ASSET_IMPAIRED
        data = event.event_data
        assert data["carrying_amount"] == "10000"
        assert data["recoverable_amount"] == "8000"
        assert data["impairment_loss"] == "2000"
        assert data["indicators"] == indicators
        assert data["tested_by"] == "grace"


class TestAssetImpairmentReversedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        previous = Decimal("2000")
        reversal = Decimal("1000")
        recoverable = Decimal("9000")
        sample_asset.accumulated_impairment = Decimal("1000")
        event = AssetImpairmentReversedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=9,
            asset=sample_asset,
            previous_impairment=previous,
            reversal_amount=reversal,
            recoverable_amount=recoverable,
            tested_by="hank",
        )
        assert event.event_type == DomainEventType.ASSET_IMPAIRMENT_REVERSED
        data = event.event_data
        assert data["previous_impairment"] == "2000"
        assert data["reversal_amount"] == "1000"
        assert data["recoverable_amount"] == "9000"
        assert data["current_impairment"] == "1000"


class TestAssetFullyDepreciatedEvent:
    def test_construction(self, sample_asset, sample_aggregate_id):
        sample_asset.accumulated_depreciation = Decimal("9000")
        sample_asset.net_book_value = Decimal("1000")
        event = AssetFullyDepreciatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=10,
            asset=sample_asset,
        )
        assert event.event_type == DomainEventType.ASSET_FULLY_DEPRECIATED
        data = event.event_data
        assert data["asset_id"] == str(sample_asset.id)
        assert data["asset_code"] == sample_asset.asset_code
        assert data["accumulated_depreciation"] == "9000"
        assert data["final_nbv"] == "1000"


class TestAssetGroupCreatedEvent:
    def test_construction(self, sample_aggregate_id):
        group_id = uuid4()
        parent_group_id = uuid4()
        event = AssetGroupCreatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=11,
            group_id=group_id,
            group_code="GRP-001",
            group_name="Buildings",
            group_type="asset_group",
            parent_group_id=parent_group_id,
            created_by="ivy",
        )
        assert event.event_type == DomainEventType.ASSET_GROUP_CREATED
        data = event.event_data
        assert data["group_id"] == str(group_id)
        assert data["group_code"] == "GRP-001"
        assert data["group_name"] == "Buildings"
        assert data["parent_group_id"] == str(parent_group_id)
        assert data["created_by"] == "ivy"


class TestAssetGroupUpdatedEvent:
    def test_construction(self, sample_aggregate_id):
        group_id = uuid4()
        changes = {"group_name": "Office Buildings"}
        event = AssetGroupUpdatedEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=12,
            group_id=group_id,
            group_code="GRP-001",
            changes=changes,
            updated_by="jack",
        )
        assert event.event_type == DomainEventType.ASSET_GROUP_UPDATED
        data = event.event_data
        assert data["group_id"] == str(group_id)
        assert data["group_code"] == "GRP-001"
        assert data["changes"] == changes
        assert data["updated_by"] == "jack"


# ----------------------------------------------------------------------
# DomainEventPublisher (Protocol)
# ----------------------------------------------------------------------
class TestDomainEventPublisher:
    def test_class_defined(self):
        assert DomainEventPublisher is not None

    def test_protocol_methods(self):
        # Can't instantiate protocol, but we can check it has the required methods
        assert hasattr(DomainEventPublisher, "publish")
        assert hasattr(DomainEventPublisher, "publish_many")


# ----------------------------------------------------------------------
# Helper Functions
# ----------------------------------------------------------------------
class TestHelpers:
    def test_serialize_domain_event(self, sample_asset, sample_aggregate_id):
        event = AssetAcquiredEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            asset=sample_asset,
            acquired_by="alice",
        )
        json_str = serialize_domain_event(event)
        data = json.loads(json_str)
        assert data["event_type"] == "asset_acquired"
        assert data["aggregate_id"] == str(sample_aggregate_id)

    def test_deserialize_domain_event(self, sample_asset, sample_aggregate_id):
        event = AssetAcquiredEvent(
            aggregate_id=sample_aggregate_id,
            aggregate_version=1,
            asset=sample_asset,
            acquired_by="alice",
        )
        json_str = serialize_domain_event(event)
        reconstructed = deserialize_domain_event(json_str)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.event_type == event.event_type
        assert reconstructed.aggregate_id == event.aggregate_id
        assert reconstructed.aggregate_version == event.aggregate_version
        assert reconstructed.event_data == event.event_data

    def test_deserialize_domain_event_invalid_event_type(self):
        with pytest.raises(ValueError):
            deserialize_domain_event('{"event_type": "invalid", "event_id": "123", "aggregate_id": "123", "aggregate_version": 1, "occurred_at": "2025-01-01T00:00:00Z", "event_data": {}}')


# ----------------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------------
def test_aliases():
    from domain.fixed_asset.domain_events import (
        AssetAcquired,
        AssetDepreciated,
        AssetDisposed,
        AssetFullyDepreciated,
        AssetGroupCreated,
        AssetGroupUpdated,
        AssetImpaired,
        AssetImpairmentRecognized,
        AssetImpairmentReversed,
        AssetRevalued,
        AssetTransferred,
        AssetUpdated,
    )
    assert AssetAcquired is AssetAcquiredEvent
    assert AssetUpdated is AssetUpdatedEvent
    assert AssetDepreciated is AssetDepreciationPostedEvent
    assert AssetRevalued is AssetRevaluatedEvent
    assert AssetDisposed is AssetDisposedEvent
    assert AssetTransferred is AssetTransferredEvent
    assert AssetImpaired is AssetImpairedEvent
    assert AssetImpairmentReversed is AssetImpairmentReversedEvent
    assert AssetFullyDepreciated is AssetFullyDepreciatedEvent
    assert AssetGroupCreated is AssetGroupCreatedEvent
    assert AssetGroupUpdated is AssetGroupUpdatedEvent
    assert AssetImpairmentRecognized is AssetImpairedEvent
