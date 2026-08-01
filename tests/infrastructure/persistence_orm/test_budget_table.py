# tests/infrastructure/persistence_orm/test_budget_table.py
"""
Comprehensive unit tests for infrastructure/persistence_orm/budget_table.py.
Covers all properties, methods, and edge cases of BudgetTable.
Uses mocking/in-memory SQLAlchemy to avoid database dependency.
"""

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from infrastructure.persistence_orm.budget_table import BudgetTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def session():
    """Create an in-memory SQLite session for ORM testing."""
    create_engine("sqlite:///:memory:")
    # We don't have the actual Base metadata, but we don't need to create tables
    # because we are just testing the model behavior in-memory without actual DB.
    # We can just instantiate the model directly without a session.
    # So we'll just return None and use direct instantiation.
    return None


@pytest.fixture
def sample_budget():
    """Create a BudgetTable instance with default values."""
    return BudgetTable(
        id=uuid.uuid4(),
        budget_code="BUDGET-001",
        budget_name="Test Budget",
        description="Test description",
        budget_type="annual",
        fiscal_year=2025,
        period=1,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        account_code="1000",
        account_name="Revenue",
        cost_center="CC-001",
        project_id=uuid.uuid4(),
        department="Finance",
        amount=Decimal("100000.00"),
        currency="IDR",
        status="draft",
        is_active=True,
        legal_entity_id=uuid.uuid4(),
        version=1,
    )


@pytest.fixture
def sample_budget_with_actuals(sample_budget):
    """Create a budget with some actuals."""
    # Create mock actuals
    class MockActual:
        def __init__(self, amount):
            self.amount = amount

    sample_budget.actuals = [
        MockActual(Decimal("5000")),
        MockActual(Decimal("3000")),
        MockActual(Decimal("2000")),
    ]
    return sample_budget


# ============================================================================
# Tests for BudgetTable
# ============================================================================

class TestBudgetTableProperties:
    def test_total_actual_no_actuals(self, sample_budget):
        """total_actual returns 0 when no actuals."""
        sample_budget.actuals = []
        assert sample_budget.total_actual == Decimal(0)

    def test_total_actual_with_actuals(self, sample_budget_with_actuals):
        """total_actual sums all actual amounts."""
        # actuals: 5000 + 3000 + 2000 = 10000
        assert sample_budget_with_actuals.total_actual == Decimal("10000.00")

    def test_variance(self, sample_budget_with_actuals):
        """variance = total_actual - amount."""
        # amount=100000, actual=10000 => variance = -90000
        assert sample_budget_with_actuals.variance == Decimal("-90000.00")

    def test_variance_percentage(self, sample_budget_with_actuals):
        """variance_percentage = (variance / amount) * 100."""
        # (-90000 / 100000) * 100 = -90.0
        assert sample_budget_with_actuals.variance_percentage == -90.0

    def test_variance_percentage_zero_amount(self, sample_budget):
        """variance_percentage returns 0 when amount is 0."""
        sample_budget.amount = Decimal(0)
        sample_budget.actuals = [MagicMock(amount=Decimal("100"))]  # actual doesn't matter
        assert sample_budget.variance_percentage == 0.0

    def test_utilization_percentage(self, sample_budget_with_actuals):
        """utilization_percentage = (total_actual / amount) * 100."""
        # (10000 / 100000) * 100 = 10.0
        assert sample_budget_with_actuals.utilization_percentage == 10.0

    def test_utilization_percentage_zero_amount(self, sample_budget):
        """utilization_percentage returns 0 when amount is 0."""
        sample_budget.amount = Decimal(0)
        sample_budget.actuals = [MagicMock(amount=Decimal("100"))]
        assert sample_budget.utilization_percentage == 0.0

    def test_is_over_budget(self, sample_budget_with_actuals):
        """is_over_budget True when actual > amount."""
        # actual=10000, amount=100000 => False
        assert sample_budget_with_actuals.is_over_budget is False
        # make actual > amount
        sample_budget_with_actuals.actuals = [MagicMock(amount=Decimal("200000"))]
        assert sample_budget_with_actuals.is_over_budget is True

    def test_is_under_budget(self, sample_budget_with_actuals):
        """is_under_budget True when actual < amount."""
        # actual=10000, amount=100000 => True
        assert sample_budget_with_actuals.is_under_budget is True
        # make actual == amount
        sample_budget_with_actuals.actuals = [MagicMock(amount=Decimal("100000"))]
        assert sample_budget_with_actuals.is_under_budget is False

    def test_is_approved(self, sample_budget):
        sample_budget.status = "approved"
        assert sample_budget.is_approved is True
        sample_budget.status = "draft"
        assert sample_budget.is_approved is False

    def test_is_draft(self, sample_budget):
        sample_budget.status = "draft"
        assert sample_budget.is_draft is True
        sample_budget.status = "approved"
        assert sample_budget.is_draft is False

    def test_is_frozen(self, sample_budget):
        sample_budget.status = "frozen"
        assert sample_budget.is_frozen is True
        sample_budget.status = "draft"
        assert sample_budget.is_frozen is False


