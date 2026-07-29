# test_project_table.py
# Comprehensive tests for infrastructure/persistence_orm/project_table.py

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from infrastructure.persistence_orm.project_table import ProjectTable


# -------------------- Fixtures --------------------
@pytest.fixture
def fixed_date():
    return date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_date_today(fixed_date):
    with patch("infrastructure.persistence_orm.project_table.date") as mock_date:
        mock_date.today.return_value = fixed_date
        yield mock_date


@pytest.fixture
def sample_project():
    return ProjectTable(
        id=uuid.uuid4(),
        project_code="PRJ-001",
        project_name="Test Project",
        customer_id=uuid.uuid4(),
        customer_name="Acme Corp",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 6, 30),
        budget=Decimal("1000000"),
        actual_cost=Decimal("0"),
        billed_amount=Decimal("0"),
        paid_amount=Decimal("0"),
        currency="IDR",
        progress_percent=Decimal("0"),
        status="planning",
        project_manager_id=uuid.uuid4(),
        project_manager_name="John Doe",
        department="Engineering",
        cost_center="CC-001",
        billing_type="time_material",
        contract_value=Decimal("1200000"),
        retainer_amount=Decimal("0"),
        description="Test project",
        notes="Some notes",
        project_type="internal",
        priority="high",
        parent_project_id=None,
        created_by=uuid.uuid4(),
        version=1,
    )


# -------------------- Tests for Properties --------------------
class TestProjectTableProperties:
    def test_remaining_budget(self, sample_project):
        assert sample_project.remaining_budget == Decimal("1000000")
        sample_project.actual_cost = Decimal("300000")
        assert sample_project.remaining_budget == Decimal("700000")
        # Should not go below zero
        sample_project.actual_cost = Decimal("1500000")
        assert sample_project.remaining_budget == Decimal("0")

    def test_outstanding_billed(self, sample_project):
        assert sample_project.outstanding_billed == Decimal("0")
        sample_project.billed_amount = Decimal("500000")
        assert sample_project.outstanding_billed == Decimal("500000")
        sample_project.paid_amount = Decimal("200000")
        assert sample_project.outstanding_billed == Decimal("300000")
        # Should not go below zero
        sample_project.paid_amount = Decimal("600000")
        assert sample_project.outstanding_billed == Decimal("0")

    def test_cost_overrun(self, sample_project):
        assert sample_project.cost_overrun == Decimal("0")
        sample_project.actual_cost = Decimal("1200000")
        assert sample_project.cost_overrun == Decimal("200000")
        # Not over budget, should be 0
        sample_project.actual_cost = Decimal("800000")
        assert sample_project.cost_overrun == Decimal("0")

    def test_is_over_budget(self, sample_project):
        assert sample_project.is_over_budget is False
        sample_project.actual_cost = Decimal("1200000")
        assert sample_project.is_over_budget is True

    def test_is_completed(self, sample_project):
        assert sample_project.is_completed is False
        sample_project.status = "completed"
        assert sample_project.is_completed is True

    def test_is_active(self, sample_project):
        assert sample_project.is_active is False
        sample_project.status = "active"
        assert sample_project.is_active is True

    def test_progress_status(self, sample_project):
        sample_project.progress_percent = Decimal("0")
        assert sample_project.progress_status == "not_started"
        sample_project.progress_percent = Decimal("10")
        assert sample_project.progress_status == "just_started"
        sample_project.progress_percent = Decimal("30")
        assert sample_project.progress_status == "started"
        sample_project.progress_percent = Decimal("60")
        assert sample_project.progress_status == "halfway"
        sample_project.progress_percent = Decimal("80")
        assert sample_project.progress_status == "near_completion"
        sample_project.progress_percent = Decimal("100")
        assert sample_project.progress_status == "completed"
        # Edge: >100 is not allowed, but if it happens, should still behave
        sample_project.progress_percent = Decimal("110")
        assert sample_project.progress_status == "completed"  # since >=100

    def test_profitability(self, sample_project):
        sample_project.billed_amount = Decimal("800000")
        sample_project.actual_cost = Decimal("600000")
        assert sample_project.profitability == Decimal("200000")
        # Loss
        sample_project.actual_cost = Decimal("900000")
        assert sample_project.profitability == Decimal("-100000")


