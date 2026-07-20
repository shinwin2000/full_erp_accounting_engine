# domain/intangible_asset/test_invariants.py
"""
Comprehensive unit tests for Intangible Asset invariants.

FIXES:
- Semua datetime.now() diganti dengan FIXED_NOW via mock.
- Semua test memiliki assertion (termasuk valid case dengan assert True).
- Duplikasi struktural dihilangkan dengan parametrize.
- Semua async test diberi @pytest.mark.asyncio.
- Negative path tests menggunakan pytest.raises.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domain.intangible_asset.amortization_method_enum import AmortizationMethod
from domain.intangible_asset.asset_entity import (
    IntangibleAssetEntity,
    IntangibleAssetStatus,
    IntangibleAssetType,
)
from domain.intangible_asset.invariants import (
    ALLOWED_STATUS_TRANSITIONS,
    IntangibleAssetInvariantEnforcer,
    IntangibleAssetInvariants,
    IntangibleAssetInvariantsValidator,
    InvariantResult,
    validate_currency,
    validate_date_not_future,
    validate_date_sequence,
    validate_non_negative_decimal,
    validate_positive_decimal,
    validate_status_transition,
    validate_string_not_empty,
    validate_version,
)

# =============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# =============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=365)
FIXED_FUTURE = FIXED_NOW + timedelta(days=365)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.intangible_asset.invariants.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# =============================================================================
# Helper: create a mock asset for testing
# =============================================================================

def create_mock_asset(
    asset_code="TEST-001",
    asset_name="Test Asset",
    asset_type=IntangibleAssetType.PATENT,
    status=IntangibleAssetStatus.ACTIVE,
    acquisition_date=FIXED_PAST,
    cost=Decimal("100000"),
    residual_value=Decimal("0"),
    useful_life_years=20,
    amortization_method=AmortizationMethod.STRAIGHT_LINE,
    accumulated_amortization=Decimal("0"),
    nbv=Decimal("100000"),
    currency="IDR",
    expiry_date=None,
    has_indefinite_life=False,
):
    asset = MagicMock(spec=IntangibleAssetEntity)
    asset.asset_code = asset_code
    asset.asset_name = asset_name
    asset.asset_type = asset_type
    asset.status = status
    asset.acquisition_date = acquisition_date
    asset.cost = cost
    asset.residual_value = residual_value
    asset.useful_life_years = useful_life_years
    asset.amortization_method = amortization_method
    asset.accumulated_amortization = accumulated_amortization
    asset.nbv = nbv
    asset.currency = currency
    asset.expiry_date = expiry_date
    asset.has_indefinite_life = has_indefinite_life
    asset.remaining_amortizable = cost - residual_value - accumulated_amortization
    asset.status.can_impair.return_value = True
    asset.status.can_amortize.return_value = True
    asset.status.display_name.return_value = status.value
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
    @pytest.mark.parametrize("value, expected_valid, error_contains", [
        (Decimal("10.00"), True, None),
        (Decimal("0"), False, "positive"),
        (Decimal("-5"), False, "positive"),
    ])
    def test_validate_positive_decimal(self, value, expected_valid, error_contains):
        result = validate_positive_decimal(value)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Parametrized for non_negative_decimal
    @pytest.mark.parametrize("value, expected_valid, error_contains", [
        (Decimal("10"), True, None),
        (Decimal("0"), True, None),
        (Decimal("-1"), False, "negative"),
    ])
    def test_validate_non_negative_decimal(self, value, expected_valid, error_contains):
        result = validate_non_negative_decimal(value)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Parametrized for string_not_empty
    @pytest.mark.parametrize("value, min_len, field, expected_valid, error_contains", [
        ("hello", 1, "Field", True, None),
        ("abc", 3, "Field", True, None),
        ("ab", 3, "Field", False, "at least 3"),
        (None, 1, "Field", False, "cannot be None"),
        (123, 1, "Field", False, "must be a string"),
    ])
    def test_validate_string_not_empty(self, value, min_len, field, expected_valid, error_contains):
        result = validate_string_not_empty(value, field, min_len)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Parametrized for date_not_future
    @pytest.mark.parametrize("dt, expected_valid", [
        (FIXED_PAST, True),
        (FIXED_NOW, True),
        (FIXED_FUTURE, False),
    ])
    def test_validate_date_not_future(self, dt, expected_valid):
        result = validate_date_not_future(dt, "Date")
        assert result.is_valid == expected_valid
        if not expected_valid:
            assert "future" in result.errors[0]

    # Parametrized for date_sequence
    @pytest.mark.parametrize("start,end,expected_valid,error_contains", [
        (FIXED_PAST, FIXED_NOW, True, None),
        (FIXED_NOW, FIXED_FUTURE, True, None),
        (FIXED_NOW, FIXED_NOW, False, "must be before"),
        (FIXED_FUTURE, FIXED_NOW, False, "must be before"),
    ])
    def test_validate_date_sequence(self, start, end, expected_valid, error_contains):
        result = validate_date_sequence(start, end)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Parametrized for version
    @pytest.mark.parametrize("version, expected_version, expected_valid, error_contains", [
        (1, None, True, None),
        (5, None, True, None),
        (0, None, False, ">= 1"),
        (1, 2, False, "mismatch"),
        (2, 2, True, None),
    ])
    def test_validate_version(self, version, expected_version, expected_valid, error_contains):
        result = validate_version(version, expected_version)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Parametrized for currency
    @pytest.mark.parametrize("currency, expected_valid, error_contains", [
        ("IDR", True, None),
        ("USD", True, None),
        ("IN", False, "exactly 3"),
        ("I1R", False, "only letters"),
        ("", False, "non-empty"),
    ])
    def test_validate_currency(self, currency, expected_valid, error_contains):
        result = validate_currency(currency)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for IntangibleAssetInvariants
# =============================================================================

class TestIntangibleAssetInvariants:
    # Asset code tests
    @pytest.mark.parametrize("code, expected_valid, error_contains", [
        ("PAT-001", True, None),
        ("", False, "at least"),
        ("A" * 31, False, "exceed 30"),
        ("PAT 001", False, "only contain"),
    ])
    def test_validate_asset_code(self, code, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_asset_code(code)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Asset name tests
    @pytest.mark.parametrize("name, expected_valid, error_contains", [
        ("Test Patent", True, None),
        ("", False, "at least"),
        ("A" * 201, False, "exceed 200"),
    ])
    def test_validate_asset_name(self, name, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_asset_name(name)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Asset type
    def test_validate_asset_type_valid(self):
        result = IntangibleAssetInvariants.validate_asset_type(IntangibleAssetType.PATENT)
        assert result.is_valid is True

    def test_validate_asset_type_invalid(self):
        result = IntangibleAssetInvariants.validate_asset_type("INVALID")
        assert result.is_valid is False

    # Asset status
    def test_validate_asset_status_valid(self):
        result = IntangibleAssetInvariants.validate_asset_status(IntangibleAssetStatus.ACTIVE)
        assert result.is_valid is True

    def test_validate_asset_status_invalid(self):
        result = IntangibleAssetInvariants.validate_asset_status("INVALID")
        assert result.is_valid is False

    # Acquisition date
    def test_validate_acquisition_date_valid(self):
        result = IntangibleAssetInvariants.validate_acquisition_date(FIXED_PAST)
        assert result.is_valid is True

    def test_validate_acquisition_date_future(self):
        result = IntangibleAssetInvariants.validate_acquisition_date(FIXED_FUTURE)
        assert result.is_valid is False
        assert "future" in result.errors[0]

    # Cost
    def test_validate_cost_valid(self):
        result = IntangibleAssetInvariants.validate_cost(Decimal("1000"))
        assert result.is_valid is True

    def test_validate_cost_zero(self):
        result = IntangibleAssetInvariants.validate_cost(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]

    # Residual value
    def test_validate_residual_value_valid(self):
        result = IntangibleAssetInvariants.validate_residual_value(Decimal("100"), Decimal("1000"))
        assert result.is_valid is True

    def test_validate_residual_value_negative(self):
        result = IntangibleAssetInvariants.validate_residual_value(Decimal("-10"), Decimal("1000"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_residual_value_exceeds_cost(self):
        result = IntangibleAssetInvariants.validate_residual_value(Decimal("1500"), Decimal("1000"))
        assert result.is_valid is False
        assert "cannot exceed" in result.errors[0]

    # Useful life
    @pytest.mark.parametrize("years, asset_type, method, expected_valid, warning_contains", [
        (20, IntangibleAssetType.PATENT, AmortizationMethod.STRAIGHT_LINE, True, None),
        (0, IntangibleAssetType.GOODWILL, AmortizationMethod.NO_AMORTIZATION, True, None),
        (0, IntangibleAssetType.PATENT, AmortizationMethod.NO_AMORTIZATION, True, None),  # indefinite life
        (-1, IntangibleAssetType.PATENT, AmortizationMethod.STRAIGHT_LINE, False, None),
        (150, IntangibleAssetType.PATENT, AmortizationMethod.STRAIGHT_LINE, True, "unusually long"),
    ])
    def test_validate_useful_life(self, years, asset_type, method, expected_valid, warning_contains):
        result = IntangibleAssetInvariants.validate_useful_life(years, asset_type, method)
        assert result.is_valid == expected_valid
        if warning_contains:
            assert any(warning_contains in w for w in result.warnings)
        if not expected_valid:
            assert result.errors != []

    # Amortization method
    @pytest.mark.parametrize("method, asset_type, useful_life, expected_valid, error_contains", [
        (AmortizationMethod.STRAIGHT_LINE, IntangibleAssetType.PATENT, 20, True, None),
        (AmortizationMethod.STRAIGHT_LINE, IntangibleAssetType.GOODWILL, 0, False, "Goodwill must use NO_AMORTIZATION"),
        (AmortizationMethod.STRAIGHT_LINE, IntangibleAssetType.PATENT, 0, False, "indefinite life must use NO_AMORTIZATION"),
    ])
    def test_validate_amortization_method(self, method, asset_type, useful_life, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_amortization_method(method, asset_type, useful_life)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    def test_validate_amortization_method_invalid_enum(self):
        result = IntangibleAssetInvariants.validate_amortization_method("INVALID", IntangibleAssetType.PATENT, 20)
        assert result.is_valid is False

    # Accumulated amortization
    @pytest.mark.parametrize("acc_amort, cost, residual, expected_valid, error_contains", [
        (Decimal("1000"), Decimal("10000"), Decimal("500"), True, None),
        (Decimal("-100"), Decimal("10000"), Decimal("500"), False, "negative"),
        (Decimal("10000"), Decimal("10000"), Decimal("500"), False, "exceeds amortizable amount"),
    ])
    def test_validate_accumulated_amortization(self, acc_amort, cost, residual, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_accumulated_amortization(acc_amort, cost, residual)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # NBV
    @pytest.mark.parametrize("nbv, cost, acc_amort, expected_valid, error_contains", [
        (Decimal("9000"), Decimal("10000"), Decimal("1000"), True, None),
        (Decimal("8000"), Decimal("10000"), Decimal("1000"), False, "mismatch"),
        (Decimal("-100"), Decimal("10000"), Decimal("9000"), False, "cannot be negative"),
    ])
    def test_validate_nbv(self, nbv, cost, acc_amort, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_nbv(nbv, cost, acc_amort)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Asset code unique
    def test_validate_asset_code_unique_valid(self):
        result = IntangibleAssetInvariants.validate_asset_code_unique("PAT-001", {"PAT-002"})
        assert result.is_valid is True

    def test_validate_asset_code_unique_duplicate(self):
        result = IntangibleAssetInvariants.validate_asset_code_unique("PAT-001", {"PAT-001"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    # Disposal allowed
    def test_validate_disposal_allowed_not_disposed(self):
        asset = create_mock_asset(status=IntangibleAssetStatus.ACTIVE)
        result = IntangibleAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid is True

    def test_validate_disposal_allowed_already_disposed(self):
        asset = create_mock_asset(status=IntangibleAssetStatus.DISPOSED)
        result = IntangibleAssetInvariants.validate_disposal_allowed(asset)
        assert result.is_valid is False
        assert "already disposed" in result.errors[0]

    # Impairment allowed
    @pytest.mark.parametrize("loss, nbv, status, can_impair, expected_valid, error_contains", [
        (Decimal("20000"), Decimal("100000"), IntangibleAssetStatus.ACTIVE, True, True, None),
        (Decimal("0"), Decimal("100000"), IntangibleAssetStatus.ACTIVE, True, False, "positive"),
        (Decimal("60000"), Decimal("50000"), IntangibleAssetStatus.ACTIVE, True, False, "exceeds NBV"),
        (Decimal("1000"), Decimal("100000"), IntangibleAssetStatus.DISPOSED, False, False, "cannot be impaired"),
    ])
    def test_validate_impairment_allowed(self, loss, nbv, status, can_impair, expected_valid, error_contains):
        asset = create_mock_asset(nbv=nbv, status=status)
        asset.status.can_impair.return_value = can_impair
        result = IntangibleAssetInvariants.validate_impairment_allowed(asset, loss)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Amortization allowed
    @pytest.mark.parametrize("amount, has_indefinite_life, status, can_amortize, remaining, expected_valid, error_contains", [
        (Decimal("5000"), False, IntangibleAssetStatus.ACTIVE, True, Decimal("100000"), True, None),
        (Decimal("0"), False, IntangibleAssetStatus.ACTIVE, True, Decimal("100000"), False, "positive"),
        (Decimal("1000"), True, IntangibleAssetStatus.ACTIVE, True, Decimal("100000"), False, "indefinite life"),
        (Decimal("1000"), False, IntangibleAssetStatus.DISPOSED, False, Decimal("100000"), False, "cannot be amortized"),
        (Decimal("15000"), False, IntangibleAssetStatus.ACTIVE, True, Decimal("10000"), False, "exceeds remaining amortizable"),
    ])
    def test_validate_amortization_allowed(self, amount, has_indefinite_life, status, can_amortize, remaining, expected_valid, error_contains):
        asset = create_mock_asset(
            status=status,
            has_indefinite_life=has_indefinite_life,
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            accumulated_amortization=Decimal("0"),
        )
        asset.status.can_amortize.return_value = can_amortize
        asset.remaining_amortizable = remaining
        result = IntangibleAssetInvariants.validate_amortization_allowed(asset, amount)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)

    # Expiry date
    @pytest.mark.parametrize("expiry, acquisition, expected_valid, error_contains", [
        (FIXED_FUTURE, FIXED_PAST, True, None),
        (None, FIXED_PAST, True, None),
        (FIXED_PAST, FIXED_FUTURE, False, "must be after"),
    ])
    def test_validate_expiry_date(self, expiry, acquisition, expected_valid, error_contains):
        result = IntangibleAssetInvariants.validate_expiry_date(expiry, acquisition)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for Status Transition Validation
# =============================================================================

class TestStatusTransition:
    def test_transition_definition_consistency(self):
        for status in IntangibleAssetStatus:
            assert status in ALLOWED_STATUS_TRANSITIONS, f"Missing transition for {status}"
        for targets in ALLOWED_STATUS_TRANSITIONS.values():
            for t in targets:
                assert isinstance(t, IntangibleAssetStatus)

    @pytest.mark.parametrize("from_status,to_status,user_role,expected_valid,error_contains", [
        (IntangibleAssetStatus.PENDING_ACTIVATION, IntangibleAssetStatus.ACTIVE, "finance_manager", True, None),
        (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.FULLY_AMORTIZED, "user", True, None),
        (IntangibleAssetStatus.PENDING_ACTIVATION, IntangibleAssetStatus.ACTIVE, "user", False, "requires role"),
        (IntangibleAssetStatus.PENDING_ACTIVATION, IntangibleAssetStatus.ACTIVE, "admin", True, None),
        (IntangibleAssetStatus.FULLY_AMORTIZED, IntangibleAssetStatus.ACTIVE, "admin", False, "not allowed"),
        (IntangibleAssetStatus.ACTIVE, IntangibleAssetStatus.ACTIVE, "user", False, "not allowed"),
        (IntangibleAssetStatus.DISPOSED, IntangibleAssetStatus.ACTIVE, "admin", False, "not allowed"),
    ])
    def test_validate_status_transition(self, from_status, to_status, user_role, expected_valid, error_contains):
        result = validate_status_transition(from_status, to_status, user_role)
        assert result.is_valid == expected_valid
        if not expected_valid and error_contains:
            assert any(error_contains in e for e in result.errors)


# =============================================================================
# Tests for IntangibleAssetInvariantEnforcer (Async)
# =============================================================================

@pytest.mark.asyncio
class TestIntangibleAssetInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        existing_codes = {"EXISTING-001", "EXISTING-002"}
        get_codes = AsyncMock(return_value=existing_codes)
        return IntangibleAssetInvariantEnforcer(get_existing_codes=get_codes)

    async def test_enforce_asset_create_valid(self, enforcer):
        asset = create_mock_asset(
            asset_code="NEW-001",
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            useful_life_years=20,
            amortization_method=AmortizationMethod.STRAIGHT_LINE,
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
            cost=Decimal("-1000"),
            residual_value=Decimal("2000"),
        )
        result = await enforcer.enforce_asset_create(asset)
        assert result.is_valid is False
        assert len(result.errors) >= 3

    async def test_enforce_asset_update_valid(self, enforcer):
        asset = create_mock_asset()
        result = await enforcer.enforce_asset_update(asset)
        assert result.is_valid is True

    async def test_enforce_asset_update_invalid(self, enforcer):
        asset = create_mock_asset(asset_name="", cost=Decimal("-100"))
        result = await enforcer.enforce_asset_update(asset)
        assert result.is_valid is False

    async def test_enforce_amortization_valid(self, enforcer):
        asset = create_mock_asset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            accumulated_amortization=Decimal("0"),
        )
        asset.remaining_amortizable = Decimal("100000")
        result = await enforcer.enforce_amortization(asset, Decimal("5000"))
        assert result.is_valid is True

    async def test_enforce_amortization_exceeds_remaining(self, enforcer):
        asset = create_mock_asset(
            cost=Decimal("100000"),
            residual_value=Decimal("0"),
            accumulated_amortization=Decimal("95000"),
        )
        asset.remaining_amortizable = Decimal("5000")
        result = await enforcer.enforce_amortization(asset, Decimal("10000"))
        assert result.is_valid is False
        assert "exceeds remaining amortizable" in result.errors[0]

    async def test_enforce_impairment_valid(self, enforcer):
        asset = create_mock_asset(nbv=Decimal("100000"))
        result = await enforcer.enforce_impairment(asset, Decimal("20000"))
        assert result.is_valid is True

    async def test_enforce_impairment_exceeds_nbv(self, enforcer):
        asset = create_mock_asset(nbv=Decimal("50000"))
        result = await enforcer.enforce_impairment(asset, Decimal("60000"))
        assert result.is_valid is False
        assert "exceeds NBV" in result.errors[0]

    async def test_enforce_disposal_allowed(self, enforcer):
        asset = create_mock_asset(status=IntangibleAssetStatus.ACTIVE)
        result = await enforcer.enforce_disposal(asset)
        assert result.is_valid is True

    async def test_enforce_disposal_already_disposed(self, enforcer):
        asset = create_mock_asset(status=IntangibleAssetStatus.DISPOSED)
        result = await enforcer.enforce_disposal(asset)
        assert result.is_valid is False

    async def test_enforce_status_transition_valid(self, enforcer):
        result = await enforcer.enforce_status_transition(
            IntangibleAssetStatus.PENDING_ACTIVATION,
            IntangibleAssetStatus.ACTIVE,
            user_role="finance_manager",
        )
        assert result.is_valid is True

    async def test_enforce_status_transition_invalid(self, enforcer):
        result = await enforcer.enforce_status_transition(
            IntangibleAssetStatus.FULLY_AMORTIZED,
            IntangibleAssetStatus.ACTIVE,
        )
        assert result.is_valid is False


# =============================================================================
# Tests for IntangibleAssetInvariantsValidator (Sync)
# =============================================================================

class TestIntangibleAssetInvariantsValidator:
    # For valid cases, we call the function and assert no exception (with assert True)
    def test_validate_asset_cost_valid(self):
        asset = create_mock_asset(cost=Decimal("1000"), residual_value=Decimal("100"))
        IntangibleAssetInvariantsValidator.validate_asset_cost(asset)
        assert True

    def test_validate_asset_cost_negative(self):
        asset = create_mock_asset(cost=Decimal("-100"))
        with pytest.raises(ValueError, match="positive"):
            IntangibleAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_asset_cost_residual_negative(self):
        asset = create_mock_asset(cost=Decimal("1000"), residual_value=Decimal("-10"))
        with pytest.raises(ValueError, match="cannot be negative"):
            IntangibleAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_asset_cost_residual_exceeds_cost(self):
        asset = create_mock_asset(cost=Decimal("1000"), residual_value=Decimal("1500"))
        with pytest.raises(ValueError, match="cannot exceed"):
            IntangibleAssetInvariantsValidator.validate_asset_cost(asset)

    def test_validate_useful_life_valid(self):
        asset = create_mock_asset(
            asset_type=IntangibleAssetType.PATENT,
            useful_life_years=20,
            has_indefinite_life=False,
        )
        IntangibleAssetInvariantsValidator.validate_useful_life(asset)
        assert True

    def test_validate_useful_life_goodwill_skips(self):
        asset = create_mock_asset(asset_type=IntangibleAssetType.GOODWILL, useful_life_years=0)
        IntangibleAssetInvariantsValidator.validate_useful_life(asset)
        assert True

    def test_validate_useful_life_indefinite_skips(self):
        asset = create_mock_asset(
            asset_type=IntangibleAssetType.PATENT,
            useful_life_years=0,
            has_indefinite_life=True,
        )
        IntangibleAssetInvariantsValidator.validate_useful_life(asset)
        assert True

    def test_validate_useful_life_zero_for_amortizable(self):
        asset = create_mock_asset(
            asset_type=IntangibleAssetType.PATENT,
            useful_life_years=0,
            has_indefinite_life=False,
        )
        with pytest.raises(ValueError, match="positive"):
            IntangibleAssetInvariantsValidator.validate_useful_life(asset)

    def test_validate_amortization_method_valid(self):
        asset = create_mock_asset(amortization_method=AmortizationMethod.STRAIGHT_LINE)
        IntangibleAssetInvariantsValidator.validate_amortization_method(asset)
        assert True

    def test_validate_amortization_method_invalid(self):
        asset = create_mock_asset()
        asset.amortization_method.value = "invalid"
        with pytest.raises(ValueError, match="Invalid"):
            IntangibleAssetInvariantsValidator.validate_amortization_method(asset)

    def test_validate_amortization_amount_valid(self):
        asset = create_mock_asset()
        asset.remaining_amortizable = Decimal("10000")
        IntangibleAssetInvariantsValidator.validate_amortization_amount(asset, Decimal("5000"))
        assert True

    def test_validate_amortization_amount_negative(self):
        asset = create_mock_asset()
        with pytest.raises(ValueError, match="cannot be negative"):
            IntangibleAssetInvariantsValidator.validate_amortization_amount(asset, Decimal("-100"))

    def test_validate_amortization_amount_indefinite_life(self):
        asset = create_mock_asset(has_indefinite_life=True)
        with pytest.raises(ValueError, match="indefinite life"):
            IntangibleAssetInvariantsValidator.validate_amortization_amount(asset, Decimal("1000"))

    def test_validate_amortization_amount_exceeds_remaining(self):
        asset = create_mock_asset()
        asset.remaining_amortizable = Decimal("1000")
        with pytest.raises(ValueError, match="exceeds remaining"):
            IntangibleAssetInvariantsValidator.validate_amortization_amount(asset, Decimal("2000"))

    def test_validate_asset_code_unique_valid(self):
        IntangibleAssetInvariantsValidator.validate_asset_code_unique("NEW", {"EXISTING"})
        assert True

    def test_validate_asset_code_unique_duplicate(self):
        with pytest.raises(ValueError, match="already exists"):
            IntangibleAssetInvariantsValidator.validate_asset_code_unique("EXISTING", {"EXISTING"})

    def test_validate_impairment_valid(self):
        asset = create_mock_asset(nbv=Decimal("100000"))
        IntangibleAssetInvariantsValidator.validate_impairment(asset, Decimal("20000"))
        assert True

    def test_validate_impairment_loss_zero(self):
        asset = create_mock_asset()
        with pytest.raises(ValueError, match="positive"):
            IntangibleAssetInvariantsValidator.validate_impairment(asset, Decimal("0"))

    def test_validate_impairment_loss_exceeds_nbv(self):
        asset = create_mock_asset(nbv=Decimal("50000"))
        with pytest.raises(ValueError, match="exceeds NBV"):
            IntangibleAssetInvariantsValidator.validate_impairment(asset, Decimal("60000"))

    def test_validate_impairment_status_disallows(self):
        asset = create_mock_asset(status=IntangibleAssetStatus.DISPOSED)
        asset.status.can_impair.return_value = False
        with pytest.raises(ValueError, match="cannot be impaired"):
            IntangibleAssetInvariantsValidator.validate_impairment(asset, Decimal("1000"))

    def test_validate_disposal_valid(self):
        asset = create_mock_asset(status=IntangibleAssetStatus.ACTIVE)
        IntangibleAssetInvariantsValidator.validate_disposal(asset)
        assert True

    def test_validate_disposal_already_disposed(self):
        asset = create_mock_asset(status=IntangibleAssetStatus.DISPOSED)
        with pytest.raises(ValueError, match="already disposed"):
            IntangibleAssetInvariantsValidator.validate_disposal(asset)

    def test_validate_nbv_non_negative(self):
        asset = create_mock_asset(nbv=Decimal("1000"))
        IntangibleAssetInvariantsValidator.validate_nbv(asset)
        assert True

    def test_validate_nbv_negative(self):
        asset = create_mock_asset(nbv=Decimal("-100"))
        with pytest.raises(ValueError, match="cannot be negative"):
            IntangibleAssetInvariantsValidator.validate_nbv(asset)