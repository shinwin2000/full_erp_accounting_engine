# test_hedged_item.py
# Comprehensive tests for hedged_item.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.hedge.hedged_item import (
    HedgedItem,
    HedgedItemAdjustment,
    HedgedItemError,
    HedgedItemRepository,
    HedgedItemStatus,
    HedgedItemType,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_audit_trail():
    """Reset class variables before each test."""
    HedgedItem._audit_trail = []
    HedgedItemRepository._storage = {}
    yield
    HedgedItem._audit_trail = []
    HedgedItemRepository._storage = {}


@pytest.fixture
def valid_hedged_item():
    """Create a valid HedgedItem."""
    return HedgedItem.create(
        item_number="HEDGE-001",
        item_type=HedgedItemType.INVENTORY,
        legal_entity_id=uuid4(),
        description="Raw materials inventory",
        carrying_amount=Decimal("10000000"),
        currency="IDR",
        reference_id=uuid4(),
        risk_exposure="price_risk",
        created_by=uuid4(),
    )


@pytest.fixture
def hedged_item_with_adjustments(valid_hedged_item):
    """HedgedItem with one adjustment."""
    return valid_hedged_item.record_adjustment(
        adjustment_amount=Decimal("500000"),
        adjustment_type="fair_value",
        description="Fair value increase",
        recorded_by="user1",
    )


@pytest.fixture
def settled_hedged_item(valid_hedged_item):
    """HedgedItem that has been settled."""
    return valid_hedged_item.deactivate(deactivated_by="user1", reason="Settled")


@pytest.fixture
def cancelled_hedged_item(valid_hedged_item):
    """HedgedItem that has been cancelled."""
    return valid_hedged_item.delete(deleted_by="user1", reason="Cancelled")


# ============================================================================
# Tests for Enums
# ============================================================================

class TestHedgedItemType:
    def test_display_name(self):
        assert HedgedItemType.INVENTORY.display_name() == "Persediaan"
        assert HedgedItemType.FIXED_ASSET.display_name() == "Aset Tetap"
        assert HedgedItemType.LOAN.display_name() == "Pinjaman"
        assert HedgedItemType.FORECAST_SALE.display_name() == "Penjualan yang Diharapkan"
        assert HedgedItemType.FORECAST_PURCHASE.display_name() == "Pembelian yang Diharapkan"
        assert HedgedItemType.OTHER.display_name() == "Lainnya"

    def test_is_forecast(self):
        assert HedgedItemType.FORECAST_SALE.is_forecast() is True
        assert HedgedItemType.FORECAST_PURCHASE.is_forecast() is True
        assert HedgedItemType.INVENTORY.is_forecast() is False
        assert HedgedItemType.FIXED_ASSET.is_forecast() is False

    def test_is_existing_asset_liability(self):
        assert HedgedItemType.INVENTORY.is_existing_asset_liability() is True
        assert HedgedItemType.FIXED_ASSET.is_existing_asset_liability() is True
        assert HedgedItemType.LOAN.is_existing_asset_liability() is True
        assert HedgedItemType.FORECAST_SALE.is_existing_asset_liability() is False

    def test_from_string(self):
        assert HedgedItemType.from_string("inventory") == HedgedItemType.INVENTORY
        assert HedgedItemType.from_string("forecast_sale") == HedgedItemType.FORECAST_SALE
        assert HedgedItemType.from_string("unknown") is None


class TestHedgedItemStatus:
    def test_is_active(self):
        assert HedgedItemStatus.ACTIVE.is_active() is True
        assert HedgedItemStatus.SETTLED.is_active() is False
        assert HedgedItemStatus.CANCELLED.is_active() is False

    def test_display_name(self):
        assert HedgedItemStatus.ACTIVE.display_name() == "Aktif"
        assert HedgedItemStatus.SETTLED.display_name() == "Diselesaikan"
        assert HedgedItemStatus.CANCELLED.display_name() == "Dibatalkan"

    def test_from_string(self):
        assert HedgedItemStatus.from_string("active") == HedgedItemStatus.ACTIVE
        assert HedgedItemStatus.from_string("settled") == HedgedItemStatus.SETTLED
        assert HedgedItemStatus.from_string("cancelled") == HedgedItemStatus.CANCELLED
        assert HedgedItemStatus.from_string("unknown") is None


# ============================================================================
# Tests for HedgedItemAdjustment
# ============================================================================

