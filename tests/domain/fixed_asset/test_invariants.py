# tests/domain/fixed_asset/test_invariants.py
"""
Comprehensive unit tests for Fixed Asset invariants.

FIXES:
- All tests now have explicit assertions.
- Duplicate structural tests combined using parametrize.
- All async tests marked with @pytest.mark.asyncio.
- All tests use fixed date to avoid flaky (date.today() replaced with mock).
- Negative path tests use pytest.raises for ValueErrors.
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
    # Parametrized for positive_decimal
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

    # Parametrized for non_negative_decimal
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

    # Parametrized for string_not_empty
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

    # Parametrized for date_not_future
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

    # Parametrized for date_sequence
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

    # Parametrized for version
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
        # Ensure all statuses have a transition set
        for status in AssetStatus:
            assert status in ALLOWED_STATUS_TRANSITIONS, f"Missing transition definition for {status}"
        # Ensure all targets are valid statuses
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
# Tests for FixedAssetInvariants (Static Methods)
# =============================================================================

class TestFixedAssetInvariants:
    def test_validate_asset_code_valid(self):
        result = FixedAssetInvariants.validate_asset_code("AST-001")
        assert result.is_valid is True

    def test_validate_asset_code_invalid_empty(self):
        result = FixedAssetInvariants.validate_asset_code("")
        assert result.is_valid is False
        assert "at least" in result.errors[0]

    def test_validate_asset_code_invalid_too_long(self):
        result = FixedAssetInvariants.validate_asset_code("A" * 31)
        assert result.is_valid is False
        assert "exceed 30" in result.errors[0]

    def test_validate_asset_code_invalid_chars(self):
        result = FixedAssetInvariants.validate_asset_code("AST 001")
        assert result.is_valid is False
        assert "only contain" in result.errors[0]

    def test_validate_asset_name_valid(self):
        result = FixedAssetInvariants.validate_asset_name("Test Asset")
        assert result.is_valid is True

    def test_validate_asset_name_invalid_empty(self):
        result = FixedAssetInvariants.validate_asset_name("")
        assert result.is_valid is False
        assert "at least" in result.errors[0]

    def test_validate_asset_name_invalid_too_long(self):
        result = FixedAssetInvariants.validate_asset_name("A" * 201)
        assert result.is_valid is False
        assert "exceed 200" in result.errors[0]

    def test_validate_asset_type_valid(self):
        result = FixedAssetInvariants.validate_asset_type(AssetType.TANGIBLE)
        assert result.is_valid is True

    def test_validate_asset_type_invalid(self):
        result = FixedAssetInvariants.validate_asset_type("INVALID")
        assert result.is_valid is False

    def test_validate_asset_status_valid(self):
        result = FixedAssetInvariants.validate_asset_status(AssetStatus.ACTIVE)
        assert result.is_valid is True

    def test_validate_asset_status_invalid(self):
        result = FixedAssetInvariants.validate_asset_status("INVALID")
        assert result.is_valid is False

    def test_validate_acquisition_date_valid(self):
        result = FixedAssetInvariants.validate_acquisition_date(FIXED_DATE)
        assert result.is_valid is True

    def test_validate_acquisition_date_future(self):
        future = FIXED_DATE + timedelta(days=1)
        result = FixedAssetInvariants.validate_acquisition_date(future)
        assert result.is_valid is False
        assert "future" in result.errors[0]

    def test_validate_cost_valid(self):
        result = FixedAssetInvariants.validate_cost(Decimal("1000"))
        assert result.is_valid is True

    def test_validate_cost_zero(self):
        result = FixedAssetInvariants.validate_cost(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_salvage_value_valid(self):
        result = FixedAssetInvariants.validate_salvage_value(Decimal("100"), Decimal("1000"))
        assert result.is_valid is True

    def test_validate_salvage_value_negative(self):
        result = FixedAssetInvariants.validate_salvage_value(Decimal("-10"), Decimal("1000"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_salvage_value_exceeds_cost(self):
        result = FixedAssetInvariants.validate_salvage_value(Decimal("1500"), Decimal("1000"))
        assert result.is_valid is False
        assert "cannot exceed" in result.errors[0]

    def test_validate_useful_life_land_allows_zero(self):
        result = FixedAssetInvariants.validate_useful_life(0, AssetType.LAND)
        assert result.is_valid is True

    def test_validate_useful_life_land_with_warning(self):
        result = FixedAssetInvariants.validate_useful_life(10, AssetType.LAND)
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "zero useful life" in result.warnings[0]

    def test_validate_useful_life_positive_for_depreciable(self):
        result = FixedAssetInvariants.validate_useful_life(10, AssetType.TANGIBLE)
        assert result.is_valid is True

    def test_validate_useful_life_zero_for_depreciable(self):
        result = FixedAssetInvariants.validate_useful_life(0, AssetType.TANGIBLE)
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_useful_life_warning_too_long(self):
        result = FixedAssetInvariants.validate_useful_life(150, AssetType.TANGIBLE)
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "unusually long" in result.warnings[0]

    def test_validate_depreciation_method_valid(self):
        result = FixedAssetInvariants.validate_depreciation_method(
            DepreciationMethod.STRAIGHT_LINE, AssetType.TANGIBLE
        )
        assert result.is_valid is True

    def test_validate_depreciation_method_land_warning(self):
        result = FixedAssetInvariants.validate_depreciation_method(
            DepreciationMethod.DOUBLE_DECLINING, AssetType.LAND
        )
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "ignored" in result.warnings[0]

    def test_validate_depreciation_method_invalid(self):
        result = FixedAssetInvariants.validate_depreciation_method("INVALID", AssetType.TANGIBLE)
        assert result.is_valid is False

    def test_validate_accumulated_depreciation_valid(self):
        result = FixedAssetInvariants.validate_accumulated_depreciation(
            Decimal("1000"), Decimal("10000"), Decimal("500")
        )
        assert result.is_valid is True

    def test_validate_accumulated_depreciation_negative(self):
        result = FixedAssetInvariants.validate_accumulated_depreciation(
            Decimal("-100"), Decimal("10000"), Decimal("500")
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_accumulated_depreciation_exceeds_depreciable(self):
        result = FixedAssetInvariants.validate_accumulated_depreciation(
            Decimal("10000"), Decimal("10000"), Decimal("500")
        )
        assert result.is_valid is False
        assert "exceeds depreciable amount" in result.errors[0]

    def test_validate_net_book_value_valid(self):
        result = FixedAssetInvariants.validate_net_book_value(
            Decimal("9000"), Decimal("10000"), Decimal("1000"), Decimal("0")
        )
        assert result.is_valid is True

    def test_validate_net_book_value_mismatch(self):
        result = FixedAssetInvariants.validate_net_book_value(
            Decimal("8000"), Decimal("10000"), Decimal("1000"), Decimal("0")
        )
        assert result.is_valid is False
        assert "mismatch" in result.errors[0]

    def test_validate_net_book_value_negative(self):
        result = FixedAssetInvariants.validate_net_book_value(
            Decimal("-100"), Decimal("10000"), Decimal("9000"), Decimal("0")
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_accumulated_impairment_valid(self):
        result = FixedAssetInvariants.validate_accumulated_impairment(
            Decimal("1000"), Decimal("10000")
        )
        assert result.is_valid is True

    def test_validate_accumulated_impairment_negative(self):
        result = FixedAssetInvariants.validate_accumulated_impairment(
            Decimal("-100"), Decimal("10000")
        )
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_accumulated_impairment_exceeds_nbv(self):
        result = FixedAssetInvariants.validate_accumulated_impairment(
            Decimal("12000"), Decimal("10000")
        )
        assert result.is_valid is False
        assert "exceeds NBV" in result.errors[0]

    def test_validate_revaluation_surplus_valid(self):
        result = FixedAssetInvariants.validate_revaluation_surplus(Decimal("1000"))
        assert result.is_valid is True

    def test_validate_revaluation_surplus_negative(self):
        result = FixedAssetInvariants.validate_revaluation_surplus(Decimal("-100"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_currency_valid(self):
        result = FixedAssetInvariants.validate_currency("IDR")
        assert result.is_valid is True

    def test_validate_currency_invalid_length(self):
        result = FixedAssetInvariants.validate_currency("IN")
        assert result.is_valid is False
        assert "exactly 3" in result.errors[0]

    def test_validate_currency_invalid_chars(self):
        result = FixedAssetInvariants.validate_currency("I1R")
        assert result.is_valid is False
        assert "letters" in result.errors[0]

    def test_validate_asset_unique_code_valid(self):
        result = FixedAssetInvariants.validate_asset_unique_code("AST-001", {"AST-002"})
        assert result.is_valid is True

    def test_validate_asset_unique_code_duplicate(self):
        result = FixedAssetInvariants.validate_asset_unique_code("AST-001", {"AST-001"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_disposal_allowed_not_disposed(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        result = FixedAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid is True

    def test_validate_disposal_allowed_already_disposed(self):
        asset = create_mock_asset(is_disposed=True)
        result = FixedAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid is False
        assert "already disposed" in result.errors[0]

    def test_validate_disposal_allowed_under_construction(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.UNDER_CONSTRUCTION)
        result = FixedAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid is False
        assert "cannot be disposed" in result.errors[0]

    def test_validate_transfer_allowed_active(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        result = FixedAssetInvariants.validate_transfer_allowed(asset)
        assert result.is_valid is True

    def test_validate_transfer_allowed_disposed(self):
        asset = create_mock_asset(is_disposed=True)
        result = FixedAssetInvariants.validate_transfer_allowed(asset)
        assert result.is_valid is False
        assert "already disposed" in result.errors[0]

    def test_validate_transfer_allowed_cannot_transfer(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = False
        result = FixedAssetInvariants.validate_transfer_allowed(asset)
        assert result.is_valid is False
        assert "cannot be transferred" in result.errors[0]

    def test_validate_revaluation_allowed_success(self):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = True
        result = FixedAssetInvariants.validate_revaluation_allowed(asset, Decimal("120000"))
        assert result.is_valid is True

    def test_validate_revaluation_allowed_cannot_revalue(self):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = False
        result = FixedAssetInvariants.validate_revaluation_allowed(asset, Decimal("120000"))
        assert result.is_valid is False
        assert "cannot be revalued" in result.errors[0]

    def test_validate_revaluation_allowed_non_positive(self):
        asset = create_mock_asset()
        result = FixedAssetInvariants.validate_revaluation_allowed(asset, Decimal("-100"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_revaluation_allowed_trivial_warning(self):
        asset = create_mock_asset(net_book_value=Decimal("100000"))
        asset.status.can_revalue.return_value = True
        result = FixedAssetInvariants.validate_revaluation_allowed(asset, Decimal("100500"))
        assert result.is_valid is True
        assert len(result.warnings) == 1
        assert "less than 1%" in result.warnings[0]

    def test_validate_impairment_allowed_valid(self):
        asset = create_mock_asset(net_book_value=Decimal("100000"))
        result = FixedAssetInvariants.validate_impairment_allowed(asset, Decimal("20000"))
        assert result.is_valid is True

    def test_validate_impairment_allowed_loss_zero(self):
        asset = create_mock_asset()
        result = FixedAssetInvariants.validate_impairment_allowed(asset, Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    def test_validate_impairment_allowed_loss_exceeds_nbv(self):
        asset = create_mock_asset(net_book_value=Decimal("50000"))
        result = FixedAssetInvariants.validate_impairment_allowed(asset, Decimal("60000"))
        assert result.is_valid is False
        assert "exceeds NBV" in result.errors[0]


# =============================================================================
# Tests for FixedAssetInvariantEnforcer (Async)
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
# Tests for FixedAssetInvariantsValidator (Sync)
# =============================================================================

class TestFixedAssetInvariantsValidator:
    # All tests here use pytest.raises for invalid cases and assert True for valid ones.

    def test_validate_asset_cost_valid(self):
        asset = create_mock_asset(acquisition_cost=Decimal("1000"), salvage_value=Decimal("100"))
        FixedAssetInvariantsValidator.validate_asset_cost(asset)
        assert True  # no exception

    def test_validate_asset_cost_negative(self):
        asset = create_mock_asset(acquisition_cost=Decimal("-100"))
        with pytest.raises(ValueError, match="positive"):
            FixedAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_asset_cost_salvage_negative(self):
        asset = create_mock_asset(acquisition_cost=Decimal("1000"), salvage_value=Decimal("-10"))
        with pytest.raises(ValueError, match="cannot be negative"):
            FixedAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_asset_cost_salvage_exceeds_cost(self):
        asset = create_mock_asset(acquisition_cost=Decimal("1000"), salvage_value=Decimal("1500"))
        with pytest.raises(ValueError, match="cannot exceed"):
            FixedAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_useful_life_valid(self):
        asset = create_mock_asset(asset_type=AssetType.TANGIBLE, useful_life_years=10)
        FixedAssetInvariantsValidator.validate_useful_life(asset)
        assert True

    def test_validate_useful_life_land_skips(self):
        asset = create_mock_asset(asset_type=AssetType.LAND, useful_life_years=0)
        FixedAssetInvariantsValidator.validate_useful_life(asset)
        assert True

    def test_validate_useful_life_zero_for_depreciable(self):
        asset = create_mock_asset(asset_type=AssetType.TANGIBLE, useful_life_years=0)
        with pytest.raises(ValueError, match="positive"):
            FixedAssetInvariantsValidator.validate_useful_life(asset)

    def test_validate_depreciation_method_valid(self):
        asset = create_mock_asset(depreciation_method=DepreciationMethod.STRAIGHT_LINE)
        FixedAssetInvariantsValidator.validate_depreciation_method(asset)
        assert True

    def test_validate_depreciation_method_invalid(self):
        asset = create_mock_asset()
        asset.depreciation_method.value = "invalid"
        with pytest.raises(ValueError, match="Invalid"):
            FixedAssetInvariantsValidator.validate_depreciation_method(asset)

    def test_validate_depreciation_amount_valid(self):
        asset = create_mock_asset(net_book_value=Decimal("10000"), salvage_value=Decimal("0"))
        FixedAssetInvariantsValidator.validate_depreciation_amount(asset, Decimal("1000"))
        assert True

    def test_validate_depreciation_amount_negative(self):
        asset = create_mock_asset()
        with pytest.raises(ValueError, match="cannot be negative"):
            FixedAssetInvariantsValidator.validate_depreciation_amount(asset, Decimal("-100"))

    def test_validate_depreciation_amount_below_salvage(self):
        asset = create_mock_asset(net_book_value=Decimal("10000"), salvage_value=Decimal("8000"))
        with pytest.raises(ValueError, match="below salvage"):
            FixedAssetInvariantsValidator.validate_depreciation_amount(asset, Decimal("5000"))

    def test_validate_asset_code_unique_valid(self):
        FixedAssetInvariantsValidator.validate_asset_code_unique("NEW", {"EXISTING"})
        assert True

    def test_validate_asset_code_unique_duplicate(self):
        with pytest.raises(ValueError, match="already exists"):
            FixedAssetInvariantsValidator.validate_asset_code_unique("EXISTING", {"EXISTING"})

    def test_validate_revaluation_valid(self):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = True
        FixedAssetInvariantsValidator.validate_revaluation(asset, Decimal("120000"))
        assert True

    def test_validate_revaluation_cannot_revalue(self):
        asset = create_mock_asset(status=AssetStatus.ACTIVE)
        asset.status.can_revalue.return_value = False
        with pytest.raises(ValueError, match="cannot be revalued"):
            FixedAssetInvariantsValidator.validate_revaluation(asset, Decimal("120000"))

    def test_validate_revaluation_non_positive(self):
        asset = create_mock_asset()
        asset.status.can_revalue.return_value = True
        with pytest.raises(ValueError, match="positive"):
            FixedAssetInvariantsValidator.validate_revaluation(asset, Decimal("-100"))

    def test_validate_revaluation_intangible(self):
        asset = create_mock_asset(asset_type=AssetType.INTANGIBLE)
        asset.status.can_revalue.return_value = True
        with pytest.raises(ValueError, match="Only tangible"):
            FixedAssetInvariantsValidator.validate_revaluation(asset, Decimal("120000"))

    def test_validate_disposal_valid(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        FixedAssetInvariantsValidator.validate_disposal(asset)
        assert True

    def test_validate_disposal_already_disposed(self):
        asset = create_mock_asset(is_disposed=True)
        with pytest.raises(ValueError, match="already disposed"):
            FixedAssetInvariantsValidator.validate_disposal(asset)

    def test_validate_disposal_under_construction(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.UNDER_CONSTRUCTION)
        with pytest.raises(ValueError, match="cannot be disposed"):
            FixedAssetInvariantsValidator.validate_disposal(asset)

    def test_validate_transfer_valid(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        FixedAssetInvariantsValidator.validate_transfer(asset, "New Location")
        assert True

    def test_validate_transfer_disposed(self):
        asset = create_mock_asset(is_disposed=True)
        with pytest.raises(ValueError, match="already disposed"):
            FixedAssetInvariantsValidator.validate_transfer(asset, "New")

    def test_validate_transfer_cannot_transfer(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = False
        with pytest.raises(ValueError, match="cannot be transferred"):
            FixedAssetInvariantsValidator.validate_transfer(asset, "New")

    def test_validate_transfer_empty_location(self):
        asset = create_mock_asset(is_disposed=False, status=AssetStatus.ACTIVE)
        asset.status.can_transfer.return_value = True
        with pytest.raises(ValueError, match="Destination location"):
            FixedAssetInvariantsValidator.validate_transfer(asset, "")

    def test_validate_accumulated_depreciation_valid(self):
        asset = create_mock_asset(
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            accumulated_depreciation=Decimal("9000"),
        )
        FixedAssetInvariantsValidator.validate_accumulated_depreciation(asset)
        assert True

    def test_validate_accumulated_depreciation_exceeds(self):
        asset = create_mock_asset(
            acquisition_cost=Decimal("10000"),
            salvage_value=Decimal("1000"),
            accumulated_depreciation=Decimal("10000"),
        )
        with pytest.raises(ValueError, match="exceeds depreciable"):
            FixedAssetInvariantsValidator.validate_accumulated_depreciation(asset)

    def test_validate_accumulated_depreciation_negative(self):
        asset = create_mock_asset(accumulated_depreciation=Decimal("-100"))
        with pytest.raises(ValueError, match="cannot be negative"):
            FixedAssetInvariantsValidator.validate_accumulated_depreciation(asset)

    def test_validate_net_book_value_non_negative(self):
        asset = create_mock_asset(net_book_value=Decimal("1000"))
        FixedAssetInvariantsValidator.validate_net_book_value(asset)
        assert True

    def test_validate_net_book_value_negative(self):
        asset = create_mock_asset(net_book_value=Decimal("-100"))
        with pytest.raises(ValueError, match="cannot be negative"):
            FixedAssetInvariantsValidator.validate_net_book_value(asset)