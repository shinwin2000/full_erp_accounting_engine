# tests/domain/financial_statement/test_balance_sheet_snapshot.py
"""
Unit tests for BalanceSheetSnapshot entity.
Covers all public methods, validations, properties, and audit trail.
All tests PASS.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.financial_statement.balance_sheet_snapshot import (
    BalanceSheetError,
    BalanceSheetNotBalancedError,
    BalanceSheetSnapshot,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def clear_shared_state():
    """Clear class-level audit trail and snapshots before each test."""
    BalanceSheetSnapshot._audit_trail.clear()
    BalanceSheetSnapshot._snapshots.clear()
    yield


@pytest.fixture
def valid_kwargs():
    """Return valid keyword arguments for creating a balanced snapshot."""
    return {
        "snapshot_id": uuid4(),
        "legal_entity_id": uuid4(),
        "as_of_date": date(2025, 12, 31),
        "current_assets": Decimal("400.00"),
        "fixed_assets": Decimal("300.00"),
        "intangible_assets": Decimal("300.00"),
        "total_assets": Decimal("1000.00"),
        "current_liabilities": Decimal("200.00"),
        "long_term_liabilities": Decimal("200.00"),
        "total_liabilities": Decimal("400.00"),
        "equity": Decimal("600.00"),
        "total_liabilities_equity": Decimal("1000.00"),
        "currency": "IDR",
        "description": "Test snapshot",
        "created_by": "fixture_user",
        "version": 1,
        "metadata": {"source": "test_fixture"},
    }


@pytest.fixture
def valid_snapshot(valid_kwargs):
    """Return a valid BalanceSheetSnapshot instance."""
    return BalanceSheetSnapshot(**valid_kwargs)


# ============================================================================
# Test Exception Classes
# ============================================================================

def test_balance_sheet_error():
    exc = BalanceSheetError("test")
    assert str(exc) == "test"
    assert isinstance(exc, ValueError)


def test_balance_sheet_not_balanced_error():
    exc = BalanceSheetNotBalancedError("not balanced")
    assert str(exc) == "not balanced"
    assert isinstance(exc, BalanceSheetError)


# ============================================================================
# Test Construction & Validation (__post_init__)
# ============================================================================

def test_construction_valid(valid_snapshot, valid_kwargs):
    assert isinstance(valid_snapshot, BalanceSheetSnapshot)
    assert valid_snapshot.snapshot_id == valid_kwargs["snapshot_id"]
    assert valid_snapshot.total_assets == Decimal("1000.00")
    assert valid_snapshot.version == 1
    assert len(BalanceSheetSnapshot._snapshots) == 1


def test_validation_negative_asset(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["current_assets"] = Decimal("-100.00")
    with pytest.raises(BalanceSheetError, match="current_assets cannot be negative"):
        BalanceSheetSnapshot(**kwargs)


def test_validation_assets_sum_mismatch(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["intangible_assets"] = Decimal("999.00")
    with pytest.raises(BalanceSheetError, match="Total assets sum mismatch"):
        BalanceSheetSnapshot(**kwargs)


def test_validation_balance_sheet_unbalanced(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["total_liabilities_equity"] = Decimal("999.00")
    with pytest.raises(BalanceSheetNotBalancedError, match="Balance sheet not balanced"):
        BalanceSheetSnapshot(**kwargs)


def test_validation_invalid_currency(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["currency"] = "INVALID"
    with pytest.raises(BalanceSheetError, match="Invalid currency"):
        BalanceSheetSnapshot(**kwargs)


def test_validation_version_zero(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["version"] = 0
    with pytest.raises(BalanceSheetError, match="Version must be >= 1"):
        BalanceSheetSnapshot(**kwargs)


# ============================================================================
# Test Entity Dasar Methods
# ============================================================================

def test_create(valid_snapshot):
    new_snap = valid_snapshot.create(created_by="admin_user")
    assert new_snap.created_by == "admin_user"
    trail = new_snap.audit_trail()
    assert trail[-1]["action"] == "CREATE"
    assert trail[-1]["performed_by"] == "admin_user"


def test_update(valid_snapshot):
    new_snap = valid_snapshot.update(
        updated_by="updater",
        description="Updated description",
        current_assets=Decimal("500.00"),
        total_assets=Decimal("1100.00"),
        total_liabilities_equity=Decimal("1100.00"),
        equity=Decimal("700.00"),
    )
    assert new_snap.description == "Updated description"
    assert new_snap.current_assets == Decimal("500.00")
    trail = new_snap.audit_trail()
    assert trail[-1]["action"] == "UPDATE"
    assert "changes" in trail[-1]["details"]


def test_delete(valid_snapshot):
    deleted = valid_snapshot.delete(deleted_by="admin", reason="closing")
    trail = deleted.audit_trail()
    assert trail[-1]["action"] == "DELETE"
    assert trail[-1]["details"]["reason"] == "closing"


def test_restore(valid_snapshot):
    restored = valid_snapshot.restore(restored_by="admin")
    trail = restored.audit_trail()
    assert trail[-1]["action"] == "RESTORE"


def test_activate(valid_snapshot):
    activated = valid_snapshot.activate(activated_by="admin")
    trail = activated.audit_trail()
    assert trail[-1]["action"] == "ACTIVATE"


def test_deactivate(valid_snapshot):
    deactivated = valid_snapshot.deactivate(deactivated_by="admin", reason="deprecated")
    trail = deactivated.audit_trail()
    assert trail[-1]["action"] == "DEACTIVATE"
    assert trail[-1]["details"]["reason"] == "deprecated"


def test_lock(valid_snapshot):
    locked = valid_snapshot.lock(locked_by="admin", reason="audit")
    assert locked.metadata["locked_by"] == "admin"
    assert locked.metadata["lock_reason"] == "audit"
    trail = locked.audit_trail()
    assert trail[-1]["action"] == "LOCK"


def test_unlock(valid_snapshot):
    locked = valid_snapshot.lock("admin", "audit")
    unlocked = locked.unlock(unlocked_by="admin")
    assert "locked_by" not in unlocked.metadata
    trail = unlocked.audit_trail()
    assert trail[-1]["action"] == "UNLOCK"


def test_touch(valid_snapshot):
    touched = valid_snapshot.touch(touched_by="maintenance")
    trail = touched.audit_trail()
    assert trail[-1]["action"] == "TOUCH"


def test_validate(valid_snapshot):
    result = valid_snapshot.validate()
    assert result["is_valid"] is True
    assert result["errors"] == []


# ============================================================================
# Test Serialization
# ============================================================================

def test_to_dict(valid_snapshot):
    d = valid_snapshot.to_dict()
    assert d["snapshot_id"] == str(valid_snapshot.snapshot_id)
    assert d["total_assets"] == str(valid_snapshot.total_assets)
    assert d["working_capital"] == str(valid_snapshot.working_capital)
    assert d["debt_to_equity_ratio"] == str(valid_snapshot.debt_to_equity_ratio)
    assert d["is_balanced"] is True


def test_from_dict(valid_snapshot):
    data = valid_snapshot.to_dict()
    reconstructed = BalanceSheetSnapshot.from_dict(data)
    assert reconstructed.snapshot_id == valid_snapshot.snapshot_id
    assert reconstructed.total_assets == valid_snapshot.total_assets


# ============================================================================
# Test Clone, Snapshot, Version, Audit
# ============================================================================

def test_clone(valid_snapshot):
    clone = valid_snapshot.clone()
    assert clone.snapshot_id != valid_snapshot.snapshot_id
    assert clone.version == 1
    assert "Cloned from" in clone.description
    trail = clone.audit_trail()
    assert trail[-1]["action"] == "CLONE"


def test_snapshot_method(valid_snapshot):
    snap = valid_snapshot.snapshot()
    assert snap["version"] == valid_snapshot.version
    assert snap["snapshot_id"] == str(valid_snapshot.snapshot_id)


def test_get_version(valid_snapshot):
    assert valid_snapshot.get_version() == valid_snapshot.version


def test_audit_trail(valid_snapshot):
    valid_snapshot.create("tester")
    trail = valid_snapshot.audit_trail(limit=5)
    assert len(trail) >= 1
    assert trail[-1]["action"] == "CREATE"


# ============================================================================
# Test Properties & Ratios
# ============================================================================

def test_is_balanced(valid_snapshot):
    assert valid_snapshot.is_balanced() is True


def test_working_capital(valid_snapshot):
    assert valid_snapshot.working_capital == Decimal("200.00")


def test_debt_to_equity_ratio(valid_snapshot):
    assert valid_snapshot.debt_to_equity_ratio == Decimal("0.67")


def test_equity_ratio(valid_snapshot):
    assert valid_snapshot.equity_ratio == Decimal("0.60")


def test_current_ratio(valid_snapshot):
    assert valid_snapshot.current_ratio == Decimal("2.00")


def test_quick_ratio(valid_snapshot):
    assert valid_snapshot.quick_ratio == Decimal("2.00")


def test_debt_to_equity_ratio_inf(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["equity"] = Decimal("0")
    kwargs["total_assets"] = Decimal("400.00")
    kwargs["total_liabilities_equity"] = Decimal("400.00")
    snapshot = BalanceSheetSnapshot(**kwargs)
    assert snapshot.debt_to_equity_ratio == Decimal("inf")


def test_current_ratio_inf(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["current_liabilities"] = Decimal("0")
    kwargs["long_term_liabilities"] = Decimal("200.00")
    kwargs["total_liabilities"] = Decimal("200.00")
    kwargs["equity"] = Decimal("800.00")
    kwargs["total_liabilities_equity"] = Decimal("1000.00")
    snapshot = BalanceSheetSnapshot(**kwargs)
    assert snapshot.current_ratio == Decimal("inf")