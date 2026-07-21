# tests/domain/fixed_asset/test_invariants.py
"""
Comprehensive unit tests for Fixed Asset invariants.

FIXES:
- All async tests now have @pytest.mark.asyncio marker.
- Duplicate structural tests combined using parametrize.
- All tests use fixed date to avoid flaky (date.today() replaced with mock).
- Negative path tests use pytest.raises for ValueErrors.
- Mock quality improved using spec/autospec.
"""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.fixed_asset.asset_entity import AssetStatus, AssetType, FixedAsset
from domain.fixed_asset.depreciation_schedule_engine import DepreciationMethod
from domain.fixed_asset.invariants import (
    ALLOWED_STATUS_TRANSITIONS,
    FixedAssetInvariantEnforcer,
    FixedAssetInvariants,
    FixedAssetInvariantsValidator,
    InvariantResult,
    validate_date_not_future,
    validate_date_sequence,
    validate_non_negative_decimal,
    validate_positive_decimal,
    validate_status_transition,
    validate_string_not_empty,
    validate_version,
)

# =============================================================================
# FIXED DATE (untuk menghindari flaky)
# =============================================================================

FIXED_DATE = date(2026, 1, 1)


@pytest.fixture(autouse=True)
def mock_date_today():
    with patch("domain.fixed_asset.invariants.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


# =============================================================================
# Helper: create a mock FixedAsset for testing
# =============================================================================

def create_mock_asset(
    asset_code="ASSET-001",
    name="Test Asset",
    asset_type=AssetType.TANGIBLE,
    status=AssetStatus.ACTIVE,
    acquisition_date=FIXED_DATE,
    acquisition_cost=Decimal("100000"),
    salvage_value=Decimal("0"),
    useful_life_years=10,
    depreciation_method=DepreciationMethod.STRAIGHT_LINE,
    accumulated_depreciation=Decimal("0"),
    accumulated_impairment=Decimal("0"),
    net_book_value=Decimal("100000"),
    currency="IDR",
    is_disposed=False,
):
    asset = MagicMock(spec=FixedAsset)
    asset.asset_code = asset_code
    asset.name = name
    asset.asset_type = asset_type
    asset.status = status
    asset.acquisition_date = acquisition_date
    asset.acquisition_cost = acquisition_cost
    asset.salvage_value = salvage_value
    asset.useful_life_years = useful_life_years
    asset.depreciation_method = depreciation_method
    asset.accumulated_depreciation = accumulated_depreciation
    asset.accumulated_impairment = accumulated_impairment
    asset.net_book_value = net_book_value
    asset.currency = currency
    asset.is_disposed = is_disposed
    asset.status.display_name.return_value = status.value
    asset.status.can_transfer.return_value = True
    asset.status.can_revalue.return_value = True
    return asset


# =============================================================================
# Tests for InvariantResult
# =============================================================================

class TestInvariantResult:
    def test_default_initialization(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_initialization_with_values(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["e1"]
        assert result.warnings == ["w1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("invalid amount")
        assert result.is_valid is False
        assert result.errors == ["invalid amount"]

    def test_add_warning(self):
        result = InvariantResult()
        result.add_warning("date not timezone-aware")
        assert result.is_valid is True
        assert result.warnings == ["date not timezone-aware"]

    def test_merge_valid(self):
        r1 = InvariantResult()
        r2 = InvariantResult()
        merged = r1.merge(r2)
        assert merged.is_valid is True
        assert merged.errors == []
        assert merged.warnings == []

    def test_merge_invalid(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e2"]
        assert merged.warnings == ["w2"]

    def test_merge_multiple(self):
        r1 = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        r2 = InvariantResult(is_valid=False, errors=["e2"], warnings=["w2"])
        merged = r1.merge(r2)
        assert merged.is_valid is False
        assert merged.errors == ["e1", "e2"]
        assert merged.warnings == ["w1", "w2"]

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["e1"], warnings=["w1"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e1"]
        assert d["warnings"] == ["w1"]

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False

    def test_success_classmethod(self):
        result = InvariantResult.success()
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []
        result_with_warnings = InvariantResult.success(warnings=["w1"])
        assert result_with_warnings.warnings == ["w1"]

    def test_failure_classmethod(self):
        result = InvariantResult.failure("error", warnings=["w1"])
        assert result.is_valid is False
        assert result.errors == ["error"]
        assert result.warnings == ["w1"]


# =============================================================================
# Tests for Validator Functions (parametrized to reduce duplication)
# =============================================================================

class TestValidators:
    @pytest.mark.parametrize("value, expected_valid, expected_error_contains", [
        (Decimal("10.00"), True, None),
        (Decimal("0"), False, "positive"),
        (Decimal("-5"), False, "positive"),
    ])
    def test_validate_positive_decimal(self, value, expected_valid, expected_error_contains):
        result = validate_positive_decimal(value)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(expected_error_contains in e for e in result.errors)

    @pytest.mark.parametrize("value, expected_valid, expected_error_contains", [
        (Decimal("10"), True, None),
        (Decimal("0"), True, None),
        (Decimal("-1"), False, "negative"),
    ])
    def test_validate_non_negative_decimal(self, value, expected_valid, expected_error_contains):
        result = validate_non_negative_decimal(value)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(expected_error_contains in e for e in result.errors)

    @pytest.mark.parametrize("value, min_len, field, expected_valid, expected_error_contains", [
        ("hello", 1, "Field", True, None),
        ("abc", 3, "Field", True, None),
        ("ab", 3, "Field", False, "at least 3"),
        (None, 1, "Field", False, "cannot be None"),
        (123, 1, "Field", False, "must be a string"),
    ])
    def test_validate_string_not_empty(self, value, min_len, field, expected_valid, expected_error_contains):
        result = validate_string_not_empty(value, field, min_len)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(expected_error_contains in e for e in result.errors)

    @pytest.mark.parametrize("dt, expected_valid", [
        (FIXED_DATE - timedelta(days=1), True),
        (FIXED_DATE, True),
        (FIXED_DATE + timedelta(days=1), False),
    ])
    def test_validate_date_not_future(self, dt, expected_valid):
        result = validate_date_not_future(dt, "Date")
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "future" in result.errors[0]

    @pytest.mark.parametrize("start,end,expected_valid", [
        (FIXED_DATE, FIXED_DATE, True),
        (FIXED_DATE, FIXED_DATE + timedelta(days=1), True),
        (FIXED_DATE + timedelta(days=1), FIXED_DATE, False),
    ])
    def test_validate_date_sequence(self, start, end, expected_valid):
        result = validate_date_sequence(start, end)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "before or equal" in result.errors[0]

    @pytest.mark.parametrize("version, expected_version, expected_valid, expected_error_contains", [
        (1, None, True, None),
        (5, None, True, None),
        (0, None, False, ">= 1"),
        (1, 2, False, "mismatch"),
        (2, 2, True, None),
    ])
    def test_validate_version(self, version, expected_version, expected_valid, expected_error_contains):
        result = validate_version(version, expected_version)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(expected_error_contains in e for e in result.errors)


# =============================================================================
# Tests for Status Transition Validation
# =============================================================================

class TestStatusTransition:
    def test_transition_definition_consistency(self):
        for status in AssetStatus:
            assert status in ALLOWED_STATUS_TRANSITIONS, f"Missing transition definition for {status}"
        for targets in ALLOWED_STATUS_TRANSITIONS.values():
            for t in targets:
                assert isinstance(t, AssetStatus)

    @pytest.mark.parametrize("from_status,to_status,user_role,expected_valid,error_contains", [
        (AssetStatus.ACTIVE, AssetStatus.FULLY_DEPRECIATED, "user", True, None),
        (AssetStatus.ACTIVE, AssetStatus.DISPOSED, "finance_manager", True, None),
        (AssetStatus.ACTIVE, AssetStatus.DISPOSED, "admin", True, None),
        (AssetStatus.DISPOSED, AssetStatus.ACTIVE, "admin", False, "not allowed"),
        (AssetStatus.ACTIVE, AssetStatus.DISPOSED, "user", False, "finance manager"),
        (AssetStatus.ACTIVE, AssetStatus.ACTIVE, "user", False, "not allowed"),
        (AssetStatus.UNDER_CONSTRUCTION, AssetStatus.ACTIVE, "user", True, None),
    ])
    def test_status_transition(self, from_status, to_status, user_role, expected_valid, error_contains):
        result = validate_status_transition(from_status, to_status, user_role)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for FixedAssetInvariants (Static Methods) - with parametrized duplication
# =============================================================================

class TestFixedAssetInvariants:
    # --- Asset Code ---
    @pytest.mark.parametrize("code, expected_valid, error_contains", [
        ("AST-001", True, None),
        ("", False, "at least"),
        ("A" * 31, False, "exceed 30"),
        ("AST 001", False, "only contain"),
    ])
    def test_validate_asset_code(self, code, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_asset_code(code)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Asset Name ---
    @pytest.mark.parametrize("name, expected_valid, error_contains", [
        ("Test Asset", True, None),
        ("", False, "at least"),
        ("A" * 201, False, "exceed 200"),
    ])
    def test_validate_asset_name(self, name, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_asset_name(name)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Asset Type ---
    @pytest.mark.parametrize("asset_type, expected_valid", [
        (AssetType.TANGIBLE, True),
        ("INVALID", False),
    ])
    def test_validate_asset_type(self, asset_type, expected_valid):
        result = FixedAssetInvariants.validate_asset_type(asset_type)
        assert result.is_valid == expected_valid

    # --- Asset Status ---
    @pytest.mark.parametrize("status, expected_valid", [
        (AssetStatus.ACTIVE, True),
        ("INVALID", False),
    ])
    def test_validate_asset_status(self, status, expected_valid):
        result = FixedAssetInvariants.validate_asset_status(status)
        assert result.is_valid == expected_valid

    # --- Acquisition Date ---
    @pytest.mark.parametrize("dt, expected_valid", [
        (FIXED_DATE, True),
        (FIXED_DATE + timedelta(days=1), False),
    ])
    def test_validate_acquisition_date(self, dt, expected_valid):
        result = FixedAssetInvariants.validate_acquisition_date(dt)
        assert result.is_valid == expected_valid

    # --- Cost ---
    @pytest.mark.parametrize("cost, expected_valid", [
        (Decimal("1000"), True),
        (Decimal("0"), False),
        (Decimal("-100"), False),
    ])
    def test_validate_cost(self, cost, expected_valid):
        result = FixedAssetInvariants.validate_cost(cost)
        assert result.is_valid == expected_valid

    # --- Salvage Value (combined: negative & exceed) ---
    @pytest.mark.parametrize("salvage, cost, expected_valid, error_contains", [
        (Decimal("100"), Decimal("1000"), True, None),
        (Decimal("-10"), Decimal("1000"), False, "cannot be negative"),
        (Decimal("1500"), Decimal("1000"), False, "cannot exceed"),
    ])
    def test_validate_salvage_value(self, salvage, cost, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_salvage_value(salvage, cost)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Useful Life ---
    @pytest.mark.parametrize("years, asset_type, expected_valid, warning_contains", [
        (0, AssetType.LAND, True, None),
        (10, AssetType.LAND, True, "zero useful life"),
        (10, AssetType.TANGIBLE, True, None),
        (0, AssetType.TANGIBLE, False, "positive"),
        (150, AssetType.TANGIBLE, True, "unusually long"),
    ])
    def test_validate_useful_life(self, years, asset_type, expected_valid, warning_contains):
        result = FixedAssetInvariants.validate_useful_life(years, asset_type)
        assert result.is_valid == expected_valid
        if warning_contains:
            assert any(warning_contains in w for w in result.warnings)

    # --- Depreciation Method ---
    @pytest.mark.parametrize("method, asset_type, expected_valid, warning_contains", [
        (DepreciationMethod.STRAIGHT_LINE, AssetType.TANGIBLE, True, None),
        (DepreciationMethod.DOUBLE_DECLINING, AssetType.LAND, True, "ignored"),
        ("INVALID", AssetType.TANGIBLE, False, None),
    ])
    def test_validate_depreciation_method(self, method, asset_type, expected_valid, warning_contains):
        result = FixedAssetInvariants.validate_depreciation_method(method, asset_type)
        assert result.is_valid == expected_valid
        if warning_contains and result.warnings:
            assert any(warning_contains in w for w in result.warnings)

    # --- Accumulated Depreciation (negative & exceeds) ---
    @pytest.mark.parametrize("acc_dep, cost, salvage, expected_valid, error_contains", [
        (Decimal("1000"), Decimal("10000"), Decimal("500"), True, None),
        (Decimal("-100"), Decimal("10000"), Decimal("500"), False, "cannot be negative"),
        (Decimal("10000"), Decimal("10000"), Decimal("500"), False, "exceeds depreciable"),
    ])
    def test_validate_accumulated_depreciation(self, acc_dep, cost, salvage, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_accumulated_depreciation(acc_dep, cost, salvage)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Net Book Value (mismatch & negative) ---
    @pytest.mark.parametrize("nbv, cost, acc_dep, impairment, expected_valid, error_contains", [
        (Decimal("9000"), Decimal("10000"), Decimal("1000"), Decimal("0"), True, None),
        (Decimal("8000"), Decimal("10000"), Decimal("1000"), Decimal("0"), False, "mismatch"),
        (Decimal("-100"), Decimal("10000"), Decimal("9000"), Decimal("0"), False, "negative"),
    ])
    def test_validate_net_book_value(self, nbv, cost, acc_dep, impairment, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_net_book_value(nbv, cost, acc_dep, impairment)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Accumulated Impairment (negative & exceeds) ---
    @pytest.mark.parametrize("impairment, nbv_before, expected_valid, error_contains", [
        (Decimal("1000"), Decimal("10000"), True, None),
        (Decimal("-100"), Decimal("10000"), False, "cannot be negative"),
        (Decimal("12000"), Decimal("10000"), False, "exceeds NBV"),
    ])
    def test_validate_accumulated_impairment(self, impairment, nbv_before, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_accumulated_impairment(impairment, nbv_before)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Revaluation Surplus ---
    @pytest.mark.parametrize("surplus, expected_valid", [
        (Decimal("1000"), True),
        (Decimal("-100"), False),
    ])
    def test_validate_revaluation_surplus(self, surplus, expected_valid):
        result = FixedAssetInvariants.validate_revaluation_surplus(surplus)
        assert result.is_valid == expected_valid

    # --- Currency (invalid length & chars) ---
    @pytest.mark.parametrize("currency, expected_valid, error_contains", [
        ("IDR", True, None),
        ("IN", False, "exactly 3"),
        ("I1R", False, "letters"),
    ])
    def test_validate_currency(self, currency, expected_valid, error_contains):
        result = FixedAssetInvariants.validate_currency(currency)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Unique Code ---
    @pytest.mark.parametrize("code, existing, expected_valid", [
        ("NEW", {"EXISTING"}, True),
        ("EXISTING", {"EXISTING"}, False),
    ])
    def test_validate_asset_unique_code(self, code, existing, expected_valid):
        result = FixedAssetInvariants.validate_asset_unique_code(code, existing)
        assert result.is_valid == expected_valid

    # --- Disposal ---
    @pytest.mark.parametrize("is_disposed, status, expected_valid, error_contains", [
        (False, AssetStatus.ACTIVE, True, None),
        (True, AssetStatus.ACTIVE, False, "already disposed"),
        (False, AssetStatus.UNDER_CONSTRUCTION, False, "cannot be disposed"),
    ])
    def test_validate_disposal_allowed(self, is_disposed, status, expected_valid, error_contains):
        asset = create_mock_asset(is_disposed=is_disposed, status=status)
        result = FixedAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Transfer ---
    @pytest.mark.parametrize("is_disposed, can_transfer, expected_valid, error_contains", [
        (False, True, True, None),
        (True, True, False, "already disposed"),
        (False, False, False, "cannot be transferred"),
    ])
    def test_validate_transfer_allowed(self, is_disposed, can_transfer, expected_valid, error_contains):
        asset = create_mock_asset(is_disposed=is_disposed, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = can_transfer
        result = FixedAssetInvariants.validate_transfer_allowed(asset)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)

    # --- Revaluation ---
    @pytest.mark.parametrize("can_revalue, new_value, expected_valid, error_contains, warning_contains", [
        (True, Decimal("120000"), True, None, None),
        (False, Decimal("120000"), False, "cannot be revalued", None),
        (True, Decimal("-100"), False, "positive", None),
        (True, Decimal("100500"), True, None, "less than 1%"),
    ])
    def test_validate_revaluation_allowed(self, can_revalue, new_value, expected_valid, error_contains, warning_contains):
        asset = create_mock_asset(net_book_value=Decimal("100000"))
        asset.status.can_revalue.return_value = can_revalue
        result = FixedAssetInvariants.validate_revaluation_allowed(asset, new_value)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)
        if warning_contains and result.warnings:
            assert any(warning_contains in w for w in result.warnings)

    # --- Impairment ---
    @pytest.mark.parametrize("nbv, loss, expected_valid, error_contains", [
        (Decimal("100000"), Decimal("20000"), True, None),
        (Decimal("100000"), Decimal("0"), False, "positive"),
        (Decimal("50000"), Decimal("60000"), False, "exceeds NBV"),
    ])
    def test_validate_impairment_allowed(self, nbv, loss, expected_valid, error_contains):
        asset = create_mock_asset(net_book_value=nbv)
        result = FixedAssetInvariants.validate_impairment_allowed(asset, loss)
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for FixedAssetInvariantEnforcer (Async) - all marked with asyncio
# =============================================================================

@pytest.mark.asyncio
class TestFixedAssetInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        existing_codes = {"EXISTING-001", "EXISTING-002"}
        get_codes = AsyncMock(return_value=existing_codes)
        return FixedAssetInvariantEnforcer(get_existing_codes=get_codes)

    async def test_enforce_asset_create_valid(self, enforcer):
        asset = create_mock_asset(
            asset_code="NEW-001",
            acquisition_cost=Decimal("100000"),
            salvage_value=Decimal("0"),
            useful_life_years=10,
            depreciation_method=DepreciationMethod.STRAIGHT_LINE,
            net_book_value=Decimal("100000"),
        )
        result = await enforcer.enforce_asset_create(asset)
        assert result.is_valid is True

    async def test_enforce_asset_create_duplicate_code(self, enforcer):
        asset = create_mock_asset(asset_code="EXISTING-001")
        result = await enforcer.enforce_asset_create(asset)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_asset_create_invalid_data(self, enforcer):
        asset = create_mock_asset(
            asset_code="",
            acquisition_cost=Decimal("-1000"),
            salvage_value=Decimal("2000"),
        )
        result = await enforcer.enforce_asset_create(asset)
        assert result.is_valid is False
        assert len(result.errors) >= 3

    async def test_enforce_asset_update_valid(self, enforcer):
        asset = create_mock_asset()
        result = await enforcer.enforce_asset_update(asset)
        assert result.is_valid is True

    async def test_enforce_asset_update_invalid(self, enforcer):
        asset = create_mock_asset(name="", acquisition_cost=Decimal("-100"))
        result = await enforcer.enforce_asset_update(asset)
        assert result.is_valid is False

    async def test_enforce_asset_update_code_change_duplicate(self, enforcer):
        old_asset = create_mock_asset(asset_code="OLD-001")
        asset = create_mock_asset(asset_code="EXISTING-001")
        result = await enforcer.enforce_asset_update(asset, old_asset=old_asset)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_depreciation_valid(self, enforcer):
        asset = create_mock_asset(net_book_value=Decimal("100000"), salvage_value=Decimal("0"))
        result = await enforcer.enforce_depreciation(asset, Decimal("5000"))
        assert result.is_valid is True

    async def test_enforce_depreciation_amount_zero(self, enforcer):
        asset = create_mock_asset()
        result = await enforcer.enforce_depreciation(asset, Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    async def test_enforce_depreciation_below_salvage(self, enforcer):
        asset = create_mock_asset(net_book_value=Decimal("10000"), salvage_value=Decimal("8000"))
        result = await enforcer.enforce_depreciation(asset, Decimal("5000"))
        assert result.is_valid is False
        assert "below salvage" in result.errors[0]

    async def test_enforce_disposal_allowed(self, enforcer):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        result = await enforcer.enforce_disposal(asset)
        assert result.is_valid is True

    async def test_enforce_disposal_already_disposed(self, enforcer):
        asset = create_mock_asset(is_disposed=True)
        result = await enforcer.enforce_disposal(asset)
        assert result.is_valid is False

    async def test_enforce_transfer_allowed(self, enforcer):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        result = await enforcer.enforce_transfer(asset, "New Location")
        assert result.is_valid is True

    async def test_enforce_transfer_disposed(self, enforcer):
        asset = create_mock_asset(is_disposed=True)
        result = await enforcer.enforce_transfer(asset, "New")
        assert result.is_valid is False

    async def test_enforce_transfer_empty_location(self, enforcer):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        result = await enforcer.enforce_transfer(asset, "")
        assert result.is_valid is False
        assert "Destination location" in result.errors[0]

    async def test_enforce_revaluation_allowed(self, enforcer):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = True
        result = await enforcer.enforce_revaluation(asset, Decimal("120000"))
        assert result.is_valid is True

    async def test_enforce_revaluation_not_allowed(self, enforcer):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = False
        result = await enforcer.enforce_revaluation(asset, Decimal("120000"))
        assert result.is_valid is False

    async def test_enforce_impairment_valid(self, enforcer):
        asset = create_mock_asset(net_book_value=Decimal("100000"))
        result = await enforcer.enforce_impairment(asset, Decimal("20000"))
        assert result.is_valid is True

    async def test_enforce_impairment_loss_exceeds_nbv(self, enforcer):
        asset = create_mock_asset(net_book_value=Decimal("50000"))
        result = await enforcer.enforce_impairment(asset, Decimal("60000"))
        assert result.is_valid is False

    async def test_enforce_status_transition_valid(self, enforcer):
        result = await enforcer.enforce_status_transition(
            AssetStatus.ACTIVE, AssetStatus.FULLY_DEPRECIATED, user_role="user"
        )
        assert result.is_valid is True

    async def test_enforce_status_transition_invalid(self, enforcer):
        result = await enforcer.enforce_status_transition(AssetStatus.DISPOSED, AssetStatus.ACTIVE)
        assert result.is_valid is False


# =============================================================================
# Tests for FixedAssetInvariantsValidator (Sync) - using pytest.raises
# =============================================================================

class TestFixedAssetInvariantsValidator:
    def test_validate_asset_cost_valid(self):
        asset = create_mock_asset(acquisition_cost=Decimal("1000"), salvage_value=Decimal("100"))
        FixedAssetInvariantsValidator.validate_asset_cost(asset)

    @pytest.mark.parametrize("cost, salvage, error_contains", [
        (Decimal("-100"), Decimal("0"), "positive"),
        (Decimal("1000"), Decimal("-10"), "cannot be negative"),
        (Decimal("1000"), Decimal("1500"), "cannot exceed"),
    ])
    def test_validate_asset_cost_negative(self, cost, salvage, error_contains):
        asset = create_mock_asset(acquisition_cost=cost, salvage_value=salvage)
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_useful_life_valid(self):
        asset = create_mock_asset(asset_type=AssetType.TANGIBLE, useful_life_years=10)
        FixedAssetInvariantsValidator.validate_useful_life(asset)

    def test_validate_useful_life_land_skips(self):
        asset = create_mock_asset(asset_type=AssetType.LAND, useful_life_years=0)
        FixedAssetInvariantsValidator.validate_useful_life(asset)

    def test_validate_useful_life_zero_for_depreciable(self):
        asset = create_mock_asset(asset_type=AssetType.TANGIBLE, useful_life_years=0)
        with pytest.raises(ValueError, match="positive"):
            FixedAssetInvariantsValidator.validate_useful_life(asset)

    def test_validate_depreciation_method_valid(self):
        asset = create_mock_asset(depreciation_method=DepreciationMethod.STRAIGHT_LINE)
        FixedAssetInvariantsValidator.validate_depreciation_method(asset)

    def test_validate_depreciation_method_invalid(self):
        asset = create_mock_asset()
        asset.depreciation_method.value = "invalid"
        with pytest.raises(ValueError, match="Invalid"):
            FixedAssetInvariantsValidator.validate_depreciation_method(asset)

    def test_validate_depreciation_amount_valid(self):
        asset = create_mock_asset(net_book_value=Decimal("10000"), salvage_value=Decimal("0"))
        FixedAssetInvariantsValidator.validate_depreciation_amount(asset, Decimal("1000"))

    @pytest.mark.parametrize("amount, error_contains", [
        (Decimal("-100"), "cannot be negative"),
        (Decimal("5000"), "below salvage"),
    ])
    def test_validate_depreciation_amount_invalid(self, amount, error_contains):
        asset = create_mock_asset(net_book_value=Decimal("10000"), salvage_value=Decimal("8000"))
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_depreciation_amount(asset, amount)

    def test_validate_asset_code_unique_valid(self):
        FixedAssetInvariantsValidator.validate_asset_code_unique("NEW", {"EXISTING"})

    def test_validate_asset_code_unique_duplicate(self):
        with pytest.raises(ValueError, match="already exists"):
            FixedAssetInvariantsValidator.validate_asset_code_unique("EXISTING", {"EXISTING"})

    @pytest.mark.parametrize("can_revalue, asset_type, new_value, error_contains", [
        (False, AssetType.TANGIBLE, Decimal("120000"), "cannot be revalued"),
        (True, AssetType.TANGIBLE, Decimal("-100"), "positive"),
        (True, AssetType.INTANGIBLE, Decimal("120000"), "Only tangible"),
    ])
    def test_validate_revaluation_invalid(self, can_revalue, asset_type, new_value, error_contains):
        asset = create_mock_asset(asset_type=asset_type, status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = can_revalue
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_revaluation(asset, new_value)

    def test_validate_revaluation_valid(self):
        asset = create_mock_asset(asset_type=AssetType.TANGIBLE, status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = True
        FixedAssetInvariantsValidator.validate_revaluation(asset, Decimal("120000"))

    @pytest.mark.parametrize("is_disposed, status, error_contains", [
        (True, AssetStatus.ACTIVE, "already disposed"),
        (False, AssetStatus.UNDER_CONSTRUCTION, "cannot be disposed"),
    ])
    def test_validate_disposal_invalid(self, is_disposed, status, error_contains):
        asset = create_mock_asset(is_disposed=is_disposed, status=status)
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_disposal(asset)

    def test_validate_disposal_valid(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        FixedAssetInvariantsValidator.validate_disposal(asset)

    @pytest.mark.parametrize("is_disposed, can_transfer, location, error_contains", [
        (True, True, "New", "already disposed"),
        (False, False, "New", "cannot be transferred"),
        (False, True, "", "Destination location"),
    ])
    def test_validate_transfer_invalid(self, is_disposed, can_transfer, location, error_contains):
        asset = create_mock_asset(is_disposed=is_disposed, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = can_transfer
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_transfer(asset, location)

    def test_validate_transfer_valid(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        FixedAssetInvariantsValidator.validate_transfer(asset, "New Location")

    @pytest.mark.parametrize("acc_dep, cost, salvage, error_contains", [
        (Decimal("-100"), Decimal("10000"), Decimal("1000"), "cannot be negative"),
        (Decimal("10000"), Decimal("10000"), Decimal("1000"), "exceeds depreciable"),
    ])
    def test_validate_accumulated_depreciation_invalid(self, acc_dep, cost, salvage, error_contains):
        asset = create_mock_asset(
            acquisition_cost=cost,
            salvage_value=salvage,
            accumulated_depreciation=acc_dep,
        )
        with pytest.raises(ValueError, match=error_contains):
            FixedAssetInvariantsValidator.validate_accumulated_depreciation(asset)

    def test_validate_accumulated_depreciation_valid(self):
        asset = create_mock_asset(
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            accumulated_depreciation=Decimal("9000"),
        )
        FixedAssetInvariantsValidator.validate_accumulated_depreciation(asset)

    def test_validate_net_book_value_negative(self):
        asset = create_mock_asset(net_book_value=Decimal("-100"))
        with pytest.raises(ValueError, match="cannot be negative"):
            FixedAssetInvariantsValidator.validate_net_book_value(asset)

    def test_validate_net_book_value_valid(self):
        asset = create_mock_asset(net_book_value=Decimal("1000"))
        FixedAssetInvariantsValidator.validate_net_book_value(asset)