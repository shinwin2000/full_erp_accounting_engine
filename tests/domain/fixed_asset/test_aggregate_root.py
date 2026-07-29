# tests/domain/fixed_asset/test_aggregate_root.py
"""
Comprehensive tests for domain/fixed_asset/aggregate_root.py.
Covers all methods and edge cases with mocked datetime to avoid flakiness.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.fixed_asset.aggregate_root import (
    FixedAssetAggregate,
    FixedAssetCollection,
    FixedAssetRepository,
)
from domain.fixed_asset.asset_entity import AssetStatus, AssetType, FixedAsset
from domain.fixed_asset.disposal_entity import DisposalEntity, DisposalType
from domain.fixed_asset.domain_events import (
    AssetAcquiredEvent,
    AssetDepreciationPostedEvent,
    AssetDisposedEvent,
    AssetRevaluatedEvent,
    AssetTransferredEvent,
    AssetUpdatedEvent,
)
from domain.fixed_asset.revaluation_entity import RevaluationEntity, RevaluationMethod
from domain.fixed_asset.transfer_entity import TransferEntity, TransferType

# =============================================================================
# Fixed datetime for deterministic tests
# =============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 7, 23)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now and date.today in aggregate_root module."""
    with patch("domain.fixed_asset.aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture(autouse=True)
def mock_date_today():
    with patch("domain.fixed_asset.aggregate_root.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_asset(legal_entity_id) -> FixedAsset:
    return FixedAsset(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        asset_code="AST-001",
        name="Test Asset",
        description="Test Description",
        asset_type=AssetType.EQUIPMENT,
        category="Machinery",
        acquisition_date=FIXED_DATE,
        acquisition_cost=Decimal("10000.00"),
        residual_value=Decimal("1000.00"),
        useful_life_years=10,
        depreciation_method="straight_line",
        location="Warehouse A",
        responsible_person=uuid4(),
        status=AssetStatus.ACTIVE,
        accumulated_depreciation=Decimal("0.00"),
        revaluation_surplus=Decimal("0.00"),
        last_depreciation_date=FIXED_DATE,
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        created_by="system",
        version=1,
    )


@pytest.fixture
def sample_asset2(legal_entity_id) -> FixedAsset:
    return FixedAsset(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        asset_code="AST-002",
        name="Test Asset 2",
        description="Another asset",
        asset_type=AssetType.BUILDING,
        category="Infrastructure",
        acquisition_date=FIXED_DATE - timedelta(days=365),
        acquisition_cost=Decimal("50000.00"),
        residual_value=Decimal("5000.00"),
        useful_life_years=20,
        depreciation_method="straight_line",
        location="Warehouse B",
        responsible_person=uuid4(),
        status=AssetStatus.ACTIVE,
        accumulated_depreciation=Decimal("0.00"),
        revaluation_surplus=Decimal("0.00"),
        last_depreciation_date=FIXED_DATE - timedelta(days=365),
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        created_by="system",
        version=1,
    )


@pytest.fixture
def sample_disposed_asset(legal_entity_id) -> FixedAsset:
    return FixedAsset(
        id=uuid4(),
        legal_entity_id=legal_entity_id,
        asset_code="AST-DISP",
        name="Disposed Asset",
        description="To be disposed",
        asset_type=AssetType.VEHICLE,
        category="Transport",
        acquisition_date=FIXED_DATE - timedelta(days=365 * 3),
        acquisition_cost=Decimal("20000.00"),
        residual_value=Decimal("2000.00"),
        useful_life_years=10,
        depreciation_method="straight_line",
        location="Yard",
        responsible_person=uuid4(),
        status=AssetStatus.DISPOSED,
        accumulated_depreciation=Decimal("18000.00"),
        revaluation_surplus=Decimal("0.00"),
        last_depreciation_date=FIXED_DATE - timedelta(days=365 * 2),
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        created_by="system",
        version=1,
    )


@pytest.fixture
def collection(legal_entity_id, sample_asset) -> FixedAssetCollection:
    return FixedAssetCollection(
        asset_id=uuid4(),
        legal_entity_id=legal_entity_id,
        assets={sample_asset.id: sample_asset},
        created_by="tester",
    )


@pytest.fixture
def empty_collection(legal_entity_id) -> FixedAssetCollection:
    return FixedAssetCollection(
        asset_id=uuid4(),
        legal_entity_id=legal_entity_id,
        created_by="tester",
    )


# =============================================================================
# Tests for FixedAssetCollection
# =============================================================================

class TestFixedAssetCollection:
    def test_construction(self, legal_entity_id):
        collection = FixedAssetCollection(
            asset_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_by="tester"
        )
        assert isinstance(collection, FixedAssetCollection)
        assert collection.version == 1
        assert len(collection.assets) == 0
        assert collection._events == []

    def test_event_contract(self, collection):
        event = MagicMock(spec=AssetAcquiredEvent)
        collection.register_event(event)
        assert len(collection._events) == 1
        assert collection.get_events() == [event]
        events = collection.pull_events()
        assert events == [event]
        assert collection._events == []
        collection.register_event(event)
        collection.clear_events()
        assert collection._events == []

    def test_domain_events_property(self, collection):
        event = MagicMock(spec=AssetAcquiredEvent)
        collection.register_event(event)
        assert collection.domain_events == [event]

    def test_take_snapshot(self, collection):
        assert len(collection._snapshots) == 1
        for i in range(12):
            collection.add_asset(FixedAsset(
                id=uuid4(),
                legal_entity_id=collection.legal_entity_id,
                asset_code=f"AST-{i}",
                name=f"Asset {i}",
                asset_type=AssetType.EQUIPMENT,
                acquisition_date=FIXED_DATE,
                acquisition_cost=Decimal("100"),
                residual_value=Decimal("0"),
                useful_life_years=5,
                depreciation_method="straight_line",
                location="loc",
                status=AssetStatus.ACTIVE,
                created_by="system",
                version=1,
            ))
        assert len(collection._snapshots) == 10

    def test_audit_trail(self, collection):
        collection._record_audit("TEST", "user", {"foo": "bar"})
        trail = collection.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"

    # --- Entity basic methods ---
    def test_create(self, collection):
        new_collection = collection.create("creator")
        assert new_collection.version == collection.version
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "CREATE" for entry in trail)

    def test_update(self, collection):
        new_collection = collection.update("updater", location="New Location")
        assert new_collection.version == collection.version + 1
        assert new_collection.updated_at == FIXED_NOW
        assert new_collection.created_by == "updater"
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "UPDATE" for entry in trail)

    def test_delete_raises_if_assets_present(self, collection):
        with pytest.raises(ValueError, match="Cannot delete collection with existing assets"):
            collection.delete("deleter")

    def test_delete_empty_ok(self, empty_collection):
        new_collection = empty_collection.delete("deleter", "no assets")
        assert new_collection.version == empty_collection.version + 1
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "DELETE" for entry in trail)

    def test_restore(self, collection):
        new_collection = collection.restore("restorer")
        assert new_collection.version == collection.version + 1
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "RESTORE" for entry in trail)

    def test_activate(self, collection):
        new_collection = collection.activate("activator")
        assert new_collection.version == collection.version + 1
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "ACTIVATE" for entry in trail)

    def test_deactivate(self, collection):
        new_collection = collection.deactivate("deactivator", "reason")
        assert new_collection.version == collection.version + 1
        trail = new_collection.audit_trail()
        assert any(entry["action"] == "DEACTIVATE" for entry in trail)

    def test_lock_unlock(self, collection):
        locked = collection.lock("locker", "reason")
        assert locked.version == collection.version + 1
        unlocked = locked.unlock("unlocker")
        assert unlocked.version == locked.version + 1
        trail = unlocked.audit_trail()
        assert any(entry["action"] == "LOCK" for entry in trail)
        assert any(entry["action"] == "UNLOCK" for entry in trail)

    def test_validate(self, collection):
        result = collection.validate()
        assert result["is_valid"] is True
        asset = collection.assets[next(iter(collection.assets))]
        duplicate = asset.clone()
        duplicate.id = uuid4()
        new_collection = collection.add_asset(duplicate)
        result = new_collection.validate()
        assert result["is_valid"] is False
        assert "Duplicate asset code" in result["errors"][0]

    def test_to_dict(self, collection):
        data = collection.to_dict()
        assert "asset_id" in data
        assert data["total_assets"] == 1
        assert data["version"] == 1

    def test_from_dict(self, collection):
        asset_data = collection.assets[next(iter(collection.assets))].to_dict()
        full_data = {
            "asset_id": str(collection.asset_id),
            "legal_entity_id": str(collection.legal_entity_id),
            "assets": [asset_data],
            "revaluations": [],
            "disposals": [],
            "transfers": [],
            "created_at": collection.created_at.isoformat(),
            "updated_at": collection.updated_at.isoformat(),
            "created_by": collection.created_by,
            "version": collection.version,
        }
        new_collection = FixedAssetCollection.from_dict(full_data)
        assert new_collection.asset_id == collection.asset_id
        assert len(new_collection.assets) == 1

    def test_clone(self, collection):
        cloned = collection.clone()
        assert cloned.asset_id != collection.asset_id
        assert cloned.legal_entity_id == collection.legal_entity_id
        assert len(cloned.assets) == len(collection.assets)
        assert cloned.version == 1
        for orig_asset, new_asset in zip(collection.assets.values(), cloned.assets.values(), strict=False):
            assert orig_asset.id != new_asset.id
            assert orig_asset.asset_code == new_asset.asset_code

    def test_snapshot(self, collection):
        snap = collection.snapshot()
        assert "version" in snap
        assert snap["total_assets"] == 1

    def test_version_method(self, collection):
        assert collection.version() == collection.version

    def test_touch(self, collection):
        touched = collection.touch("toucher")
        assert touched.version == collection.version + 1
        assert touched.updated_at == FIXED_NOW
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    # --- Aggregate root command methods ---
    def test_add_child(self, collection, sample_asset2):
        new_collection = collection.add_child(sample_asset2, "creator")
        assert len(new_collection.assets) == 2
        assert new_collection.version == collection.version + 1
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetAcquiredEvent) for e in events)

    def test_remove_child(self, collection, sample_asset):
        disposed = sample_asset.dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        collection_with_disposed = collection.update_asset(disposed)
        new_collection = collection_with_disposed.remove_child(disposed.id, "remover")
        assert len(new_collection.assets) == 0
        assert new_collection.version == collection_with_disposed.version + 1

    def test_can_post(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_post(asset_id) is True
        asset = collection.assets[asset_id]
        inactive = asset.deactivate("user", "reason")
        collection_inactive = collection.update_asset(inactive)
        assert collection_inactive.can_post(asset_id) is False

    def test_post_depreciation(self, collection):
        asset_id = next(iter(collection.assets))
        amount = Decimal("100.00")
        new_collection = collection.post(asset_id, amount, "poster", "depreciation")
        assert len(new_collection.assets) == 1
        updated_asset = new_collection.assets[asset_id]
        assert updated_asset.accumulated_depreciation == amount
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetDepreciationPostedEvent) for e in events)

    def test_post_unknown_transaction_type(self, collection):
        with pytest.raises(ValueError, match="Unknown transaction type"):
            collection.post(next(iter(collection.assets)), Decimal("100"), "poster", "unknown")

    def test_can_approve(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_approve(asset_id, "finance_manager") is True
        assert collection.can_approve(asset_id, "user") is False

    def test_approve(self, collection):
        asset_id = next(iter(collection.assets))
        new_collection = collection.approve(asset_id, "approver")
        assert new_collection is collection

    def test_approve_fails(self, collection):
        asset_id = next(iter(collection.assets))
        with pytest.raises(ValueError, match="Cannot approve"):
            collection.approve(asset_id, "user")

    def test_can_reject(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_reject(asset_id, "user") is True

    def test_reject(self, collection):
        asset_id = next(iter(collection.assets))
        new_collection = collection.reject(asset_id, "rejecter", "bad asset")
        assert new_collection is collection

    def test_can_cancel(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_cancel(asset_id) is False
        asset = collection.assets[asset_id]
        under_constr = FixedAsset(
            id=asset_id,
            legal_entity_id=asset.legal_entity_id,
            asset_code=asset.asset_code,
            name=asset.name,
            asset_type=asset.asset_type,
            category=asset.category,
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            depreciation_method=asset.depreciation_method,
            location=asset.location,
            responsible_person=asset.responsible_person,
            status=AssetStatus.UNDER_CONSTRUCTION,
            accumulated_depreciation=asset.accumulated_depreciation,
            revaluation_surplus=asset.revaluation_surplus,
            last_depreciation_date=asset.last_depreciation_date,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            version=asset.version,
        )
        collection_under = collection.update_asset(under_constr)
        assert collection_under.can_cancel(asset_id) is True

    def test_cancel(self, collection):
        asset_id = next(iter(collection.assets))
        asset = collection.assets[asset_id]
        under_constr = FixedAsset(
            id=asset_id,
            legal_entity_id=asset.legal_entity_id,
            asset_code=asset.asset_code,
            name=asset.name,
            asset_type=asset.asset_type,
            category=asset.category,
            acquisition_date=asset.acquisition_date,
            acquisition_cost=asset.acquisition_cost,
            residual_value=asset.residual_value,
            useful_life_years=asset.useful_life_years,
            depreciation_method=asset.depreciation_method,
            location=asset.location,
            responsible_person=asset.responsible_person,
            status=AssetStatus.UNDER_CONSTRUCTION,
            accumulated_depreciation=asset.accumulated_depreciation,
            revaluation_surplus=asset.revaluation_surplus,
            last_depreciation_date=asset.last_depreciation_date,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
            created_by=asset.created_by,
            version=asset.version,
        )
        collection_under = collection.update_asset(under_constr)
        new_collection = collection_under.cancel(asset_id, "canceller", "reason")
        assert new_collection is collection_under

    def test_cancel_fails_if_not_under_construction(self, collection):
        asset_id = next(iter(collection.assets))
        with pytest.raises(ValueError, match="Cannot cancel"):
            collection.cancel(asset_id, "canceller", "reason")

    def test_can_reverse(self, collection):
        assert collection.can_reverse(next(iter(collection.assets))) is False

    def test_reverse_raises(self, collection):
        with pytest.raises(NotImplementedError):
            collection.reverse(next(iter(collection.assets)), "reverser", "reason")

    def test_can_close(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_close(asset_id) is False
        disposed = collection.assets[asset_id].dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        collection_disposed = collection.update_asset(disposed)
        assert collection_disposed.can_close(asset_id) is True

    def test_close(self, collection):
        asset_id = next(iter(collection.assets))
        disposed = collection.assets[asset_id].dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        collection_disposed = collection.update_asset(disposed)
        new_collection = collection_disposed.close(asset_id, "closer", "closed")
        assert new_collection is collection_disposed

    def test_close_fails_if_not_disposed(self, collection):
        with pytest.raises(ValueError, match="Cannot close"):
            collection.close(next(iter(collection.assets)), "closer", "reason")

    def test_can_reopen(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.can_reopen(asset_id) is False
        disposed = collection.assets[asset_id].dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        collection_disposed = collection.update_asset(disposed)
        assert collection_disposed.can_reopen(asset_id) is True

    def test_reopen(self, collection):
        asset_id = next(iter(collection.assets))
        disposed = collection.assets[asset_id].dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        collection_disposed = collection.update_asset(disposed)
        new_collection = collection_disposed.reopen(asset_id, "reopener", "reopen")
        assert new_collection is collection_disposed

    def test_can_archive(self, empty_collection):
        assert empty_collection.can_archive() is True
        assert collection.can_archive() is False

    def test_archive(self, empty_collection):
        archived = empty_collection.archive("archiver", "reason")
        assert archived.version == empty_collection.version + 1
        trail = archived.audit_trail()
        assert any(entry["action"] == "ARCHIVE" for entry in trail)

    def test_archive_fails_if_assets(self, collection):
        with pytest.raises(ValueError, match="Cannot archive collection with assets"):
            collection.archive("archiver")

    def test_can_unarchive(self, empty_collection):
        assert empty_collection.can_unarchive() is True

    def test_unarchive(self, empty_collection):
        unarchived = empty_collection.unarchive("unarchiver")
        assert unarchived.version == empty_collection.version + 1
        trail = unarchived.audit_trail()
        assert any(entry["action"] == "UNARCHIVE" for entry in trail)

    # --- Query methods ---
    def test_get_asset(self, collection, sample_asset):
        assert collection.get_asset(sample_asset.id) == sample_asset
        assert collection.get_asset(uuid4()) is None

    def test_get_asset_by_code(self, collection, sample_asset):
        assert collection.get_asset_by_code(sample_asset.asset_code) == sample_asset
        assert collection.get_asset_by_code("NONEXISTENT") is None

    def test_get_all_assets(self, collection):
        assets = collection.get_all_assets()
        assert len(assets) == 1
        assert assets[0] == list(collection.assets.values())[0]

    def test_get_active_assets(self, collection):
        active = collection.get_active_assets()
        assert len(active) == 1
        asset = collection.assets[next(iter(collection.assets))]
        inactive = asset.deactivate("user", "reason")
        new_collection = collection.update_asset(inactive)
        active = new_collection.get_active_assets()
        assert len(active) == 0

    def test_get_disposed_assets(self, collection):
        assert len(collection.get_disposed_assets()) == 0
        asset = collection.assets[next(iter(collection.assets))]
        disposed = asset.dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        new_collection = collection.update_asset(disposed)
        disposed_list = new_collection.get_disposed_assets()
        assert len(disposed_list) == 1
        assert disposed_list[0].id == disposed.id

    def test_get_fully_depreciated_assets(self, collection):
        assert len(collection.get_fully_depreciated_assets()) == 0
        asset = collection.assets[next(iter(collection.assets))]
        fully = asset.record_depreciation("2024", Decimal("9000"), uuid4())
        new_collection = collection.update_asset(fully)
        fully_list = new_collection.get_fully_depreciated_assets()
        assert len(fully_list) == 1

    def test_get_assets_by_type(self, collection, sample_asset):
        by_type = collection.get_assets_by_type(AssetType.EQUIPMENT)
        assert len(by_type) == 1
        assert by_type[0].id == sample_asset.id

    def test_get_assets_by_category(self, collection, sample_asset):
        by_cat = collection.get_assets_by_category(sample_asset.category)
        assert len(by_cat) == 1

    def test_get_total_cost(self, collection):
        total = collection.get_total_cost()
        assert total == Decimal("10000.00")

    def test_get_total_accumulated_depreciation(self, collection):
        total = collection.get_total_accumulated_depreciation()
        assert total == Decimal("0.00")
        asset = collection.assets[next(iter(collection.assets))]
        depreciated = asset.record_depreciation("2024", Decimal("1000"), uuid4())
        new_collection = collection.update_asset(depreciated)
        assert new_collection.get_total_accumulated_depreciation() == Decimal("1000.00")

    def test_get_total_nbv(self, collection):
        assert collection.get_total_nbv() == Decimal("10000.00")

    def test_get_revaluations_for_asset(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.get_revaluations_for_asset(asset_id) == []
        reval = RevaluationEntity(
            id=uuid4(),
            asset_id=asset_id,
            old_value=Decimal("10000"),
            new_value=Decimal("12000"),
            revaluation_method=RevaluationMethod.REVALUATION_SURPLUS,
            revaluation_date=FIXED_DATE,
            approved_by=uuid4(),
            created_at=FIXED_NOW,
            created_by="system",
        )
        new_collection = collection.add_revaluation(asset_id, reval)
        revals = new_collection.get_revaluations_for_asset(asset_id)
        assert len(revals) == 1
        assert revals[0].id == reval.id

    def test_get_disposals_for_asset(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.get_disposals_for_asset(asset_id) == []
        asset = collection.assets[asset_id]
        disposed = asset.dispose(FIXED_DATE, "Sale", Decimal("0"), "reason", uuid4())
        new_collection = collection.update_asset(disposed)
        disposal = DisposalEntity(
            id=uuid4(),
            asset_id=asset_id,
            disposal_date=FIXED_DATE,
            disposal_type=DisposalType.SALE,
            proceeds=Decimal("0"),
            gain_loss=Decimal("0"),
            reason="reason",
            disposed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        new_collection = new_collection.add_disposal(asset_id, disposal)
        disposals = new_collection.get_disposals_for_asset(asset_id)
        assert len(disposals) == 1

    def test_get_transfers_for_asset(self, collection):
        asset_id = next(iter(collection.assets))
        assert collection.get_transfers_for_asset(asset_id) == []
        transfer = TransferEntity(
            id=uuid4(),
            asset_id=asset_id,
            source="loc1",
            destination="loc2",
            transfer_type=TransferType.INTERNAL,
            transfer_date=FIXED_DATE,
            status="completed",
            completed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        new_collection = collection.add_transfer(asset_id, transfer)
        transfers = new_collection.get_transfers_for_asset(asset_id)
        assert len(transfers) == 1

    # --- Command methods ---
    def test_add_asset(self, collection, sample_asset2):
        new_collection = collection.add_asset(sample_asset2)
        assert len(new_collection.assets) == 2
        assert new_collection.version == collection.version + 1
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetAcquiredEvent) for e in events)

    def test_add_asset_duplicate_id(self, collection, sample_asset):
        with pytest.raises(ValueError, match="already exists"):
            collection.add_asset(sample_asset)

    def test_add_asset_duplicate_code(self, collection, sample_asset):
        dup = sample_asset.clone()
        dup.id = uuid4()
        with pytest.raises(ValueError, match="already exists"):
            collection.add_asset(dup)

    def test_remove_asset(self, collection, sample_disposed_asset):
        new_collection = collection.add_asset(sample_disposed_asset)
        asset_id = sample_disposed_asset.id
        removed = new_collection.remove_asset(asset_id, "remover")
        assert len(removed.assets) == 1
        assert removed.version == new_collection.version + 1

    def test_remove_asset_not_found(self, collection):
        with pytest.raises(ValueError, match="not found"):
            collection.remove_asset(uuid4(), "remover")

    def test_remove_asset_not_disposed(self, collection):
        asset_id = next(iter(collection.assets))
        with pytest.raises(ValueError, match="Cannot remove non-disposed"):
            collection.remove_asset(asset_id, "remover")

    def test_update_asset(self, collection, sample_asset):
        updated = sample_asset.update_name("New Name", uuid4())
        new_collection = collection.update_asset(updated)
        assert new_collection.assets[updated.id].name == "New Name"
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetUpdatedEvent) for e in events)

    def test_update_asset_not_found(self, collection):
        asset = FixedAsset(
            id=uuid4(),
            legal_entity_id=collection.legal_entity_id,
            asset_code="TEMP",
            name="temp",
            asset_type=AssetType.EQUIPMENT,
            acquisition_date=FIXED_DATE,
            acquisition_cost=Decimal("0"),
            residual_value=Decimal("0"),
            useful_life_years=1,
            depreciation_method="straight_line",
            location="",
            status=AssetStatus.ACTIVE,
            created_by="system",
            version=1,
        )
        with pytest.raises(ValueError, match="not found"):
            collection.update_asset(asset)

    def test_calculate_depreciation(self, collection):
        asset_id = next(iter(collection.assets))
        amount = collection.calculate_depreciation(asset_id, FIXED_NOW)
        assert isinstance(amount, Decimal)
        assert amount >= Decimal("0")

    def test_calculate_depreciation_asset_not_found(self, collection):
        with pytest.raises(ValueError, match="not found"):
            collection.calculate_depreciation(uuid4(), FIXED_NOW)

    def test_post_depreciation(self, collection):
        asset_id = next(iter(collection.assets))
        period = "2024-01"
        amount = Decimal("100.00")
        new_collection = collection.post_depreciation(asset_id, period, amount, "poster")
        updated = new_collection.assets[asset_id]
        assert updated.accumulated_depreciation == amount
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetDepreciationPostedEvent) for e in events)

    def test_post_depreciation_negative_amount(self, collection):
        with pytest.raises(ValueError, match="positive"):
            collection.post_depreciation(next(iter(collection.assets)), "2024", Decimal("-1"), "poster")

    def test_post_depreciation_asset_not_found(self, collection):
        with pytest.raises(ValueError, match="not found"):
            collection.post_depreciation(uuid4(), "2024", Decimal("100"), "poster")

    def test_add_revaluation(self, collection):
        asset_id = next(iter(collection.assets))
        reval = RevaluationEntity(
            id=uuid4(),
            asset_id=asset_id,
            old_value=Decimal("10000"),
            new_value=Decimal("12000"),
            revaluation_method=RevaluationMethod.REVALUATION_SURPLUS,
            revaluation_date=FIXED_DATE,
            approved_by=uuid4(),
            created_at=FIXED_NOW,
            created_by="system",
        )
        new_collection = collection.add_revaluation(asset_id, reval)
        updated = new_collection.assets[asset_id]
        assert updated.revaluation_surplus == Decimal("2000")
        assert len(new_collection.revaluations) == 1
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetRevaluatedEvent) for e in events)

    def test_add_revaluation_asset_not_found(self, collection):
        reval = RevaluationEntity(
            id=uuid4(),
            asset_id=uuid4(),
            old_value=Decimal("0"),
            new_value=Decimal("0"),
            revaluation_method=RevaluationMethod.REVALUATION_SURPLUS,
            revaluation_date=FIXED_DATE,
            approved_by=uuid4(),
            created_at=FIXED_NOW,
            created_by="system",
        )
        with pytest.raises(ValueError, match="not found"):
            collection.add_revaluation(uuid4(), reval)

    def test_add_disposal(self, collection):
        asset_id = next(iter(collection.assets))
        disposal = DisposalEntity(
            id=uuid4(),
            asset_id=asset_id,
            disposal_date=FIXED_DATE,
            disposal_type=DisposalType.SALE,
            proceeds=Decimal("0"),
            gain_loss=Decimal("0"),
            reason="reason",
            disposed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        new_collection = collection.add_disposal(asset_id, disposal)
        updated = new_collection.assets[asset_id]
        assert updated.status == AssetStatus.DISPOSED
        assert len(new_collection.disposals) == 1
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetDisposedEvent) for e in events)

    def test_add_disposal_already_disposed(self, collection):
        asset_id = next(iter(collection.assets))
        disposal1 = DisposalEntity(
            id=uuid4(),
            asset_id=asset_id,
            disposal_date=FIXED_DATE,
            disposal_type=DisposalType.SALE,
            proceeds=Decimal("0"),
            gain_loss=Decimal("0"),
            reason="reason",
            disposed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        new_collection = collection.add_disposal(asset_id, disposal1)
        disposal2 = DisposalEntity(
            id=uuid4(),
            asset_id=asset_id,
            disposal_date=FIXED_DATE,
            disposal_type=DisposalType.SALE,
            proceeds=Decimal("0"),
            gain_loss=Decimal("0"),
            reason="reason2",
            disposed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        with pytest.raises(ValueError, match="already disposed"):
            new_collection.add_disposal(asset_id, disposal2)

    def test_add_transfer(self, collection):
        asset_id = next(iter(collection.assets))
        transfer = TransferEntity(
            id=uuid4(),
            asset_id=asset_id,
            source="loc1",
            destination="loc2",
            transfer_type=TransferType.INTERNAL,
            transfer_date=FIXED_DATE,
            status="completed",
            completed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        new_collection = collection.add_transfer(asset_id, transfer)
        updated = new_collection.assets[asset_id]
        assert updated.location == "loc2"
        assert len(new_collection.transfers) == 1
        events = new_collection.pull_events()
        assert any(isinstance(e, AssetTransferredEvent) for e in events)

    def test_add_transfer_asset_not_found(self, collection):
        transfer = TransferEntity(
            id=uuid4(),
            asset_id=uuid4(),
            source="loc1",
            destination="loc2",
            transfer_type=TransferType.INTERNAL,
            transfer_date=FIXED_DATE,
            status="completed",
            completed_by=uuid4(),
            created_at=FIXED_NOW,
        )
        with pytest.raises(ValueError, match="not found"):
            collection.add_transfer(uuid4(), transfer)

    def test_get_summary(self, collection):
        summary = collection.get_summary()
        assert summary["total_assets"] == 1
        assert summary["active_assets"] == 1
        assert "total_cost" in summary

    # --- Private helpers ---
    def test_copy(self, collection):
        copied = collection._copy()
        assert copied.asset_id == collection.asset_id
        assert copied.assets is not collection.assets
        assert len(copied.assets) == len(collection.assets)


# =============================================================================
# Tests for FixedAssetAggregate
# =============================================================================

class TestFixedAssetAggregate:
    def test_construction(self):
        agg = FixedAssetAggregate()
        assert agg._asset is None
        assert agg.version == 1
        assert agg._events == []

    def test_construction_with_asset(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        assert agg._asset == sample_asset
        assert agg.version == sample_asset.version
        assert agg.id == sample_asset.id

    def test_event_contract(self):
        agg = FixedAssetAggregate()
        event = MagicMock(spec=AssetAcquiredEvent)
        agg.register_event(event)
        assert len(agg._events) == 1
        assert agg.get_events() == [event]
        events = agg.pull_events()
        assert events == [event]
        assert agg._events == []
        agg.register_event(event)
        agg.clear_events()
        assert agg._events == []

    def test_domain_events_property(self):
        agg = FixedAssetAggregate()
        event = MagicMock(spec=AssetAcquiredEvent)
        agg.register_event(event)
        assert agg.domain_events == [event]

    def test_pop_events_alias(self):
        agg = FixedAssetAggregate()
        event = MagicMock(spec=AssetAcquiredEvent)
        agg.register_event(event)
        events = agg.pop_events()
        assert events == [event]
        assert agg._events == []

    def test_snapshot_without_asset(self):
        agg = FixedAssetAggregate()
        snap = agg.snapshot()
        assert "version" in snap
        assert "asset_id" in snap

    def test_snapshot_with_asset(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        snap = agg.snapshot()
        assert snap["asset_code"] == sample_asset.asset_code

    def test_asset_property_raises_if_not_loaded(self):
        agg = FixedAssetAggregate()
        with pytest.raises(ValueError, match="Asset not loaded"):
            _ = agg.asset

    def test_asset_property_returns_asset(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        assert agg.asset == sample_asset

    def test_load(self, sample_asset):
        agg = FixedAssetAggregate()
        agg.load(sample_asset)
        assert agg._asset == sample_asset
        assert agg.id == sample_asset.id
        assert agg.version == sample_asset.version

    def test_create(self, sample_asset):
        agg = FixedAssetAggregate()
        agg.create(sample_asset, "creator")
        assert agg._asset == sample_asset
        assert agg.version == 1
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], AssetAcquiredEvent)

    def test_update_name(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        new_name = "Updated Name"
        agg.update_name(new_name, uuid4())
        assert agg.asset.name == new_name
        assert agg.version == sample_asset.version + 1
        events = agg.pull_events()
        assert len(events) == 1
        assert isinstance(events[0], AssetUpdatedEvent)

    def test_update_name_raises_if_no_asset(self):
        agg = FixedAssetAggregate()
        with pytest.raises(ValueError, match="No asset loaded"):
            agg.update_name("new", uuid4())

    def test_update_description(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        agg.update_description("New desc", uuid4())
        assert agg.asset.description == "New desc"
        events = agg.pull_events()
        assert isinstance(events[0], AssetUpdatedEvent)

    def test_update_location(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        agg.update_location("New Loc", uuid4())
        assert agg.asset.location == "New Loc"
        events = agg.pull_events()
        assert isinstance(events[0], AssetUpdatedEvent)

    def test_update_responsible_person(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        new_person = uuid4()
        agg.update_responsible_person(new_person, uuid4())
        assert agg.asset.responsible_person == new_person
        events = agg.pull_events()
        assert isinstance(events[0], AssetUpdatedEvent)

    def test_record_depreciation(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        amount = Decimal("100.00")
        agg.record_depreciation("2024", amount, uuid4())
        assert agg.asset.accumulated_depreciation == amount
        events = agg.pull_events()
        assert isinstance(events[0], AssetDepreciationPostedEvent)

    def test_apply_revaluation(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        new_value = Decimal("15000")
        agg.apply_revaluation(new_value, "REVALUATION_SURPLUS", uuid4())
        assert agg.asset.revaluation_surplus == Decimal("5000")
        events = agg.pull_events()
        assert isinstance(events[0], AssetRevaluatedEvent)

    def test_dispose(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        agg.dispose(FIXED_DATE, "SALE", Decimal("0"), "reason", uuid4(), Decimal("0"))
        assert agg.asset.status == AssetStatus.DISPOSED
        events = agg.pull_events()
        assert isinstance(events[0], AssetDisposedEvent)

    def test_apply_event_sourcing_methods(self, sample_asset):
        agg = FixedAssetAggregate(sample_asset)
        event = MagicMock(spec=DomainEvent)
        agg.apply(event)
        assert agg._events == [event]
        agg.replay([event, event])
        assert len(agg._events) == 3
        assert agg.version == sample_asset.version + 2
        agg.reconstruct([event])
        assert len(agg._events) == 4


# =============================================================================
# Tests for FixedAssetRepository
# =============================================================================

class TestFixedAssetRepository:
    @pytest.fixture(autouse=True)
    def clear_repo(self):
        FixedAssetRepository.clear()
        yield

    @pytest.mark.asyncio
    async def test_save_and_get_by_id(self, collection):
        await FixedAssetRepository.save(collection)
        retrieved = await FixedAssetRepository.get_by_id(collection.asset_id)
        assert retrieved == collection

    @pytest.mark.asyncio
    async def test_get_by_legal_entity(self, collection):
        await FixedAssetRepository.save(collection)
        retrieved = await FixedAssetRepository.get_by_legal_entity(collection.legal_entity_id)
        assert retrieved == collection
        assert await FixedAssetRepository.get_by_legal_entity(uuid4()) is None

    @pytest.mark.asyncio
    async def test_get_asset_by_id(self, collection):
        await FixedAssetRepository.save(collection)
        asset_id = next(iter(collection.assets))
        asset = await FixedAssetRepository.get_asset_by_id(asset_id, collection.legal_entity_id)
        assert asset == collection.assets[asset_id]
        assert await FixedAssetRepository.get_asset_by_id(asset_id, uuid4()) is None
        assert await FixedAssetRepository.get_asset_by_id(uuid4(), collection.legal_entity_id) is None

    @pytest.mark.asyncio
    async def test_get_asset_by_code(self, collection):
        await FixedAssetRepository.save(collection)
        asset = next(iter(collection.assets.values()))
        retrieved = await FixedAssetRepository.get_asset_by_code(asset.asset_code, collection.legal_entity_id)
        assert retrieved == asset
        assert await FixedAssetRepository.get_asset_by_code("NONEXISTENT", collection.legal_entity_id) is None

    @pytest.mark.asyncio
    async def test_get_all(self, collection):
        await FixedAssetRepository.save(collection)
        all_collections = await FixedAssetRepository.get_all()
        assert len(all_collections) == 1
        assert all_collections[0] == collection

    @pytest.mark.asyncio
    async def test_delete(self, collection):
        await FixedAssetRepository.save(collection)
        await FixedAssetRepository.delete(collection.asset_id)
        assert await FixedAssetRepository.exists(collection.asset_id) is False

    @pytest.mark.asyncio
    async def test_exists(self, collection):
        assert await FixedAssetRepository.exists(collection.asset_id) is False
        await FixedAssetRepository.save(collection)
        assert await FixedAssetRepository.exists(collection.asset_id) is True

    @pytest.mark.asyncio
    async def test_count(self, collection):
        assert await FixedAssetRepository.count() == 0
        await FixedAssetRepository.save(collection)
        assert await FixedAssetRepository.count() == 1

    @pytest.mark.asyncio
    async def test_list(self, collection):
        await FixedAssetRepository.save(collection)
        items = await FixedAssetRepository.list(limit=10, offset=0)
        assert len(items) == 1
        assert items[0] == collection

    @pytest.mark.asyncio
    async def test_clear(self, collection):
        await FixedAssetRepository.save(collection)
        await FixedAssetRepository.clear()
        assert await FixedAssetRepository.count() == 0