class TestBudgetTableMethods:
    def test_submit_success(self, sample_budget):
        user_id = uuid.uuid4()
        sample_budget.submit(user_id)
        assert sample_budget.status == "submitted"
        assert sample_budget.submitted_by == user_id
        assert sample_budget.submitted_at is not None
        assert sample_budget.version == 2  # increment_version called

    def test_submit_not_draft_raises(self, sample_budget):
        sample_budget.status = "submitted"
        with pytest.raises(ValueError, match="Cannot submit budget with status submitted"):
            sample_budget.submit(uuid.uuid4())

    def test_approve_success(self, sample_budget):
        sample_budget.status = "submitted"
        user_id = uuid.uuid4()
        sample_budget.approve(user_id)
        assert sample_budget.status == "approved"
        assert sample_budget.approved_by == user_id
        assert sample_budget.approved_at is not None
        assert sample_budget.version == 2

    def test_approve_not_submitted_raises(self, sample_budget):
        sample_budget.status = "draft"
        with pytest.raises(ValueError, match="Cannot approve budget with status draft"):
            sample_budget.approve(uuid.uuid4())

    def test_reject_success(self, sample_budget):
        sample_budget.status = "submitted"
        reason = "Insufficient details"
        sample_budget.reject(reason)
        assert sample_budget.status == "rejected"
        assert sample_budget.rejection_reason == reason
        assert sample_budget.version == 2

    def test_reject_not_submitted_raises(self, sample_budget):
        sample_budget.status = "draft"
        with pytest.raises(ValueError, match="Cannot reject budget with status draft"):
            sample_budget.reject("reason")

    def test_freeze_success(self, sample_budget):
        sample_budget.status = "approved"
        sample_budget.freeze()
        assert sample_budget.status == "frozen"
        assert sample_budget.version == 2

    def test_freeze_not_approved_raises(self, sample_budget):
        sample_budget.status = "draft"
        with pytest.raises(ValueError, match="Cannot freeze budget with status draft"):
            sample_budget.freeze()

    def test_archive(self, sample_budget):
        sample_budget.archive()
        assert sample_budget.status == "archived"
        assert sample_budget.is_active is False
        assert sample_budget.version == 2

    def test_revise_success(self, sample_budget):
        sample_budget.status = "approved"
        initial_version = sample_budget.version
        initial_revision = sample_budget.revision_number
        new_amount = Decimal("150000")
        sample_budget.revise(new_amount, "Increase allocation")
        assert sample_budget.is_active is False
        assert sample_budget.version == initial_version + 1
        assert sample_budget.revision_number == initial_revision + 1
        # amount is not changed by revise; caller should create new record
        # But we can assert that the method did not change amount.
        assert sample_budget.amount == Decimal("100000")  # unchanged

    def test_revise_frozen_raises(self, sample_budget):
        sample_budget.status = "frozen"
        with pytest.raises(ValueError, match="Cannot revise frozen budget"):
            sample_budget.revise(Decimal("200000"), "Reason")

    def test_to_dict(self, sample_budget_with_actuals):
        d = sample_budget_with_actuals.to_dict()
        assert d["id"] == str(sample_budget_with_actuals.id)
        assert d["budget_code"] == "BUDGET-001"
        assert d["budget_name"] == "Test Budget"
        assert d["amount"] == "100000.00"
        assert d["total_actual"] == "10000.00"
        assert d["variance"] == "-90000.00"
        assert d["variance_percentage"] == -90.0
        assert d["utilization_percentage"] == 10.0
        assert "legal_entity_id" in d
        assert d["version"] == 1

    def test_to_dict_truncates_none_project_id(self, sample_budget):
        sample_budget.project_id = None
        d = sample_budget.to_dict()
        assert d["project_id"] is None


# ============================================================================
# Integration tests with SQLAlchemy (optional, but we can test model constraints)
# ============================================================================

class TestBudgetTableConstraints:
    def test_budget_code_not_null(self):
        with pytest.raises(Exception):
            BudgetTable(budget_code=None)

    def test_amount_non_negative(self):
        with pytest.raises(Exception):
            BudgetTable(amount=Decimal("-1"))

    def test_status_enum(self):
        # Valid statuses
        for status in ["draft", "submitted", "approved", "frozen", "rejected", "archived"]:
            BudgetTable(status=status)
        # Invalid status should raise
        with pytest.raises(Exception):
            BudgetTable(status="invalid")

    def test_budget_type_enum(self):
        for btype in ["annual", "quarterly", "monthly", "project", "ad_hoc"]:
            BudgetTable(budget_type=btype)
        with pytest.raises(Exception):
            BudgetTable(budget_type="invalid")
