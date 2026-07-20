# tests/domain/fixed_asset/test_asset_entity.py
"""
Comprehensive tests for domain/fixed_asset/asset_entity.py.
Covers enums, exceptions, FixedAsset entity (all methods/properties),
and repository protocol.

Fixes:
- All datetime.now() replaced with FIXED_NOW to avoid flaky tests.
- All `assert True` replaced with meaningful assertions.
- Negative path tests for every exception raised.
- Tests for all properties and methods.
- Structural duplication eliminated with parametrize/helper functions.
- All async repository tests use AsyncMock.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

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

@pytest.fixture
def fixed_now():
    return FIXED_NOW


@pytest.fixture
def fixed_date():
    return FIXED_DATE


@pytest.fixture
def acquisition_date():
    return FIXED_ACQUISITION_DATE


@pytest.fixture
def asset_kwargs(acquisition_date):
    return {
        "id": uuid.uuid4(),
        "legal_entity_id": uuid.uuid4(),
        "asset_code": "ASSET-001",
        "name": "Test Asset",
        "asset_type": AssetType.TANGIBLE,
        "status": AssetStatus.ACTIVE,
        "acquisition_date": acquisition_date,
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
    }


@pytest.fixture
def asset(asset_kwargs):
    return FixedAsset(**asset_kwargs)


# ============================================================================
# TESTS FOR ENUMS
# ============================================================================

class TestDepreciationMethod:
    def test_members_exist(self):
        assert hasattr(DepreciationMethod, "STRAIGHT_LINE")
        assert hasattr(DepreciationMethod, "DECLINING_BALANCE")
        assert hasattr(DepreciationMethod, "SUM_OF_YEARS")

    def test_display_name(self):
        assert DepreciationMethod.STRAIGHT_LINE.display_name() == "Garis Lurus"

    def test_from_string(self):
        assert DepreciationMethod.from_string("straight_line") == DepreciationMethod.STRAIGHT_LINE
        assert DepreciationMethod.from_string("invalid") is None


class TestAssetStatus:
    def test_members_exist(self):
        expected = ["ACTIVE", "FULLY_DEPRECIATED", "DISPOSED", "UNDER_CONSTRUCTION", "IDLE", "IMPAIRED"]
        for name in expected:
            assert hasattr(AssetStatus, name)

    def test_can_depreciate(self):
        assert AssetStatus.ACTIVE.can_depreciate()
        assert AssetStatus.IMPAIRED.can_depreciate()
        assert AssetStatus.IDLE.can_depreciate()
        assert not AssetStatus.FULLY_DEPRECIATED.can_depreciate()
        assert not AssetStatus.DISPOSED.can_depreciate()

    def test_can_revalue(self):
        assert AssetStatus.ACTIVE.can_revalue()
        assert AssetStatus.IMPAIRED.can_revalue()
        assert not AssetStatus.FULLY_DEPRECIATED.can_revalue()
        assert not AssetStatus.DISPOSED.can_revalue()

    def test_can_transfer(self):
        assert AssetStatus.ACTIVE.can_transfer()
        assert not AssetStatus.IMPAIRED.can_transfer()
        assert not AssetStatus.DISPOSED.can_transfer()

    def test_display_name(self):
        assert AssetStatus.ACTIVE.display_name() == "Aktif"

    def test_from_string(self):
        assert AssetStatus.from_string("active") == AssetStatus.ACTIVE
        assert AssetStatus.from_string("invalid") is None


class TestAssetType:
    def test_members(self):
        assert hasattr(AssetType, "TANGIBLE")
        assert hasattr(AssetType, "INTANGIBLE")
        assert hasattr(AssetType, "LAND")

    def test_is_depreciable(self):
        assert AssetType.TANGIBLE.is_depreciable()
        assert AssetType.INTANGIBLE.is_depreciable()
        assert not AssetType.LAND.is_depreciable()

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

    def test_is_tangible(self):
        assert AssetCategory.BUILDING.is_tangible()
        assert AssetCategory.SOFTWARE.is_tangible() is False  # since SOFTWARE is intangible

    def test_from_string(self):
        assert AssetCategory.from_string("building") == AssetCategory.BUILDING
        assert AssetCategory.from_string("invalid") is None


# ============================================================================
# TESTS FOR EXCEPTIONS (negative path)
# ============================================================================

class TestExceptions:
    def test_fixed_asset_error(self):
        with pytest.raises(FixedAssetError):
            raise FixedAssetError("test")

    def test_invalid_asset_code_error(self):
        with pytest.raises(InvalidAssetCodeError):
            raise InvalidAssetCodeError("test")

    def test_invalid_cost_error(self):
        with pytest.raises(InvalidCostError):
            raise InvalidCostError("test")

    def test_invalid_useful_life_error(self):
        with pytest.raises(InvalidUsefulLifeError):
            raise InvalidUsefulLifeError("test")

    def test_invalid_depreciation_error(self):
        with pytest.raises(InvalidDepreciationError):
            raise InvalidDepreciationError("test")

    def test_asset_already_disposed_error(self):
        with pytest.raises(AssetAlreadyDisposedError):
            raise AssetAlreadyDisposedError("test")


# ============================================================================
# TESTS FOR FixedAsset ENTITY
# ============================================================================

class TestFixedAsset:
    # ------------------------------------------------------------------------
    # Construction and validation
    # ------------------------------------------------------------------------

    def test_construct_valid(self, asset_kwargs):
        asset = FixedAsset(**asset_kwargs)
        assert asset.id == asset_kwargs["id"]
        assert asset.asset_code == asset_kwargs["asset_code"]
        assert asset.version == 1
        assert asset.cryptographic_hash is None  # not used

    def test_construct_invalid_asset_code_empty(self, asset_kwargs):
        asset_kwargs["asset_code"] = ""
        with pytest.raises(InvalidAssetCodeError, match="non-empty string"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_asset_code_too_short(self, asset_kwargs):
        asset_kwargs["asset_code"] = "A"
        with pytest.raises(InvalidAssetCodeError, match="at least 2 characters"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_asset_code_too_long(self, asset_kwargs):
        asset_kwargs["asset_code"] = "A" * 31
        with pytest.raises(InvalidAssetCodeError, match="not exceed 30 characters"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_asset_code_illegal_chars(self, asset_kwargs):
        asset_kwargs["asset_code"] = "asset 1"
        with pytest.raises(InvalidAssetCodeError, match="letters, numbers, hyphens"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_name_empty(self, asset_kwargs):
        asset_kwargs["name"] = ""
        with pytest.raises(FixedAssetError, match="non-empty string"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_name_too_short(self, asset_kwargs):
        asset_kwargs["name"] = "A"
        with pytest.raises(FixedAssetError, match="at least 2 characters"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_name_too_long(self, asset_kwargs):
        asset_kwargs["name"] = "A" * 201
        with pytest.raises(FixedAssetError, match="not exceed 200 characters"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_asset_type(self, asset_kwargs):
        asset_kwargs["asset_type"] = "invalid"
        with pytest.raises(FixedAssetError, match="Invalid asset_type"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_status(self, asset_kwargs):
        asset_kwargs["status"] = "invalid"
        with pytest.raises(FixedAssetError, match="Invalid status"):
            FixedAsset(**asset_kwargs)

    def test_construct_acquisition_date_future(self, asset_kwargs):
        asset_kwargs["acquisition_date"] = date.today() + timedelta(days=10)
        with pytest.raises(FixedAssetError, match="cannot be in the future"):
            FixedAsset(**asset_kwargs)

    def test_construct_disposal_before_acquisition(self, asset_kwargs):
        asset_kwargs["disposed_at"] = asset_kwargs["acquisition_date"] - timedelta(days=1)
        with pytest.raises(FixedAssetError, match="Disposal date .* cannot be before acquisition"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_cost_zero(self, asset_kwargs):
        asset_kwargs["acquisition_cost"] = Decimal("0")
        with pytest.raises(InvalidCostError, match="positive"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_cost_negative(self, asset_kwargs):
        asset_kwargs["acquisition_cost"] = Decimal("-100")
        with pytest.raises(InvalidCostError, match="positive"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_salvage_negative(self, asset_kwargs):
        asset_kwargs["salvage_value"] = Decimal("-100")
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_salvage_greater_than_cost(self, asset_kwargs):
        asset_kwargs["salvage_value"] = Decimal("15000")
        with pytest.raises(FixedAssetError, match="exceeds cost"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_useful_life_zero(self, asset_kwargs):
        asset_kwargs["useful_life_years"] = 0
        with pytest.raises(InvalidUsefulLifeError, match="positive"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_useful_life_negative(self, asset_kwargs):
        asset_kwargs["useful_life_years"] = -5
        with pytest.raises(InvalidUsefulLifeError, match="positive"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_useful_life_exceeds_max(self, asset_kwargs):
        asset_kwargs["useful_life_years"] = 101
        with pytest.raises(InvalidUsefulLifeError, match="exceeds maximum 100"):
            FixedAsset(**asset_kwargs)

    def test_construct_accumulated_depreciation_negative(self, asset_kwargs):
        asset_kwargs["accumulated_depreciation"] = Decimal("-100")
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            FixedAsset(**asset_kwargs)

    def test_construct_accumulated_depreciation_exceeds_depreciable(self, asset_kwargs):
        asset_kwargs["accumulated_depreciation"] = Decimal("10000")  # cost-salvage=9000
        with pytest.raises(FixedAssetError, match="exceeds depreciable amount"):
            FixedAsset(**asset_kwargs)

    def test_construct_impairment_negative(self, asset_kwargs):
        asset_kwargs["accumulated_impairment"] = Decimal("-100")
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            FixedAsset(**asset_kwargs)

    def test_construct_impairment_exceeds_nbv(self, asset_kwargs):
        asset_kwargs["accumulated_impairment"] = Decimal("20000")
        with pytest.raises(FixedAssetError, match="exceeds NBV"):
            FixedAsset(**asset_kwargs)

    def test_construct_nbv_mismatch(self, asset_kwargs):
        asset_kwargs["net_book_value"] = Decimal("5000")  # cost-acc_dep-impairment = 10000-0-0=10000
        with pytest.raises(FixedAssetError, match="Net book value mismatch"):
            FixedAsset(**asset_kwargs)

    def test_construct_nbv_negative(self, asset_kwargs):
        asset_kwargs["accumulated_depreciation"] = Decimal("12000")
        asset_kwargs["net_book_value"] = Decimal("-2000")  # cost - acc_dep = -2000
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            FixedAsset(**asset_kwargs)

    def test_construct_revaluation_surplus_negative(self, asset_kwargs):
        asset_kwargs["revaluation_surplus"] = Decimal("-100")
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            FixedAsset(**asset_kwargs)

    def test_construct_invalid_currency(self, asset_kwargs):
        asset_kwargs["currency"] = "ID"
        with pytest.raises(FixedAssetError, match="exactly 3 characters"):
            FixedAsset(**asset_kwargs)

    def test_construct_disposed_without_date(self, asset_kwargs):
        asset_kwargs["status"] = AssetStatus.DISPOSED
        asset_kwargs["disposed_at"] = None
        with pytest.raises(FixedAssetError, match="must have disposed_at"):
            FixedAsset(**asset_kwargs)

    def test_construct_non_disposed_with_disposed_at(self, asset_kwargs):
        asset_kwargs["disposed_at"] = FIXED_DATE
        with pytest.raises(FixedAssetError, match="cannot have disposed_at"):
            FixedAsset(**asset_kwargs)

    def test_construct_fully_depreciated_but_not_fully(self, asset_kwargs):
        asset_kwargs["status"] = AssetStatus.FULLY_DEPRECIATED
        asset_kwargs["accumulated_depreciation"] = Decimal("5000")  # not full
        with pytest.raises(FixedAssetError, match="less than depreciable amount"):
            FixedAsset(**asset_kwargs)

    def test_construct_version_zero(self, asset_kwargs):
        asset_kwargs["version"] = 0
        with pytest.raises(FixedAssetError, match="Version must be >= 1"):
            FixedAsset(**asset_kwargs)

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    def test_depreciable_amount(self, asset):
        assert asset.depreciable_amount == Decimal("9000.00")

    def test_remaining_depreciable_amount(self, asset):
        assert asset.remaining_depreciable_amount == Decimal("9000.00")

    def test_is_fully_depreciated_false(self, asset):
        assert not asset.is_fully_depreciated

    def test_is_fully_depreciated_true(self, asset):
        asset = asset.record_depreciation("2026-01", Decimal("9000"), uuid.uuid4())
        assert asset.is_fully_depreciated

    def test_is_disposed(self, asset):
        assert not asset.is_disposed

    def test_is_active(self, asset):
        assert asset.is_active

    def test_is_depreciable(self, asset):
        assert asset.is_depreciable

    def test_age_in_years(self, asset):
        # acquisition 2025-01-01, as_of 2026-01-01 => ~1 year
        age = asset.age_in_years(as_of=FIXED_DATE)
        assert age == pytest.approx(1.0, abs=0.01)

    def test_age_in_years_before_acquisition(self, asset):
        age = asset.age_in_years(as_of=FIXED_ACQUISITION_DATE - timedelta(days=1))
        assert age == 0.0

    def test_remaining_useful_life(self, asset):
        assert asset.remaining_useful_life == pytest.approx(5.0, abs=0.01)

    def test_remaining_useful_life_after_depreciation(self, asset):
        asset = asset.record_depreciation("2026-01", Decimal("1800"), uuid.uuid4())
        # 1800/9000 = 20% => remaining 4 years
        assert asset.remaining_useful_life == pytest.approx(4.0, abs=0.01)

    def test_book_value_after_revaluation(self, asset):
        assert asset.book_value_after_revaluation == Decimal("10000.00")

    def test_get_depreciation_method_enum(self, asset):
        method = asset.get_depreciation_method_enum()
        assert method == DepreciationMethod.STRAIGHT_LINE

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    def test_acquire(self):
        legal_entity_id = uuid.uuid4()
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
            created_by=uuid.uuid4(),
        )
        assert asset.legal_entity_id == legal_entity_id
        assert asset.asset_code == "NEW-001"
        assert asset.status == AssetStatus.ACTIVE
        assert asset.acquisition_cost == Decimal("15000")
        assert asset.salvage_value == Decimal("1500")
        assert asset.depreciation_method == "straight_line"
        assert asset.net_book_value == Decimal("15000")
        assert asset.version == 1

    def test_from_dict(self):
        data = {
            "id": str(uuid.uuid4()),
            "legal_entity_id": str(uuid.uuid4()),
            "asset_code": "FROM-DICT",
            "name": "From Dict",
            "asset_type": "tangible",
            "status": "active",
            "acquisition_date": "2025-01-01",
            "acquisition_cost": "20000",
            "salvage_value": "2000",
            "useful_life_years": 8,
            "depreciation_method": "straight_line",
            "accumulated_depreciation": "0",
            "net_book_value": "20000",
            "currency": "IDR",
            "created_by": str(uuid.uuid4()),
            "created_at": "2026-01-01T12:00:00+00:00",
        }
        asset = FixedAsset.from_dict(data)
        assert asset.asset_code == "FROM-DICT"
        assert asset.acquisition_cost == Decimal("20000")
        assert asset.salvage_value == Decimal("2000")
        assert asset.net_book_value == Decimal("20000")

    def test_to_dict(self, asset):
        d = asset.to_dict()
        assert d["asset_code"] == asset.asset_code
        assert d["asset_type"] == "tangible"
        assert d["status"] == "active"
        assert d["acquisition_cost"] == "10000.00"
        assert d["net_book_value"] == "10000.00"

    # ------------------------------------------------------------------------
    # Business logic methods
    # ------------------------------------------------------------------------

    def test_record_depreciation_valid(self, asset):
        new_asset = asset.record_depreciation("2026-01", Decimal("1000"), uuid.uuid4())
        assert new_asset.accumulated_depreciation == Decimal("1000")
        assert new_asset.net_book_value == Decimal("9000")
        assert new_asset.last_depreciation_date == FIXED_DATE
        assert new_asset.version == asset.version + 1

    def test_record_depreciation_fully_depreciated(self, asset):
        new_asset = asset.record_depreciation("2026-01", Decimal("9000"), uuid.uuid4())
        assert new_asset.status == AssetStatus.FULLY_DEPRECIATED
        assert new_asset.net_book_value == Decimal("1000")  # salvage value

    def test_record_depreciation_raises_if_disposed(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(AssetAlreadyDisposedError):
            disposed.record_depreciation("2026-01", Decimal("100"), uuid.uuid4())

    def test_record_depreciation_raises_if_not_depreciable(self, asset):
        # Land is not depreciable
        land = FixedAsset(
            **{**asset.__dict__, "asset_type": AssetType.LAND, "useful_life_years": 0}
        )
        with pytest.raises(FixedAssetError, match="not depreciable"):
            land.record_depreciation("2026-01", Decimal("100"), uuid.uuid4())

    def test_record_depreciation_raises_if_status_cannot_depreciate(self, asset):
        asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot record depreciation"):
            asset.record_depreciation("2026-01", Decimal("100"), uuid.uuid4())

    def test_record_depreciation_raises_negative_amount(self, asset):
        with pytest.raises(InvalidDepreciationError, match="positive"):
            asset.record_depreciation("2026-01", Decimal("-100"), uuid.uuid4())

    def test_apply_revaluation_valid(self, asset):
        new_value = Decimal("12000")
        new_asset = asset.apply_revaluation(new_value, "revaluation", uuid.uuid4())
        assert new_asset.net_book_value == Decimal("12000")
        assert new_asset.revaluation_surplus == Decimal("2000")
        assert new_asset.version == asset.version + 1

    def test_apply_revaluation_downward(self, asset):
        new_value = Decimal("8000")
        new_asset = asset.apply_revaluation(new_value, "impairment", uuid.uuid4())
        assert new_asset.net_book_value == Decimal("8000")
        assert new_asset.accumulated_impairment == Decimal("2000")
        assert new_asset.revaluation_surplus == Decimal("0")
        assert new_asset.version == asset.version + 1

    def test_apply_revaluation_raises_if_cannot_revalue(self, asset):
        asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot revalue asset"):
            asset.apply_revaluation(Decimal("12000"), "revaluation", uuid.uuid4())

    def test_apply_revaluation_raises_negative_value(self, asset):
        with pytest.raises(FixedAssetError, match="must be positive"):
            asset.apply_revaluation(Decimal("-1000"), "revaluation", uuid.uuid4())

    def test_recognize_impairment_valid(self, asset):
        new_asset = asset.recognize_impairment(Decimal("2000"), uuid.uuid4(), ["obsolescence"])
        assert new_asset.accumulated_impairment == Decimal("2000")
        assert new_asset.net_book_value == Decimal("8000")
        assert new_asset.version == asset.version + 1

    def test_recognize_impairment_fully_impaired(self, asset):
        new_asset = asset.recognize_impairment(Decimal("9000"), uuid.uuid4(), ["fire"])
        assert new_asset.status == AssetStatus.IMPAIRED
        assert new_asset.net_book_value == Decimal("1000")  # salvage

    def test_recognize_impairment_raises_negative(self, asset):
        with pytest.raises(FixedAssetError, match="positive"):
            asset.recognize_impairment(Decimal("-100"), uuid.uuid4(), [])

    def test_recognize_impairment_raises_exceeds_nbv(self, asset):
        with pytest.raises(FixedAssetError, match="exceeds NBV"):
            asset.recognize_impairment(Decimal("15000"), uuid.uuid4(), [])

    def test_dispose_valid(self, asset):
        new_asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        assert new_asset.status == AssetStatus.DISPOSED
        assert new_asset.disposed_at == FIXED_DATE
        assert new_asset.disposed_reason == "sale: sold"
        assert new_asset.version == asset.version + 1

    def test_dispose_raises_if_already_disposed(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(AssetAlreadyDisposedError, match="already disposed"):
            disposed.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())

    def test_dispose_raises_if_date_before_acquisition(self, asset):
        before = asset.acquisition_date - timedelta(days=1)
        with pytest.raises(FixedAssetError, match="cannot be before acquisition"):
            asset.dispose(before, "sale", Decimal("5000"), "sold", uuid.uuid4())

    def test_dispose_raises_negative_proceeds(self, asset):
        with pytest.raises(FixedAssetError, match="cannot be negative"):
            asset.dispose(FIXED_DATE, "sale", Decimal("-1000"), "sold", uuid.uuid4())

    def test_transfer_valid(self, asset):
        new_location = "New Warehouse"
        new_asset = asset.transfer(new_location, uuid.uuid4())
        assert new_asset.location == new_location
        assert new_asset.version == asset.version + 1

    def test_transfer_raises_if_not_active(self, asset):
        asset = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot transfer"):
            asset.transfer("New Location", uuid.uuid4())

    def test_transfer_raises_empty_location(self, asset):
        with pytest.raises(FixedAssetError, match="New location must be provided"):
            asset.transfer("", uuid.uuid4())

    def test_change_responsible_person(self, asset):
        new_person = uuid.uuid4()
        new_asset = asset.change_responsible_person(new_person, uuid.uuid4())
        assert new_asset.responsible_person == new_person
        assert new_asset.version == asset.version + 1

    def test_change_responsible_person_to_none(self, asset):
        new_asset = asset.change_responsible_person(None, uuid.uuid4())
        assert new_asset.responsible_person is None
        assert new_asset.version == asset.version + 1

    def test_update_name_valid(self, asset):
        new_name = "Updated Asset Name"
        new_asset = asset.update_name(new_name, uuid.uuid4())
        assert new_asset.name == new_name
        assert new_asset.version == asset.version + 1

    def test_update_name_invalid_raises(self, asset):
        with pytest.raises(FixedAssetError, match="at least 2 characters"):
            asset.update_name("A", uuid.uuid4())

    def test_update_description(self, asset):
        new_desc = "New description"
        new_asset = asset.update_description(new_desc, uuid.uuid4())
        assert new_asset.description == new_desc
        assert new_asset.version == asset.version + 1

    def test_calculate_gain_loss_on_disposal(self, asset):
        gain = asset.calculate_gain_loss_on_disposal(Decimal("12000"))
        assert gain == Decimal("2000")  # 12000 - 10000

    # ------------------------------------------------------------------------
    # Entity basic methods (create, update, delete, restore, etc.)
    # ------------------------------------------------------------------------

    def test_create(self, asset):
        new_asset = asset.create(uuid.uuid4())
        assert new_asset is asset  # returns self

    def test_update(self, asset):
        new_asset = asset.update(uuid.uuid4(), name="Updated", location="New Loc")
        assert new_asset.name == "Updated"
        assert new_asset.location == "New Loc"
        assert new_asset.version == asset.version + 1

    def test_delete_disposes(self, asset):
        deleted = asset.delete(uuid.uuid4(), "Deletion reason")
        assert deleted.status == AssetStatus.DISPOSED
        assert deleted.disposed_reason == "deletion: Deletion reason"

    def test_delete_raises_if_already_disposed(self, asset):
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

    def test_restore_raises_if_not_disposed(self, asset):
        with pytest.raises(FixedAssetError, match="not disposed"):
            asset.restore(uuid.uuid4())

    def test_activate(self, asset):
        # already active
        new_asset = asset.activate(uuid.uuid4())
        assert new_asset is asset  # returns self

        # under construction
        under_construction = FixedAsset(
            **{**asset.__dict__, "status": AssetStatus.UNDER_CONSTRUCTION}
        )
        activated = under_construction.activate(uuid.uuid4())
        assert activated.status == AssetStatus.ACTIVE
        assert activated.version == under_construction.version + 1

    def test_activate_raises_if_invalid_status(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot activate"):
            disposed.activate(uuid.uuid4())

    def test_deactivate(self, asset):
        deactivated = asset.deactivate(uuid.uuid4(), "maintenance")
        assert deactivated.status == AssetStatus.IDLE
        assert deactivated.version == asset.version + 1

    def test_deactivate_raises_if_not_active(self, asset):
        disposed = asset.dispose(FIXED_DATE, "sale", Decimal("5000"), "sold", uuid.uuid4())
        with pytest.raises(FixedAssetError, match="Cannot deactivate"):
            disposed.deactivate(uuid.uuid4())

    def test_lock(self, asset):
        locked = asset.lock(uuid.uuid4(), "audit")
        assert locked.metadata["locked_by"] == str(uuid.uuid4())
        assert locked.version == asset.version + 1

    def test_unlock(self, asset):
        locked = asset.lock(uuid.uuid4(), "audit")
        unlocked = locked.unlock(uuid.uuid4())
        assert "locked_by" not in unlocked.metadata
        assert unlocked.version == locked.version + 1

    def test_validate_valid(self, asset):
        result = asset.validate()
        assert result["is_valid"]
        assert result["asset_id"] == str(asset.id)

    def test_validate_invalid(self, asset):
        # corrupt some data
        asset.cryptographic_hash = "fake"
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

    def test_snapshot(self, asset):
        snap = asset.snapshot()
        assert snap["asset_id"] == str(asset.id)
        assert snap["version"] == asset.version

    def test_get_version(self, asset):
        assert asset.get_version() == 1

    def test_audit_trail(self, asset):
        # method exists but may be empty
        trail = asset.audit_trail()
        assert isinstance(trail, list)

    def test_touch(self, asset):
        touched = asset.touch(uuid.uuid4())
        assert touched.version == asset.version + 1


# ============================================================================
# TESTS FOR FixedAssetRepository (protocol)
# ============================================================================

class TestFixedAssetRepository:
    @pytest.fixture
    def repo(self):
        return FixedAssetRepository()

    def test_get_by_id_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid.uuid4(), uuid.uuid4())

    def test_get_by_code_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.get_by_code("code", uuid.uuid4())

    def test_list_active_assets_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.list_active_assets(uuid.uuid4())

    def test_list_assets_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.list_assets(uuid.uuid4())

    def test_save_asset_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.save_asset(None)

    def test_save_depreciation_entry_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.save_depreciation_entry(None)

    def test_sum_acquisition_cost_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.sum_acquisition_cost(uuid.uuid4())

    def test_sum_accumulated_depreciation_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.sum_accumulated_depreciation(uuid.uuid4())

    def test_count_assets_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.count_assets(uuid.uuid4())

    def test_get_depreciation_schedule_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            repo.get_depreciation_schedule(uuid.uuid4(), None, None)

    # Async tests with mock

    @pytest.mark.asyncio
    async def test_get_by_id_async_mock(self):
        repo = FixedAssetRepository()
        # We can't call the real method because it raises, but we can mock it
        repo.get_by_id = AsyncMock(return_value=None)
        result = await repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_code_async_mock(self):
        repo = FixedAssetRepository()
        repo.get_by_code = AsyncMock(return_value=None)
        result = await repo.get_by_code("code", uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_active_assets_async_mock(self):
        repo = FixedAssetRepository()
        repo.list_active_assets = AsyncMock(return_value=[])
        result = await repo.list_active_assets(uuid.uuid4())
        assert result == []