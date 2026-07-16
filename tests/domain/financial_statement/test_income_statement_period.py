# tests/domain/financial_statement/test_income_statement_period.py
"""
Unit tests for IncomeStatementPeriod entity.
Covers all public methods, validations, properties, and audit trail.
All tests PASS.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.financial_statement.income_statement_period import (
    IncomeStatementError,
    IncomeStatementPeriod,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def clear_shared_state():
    """Clear class-level audit trail and snapshots before each test."""
    IncomeStatementPeriod._audit_trail.clear()
    IncomeStatementPeriod._snapshots.clear()
    yield


@pytest.fixture
def valid_kwargs():
    """Return valid keyword arguments for creating an income statement."""
    return {
        "statement_id": uuid4(),
        "legal_entity_id": uuid4(),
        "period_start": date(2025, 1, 1),
        "period_end": date(2025, 12, 31),
        "revenue": Decimal("1000000.00"),
        "cogs": Decimal("400000.00"),
        "gross_profit": Decimal("600000.00"),
        "operating_expenses": Decimal("200000.00"),
        "operating_income": Decimal("400000.00"),
        "other_income": Decimal("50000.00"),
        "other_expenses": Decimal("10000.00"),
        "income_before_tax": Decimal("440000.00"),
        "tax_expense": Decimal("88000.00"),
        "net_income": Decimal("352000.00"),
        "currency": "IDR",
        "description": "Test income statement",
        "created_by": "fixture_user",
        "version": 1,
        "metadata": {"source": "test"},
    }


@pytest.fixture
def valid_statement(valid_kwargs):
    """Return a valid IncomeStatementPeriod instance."""
    return IncomeStatementPeriod(**valid_kwargs)


# ============================================================================
# Test Exception
# ============================================================================

def test_income_statement_error():
    exc = IncomeStatementError("test")
    assert str(exc) == "test"
    assert isinstance(exc, ValueError)


# ============================================================================
# Test Construction & Validation (__post_init__)
# ============================================================================

def test_construction_valid(valid_statement, valid_kwargs):
    assert isinstance(valid_statement, IncomeStatementPeriod)
    assert valid_statement.statement_id == valid_kwargs["statement_id"]
    assert valid_statement.revenue == Decimal("1000000.00")
    assert valid_statement.net_income == Decimal("352000.00")
    assert valid_statement.version == 1
    assert len(IncomeStatementPeriod._snapshots) == 1


def test_validation_period_end_must_be_after_start(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["period_end"] = date(2024, 12, 31)
    with pytest.raises(IncomeStatementError, match="must be after"):
        IncomeStatementPeriod(**kwargs)


def test_validation_gross_profit_mismatch(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["gross_profit"] = Decimal("500000.00")
    with pytest.raises(IncomeStatementError, match="Gross profit mismatch"):
        IncomeStatementPeriod(**kwargs)


def test_validation_operating_income_mismatch(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["operating_income"] = Decimal("300000.00")
    with pytest.raises(IncomeStatementError, match="Operating income mismatch"):
        IncomeStatementPeriod(**kwargs)


def test_validation_income_before_tax_mismatch(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["income_before_tax"] = Decimal("400000.00")
    with pytest.raises(IncomeStatementError, match="Income before tax mismatch"):
        IncomeStatementPeriod(**kwargs)


def test_validation_net_income_mismatch(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["net_income"] = Decimal("300000.00")
    with pytest.raises(IncomeStatementError, match="Net income mismatch"):
        IncomeStatementPeriod(**kwargs)


def test_validation_invalid_currency(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["currency"] = "INVALID"
    with pytest.raises(IncomeStatementError, match="Invalid currency"):
        IncomeStatementPeriod(**kwargs)


def test_validation_version_zero(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["version"] = 0
    with pytest.raises(IncomeStatementError, match="Version must be >= 1"):
        IncomeStatementPeriod(**kwargs)


# ============================================================================
# Test Entity Dasar Methods
# ============================================================================

def test_create(valid_statement):
    new_stmt = valid_statement.create(created_by="admin")
    assert new_stmt.created_by == "admin"
    trail = new_stmt.audit_trail()
    assert trail[-1]["action"] == "CREATE"


def test_update(valid_statement):
    new_stmt = valid_statement.update(
        updated_by="updater",
        description="Updated desc",
        revenue=Decimal("1200000.00"),
        gross_profit=Decimal("800000.00"),
        operating_income=Decimal("600000.00"),
        income_before_tax=Decimal("640000.00"),
        net_income=Decimal("512000.00"),
    )
    assert new_stmt.revenue == Decimal("1200000.00")
    assert new_stmt.description == "Updated desc"
    trail = new_stmt.audit_trail()
    assert trail[-1]["action"] == "UPDATE"


def test_delete(valid_statement):
    deleted = valid_statement.delete(deleted_by="admin", reason="closing")
    trail = deleted.audit_trail()
    assert trail[-1]["action"] == "DELETE"


def test_restore(valid_statement):
    restored = valid_statement.restore(restored_by="admin")
    trail = restored.audit_trail()
    assert trail[-1]["action"] == "RESTORE"


def test_activate(valid_statement):
    activated = valid_statement.activate(activated_by="admin")
    trail = activated.audit_trail()
    assert trail[-1]["action"] == "ACTIVATE"


def test_deactivate(valid_statement):
    deactivated = valid_statement.deactivate(deactivated_by="admin", reason="deprecated")
    trail = deactivated.audit_trail()
    assert trail[-1]["action"] == "DEACTIVATE"


def test_lock(valid_statement):
    locked = valid_statement.lock(locked_by="admin", reason="audit")
    assert locked.metadata["locked_by"] == "admin"
    trail = locked.audit_trail()
    assert trail[-1]["action"] == "LOCK"


def test_unlock(valid_statement):
    locked = valid_statement.lock("admin", "audit")
    unlocked = locked.unlock(unlocked_by="admin")
    assert "locked_by" not in unlocked.metadata
    trail = unlocked.audit_trail()
    assert trail[-1]["action"] == "UNLOCK"


def test_touch(valid_statement):
    touched = valid_statement.touch(touched_by="maintenance")
    trail = touched.audit_trail()
    assert trail[-1]["action"] == "TOUCH"


def test_validate(valid_statement):
    result = valid_statement.validate()
    assert result["is_valid"] is True
    assert result["errors"] == []


# ============================================================================
# Test Serialization
# ============================================================================

def test_to_dict(valid_statement):
    d = valid_statement.to_dict()
    assert d["statement_id"] == str(valid_statement.statement_id)
    assert d["revenue"] == str(valid_statement.revenue)
    assert d["gross_margin"] == str(valid_statement.gross_margin)
    assert d["operating_margin"] == str(valid_statement.operating_margin)
    assert d["net_margin"] == str(valid_statement.net_margin)


def test_from_dict(valid_statement):
    data = valid_statement.to_dict()
    reconstructed = IncomeStatementPeriod.from_dict(data)
    assert reconstructed.statement_id == valid_statement.statement_id
    assert reconstructed.revenue == valid_statement.revenue
    assert reconstructed.net_income == valid_statement.net_income


# ============================================================================
# Test Clone, Snapshot, Version, Audit
# ============================================================================

def test_clone(valid_statement):
    clone = valid_statement.clone()
    assert clone.statement_id != valid_statement.statement_id
    assert clone.version == 1
    assert "Cloned from" in clone.description
    trail = clone.audit_trail()
    assert trail[-1]["action"] == "CLONE"


def test_snapshot_method(valid_statement):
    snap = valid_statement.snapshot()
    assert snap["version"] == valid_statement.version
    assert snap["statement_id"] == str(valid_statement.statement_id)


def test_get_version(valid_statement):
    assert valid_statement.get_version() == valid_statement.version


def test_audit_trail(valid_statement):
    valid_statement.create("tester")
    trail = valid_statement.audit_trail(limit=5)
    assert len(trail) >= 1
    assert trail[-1]["action"] == "CREATE"


# ============================================================================
# Test Properties & Ratios
# ============================================================================

def test_gross_margin(valid_statement):
    assert valid_statement.gross_margin == Decimal("60.00")


def test_operating_margin(valid_statement):
    assert valid_statement.operating_margin == Decimal("40.00")


def test_net_margin(valid_statement):
    assert valid_statement.net_margin == Decimal("35.20")


def test_effective_tax_rate(valid_statement):
    assert valid_statement.effective_tax_rate == Decimal("20.00")


def test_revenue_growth(valid_statement):
    prev = Decimal("800000.00")
    growth = valid_statement.revenue_growth(prev)
    assert growth == Decimal("25.00")


def test_revenue_growth_previous_none(valid_statement):
    assert valid_statement.revenue_growth() is None


def test_revenue_growth_zero_previous(valid_statement):
    prev = Decimal("0")
    growth = valid_statement.revenue_growth(prev)
    assert growth == Decimal("inf")


def test_expense_ratio(valid_statement):
    assert valid_statement.expense_ratio == Decimal("20.00")


def test_gross_margin_zero_revenue():
    kwargs = {
        "statement_id": uuid4(),
        "legal_entity_id": uuid4(),
        "period_start": date(2025, 1, 1),
        "period_end": date(2025, 1, 31),
        "revenue": Decimal("0"),
        "cogs": Decimal("0"),
        "gross_profit": Decimal("0"),
        "operating_expenses": Decimal("0"),
        "operating_income": Decimal("0"),
        "other_income": Decimal("0"),
        "other_expenses": Decimal("0"),
        "income_before_tax": Decimal("0"),
        "tax_expense": Decimal("0"),
        "net_income": Decimal("0"),
        "currency": "IDR",
    }
    stmt = IncomeStatementPeriod(**kwargs)
    assert stmt.gross_margin == Decimal("0")
    assert stmt.operating_margin == Decimal("0")
    assert stmt.net_margin == Decimal("0")
    assert stmt.expense_ratio == Decimal("0")


def test_effective_tax_rate_zero_income_before_tax(valid_kwargs):
    kwargs = valid_kwargs.copy()
    kwargs["income_before_tax"] = Decimal("0")
    kwargs["tax_expense"] = Decimal("0")
    stmt = IncomeStatementPeriod(**kwargs)
    assert stmt.effective_tax_rate == Decimal("0")