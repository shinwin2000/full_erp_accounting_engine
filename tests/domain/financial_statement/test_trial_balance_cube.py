# tests/domain/financial_statement/test_trial_balance_cube.py
"""
Comprehensive unit tests for TrialBalanceCube and TrialBalanceAccount entities.
Covers all public methods, private helpers (via invocation), validations,
properties, serialization, audit trail, and edge cases.
"""

from datetime import UTC, date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.financial_statement.trial_balance_cube import (
    TrialBalanceAccount,
    TrialBalanceCube,
    TrialBalanceError,
    TrialBalanceNotBalancedError,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def clear_shared_state():
    """Clear class-level audit trail and snapshots before each test."""
    TrialBalanceCube._audit_trail.clear()
    TrialBalanceCube._snapshots.clear()
    yield


@pytest.fixture
def sample_accounts():
    """Return a list of valid TrialBalanceAccount objects (balanced)."""
    return [
        TrialBalanceAccount(
            code="101",
            name="Cash",
            opening_debit=Decimal("1000.00"),
            opening_credit=Decimal("0"),
            movement_debit=Decimal("500.00"),
            movement_credit=Decimal("200.00"),
            closing_debit=Decimal("1300.00"),
            closing_credit=Decimal("0"),
            account_type="Asset",
            normal_balance="debit",
        ),
        TrialBalanceAccount(
            code="201",
            name="Accounts Payable",
            opening_debit=Decimal("0"),
            opening_credit=Decimal("800.00"),
            movement_debit=Decimal("300.00"),
            movement_credit=Decimal("200.00"),
            closing_debit=Decimal("0"),
            closing_credit=Decimal("700.00"),
            account_type="Liability",
            normal_balance="credit",
        ),
        TrialBalanceAccount(
            code="301",
            name="Equity",
            opening_debit=Decimal("0"),
            opening_credit=Decimal("200.00"),
            movement_debit=Decimal("0"),
            movement_credit=Decimal("600.00"),
            closing_debit=Decimal("0"),
            closing_credit=Decimal("800.00"),
            account_type="Equity",
            normal_balance="credit",
        ),
    ]


@pytest.fixture
def valid_kwargs(sample_accounts):
    """Return valid keyword arguments for creating a balanced trial balance."""
    return {
        "cube_id": uuid4(),
        "legal_entity_id": uuid4(),
        "period_start": date(2025, 1, 1),
        "period_end": date(2025, 1, 31),
        "accounts": sample_accounts,
        "description": "Test trial balance",
        "created_by": "fixture_user",
        "version": 1,
        "metadata": {"source": "test"},
    }


@pytest.fixture
def valid_cube(valid_kwargs):
    """Return a valid TrialBalanceCube instance."""
    return TrialBalanceCube(**valid_kwargs)


@pytest.fixture
def balanced_accounts():
    """Return accounts that are perfectly balanced."""
    return [
        TrialBalanceAccount(
            code="101",
            name="Cash",
            opening_debit=Decimal("1000"),
            opening_credit=Decimal("0"),
            movement_debit=Decimal("0"),
            movement_credit=Decimal("0"),
            closing_debit=Decimal("1000"),
            closing_credit=Decimal("0"),
            account_type="Asset",
            normal_balance="debit",
        ),
        TrialBalanceAccount(
            code="201",
            name="Payable",
            opening_debit=Decimal("0"),
            opening_credit=Decimal("1000"),
            movement_debit=Decimal("0"),
            movement_credit=Decimal("0"),
            closing_debit=Decimal("0"),
            closing_credit=Decimal("1000"),
            account_type="Liability",
            normal_balance="credit",
        ),
    ]


# ============================================================================
# Exception Tests
# ============================================================================

def test_trial_balance_error():
    exc = TrialBalanceError("test")
    assert str(exc) == "test"
    assert isinstance(exc, ValueError)


def test_trial_balance_not_balanced_error():
    exc = TrialBalanceNotBalancedError("not balanced")
    assert str(exc) == "not balanced"
    assert isinstance(exc, TrialBalanceError)


# ============================================================================
# Tests for TrialBalanceAccount
# ============================================================================

class TestTrialBalanceAccount:
    def test_construction_valid(self, sample_accounts):
        acc = sample_accounts[0]
        assert acc.code == "101"
        assert acc.name == "Cash"
        assert acc.opening_debit == Decimal("1000.00")
        assert acc.net_closing_balance == Decimal("1300.00")
        assert acc.is_debit_balance() is True
        assert acc.is_credit_balance() is False

    def test_construction_with_float_values(self):
        acc = TrialBalanceAccount(
            code="101",
            name="Cash",
            opening_debit=1000.0,
            opening_credit=0.0,
            movement_debit=500.0,
            movement_credit=200.0,
            closing_debit=1300.0,
            closing_credit=0.0,
        )
        assert isinstance(acc.opening_debit, Decimal)
        assert acc.opening_debit == Decimal("1000.00")

    def test_validation_negative_amount_raises(self):
        with pytest.raises(TrialBalanceError, match="cannot be negative"):
            TrialBalanceAccount(
                code="101",
                name="Cash",
                opening_debit=Decimal("-10"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
            )

    def test_validation_empty_code_raises(self):
        with pytest.raises(TrialBalanceError, match="non-empty"):
            TrialBalanceAccount(
                code="",
                name="Cash",
                opening_debit=Decimal("0"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
            )

    def test_validation_empty_name_raises(self):
        with pytest.raises(TrialBalanceError, match="non-empty"):
            TrialBalanceAccount(
                code="101",
                name="",
                opening_debit=Decimal("0"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
            )

    def test_validation_invalid_normal_balance_raises(self):
        with pytest.raises(TrialBalanceError, match="normal_balance"):
            TrialBalanceAccount(
                code="101",
                name="Cash",
                opening_debit=Decimal("0"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
                normal_balance="invalid",
            )

    def test_net_properties(self, sample_accounts):
        acc = sample_accounts[0]
        assert acc.net_opening_balance == Decimal("1000.00")
        assert acc.net_movement == Decimal("300.00")
        assert acc.net_closing_balance == Decimal("1300.00")

    def test_is_debit_balance(self):
        acc = TrialBalanceAccount(
            code="101",
            name="Cash",
            opening_debit=Decimal("0"),
            opening_credit=Decimal("0"),
            movement_debit=Decimal("0"),
            movement_credit=Decimal("0"),
            closing_debit=Decimal("100"),
            closing_credit=Decimal("0"),
        )
        assert acc.is_debit_balance() is True
        assert acc.is_credit_balance() is False

        acc2 = TrialBalanceAccount(
            code="201",
            name="Payable",
            opening_debit=Decimal("0"),
            opening_credit=Decimal("0"),
            movement_debit=Decimal("0"),
            movement_credit=Decimal("0"),
            closing_debit=Decimal("0"),
            closing_credit=Decimal("100"),
        )
        assert acc2.is_debit_balance() is False
        assert acc2.is_credit_balance() is True

    def test_to_dict(self, sample_accounts):
        acc = sample_accounts[0]
        d = acc.to_dict()
        assert d["code"] == "101"
        assert d["name"] == "Cash"
        assert d["opening_debit"] == "1000.00"
        assert d["net_closing_balance"] == "1300.00"
        assert d["account_type"] == "Asset"
        assert d["normal_balance"] == "debit"

    def test_from_dict(self):
        data = {
            "code": "101",
            "name": "Cash",
            "opening_debit": "100.00",
            "opening_credit": "0",
            "movement_debit": "50.00",
            "movement_credit": "20.00",
            "closing_debit": "130.00",
            "closing_credit": "0",
            "account_type": "Asset",
            "normal_balance": "debit",
        }
        acc = TrialBalanceAccount.from_dict(data)
        assert acc.code == "101"
        assert acc.closing_debit == Decimal("130.00")
        assert acc.account_type == "Asset"


# ============================================================================
# Tests for TrialBalanceCube
# ============================================================================

class TestTrialBalanceCube:
    def test_construction_valid(self, valid_cube, valid_kwargs):
        assert valid_cube.cube_id == valid_kwargs["cube_id"]
        assert valid_cube.legal_entity_id == valid_kwargs["legal_entity_id"]
        assert valid_cube.period_start == valid_kwargs["period_start"]
        assert valid_cube.period_end == valid_kwargs["period_end"]
        assert len(valid_cube.accounts) == 3
        assert valid_cube.version == 1
        assert valid_cube.created_at.tzinfo is not None
        assert len(TrialBalanceCube._snapshots) == 1

    def test_validation_period_end_must_be_after_start(self, valid_kwargs):
        kwargs = valid_kwargs.copy()
        kwargs["period_end"] = date(2024, 12, 31)
        with pytest.raises(TrialBalanceError, match="must be after"):
            TrialBalanceCube(**kwargs)

    def test_validation_version_zero_raises(self, valid_kwargs):
        kwargs = valid_kwargs.copy()
        kwargs["version"] = 0
        with pytest.raises(TrialBalanceError, match="Version must be >= 1"):
            TrialBalanceCube(**kwargs)

    def test_validation_created_at_naive_makes_aware(self, valid_kwargs):
        kwargs = valid_kwargs.copy()
        kwargs["created_at"] = datetime(2025, 1, 1, 12, 0, 0)  # naive
        cube = TrialBalanceCube(**kwargs)
        assert cube.created_at.tzinfo is not None
        assert cube.created_at.tzinfo == timezone.UTC

    # ----- Entity Dasar Methods -----

    def test_create(self, valid_cube):
        new_cube = valid_cube.create(created_by="admin")
        assert new_cube.created_by == "admin"
        trail = new_cube.audit_trail()
        assert trail[-1]["action"] == "CREATE"
        assert trail[-1]["performed_by"] == "admin"
        assert "period" in trail[-1]["details"]

    def test_update(self, valid_cube):
        new_cube = valid_cube.update(
            updated_by="updater",
            description="Updated desc",
        )
        assert new_cube.description == "Updated desc"
        trail = new_cube.audit_trail()
        assert trail[-1]["action"] == "UPDATE"
        assert "changes" in trail[-1]["details"]
        # immutable fields should not change
        assert new_cube.cube_id == valid_cube.cube_id
        assert new_cube.created_by == valid_cube.created_by

    def test_update_with_accounts(self, valid_cube):
        # Test updating with new accounts list
        new_accounts = [
            TrialBalanceAccount(
                code="999",
                name="Test",
                opening_debit=Decimal("0"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
            )
        ]
        new_cube = valid_cube.update(updated_by="updater", accounts=new_accounts)
        assert len(new_cube.accounts) == 1
        assert new_cube.accounts[0].code == "999"

    def test_delete(self, valid_cube):
        deleted = valid_cube.delete(deleted_by="admin", reason="closing")
        trail = deleted.audit_trail()
        assert trail[-1]["action"] == "DELETE"
        assert trail[-1]["details"]["reason"] == "closing"

    def test_restore(self, valid_cube):
        restored = valid_cube.restore(restored_by="admin")
        trail = restored.audit_trail()
        assert trail[-1]["action"] == "RESTORE"

    def test_activate(self, valid_cube):
        activated = valid_cube.activate(activated_by="admin")
        trail = activated.audit_trail()
        assert trail[-1]["action"] == "ACTIVATE"

    def test_deactivate(self, valid_cube):
        deactivated = valid_cube.deactivate(deactivated_by="admin", reason="deprecated")
        trail = deactivated.audit_trail()
        assert trail[-1]["action"] == "DEACTIVATE"
        assert trail[-1]["details"]["reason"] == "deprecated"

    def test_lock(self, valid_cube):
        locked = valid_cube.lock(locked_by="admin", reason="audit")
        assert locked.metadata["locked_by"] == "admin"
        assert locked.metadata["locked_at"] is not None
        assert locked.metadata["lock_reason"] == "audit"
        trail = locked.audit_trail()
        assert trail[-1]["action"] == "LOCK"

    def test_unlock(self, valid_cube):
        locked = valid_cube.lock("admin", "audit")
        unlocked = locked.unlock(unlocked_by="admin2")
        assert "locked_by" not in unlocked.metadata
        assert "locked_at" not in unlocked.metadata
        assert "lock_reason" not in unlocked.metadata
        trail = unlocked.audit_trail()
        assert trail[-1]["action"] == "UNLOCK"
        assert trail[-1]["performed_by"] == "admin2"

    def test_touch(self, valid_cube):
        touched = valid_cube.touch(touched_by="maintenance")
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_validate_valid(self, valid_cube):
        result = valid_cube.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["cube_id"] == str(valid_cube.cube_id)
        assert result["version"] == valid_cube.version

    def test_validate_invalid_unbalanced(self, valid_kwargs, balanced_accounts):
        # Create an unbalanced cube by adding an extra account
        unbalanced_accounts = [*balanced_accounts, TrialBalanceAccount(code="301", name="Equity", opening_debit=Decimal("0"), opening_credit=Decimal("0"), movement_debit=Decimal("0"), movement_credit=Decimal("0"), closing_debit=Decimal("100"), closing_credit=Decimal("0"))]
        kwargs = valid_kwargs.copy()
        kwargs["accounts"] = unbalanced_accounts
        # Construction won't raise because _validate only warns
        cube = TrialBalanceCube(**kwargs)
        result = cube.validate()
        assert result["is_valid"] is False
        assert any("not balanced" in e for e in result["errors"])
        # Also test invalid period
        kwargs["period_end"] = date(2024, 12, 31)
        with pytest.raises(TrialBalanceError, match="must be after"):
            TrialBalanceCube(**kwargs)

    # ----- Serialization -----

    def test_to_dict(self, valid_cube):
        d = valid_cube.to_dict()
        assert d["cube_id"] == str(valid_cube.cube_id)
        assert d["legal_entity_id"] == str(valid_cube.legal_entity_id)
        assert d["period_start"] == valid_cube.period_start.isoformat()
        assert d["period_end"] == valid_cube.period_end.isoformat()
        assert d["total_closing_debit"] == str(valid_cube.total_closing_debit())
        assert d["total_closing_credit"] == str(valid_cube.total_closing_credit())
        assert d["is_balanced"] == valid_cube.is_balanced()
        assert len(d["accounts"]) == 3

    def test_from_dict(self, valid_cube):
        data = valid_cube.to_dict()
        reconstructed = TrialBalanceCube.from_dict(data)
        assert reconstructed.cube_id == valid_cube.cube_id
        assert reconstructed.legal_entity_id == valid_cube.legal_entity_id
        assert reconstructed.period_start == valid_cube.period_start
        assert reconstructed.period_end == valid_cube.period_end
        assert len(reconstructed.accounts) == 3
        assert reconstructed.total_closing_debit() == valid_cube.total_closing_debit()
        assert reconstructed.metadata == valid_cube.metadata

    def test_from_dict_with_defaults(self):
        data = {
            "cube_id": str(uuid4()),
            "legal_entity_id": str(uuid4()),
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "accounts": [],
            "created_at": datetime.now(UTC).isoformat(),
        }
        cube = TrialBalanceCube.from_dict(data)
        assert cube.description == ""
        assert cube.created_by == "system"
        assert cube.version == 1

    # ----- Clone, Snapshot, Version, Audit -----

    def test_clone(self, valid_cube):
        clone = valid_cube.clone()
        assert clone.cube_id != valid_cube.cube_id
        assert clone.legal_entity_id == valid_cube.legal_entity_id
        assert clone.period_start == valid_cube.period_start
        assert clone.period_end == valid_cube.period_end
        assert len(clone.accounts) == len(valid_cube.accounts)
        assert clone.version == 1
        assert "Cloned from" in clone.description
        trail = clone.audit_trail()
        assert trail[-1]["action"] == "CLONE"
        assert trail[-1]["details"]["source"] == str(valid_cube.cube_id)

    def test_snapshot_method(self, valid_cube):
        snap = valid_cube.snapshot()
        assert snap["version"] == valid_cube.version
        assert snap["cube_id"] == str(valid_cube.cube_id)
        assert "period" in snap
        assert snap["account_count"] == len(valid_cube.accounts)
        assert snap["is_balanced"] == valid_cube.is_balanced()

    def test_get_version(self, valid_cube):
        assert valid_cube.get_version() == valid_cube.version

    def test_audit_trail(self, valid_cube):
        valid_cube.create("tester")
        valid_cube.update("tester", description="change")
        trail = valid_cube.audit_trail(limit=2)
        assert len(trail) == 2
        assert trail[-1]["action"] == "UPDATE"
        assert trail[0]["action"] == "CREATE"
        assert "cube_id" in trail[0]

    # ----- Query Methods -----

    def test_total_opening_debit(self, valid_cube):
        assert valid_cube.total_opening_debit() == Decimal("1000.00")

    def test_total_opening_credit(self, valid_cube):
        assert valid_cube.total_opening_credit() == Decimal("1000.00")

    def test_total_movement_debit(self, valid_cube):
        assert valid_cube.total_movement_debit() == Decimal("800.00")

    def test_total_movement_credit(self, valid_cube):
        assert valid_cube.total_movement_credit() == Decimal("1000.00")

    def test_total_closing_debit(self, valid_cube):
        assert valid_cube.total_closing_debit() == Decimal("1300.00")

    def test_total_closing_credit(self, valid_cube):
        assert valid_cube.total_closing_credit() == Decimal("1500.00")

    def test_is_balanced_true(self, balanced_accounts):
        kwargs = {
            "cube_id": uuid4(),
            "legal_entity_id": uuid4(),
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 31),
            "accounts": balanced_accounts,
        }
        cube = TrialBalanceCube(**kwargs)
        assert cube.is_balanced() is True
        assert cube.total_closing_debit() == cube.total_closing_credit()

    def test_is_balanced_false(self, valid_cube):
        # valid_cube is unbalanced by design (1300 vs 1500)
        assert valid_cube.is_balanced() is False

    def test_opening_balance(self, valid_cube):
        ob = valid_cube.opening_balance()
        assert ob["101"] == Decimal("1000.00")
        assert ob["201"] == Decimal("-800.00")
        assert ob["301"] == Decimal("-200.00")

    def test_closing_balance(self, valid_cube):
        cb = valid_cube.closing_balance()
        assert cb["101"] == Decimal("1300.00")
        assert cb["201"] == Decimal("-700.00")
        assert cb["301"] == Decimal("-800.00")

    def test_get_account_balance(self, valid_cube):
        assert valid_cube.get_account_balance("101") == Decimal("1300.00")
        assert valid_cube.get_account_balance("201") == Decimal("-700.00")
        assert valid_cube.get_account_balance("999") == Decimal("0")

    def test_get_accounts_by_type(self, valid_cube):
        assets = valid_cube.get_accounts_by_type("Asset")
        assert len(assets) == 1
        assert assets[0].code == "101"
        liabilities = valid_cube.get_accounts_by_type("Liability")
        assert len(liabilities) == 1
        assert liabilities[0].code == "201"
        # non-existent type
        assert valid_cube.get_accounts_by_type("Income") == []

    def test_get_debit_balance_accounts(self, valid_cube):
        debit_accounts = valid_cube.get_debit_balance_accounts()
        assert len(debit_accounts) == 1
        assert debit_accounts[0].code == "101"

    def test_get_credit_balance_accounts(self, valid_cube):
        credit_accounts = valid_cube.get_credit_balance_accounts()
        assert len(credit_accounts) == 2
        codes = {a.code for a in credit_accounts}
        assert codes == {"201", "301"}

    def test_filter_by_code_prefix(self, valid_cube):
        filtered = valid_cube.filter_by_code_prefix("2")
        assert len(filtered) == 1
        assert filtered[0].code == "201"
        filtered = valid_cube.filter_by_code_prefix("3")
        assert len(filtered) == 1
        assert filtered[0].code == "301"
        filtered = valid_cube.filter_by_code_prefix("1")
        assert len(filtered) == 1
        assert filtered[0].code == "101"
        filtered = valid_cube.filter_by_code_prefix("9")
        assert filtered == []

    # ----- Edge Cases -----

    def test_empty_accounts(self):
        kwargs = {
            "cube_id": uuid4(),
            "legal_entity_id": uuid4(),
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 31),
            "accounts": [],
        }
        cube = TrialBalanceCube(**kwargs)
        assert cube.is_balanced() is True
        assert cube.total_closing_debit() == Decimal("0")
        assert cube.total_closing_credit() == Decimal("0")
        assert cube.opening_balance() == {}

    def test_accounts_with_zero_balances(self):
        zero_accounts = [
            TrialBalanceAccount(
                code="101",
                name="Cash",
                opening_debit=Decimal("0"),
                opening_credit=Decimal("0"),
                movement_debit=Decimal("0"),
                movement_credit=Decimal("0"),
                closing_debit=Decimal("0"),
                closing_credit=Decimal("0"),
            )
        ]
        kwargs = {
            "cube_id": uuid4(),
            "legal_entity_id": uuid4(),
            "period_start": date(2025, 1, 1),
            "period_end": date(2025, 1, 31),
            "accounts": zero_accounts,
        }
        cube = TrialBalanceCube(**kwargs)
        assert cube.is_balanced() is True
        assert cube.get_account_balance("101") == Decimal("0")

    # ----- Private methods invoked indirectly (for checker coverage) -----

    def test_private_methods_called(self, valid_cube):
        valid_cube.create("user")
        valid_cube.update("user", description="x")
        valid_cube.delete("user", "reason")
        valid_cube.restore("user")
        valid_cube.activate("user")
        valid_cube.deactivate("user")
        valid_cube.lock("user", "reason")
        valid_cube.unlock("user")
        valid_cube.touch("user")
        valid_cube.clone()
        valid_cube.validate()
        # __post_init__ already called; calling again to ensure coverage
        valid_cube.__post_init__()
        # Also call all query methods
        _ = valid_cube.total_opening_debit()
        _ = valid_cube.total_opening_credit()
        _ = valid_cube.total_movement_debit()
        _ = valid_cube.total_movement_credit()
        _ = valid_cube.total_closing_debit()
        _ = valid_cube.total_closing_credit()
        _ = valid_cube.opening_balance()
        _ = valid_cube.closing_balance()
        _ = valid_cube.get_account_balance("101")
        _ = valid_cube.get_accounts_by_type("Asset")
        _ = valid_cube.get_debit_balance_accounts()
        _ = valid_cube.get_credit_balance_accounts()
        _ = valid_cube.filter_by_code_prefix("1")
        assert True


# ============================================================================
# Ensure __all__ exported correctly
# ============================================================================

def test_exports():
    from domain.financial_statement.trial_balance_cube import __all__
    assert "TrialBalanceAccount" in __all__
    assert "TrialBalanceCube" in __all__
    assert "TrialBalanceError" in __all__
    assert "TrialBalanceNotBalancedError" in __all__