class TestHedgedItemAdjustment:
    def test_construction(self):
        adj_id = uuid4()
        hedged_id = uuid4()
        now = datetime.now(UTC)
        adj = HedgedItemAdjustment(
            adjustment_id=adj_id,
            hedged_item_id=hedged_id,
            adjustment_date=now,
            adjustment_amount=Decimal("1000"),
            adjustment_type="fair_value",
            description="Test adjustment",
            recorded_by="user1",
            created_at=now,
        )
        assert adj.adjustment_id == adj_id
        assert adj.adjustment_amount == Decimal("1000")

    def test_post_init_timezone(self):
        # Check that naive dates are converted to UTC
        naive = datetime(2024, 1, 1, 12, 0, 0)
        adj = HedgedItemAdjustment(
            adjustment_id=uuid4(),
            hedged_item_id=uuid4(),
            adjustment_date=naive,
            adjustment_amount=Decimal("100"),
            adjustment_type="cash_flow",
            description="Test",
            recorded_by="user1",
            created_at=naive,
        )
        assert adj.adjustment_date.tzinfo is not None
        assert adj.created_at.tzinfo is not None

    def test_to_dict(self):
        adj_id = uuid4()
        hedged_id = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        adj = HedgedItemAdjustment(
            adjustment_id=adj_id,
            hedged_item_id=hedged_id,
            adjustment_date=now,
            adjustment_amount=Decimal("2000"),
            adjustment_type="fair_value",
            description="Test",
            recorded_by="user1",
            created_at=now,
        )
        d = adj.to_dict()
        assert d["adjustment_id"] == str(adj_id)
        assert d["adjustment_amount"] == "2000"
        assert d["adjustment_date"] == now.isoformat()

    def test_from_dict(self):
        adj_id = uuid4()
        hedged_id = uuid4()
        now = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        data = {
            "adjustment_id": str(adj_id),
            "hedged_item_id": str(hedged_id),
            "adjustment_date": now.isoformat(),
            "adjustment_amount": "2000",
            "adjustment_type": "fair_value",
            "description": "Test",
            "recorded_by": "user1",
            "created_at": now.isoformat(),
        }
        adj = HedgedItemAdjustment.from_dict(data)
        assert adj.adjustment_id == adj_id
        assert adj.adjustment_amount == Decimal("2000")


# ============================================================================
# Tests for HedgedItem Entity
# ============================================================================

class TestHedgedItemConstruction:
    def test_create(self):
        legal_id = uuid4()
        ref_id = uuid4()
        created_by = uuid4()
        item = HedgedItem.create(
            item_number="H-001",
            item_type=HedgedItemType.LOAN,
            legal_entity_id=legal_id,
            description="Business loan",
            carrying_amount=Decimal("50000000"),
            currency="IDR",
            reference_id=ref_id,
            risk_exposure="interest_rate",
            created_by=created_by,
        )
        assert isinstance(item.id, UUID)
        assert item.item_number == "H-001"
        assert item.item_type == HedgedItemType.LOAN
        assert item.legal_entity_id == legal_id
        assert item.carrying_amount == Decimal("50000000")
        assert item.currency == "IDR"
        assert item.reference_id == ref_id
        assert item.risk_exposure == "interest_rate"
        assert item.status == HedgedItemStatus.ACTIVE
        assert item.version == 1

    def test_validation_item_number_too_short(self):
        with pytest.raises(HedgedItemError, match="Item number must be at least 3 characters"):
            HedgedItem(
                id=uuid4(),
                item_number="AB",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="Test",
                carrying_amount=Decimal("100"),
                currency="IDR",
            )

    def test_validation_description_too_short(self):
        with pytest.raises(HedgedItemError, match="Description must be at least 2 characters"):
            HedgedItem(
                id=uuid4(),
                item_number="H-001",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="A",
                carrying_amount=Decimal("100"),
                currency="IDR",
            )

    def test_validation_negative_carrying_amount(self):
        with pytest.raises(HedgedItemError, match="Carrying amount cannot be negative"):
            HedgedItem(
                id=uuid4(),
                item_number="H-001",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="Test",
                carrying_amount=Decimal("-100"),
                currency="IDR",
            )

    def test_validation_invalid_currency(self):
        with pytest.raises(HedgedItemError, match="Invalid currency"):
            HedgedItem(
                id=uuid4(),
                item_number="H-001",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="Test",
                carrying_amount=Decimal("100"),
                currency="ID",
            )

    def test_validation_risk_exposure_empty(self):
        with pytest.raises(HedgedItemError, match="Risk exposure must be specified"):
            HedgedItem(
                id=uuid4(),
                item_number="H-001",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="Test",
                carrying_amount=Decimal("100"),
                currency="IDR",
                risk_exposure="",
            )

    def test_validation_version_less_than_one(self):
        with pytest.raises(HedgedItemError, match="Version must be >= 1"):
            HedgedItem(
                id=uuid4(),
                item_number="H-001",
                item_type=HedgedItemType.INVENTORY,
                legal_entity_id=uuid4(),
                description="Test",
                carrying_amount=Decimal("100"),
                currency="IDR",
                version=0,
            )