# -------------------- Tests for Methods --------------------
class TestProjectTableMethods:
    def test_activate_from_planning(self, sample_project):
        sample_project.activate()
        assert sample_project.status == "active"
        assert sample_project.start_date == date(2026, 1, 15)  # today
        assert sample_project.version == 2

    def test_activate_from_on_hold(self, sample_project):
        sample_project.status = "on_hold"
        sample_project.start_date = None  # ensure it's set
        sample_project.activate()
        assert sample_project.status == "active"
        assert sample_project.start_date == date(2026, 1, 15)
        assert sample_project.version == 2

    def test_activate_invalid_status(self, sample_project):
        sample_project.status = "completed"
        with pytest.raises(ValueError, match="Cannot activate"):
            sample_project.activate()
        sample_project.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot activate"):
            sample_project.activate()

    def test_put_on_hold(self, sample_project):
        sample_project.status = "active"
        sample_project.put_on_hold()
        assert sample_project.status == "on_hold"
        assert sample_project.version == 2

    def test_put_on_hold_invalid_status(self, sample_project):
        with pytest.raises(ValueError, match="Cannot put project on hold"):
            sample_project.put_on_hold()

    def test_complete_from_active(self, sample_project):
        sample_project.status = "active"
        completion_date = date(2026, 6, 30)
        sample_project.complete(completion_date)
        assert sample_project.status == "completed"
        assert sample_project.actual_completion_date == completion_date
        assert sample_project.progress_percent == Decimal("100")
        assert sample_project.version == 2

    def test_complete_from_on_hold(self, sample_project):
        sample_project.status = "on_hold"
        sample_project.complete()
        assert sample_project.status == "completed"
        assert sample_project.actual_completion_date == date(2026, 1, 15)  # today
        assert sample_project.progress_percent == Decimal("100")
        assert sample_project.version == 2

    def test_complete_invalid_status(self, sample_project):
        sample_project.status = "planning"
        with pytest.raises(ValueError, match="Cannot complete"):
            sample_project.complete()
        sample_project.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot complete"):
            sample_project.complete()

    def test_cancel(self, sample_project):
        sample_project.cancel()
        assert sample_project.status == "cancelled"
        assert sample_project.version == 2

    def test_cancel_invalid_status(self, sample_project):
        sample_project.status = "completed"
        with pytest.raises(ValueError, match="Cannot cancel"):
            sample_project.cancel()
        sample_project.status = "cancelled"
        with pytest.raises(ValueError, match="Cannot cancel"):
            sample_project.cancel()
        sample_project.status = "archived"
        with pytest.raises(ValueError, match="Cannot cancel"):
            sample_project.cancel()

    def test_archive(self, sample_project):
        sample_project.status = "completed"
        sample_project.archive()
        assert sample_project.status == "archived"
        assert sample_project.version == 2

    def test_archive_invalid_status(self, sample_project):
        sample_project.status = "active"
        with pytest.raises(ValueError, match="Only completed projects"):
            sample_project.archive()

    def test_add_actual_cost(self, sample_project):
        amount = Decimal("100000")
        sample_project.add_actual_cost(amount)
        assert sample_project.actual_cost == Decimal("100000")
        # Progress calculation: (100000 / 1000000) * 100 = 10%
        assert sample_project.progress_percent == Decimal("10")
        assert sample_project.version == 2
        # Add another cost
        sample_project.add_actual_cost(Decimal("200000"))
        assert sample_project.actual_cost == Decimal("300000")
        assert sample_project.progress_percent == Decimal("30")
        # Over budget but capped at 100
        sample_project.add_actual_cost(Decimal("800000"))
        assert sample_project.actual_cost == Decimal("1100000")
        assert sample_project.progress_percent == Decimal("100")
        # Zero budget case (division by zero -> progress stays 0)
        sample_project.budget = Decimal("0")
        sample_project.actual_cost = Decimal("0")
        sample_project.add_actual_cost(Decimal("1000"))
        assert sample_project.progress_percent == Decimal("0")  # no change

    def test_add_actual_cost_negative(self, sample_project):
        with pytest.raises(ValueError, match="Amount must be positive"):
            sample_project.add_actual_cost(Decimal("-100"))

    def test_record_billing(self, sample_project):
        amount = Decimal("500000")
        sample_project.record_billing(amount)
        assert sample_project.billed_amount == Decimal("500000")
        assert sample_project.version == 2

    def test_record_billing_negative(self, sample_project):
        with pytest.raises(ValueError, match="Billing amount must be positive"):
            sample_project.record_billing(Decimal("-100"))

    def test_record_payment(self, sample_project):
        amount = Decimal("300000")
        sample_project.record_payment(amount)
        assert sample_project.paid_amount == Decimal("300000")
        assert sample_project.version == 2

    def test_record_payment_negative(self, sample_project):
        with pytest.raises(ValueError, match="Payment amount must be positive"):
            sample_project.record_payment(Decimal("-100"))

    def test_update_progress(self, sample_project):
        new_progress = Decimal("45.5")
        sample_project.update_progress(new_progress)
        assert sample_project.progress_percent == Decimal("45.5")
        assert sample_project.version == 2

    def test_update_progress_out_of_range(self, sample_project):
        with pytest.raises(ValueError, match="between 0 and 100"):
            sample_project.update_progress(Decimal("-5"))
        with pytest.raises(ValueError, match="between 0 and 100"):
            sample_project.update_progress(Decimal("105"))

    def test_increment_version_called(self, sample_project):
        # Verify that version increments on each state change method
        sample_project.status = "active"
        sample_project.version = 1
        sample_project.activate()  # version becomes 2
        assert sample_project.version == 2
        sample_project.put_on_hold()  # version becomes 3
        assert sample_project.version == 3
        sample_project.complete()  # version becomes 4
        assert sample_project.version == 4


