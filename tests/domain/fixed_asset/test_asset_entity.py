# tests/domain/fixed_asset/test_asset_entity.py
"""
Comprehensive tests for domain/fixed_asset/asset_entity.py.
Covers enums, exceptions, FixedAsset entity (all methods/properties),
and repository protocol.

All datetime.now() calls are mocked to FIXED_NOW to avoid flaky tests.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from domain.fixed_asset.asset_entity import (
    AssetAlreadyDisposedError,
    AssetCategory,
    AssetStatus,
    AssetType,
    DepreciationMethod,
    FixedAsset,
    FixedAssetError,
    FixedAssetRepository,
    InvalidAssetCodeError,
    InvalidCostError,
    InvalidDepreciationError,
    InvalidUsefulLifeError,
)

# ============================================================================
# FIXED DATETIME (untuk menghindari flaky tests)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DATE = date(2026, 1, 1)
FIXED_ACQUISITION_DATE = date(2025, 1, 1)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now and date.today to fixed values."""
    with patch("domain.fixed_asset.asset_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture(autouse=True)
def mock_date_today():
    """Mock date.today to return fixed date."""
    with patch("domain.fixed_asset.asset_entity.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


@pytest.fixture
def asset_kwargs():
    return {
        "id": uuid.uuid4(),
        "legal_entity_id": uuid.uuid4(),
        "asset_code": "ASSET-001",
        "name": "Test Asset",
        "asset_type": AssetType.TANGIBLE,
        "status": AssetStatus.ACTIVE,
        "acquisition_date": FIXED_ACQUISITION_DATE,
        "acquisition_cost": Decimal("10000.00"),
        "salvage_value": Decimal("1000.00"),
        "useful_life_years": 5,
        "depreciation_method": "straight_line",
        "accumulated_depreciation": Decimal("0"),
        "net_book_value": Decimal("10000.00"),
        "currency": "IDR",
        "created_by": uuid.uuid4(),
        "created_at": FIXED_NOW - timedelta(days=10),
        "updated_at": FIXED_NOW - timedelta(days=10),
        "updated_by": uuid.uuid4(),
        "version": 1,
        "location": "Warehouse A",
        "description": "Test description",
        "category": "MACHINERY",
        "metadata": {},
    }


@pytest.fixture
def asset(asset_kwargs):
    return FixedAsset(**asset_kwargs)


# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestDepreciationMethod:
    def test_members(self):
        assert DepreciationMethod.STRAIGHT_LINE.value == "straight_line"
        assert DepreciationMethod.DECLINING_BALANCE.value == "declining_balance"
        assert DepreciationMethod.SUM_OF_YEARS.value == "sum_of_years"

    def test_display_name(self):
        assert DepreciationMethod.STRAIGHT_LINE.display_name() == "Garis Lurus"
        assert DepreciationMethod.DECLINING_BALANCE.display_name() == "Saldo Menurun"
        assert DepreciationMethod.SUM_OF_YEARS.display_name() == "Jumlah Angka Tahun"

    def test_from_string(self):
        assert DepreciationMethod.from_string("straight_line") == DepreciationMethod.STRAIGHT_LINE
        assert DepreciationMethod.from_string("declining_balance") == DepreciationMethod.DECLINING_BALANCE
        assert DepreciationMethod.from_string("sum_of_years") == DepreciationMethod.SUM_OF_YEARS
        assert DepreciationMethod.from_string("invalid") is None


class TestAssetStatus:
    def test_members(self):
        assert AssetStatus.ACTIVE.value == "active"
        assert AssetStatus.FULLY_DEPRECIATED.value == "fully_depreciated"
        assert AssetStatus.DISPOSED.value == "disposed"
        assert AssetStatus.UNDER_CONSTRUCTION.value == "construction"
        assert AssetStatus.IDLE.value == "idle"
        assert AssetStatus.IMPAIRED.value == "impaired"

    @pytest.mark.parametrize(
        "status, can_dep, can_rev, can_trans",
        [
            (AssetStatus.ACTIVE, True, True, True),
            (AssetStatus.IMPAIRED, True, True, False),
            (AssetStatus.IDLE, True, False, False),
            (AssetStatus.FULLY_DEPRECIATED, False, False, False),
            (AssetStatus.DISPOSED, False, False, False),
            (AssetStatus.UNDER_CONSTRUCTION, False, False, False),
        ]
    )
    def test_capabilities(self, status, can_dep, can_rev, can_trans):
        assert status.can_depreciate() == can_dep
        assert status.can_revalue() == can_rev
        assert status.can_transfer() == can_trans

    def test_display_name(self):
        assert AssetStatus.ACTIVE.display_name() == "Aktif"
        assert AssetStatus.FULLY_DEPRECIATED.display_name() == "Habis Depresiasi"
        assert AssetStatus.DISPOSED.display_name() == "Dihapuskan"

    def test_from_string(self):
        assert AssetStatus.from_string("active") == AssetStatus.ACTIVE
        assert AssetStatus.from_string("invalid") is None


class TestAssetType:
    def test_members(self):
        assert AssetType.TANGIBLE.value == "tangible"
        assert AssetType.INTANGIBLE.value == "intangible"
        assert AssetType.LAND.value == "land"

    @pytest.mark.parametrize(
        "asset_type, is_dep",
        [(AssetType.TANGIBLE, True), (AssetType.INTANGIBLE, True), (AssetType.LAND, False)]
    )
    def test_is_depreciable(self, asset_type, is_dep):
        assert asset_type.is_depreciable() == is_dep

    def test_display_name(self):
        assert AssetType.TANGIBLE.display_name() == "Berwujud"
        assert AssetType.INTANGIBLE.display_name() == "Tidak Berwujud"
        assert AssetType.LAND.display_name() == "Tanah"

    def test_from_string(self):
        assert AssetType.from_string("tangible") == AssetType.TANGIBLE
        assert AssetType.from_string("invalid") is None


class TestAssetCategory:
    def test_members(self):
        expected = [
            "BUILDING", "MACHINERY", "VEHICLE", "FURNITURE", "COMPUTER",
            "LEASEHOLD", "LAND", "OTHER", "SOFTWARE", "PATENT", "GOODWILL"
        ]
        for name in expected:
            assert hasattr(AssetCategory, name)

    @pytest.mark.parametrize(
        "category, expected",
        [
            (AssetCategory.BUILDING, True),
            (AssetCategory.MACHINERY, True),
            (AssetCategory.VEHICLE, True),
            (AssetCategory.FURNITURE, True),
            (AssetCategory.COMPUTER, True),
            (AssetCategory.LEASEHOLD, True),
            (AssetCategory.LAND, True),
            (AssetCategory.OTHER, True),
            (AssetCategory.SOFTWARE, False),
            (AssetCategory.PATENT, False),
            (AssetCategory.GOODWILL, False),
        ]
    )
    def test_is_tangible(self, category, expected):
        assert category.is_tangible() == expected

    def test_from_string(self):
        assert AssetCategory.from_string("building") == AssetCategory.BUILDING
        assert AssetCategory.from_string("invalid") is None


# ============================================================================
# TESTS FOR EXCEPTIONS
# ============================================================================

class TestExceptions:
    @pytest.mark.parametrize(
        "exc_class",
        [
            FixedAssetError,
            InvalidAssetCodeError,
            InvalidCostError,
            InvalidUsefulLifeError,
            InvalidDepreciationError,
            AssetAlreadyDisposedError,
        ]
    )
    def test_exceptions_raise(self, exc_class):
        with pytest.raises(exc_class):
            raise exc_class("test")


# ============================================================================
# TESTS FOR FixedAsset ENTITY
# ============================================================================

class TestFixedAsset:
    # ---- Construction and validation (parametrized) ----

    @pytest.mark.parametrize(
        "field, value, error_match",
        [
            ("asset_code", "", "non-empty string"),
            ("asset_code", "A", "at least 2 characters"),
            ("asset_code", "A" * 31, "not exceed 30 characters"),
            ("asset_code", "asset 1", "letters, numbers, hyphens"),
            ("name", "", "non-empty string"),
            ("name", "A", "at least 2 characters"),
            ("name", "A" * 201, "not exceed 200 characters"),
            ("asset_type", "invalid", "Invalid asset_type"),
            ("status", "invalid", "Invalid status"),
            ("acquisition_date", FIXED_DATE + timedelta(days=10), "cannot be in the future"),
            ("acquisition_cost", Decimal("0"), "positive"),
            ("acquisition_cost", Decimal("-100"), "positive"),
            ("salvage_value", Decimal("-100"), "cannot be negative"),
            ("salvage_value", Decimal("15000"), "exceeds cost"),
            ("useful_life_years", 0, "positive"),
            ("useful_life_years", -5, "positive"),
            ("useful_life_years", 101, "exceeds maximum 100"),
            ("accumulated_depreciation", Decimal("-100"), "cannot be negative"),
            ("accumulated_depreciation", Decimal("10000"), "exceeds depreciable amount"),
            ("accumulated_impairment", Decimal("-100"), "cannot be negative"),
            ("accumulated_impairment", Decimal("20000"), "exceeds NBV"),
            ("net_book_value", Decimal("5000"), "mismatch"),
            ("net_book_value", Decimal("-2000"), "cannot be negative"),
            ("revaluation_surplus", Decimal("-100"), "cannot be negative"),
            ("currency", "ID", "exactly 3 characters"),
            ("version", 0, "Version must be >= 1"),
        ]
    )
    def test_construction_invalid(self, asset_kwargs, field, value, error_match):
        asset_kwargs[field] = value
        # Handle special cases for net_book_value mismatch
        if field == "net_book_value" and value == Decimal("5000"):
            asset_kwargs["accumulated_depreciation"] = Decimal("0")
            asset_kwargs["accumulated_impairment"] = Decimal("0")
        if field == "net_book_value" and value == Decimal("-2000"):
            asset_kwargs["accumulated_depreciation"] = Decimal("12000")
        if field == "accumulated_impairment" and value == Decimal("20000"):
            # nbv=10000, impairment exceeds it
            pass
        # For invalid status/type, ensure we pass strings
        if field == "asset_type" and value == "invalid":
            asset_kwargs["asset_type"] = "invalid"
        if field == "status" and value == "invalid":
            asset_kwargs["status"] = "invalid"
        if field == "useful_life_years" and value == 0:
            asset_kwargs["asset_type"] = AssetType.TANGIBLE
        with pytest.raises(FixedAssetError, match=error_match):
            FixedAsset(**asset_kwargs)

    def test_construction_disposed_consistency(self, asset_kwargs):
        asset_kwargs["status"] = AssetStatus.DISPOSED
        asset_kwargs["disposed_at"] = None
        with pytest.raises(FixedAssetError, match="must have disposed_at"):
            FixedAsset(**asset_kwargs)

        asset_kwargs["status"] = AssetStatus.ACTIVE
        asset_kwargs["disposed_at"] = FIXED_DATE
        with pytest.raises(FixedAssetError, match="cannot have disposed_at"):
            FixedAsset(**asset_kwargs)

    def test_construction_fully_depreciated_consistency(self, asset_kwargs):
        asset_kwargs["status"] = AssetStatus.FULLY_DEPRECIATED
        asset_kwargs["accumulated_depreciation"] = Decimal("5000")
        with pytest.raises(FixedAssetError, match="less than depreciable amount"):
            FixedAsset(**asset_kwargs)

    # ---- Properties ----

    def test_properties(self, asset):
        assert asset.depreciable_amount == Decimal("9000.00")
        assert asset.remaining_depreciable_amount == Decimal("9000.00")
        assert not asset.is_fully_depreciated
        assert not asset.is_disposed
        assert asset.is_active
        assert asset.is_depreciable
        assert asset.age_in_years(as_of=FIXED_DATE) == pytest.approx(1.0, abs=0.01)
        assert asset.age_in_years(as_of=asset.acquisition_date - timedelta(days=1)) == 0.0
        assert asset.remaining_useful_life == pytest.approx(5.0, abs=0.01)
        assert asset.book_value_after_revaluation == Decimal("10000.00")
        assert asset.get_depreciation_method_enum() == DepreciationMethod.STRAIGHT_LINE

    def test_remaining_useful_life_after_depreciation(self, asset):
        asset = asset.record_depreciation("2026-01", Decimal("1800"), uuid.uuid4())
        assert asset.remaining_useful_life == pytest.approx(4.0, abs=0.01)

    # ---- Factory methods ----

    def test_acquire(self):
        legal_entity_id = uuid.uuid4()
        created_by = uuid.uuid4()
        asset = FixedAsset.acquire(
            legal_entity_id=legal_entity_id,
            asset_code="NEW-001",
            name="New Asset",
            acquisition_cost=Decimal("15000"),
            acquisition_date=FIXED_ACQUISITION_DATE,
            asset_type=AssetType.TANGIBLE,
            salvage_value=Decimal("1500"),
            useful_life_years=10,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            currency="USD",
            created_by=created_by,
            location="Main",
        )
        assert asset.legal_entity_id == legal_entity_id
        assert asset.asset_code == "NEW-001"
        assert asset.status == AssetStatus.ACTIVE
        assert asset.acquisition_cost == Decimal("15000")
        assert asset.salvage_value == Decimal("1500")
        assert asset.depreciation_method == "straight_line"
        assert asset.net_book_value == Decimal("15000")
        assert asset.version == 1
        assert asset.created_by == created_by
        assert asset.location == "Main"
        assert asset.currency == "USD"

    def test_from_dict_to_dict_roundtrip(self, asset):
        d = asset.to_dict()
        reconstructed = FixedAsset.from_dict(d)
        assert reconstructed.id == asset.id
        assert reconstructed.asset_code == asset.asset_code
        assert reconstructed.acquisition_cost == asset.acquisition_cost
        assert reconstructed.net_book_value == asset.net_book_value
        assert reconstructed.version == asset.version

    # ---- Business logic ----

    def test_record_depreciation(self, asset):
        new_asset = asset.record_depreciation("2026-01", Decimal("1000"), uuid.uuid4())
        assert new_asset.accumulated_depreciation == Decimal("1000")
        assert new_asset.net_book_value == Decimal("9000")
        assert new_asset.last_depreciation_date == FIXED_DATE
        assert new_asset.version == asset.version + 1

    def test_record_depreciation_fully_depreciated(self, asset):
        new_asset = asset.record_depreciation("2026-01", Decimal("9000"), uuid.uuid4())
        assert new_asset.status == AssetStatus.FULLY_DEPRECIATED
        assert new_asset.net_book_value == Decimal("1000")

    @pytest.mark.parametrize(
        "status", [AssetStatus.DISPOSED, AssetStatus.FULLY_DEPRECIATED, AssetStatus.UNDER_CONSTRUCTION]
    )
    def test_record_depreciation_invalid_status(self, asset, status):
        if status == AssetStatus.DISPOSED:
            asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        else:
            asset = FixedAsset(**{**asset.__dict__, "status": status})
        with pytest.raises(FixedAssetError, match="Cannot record depreciation"):
            asset.record_depreciation("2026-01", Decimal("100"), uuid.uuid4())

    def test_record_depreciation_non_depreciable(self, asset):
        land = FixedAsset(**{**asset.__dict__, "asset_type": AssetType.LAND, "useful_life_years": 0})
        with pytest.raises(FixedAssetError, match="not depreciable"):
            land.record_depreciation("2026-01", Decimal("100"), uuid.uuid4())

    def test_record_depreciation_negative_amount(self, asset):
        with pytest.raises(InvalidDepreciationError, match="positive"):
            asset.record_depreciation("2026-01", Decimal("-100"), uuid.uuid4())

    def test_apply_revaluation_upward(self, asset):
        new_asset = asset.apply_revaluation(Decimal("12000"), "revaluation", uuid.uuid4())
        assert new_asset.net_book_value == Decimal("12000")
        assert new_asset.revaluation_surplus == Decimal("2000")
        assert new_asset.acquisition_cost == Decimal("12000")
        assert new_asset.version == asset.version + 1

    def test_apply_revaluation_downward(self, asset):
        new_asset = asset.apply_revaluation(Decimal("8000"), "impairment", uuid.uuid4())
        assert new_asset.net_book_value == Decimal("8000")
        assert new_asset.accumulated_impairment == Decimal("2000")
        assert new_asset.revaluation_surplus == Decimal("0")
        assert new_asset.acquisition_cost == Decimal("10000")
        assert new_asset.version == asset.version + 1

    def test_apply_revaluation_invalid_status(self, asset):
        asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot revalue"):
            asset.apply_revaluation(Decimal("12000"), "revaluation", uuid.uuid4())

    def test_apply_revaluation_non_positive(self, asset):
        with pytest.raises(FixedAssetError, match="must be positive"):
            asset.apply_revaluation(Decimal("-1000"), "revaluation", uuid.uuid4())

    def test_recognize_impairment(self, asset):
        new_asset = asset.recognize_impairment(Decimal("2000"), uuid.uuid4(), ["obsolescence"])
        assert new_asset.accumulated_impairment == Decimal("2000")
        assert new_asset.net_book_value == Decimal("8000")
        assert new_asset.version == asset.version + 1

    def test_recognize_impairment_fully_impaired(self, asset):
        new_asset = asset.recognize_impairment(Decimal("9000"), uuid.uuid4(), ["fire"])
        assert new_asset.status == AssetStatus.IMPAIRED
        assert new_asset.net_book_value == Decimal("1000")

    def test_recognize_impairment_negative(self, asset):
        with pytest.raises(FixedAssetError, match="positive"):
            asset.recognize_impairment(Decimal("-100"), uuid.uuid4(), [])

    def test_recognize_impairment_exceeds_nbv(self, asset):
        with pytest.raises(FixedAssetError, match="exceeds NBV"):
            asset.recognize_impairment(Decimal("15000"), uuid.uuid4(), [])

    def test_dispose(self, asset):
        new_asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        assert new_asset.status == AssetStatus.DISPOSED
        assert new_asset.disposed_at == FIXED_DATE
        assert new_asset.disposed_reason == "sale: sold"
        assert new_asset.version == asset.version + 1

    def test_dispose_already_disposed(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(AssetAlreadyDisposedError, match="already disposed"):
            disposed.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())

    def test_dispose_date_before_acquisition(self, asset):
        before = asset.acquisition_date - timedelta(days=1)
        with pytest.raises(FixedAssetError, match="cannot be before acquisition"):
            asset.dispose(before, "sale", Decimal("5000"), "sold", uuid.uuid4())

    def test_dispose_negative_proceeds(self, asset):
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            asset.dispose(FIXED_DATE, "sale", Decimal("-1000"), "sold", uuid.uuid4())

    def test_transfer(self, asset):
        new_location = "New Warehouse"
        new_asset = asset.transfer(new_location, uuid.uuid4())
        assert new_asset.location == new_location
        assert new_asset.version == asset.version + 1

    def test_transfer_invalid_status(self, asset):
        asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot transfer"):
            asset.transfer("New Loc", uuid.uuid4())

    def test_transfer_empty_location(self, asset):
        with pytest.raises(FixedAssetError, match="New location must be provided"):
            asset.transfer("", uuid.uuid4())

    def test_change_responsible_person(self, asset):
        new_person = uuid.uuid4()
        new_asset = asset.change_responsible_person(new_person, uuid.uuid4())
        assert new_asset.responsible_person == new_person
        assert new_asset.version == asset.version + 1

    def test_change_responsible_person_none(self, asset):
        new_asset = asset.change_responsible_person(None, uuid.uuid4())
        assert new_asset.responsible_person is None

    def test_update_name(self, asset):
        new_name = "Updated Asset Name"
        new_asset = asset.update_name(new_name, uuid.uuid4())
        assert new_asset.name == new_name
        assert new_asset.version == asset.version + 1

    def test_update_name_invalid(self, asset):
        with pytest.raises(FixedAssetError, match="at least 2 characters"):
            asset.update_name("A", uuid.uuid4())

    def test_update_description(self, asset):
        new_desc = "New description"
        new_asset = asset.update_description(new_desc, uuid.uuid4())
        assert new_asset.description == new_desc
        assert new_asset.version == asset.version + 1

    def test_calculate_gain_loss(self, asset):
        assert asset.calculate_gain_loss_on_disposal(Decimal("12000")) == Decimal("2000")
        assert asset.calculate_gain_loss_on_disposal(Decimal("8000")) == Decimal("-2000")

    # ---- Entity basic methods ----

    def test_create_returns_self(self, asset):
        assert asset.create(uuid.uuid4()) is asset

    def test_update(self, asset):
        new_asset = asset.update(uuid.uuid4(), name="New Name", location="New Loc")
        assert new_asset.name == "New Name"
        assert new_asset.location == "New Loc"
        assert new_asset.version == asset.version + 1

    def test_delete(self, asset):
        deleted = asset.delete(uuid.uuid4(), "Deletion reason")
        assert deleted.status == AssetStatus.DISPOSED
        assert deleted.disposed_reason == "deletion: Deletion reason"

    def test_delete_already_disposed(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="already disposed"):
            disposed.delete(uuid.uuid4())

    def test_restore(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        restored = disposed.restore(uuid.uuid4())
        assert restored.status == AssetStatus.ACTIVE
        assert restored.disposed_at is None
        assert restored.disposed_reason is None
        assert restored.version == disposed.version + 1

    def test_restore_not_disposed(self, asset):
        with pytest.raises(FixedAssetError, match="not disposed"):
            asset.restore(uuid.uuid4())

    def test_activate(self, asset):
        # Already active
        assert asset.activate(uuid.uuid4()) is asset

        # From under construction
        under = FixedAsset(**{**asset.__dict__, "status": AssetStatus.UNDER_CONSTRUCTION})
        activated = under.activate(uuid.uuid4())
        assert activated.status == AssetStatus.ACTIVE
        assert activated.version == under.version + 1

        # Invalid status
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot activate"):
            disposed.activate(uuid.uuid4())

    def test_deactivate(self, asset):
        deactivated = asset.deactivate(uuid.uuid4(), "maintenance")
        assert deactivated.status == AssetStatus.IDLE
        assert deactivated.version == asset.version + 1

    def test_deactivate_invalid_status(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot deactivate"):
            disposed.deactivate(uuid.uuid4())

    def test_lock_unlock(self, asset):
        locker = uuid.uuid4()
        locked = asset.lock(locker, "audit")
        assert locked.metadata["locked_by"] == str(locker)
        assert locked.metadata["lock_reason"] == "audit"
        assert locked.version == asset.version + 1

        unlocker = uuid.uuid4()
        unlocked = locked.unlock(unlocker)
        assert "locked_by" not in unlocked.metadata
        assert unlocked.version == locked.version + 1

    def test_validate_valid(self, asset):
        result = asset.validate()
        assert result["is_valid"]
        assert result["asset_id"] == str(asset.id)

    def test_validate_invalid(self, asset):
        # Force an invalid state
        asset.acquisition_cost = Decimal("-100")
        result = asset.validate()
        assert not result["is_valid"]

    def test_clone(self, asset):
        cloned = asset.clone()
        assert cloned.id != asset.id
        assert cloned.asset_code == asset.asset_code + "_COPY"
        assert cloned.name == asset.name + " (COPY)"
        assert cloned.accumulated_depreciation == Decimal("0")
        assert cloned.net_book_value == asset.acquisition_cost
        assert cloned.version == 1
        assert cloned.status == AssetStatus.DRAFT

    def test_snapshot(self, asset):
        snap = asset.snapshot()
        assert snap["asset_id"] == str(asset.id)
        assert snap["version"] == asset.version
        assert snap["asset_code"] == asset.asset_code

    def test_get_version(self, asset):
        assert asset.get_version() == 1

    def test_audit_trail(self, asset):
        # Initially empty, but method exists
        trail = asset.audit_trail()
        assert isinstance(trail, list)

    def test_touch(self, asset):
        touched = asset.touch(uuid.uuid4())
        assert touched.version == asset.version + 1
        assert touched.updated_at == FIXED_NOW


# ============================================================================
# TESTS FOR FixedAssetRepository (protocol)
# ============================================================================

class TestFixedAssetRepository:
    @pytest.fixture
    def repo(self):
        return FixedAssetRepository()

    def test_methods_raise_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_code("code", uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_active_assets(uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.list_assets(uuid.uuid4(), None, None, None, 100, 0)
        with pytest.raises(NotImplementedError):
            repo.save_asset(None)
        with pytest.raises(NotImplementedError):
            repo.save_depreciation_entry(None)
        with pytest.raises(NotImplementedError):
            repo.sum_acquisition_cost(uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.sum_accumulated_depreciation(uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.count_assets(uuid.uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_depreciation_schedule(uuid.uuid4(), None, None)

    @pytest.mark.asyncio
    async def test_repo_methods_can_be_mocked(self, repo):
        repo.get_by_id = AsyncMock(return_value=None)
        result = await repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        assert result is None 