# ============================================================================
# Tests for Properties
# ============================================================================

class TestHedgedItemProperties:
    def test_is_active(self, valid_hedged_item, settled_hedged_item, cancelled_hedged_item):
        assert valid_hedged_item.is_active is True
        assert settled_hedged_item.is_active is False
        assert cancelled_hedged_item.is_active is False

    def test_is_forecast(self, valid_hedged_item):
        assert valid_hedged_item.is_forecast is False
        forecast = HedgedItem.create(
            item_number="F-001",
            item_type=HedgedItemType.FORECAST_SALE,
            legal_entity_id=uuid4(),
            description="Forecast sale",
            carrying_amount=Decimal("1000"),
            currency="IDR",
        )
        assert forecast.is_forecast is True

    def test_is_existing(self, valid_hedged_item):
        assert valid_hedged_item.is_existing is True
        forecast = HedgedItem.create(
            item_number="F-001",
            item_type=HedgedItemType.FORECAST_PURCHASE,
            legal_entity_id=uuid4(),
            description="Forecast purchase",
            carrying_amount=Decimal("1000"),
            currency="IDR",
        )
        assert forecast.is_existing is False

    def test_total_adjustment(self, hedged_item_with_adjustments):
        # One adjustment of 500000
        assert hedged_item_with_adjustments.total_adjustment == Decimal("500000")

    def test_adjusted_carrying_amount(self, hedged_item_with_adjustments):
        # carrying 10000000 + adjustment 500000 = 10500000
        assert hedged_item_with_adjustments.adjusted_carrying_amount == Decimal("10500000")


# ============================================================================
# Tests for Factory Methods (from_dict, to_dict)
# ============================================================================