# -------------------- Tests for Edge Cases and Data Integrity --------------------
class TestProjectTableEdgeCases:
    def test_initial_values(self):
        # Test default values from column definitions
        project = ProjectTable()
        assert project.budget == Decimal("0")
        assert project.actual_cost == Decimal("0")
        assert project.billed_amount == Decimal("0")
        assert project.paid_amount == Decimal("0")
        assert project.progress_percent == Decimal("0")
        assert project.status == "planning"
        assert project.currency == "IDR"
        assert project.billing_type == "time_material"
        assert project.project_type == "internal"
        assert project.priority == "medium"
        assert project.version == 1  # from VersionMixin

    def test_progress_status_with_zero_budget(self):
        project = ProjectTable(budget=Decimal("0"), actual_cost=Decimal("0"), progress_percent=Decimal("0"))
        assert project.progress_status == "not_started"
        # If actual_cost is added, progress stays 0 because budget zero
        project.add_actual_cost(Decimal("100"))
        assert project.progress_percent == Decimal("0")
        assert project.progress_status == "not_started"

    def test_profitability_with_no_billing(self):
        project = ProjectTable(billed_amount=Decimal("0"), actual_cost=Decimal("5000"))
        assert project.profitability == Decimal("-5000")

    def test_remaining_budget_when_cost_exceeds(self):
        project = ProjectTable(budget=Decimal("1000"), actual_cost=Decimal("1500"))
        assert project.remaining_budget == Decimal("0")

    def test_outstanding_billed_when_paid_exceeds(self):
        project = ProjectTable(billed_amount=Decimal("1000"), paid_amount=Decimal("1200"))
        assert project.outstanding_billed == Decimal("0")

    def test_cost_overrun_when_under_budget(self):
        project = ProjectTable(budget=Decimal("1000"), actual_cost=Decimal("800"))
        assert project.cost_overrun == Decimal("0")

    def test_activate_sets_start_date_only_if_none(self):
        project = ProjectTable(status="planning", start_date=None)
        project.activate()
        assert project.start_date == date.today()
        # Should not change if already set
        old_date = date(2025, 12, 31)
        project2 = ProjectTable(status="on_hold", start_date=old_date)
        project2.activate()
        assert project2.start_date == old_date

    def test_complete_sets_actual_completion_date_if_not_provided(self):
        project = ProjectTable(status="active", actual_completion_date=None)
        project.complete()
        assert project.actual_completion_date == date.today()
        # With provided date
        custom_date = date(2026, 7, 1)
        project2 = ProjectTable(status="active")
        project2.complete(custom_date)
        assert project2.actual_completion_date == custom_date