class TestHedgedItemSerialization:
    def test_to_dict(self, valid_hedged_item):
        d = valid_hedged_item.to_dict(include_history=True)
        assert d["id"] == str(valid_hedged_item.id)
        assert d["item_number"] == "HEDGE-001"
        assert d["status"] == "active"
        assert d["carrying_amount"] == "10000000"
        assert d["is_active"] is True
        assert d["total_adjustment"] == "0"
        assert d["adjusted_carrying_amount"] == "10000000"
        assert "adjustments" in d
        assert len(d["adjustments"]) == 0

    def test_to_dict_with_adjustments(self, hedged_item_with_adjustments):
        d = hedged_item_with_adjustments.to_dict(include_history=True)
        assert d["total_adjustment"] == "500000"
        assert d["adjusted_carrying_amount"] == "10500000"
        assert len(d["adjustments"]) == 1
        assert d["adjustments"][0]["adjustment_amount"] == "500000"

    def test_from_dict(self, valid_hedged_item):
        data = valid_hedged_item.to_dict(include_history=True)
        # from_dict expects some fields as they are; adjust to match
        # data has "id", "item_type", "status", etc.
        restored = HedgedItem.from_dict(data)
        assert restored.id == valid_hedged_item.id
        assert restored.item_number == valid_hedged_item.item_number
        assert restored.carrying_amount == valid_hedged_item.carrying_amount
        assert restored.status == valid_hedged_item.status

    def test_from_dict_with_adjustments(self, hedged_item_with_adjustments):
        data = hedged_item_with_adjustments.to_dict(include_history=True)
        restored = HedgedItem.from_dict(data)
        assert len(restored.adjustments) == 1
        assert restored.adjustments[0].adjustment_amount == Decimal("500000")

    def test_from_dict_invalid_type(self):
        data = {
            "id": str(uuid4()),
            "item_number": "H-001",
            "item_type": "invalid",
            "legal_entity_id": str(uuid4()),
            "description": "Test",
            "carrying_amount": "100",
            "currency": "IDR",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with pytest.raises(HedgedItemError, match="Invalid item_type"):
            HedgedItem.from_dict(data)


# ============================================================================
# Tests for Entity Basic Methods
# ============================================================================

class TestHedgedItemBasicMethods:
    def test_stamp_create_audit(self, valid_hedged_item):
        # stamp_create_audit returns same instance and records audit
        item = valid_hedged_item.stamp_create_audit(created_by="admin")
        assert item == valid_hedged_item
        trail = item.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CREATE"
        assert trail[0]["performed_by"] == "admin"
        assert trail[0]["details"]["item_number"] == "HEDGE-001"

    def test_update(self, valid_hedged_item):
        updated = valid_hedged_item.update(
            updated_by="admin",
            description="Updated description",
            carrying_amount="20000000"
        )
        assert updated.description == "Updated description"
        assert updated.carrying_amount == Decimal("20000000")
        assert updated.version == valid_hedged_item.version + 1
        trail = updated.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "UPDATE"
        assert trail[0]["details"]["changes"]["description"] == "Updated description"

    def test_delete(self, valid_hedged_item):
        deleted = valid_hedged_item.delete(deleted_by="admin", reason="Obsolete")
        assert deleted.status == HedgedItemStatus.CANCELLED
        assert deleted.version == valid_hedged_item.version + 1
        trail = deleted.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "DELETE"
        assert trail[0]["details"]["reason"] == "Obsolete"

    def test_delete_non_active_raises(self, cancelled_hedged_item):
        with pytest.raises(HedgedItemError, match="Cannot delete item in status cancelled"):
            cancelled_hedged_item.delete("admin")

    def test_restore(self, cancelled_hedged_item):
        restored = cancelled_hedged_item.restore(restored_by="admin")
        assert restored.status == HedgedItemStatus.ACTIVE
        assert restored.version == cancelled_hedged_item.version + 1
        trail = restored.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "RESTORE"

    def test_restore_active_fails(self, valid_hedged_item):
        with pytest.raises(HedgedItemError, match="Cannot restore item in status active"):
            valid_hedged_item.restore("admin")

    def test_activate(self, settled_hedged_item):
        activated = settled_hedged_item.activate(activated_by="admin")
        assert activated.status == HedgedItemStatus.ACTIVE
        assert activated.version == settled_hedged_item.version + 1

    def test_activate_already_active(self, valid_hedged_item):
        result = valid_hedged_item.activate("admin")
        assert result == valid_hedged_item

    def test_deactivate(self, valid_hedged_item):
        deactivated = valid_hedged_item.deactivate(deactivated_by="admin", reason="Settled")
        assert deactivated.status == HedgedItemStatus.SETTLED
        assert deactivated.version == valid_hedged_item.version + 1
        trail = deactivated.audit_trail()
        assert trail[0]["action"] == "DEACTIVATE"
        assert trail[0]["details"]["reason"] == "Settled"

    def test_deactivate_non_active_raises(self, settled_hedged_item):
        with pytest.raises(HedgedItemError, match="Cannot deactivate item in status settled"):
            settled_hedged_item.deactivate("admin")

    def test_lock(self, valid_hedged_item):
        locked = valid_hedged_item.lock(locked_by="admin", reason="Review")
        assert locked.version == valid_hedged_item.version + 1
        trail = locked.audit_trail()
        assert trail[0]["action"] == "LOCK"
        assert trail[0]["details"]["reason"] == "Review"

    def test_unlock(self, valid_hedged_item):
        unlocked = valid_hedged_item.unlock(unlocked_by="admin")
        assert unlocked.version == valid_hedged_item.version + 1
        trail = unlocked.audit_trail()
        assert trail[0]["action"] == "UNLOCK"

    def test_validate(self, valid_hedged_item):
        result = valid_hedged_item.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        item = HedgedItem(
            id=uuid4(),
            item_number="AB",  # too short
            item_type=HedgedItemType.INVENTORY,
            legal_entity_id=uuid4(),
            description="Test",
            carrying_amount=Decimal("100"),
            currency="IDR",
        )
        result = item.validate()
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0

    def test_clone(self, valid_hedged_item):
        cloned = valid_hedged_item.clone()
        assert cloned.id != valid_hedged_item.id
        assert cloned.item_number == "HEDGE-001_COPY"
        assert cloned.description == "Cloned from HEDGE-001"
        assert cloned.status == HedgedItemStatus.ACTIVE
        assert cloned.version == 1
        assert cloned.carrying_amount == valid_hedged_item.carrying_amount
        trail = cloned.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "CLONE"
        assert trail[0]["details"]["source"] == str(valid_hedged_item.id)

    def test_snapshot(self, valid_hedged_item):
        snap = valid_hedged_item.snapshot()
        assert snap["item_id"] == str(valid_hedged_item.id)
        assert snap["version"] == 1
        assert snap["status"] == "active"

    def test_get_version(self, valid_hedged_item):
        assert valid_hedged_item.get_version() == 1

    def test_audit_trail(self, valid_hedged_item):
        # perform some actions
        item = valid_hedged_item.stamp_create_audit("admin")
        item = item.update("admin", description="Updated")
        trail = item.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[0]["action"] == "CREATE"
        assert trail[1]["action"] == "UPDATE"

    def test_touch(self, valid_hedged_item):
        touched = valid_hedged_item.touch("toucher")
        assert touched.version == valid_hedged_item.version + 1
        trail = touched.audit_trail()
        assert trail[0]["action"] == "TOUCH"


# ============================================================================
# Tests for Business Methods
# ============================================================================

class TestHedgedItemBusiness:
    def test_record_adjustment(self, valid_hedged_item):
        adjusted = valid_hedged_item.record_adjustment(
            adjustment_amount=Decimal("750000"),
            adjustment_type="cash_flow",
            description="Cash flow hedge adjustment",
            recorded_by="user1"
        )
        assert len(adjusted.adjustments) == 1
        assert adjusted.total_adjustment == Decimal("750000")
        assert adjusted.adjusted_carrying_amount == Decimal("10750000")
        assert adjusted.version == valid_hedged_item.version + 1
        trail = adjusted.audit_trail()
        assert trail[0]["action"] == "RECORD_ADJUSTMENT"
        assert trail[0]["details"]["amount"] == "750000"

    def test_settle(self, valid_hedged_item):
        settled = valid_hedged_item.settle(settled_by="user1", settlement_amount=Decimal("2000000"))
        # settle calls record_adjustment with type 'settlement'
        assert len(settled.adjustments) == 1
        assert settled.adjustments[0].adjustment_type == "settlement"
        assert settled.adjustments[0].adjustment_amount == Decimal("2000000")
        assert settled.total_adjustment == Decimal("2000000")
        # status remains ACTIVE because settle doesn't change status; it just records adjustment.
        # Actually settle only records adjustment, it doesn't change status automatically.
        # The user must deactivate separately.
        assert settled.status == HedgedItemStatus.ACTIVE
        trail = settled.audit_trail()
        assert trail[0]["action"] == "RECORD_ADJUSTMENT"
        assert trail[0]["details"]["type"] == "settlement"

    def test_settle_non_active_raises(self, settled_hedged_item):
        with pytest.raises(HedgedItemError, match="Cannot settle item in status settled"):
            settled_hedged_item.settle("user1", Decimal("1000"))


# ============================================================================
# Tests for HedgedItemRepository
# ============================================================================

class TestHedgedItemRepository:
    async def test_save_and_get_by_id(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        retrieved = await HedgedItemRepository.get_by_id(valid_hedged_item.id, legal_id)
        assert retrieved == valid_hedged_item

    async def test_get_by_number(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        retrieved = await HedgedItemRepository.get_by_number(valid_hedged_item.item_number, legal_id)
        assert retrieved == valid_hedged_item

    async def test_get_by_legal_entity(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        items = await HedgedItemRepository.get_by_legal_entity(legal_id)
        assert len(items) == 1
        assert items[0] == valid_hedged_item

    async def test_get_by_type(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        items = await HedgedItemRepository.get_by_type(HedgedItemType.INVENTORY, legal_id)
        assert len(items) == 1

    async def test_get_active(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        # Also add a settled item
        settled = valid_hedged_item.deactivate("admin", "Settled")
        await HedgedItemRepository.save(settled, legal_id)
        active_items = await HedgedItemRepository.get_active(legal_id)
        assert len(active_items) == 1
        assert active_items[0].is_active is True

    async def test_get_all(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        all_items = await HedgedItemRepository.get_all(legal_id)
        assert len(all_items) == 1

    async def test_delete(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        await HedgedItemRepository.delete(valid_hedged_item.id, legal_id)
        retrieved = await HedgedItemRepository.get_by_id(valid_hedged_item.id, legal_id)
        assert retrieved is None

    async def test_clear(self, valid_hedged_item):
        legal_id = valid_hedged_item.legal_entity_id
        await HedgedItemRepository.save(valid_hedged_item, legal_id)
        await HedgedItemRepository.clear(legal_id)
        all_items = await HedgedItemRepository.get_all(legal_id)
        assert len(all_items) == 0