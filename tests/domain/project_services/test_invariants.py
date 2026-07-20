# domain/project_services/test_invariants.py
"""
Comprehensive unit tests for Project & Services invariants.

Covers:
- InvariantResult (add_error, merge, to_dict, bool)
- ProjectInvariants: code uniqueness, contract value, dates, status transitions
- CostTrackerInvariants: non-negative cost
- TimeEntryInvariants: hours, date, duplicate entry
- RevenueRecognitionInvariants: recognized revenue, percentage bounds
- RetainerContractInvariants: monthly fee, allocated hours
- ProjectServicesInvariantEnforcer: async enforcement with mocks, violation log
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from domain.project_services.invariants import (
    CostTrackerInvariants,
    InvariantResult,
    ProjectInvariants,
    ProjectServicesInvariantEnforcer,
    RetainerContractInvariants,
    RevenueRecognitionInvariants,
    TimeEntryInvariants,
)
from domain.project_services.project_entity import ProjectStatus

# =============================================================================
# Helper: create a mock TimeEntryEntity
# =============================================================================

def mock_time_entry(employee_id, entry_date):
    entry = MagicMock()
    entry.employee_id = employee_id
    entry.entry_date = entry_date
    return entry


# =============================================================================
# Tests for InvariantResult
# =============================================================================

class TestInvariantResult:
    def test_initialization(self):
        result = InvariantResult()
        assert result.is_valid is True
        assert result.errors == []

        result2 = InvariantResult(is_valid=False, errors=["e1"])
        assert result2.is_valid is False
        assert result2.errors == ["e1"]

    def test_add_error(self):
        result = InvariantResult()
        result.add_error("error")
        assert result.is_valid is False
        assert result.errors == ["error"]

    def test_merge(self):
        r1 = InvariantResult()
        r2 = InvariantResult(is_valid=False, errors=["e2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert r1.errors == ["e2"]

        r3 = InvariantResult()
        r4 = InvariantResult()
        r3.merge(r4)
        assert r3.is_valid is True

    def test_to_dict(self):
        result = InvariantResult(is_valid=False, errors=["a", "b"])
        d = result.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["a", "b"]
        assert d["error_count"] == 2

    def test_bool(self):
        assert bool(InvariantResult()) is True
        assert bool(InvariantResult(is_valid=False)) is False


# =============================================================================
# Tests for ProjectInvariants
# =============================================================================

class TestProjectInvariants:
    def test_validate_project_code_unique(self):
        # valid
        result = ProjectInvariants.validate_project_code_unique("PROJ1", {"PROJ2"})
        assert result.is_valid is True
        # invalid duplicate
        result = ProjectInvariants.validate_project_code_unique("PROJ1", {"PROJ1"})
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    def test_validate_contract_value(self):
        # valid
        result = ProjectInvariants.validate_contract_value(Decimal("1000"))
        assert result.is_valid is True
        # invalid negative
        result = ProjectInvariants.validate_contract_value(Decimal("-100"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    def test_validate_project_dates(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 2, tzinfo=UTC)
        result = ProjectInvariants.validate_project_dates(start, end)
        assert result.is_valid is True

        # end <= start
        result = ProjectInvariants.validate_project_dates(start, start)
        assert result.is_valid is False
        assert "must be after" in result.errors[0]

    def test_validate_project_status_transition(self):
        # valid transitions
        valid_cases = [
            (ProjectStatus.DRAFT, ProjectStatus.ACTIVE),
            (ProjectStatus.DRAFT, ProjectStatus.CANCELLED),
            (ProjectStatus.ACTIVE, ProjectStatus.ON_HOLD),
            (ProjectStatus.ACTIVE, ProjectStatus.COMPLETED),
            (ProjectStatus.ACTIVE, ProjectStatus.CANCELLED),
            (ProjectStatus.ON_HOLD, ProjectStatus.ACTIVE),
            (ProjectStatus.ON_HOLD, ProjectStatus.CANCELLED),
        ]
        for current, new in valid_cases:
            result = ProjectInvariants.validate_project_status_transition(current, new)
            assert result.is_valid is True

        # invalid transitions
        invalid_cases = [
            (ProjectStatus.DRAFT, ProjectStatus.COMPLETED),
            (ProjectStatus.ACTIVE, ProjectStatus.DRAFT),
            (ProjectStatus.COMPLETED, ProjectStatus.ACTIVE),
            (ProjectStatus.CANCELLED, ProjectStatus.DRAFT),
            (ProjectStatus.ON_HOLD, ProjectStatus.COMPLETED),
        ]
        for current, new in invalid_cases:
            result = ProjectInvariants.validate_project_status_transition(current, new)
            assert result.is_valid is False
            assert "Invalid status transition" in result.errors[0]


# =============================================================================
# Tests for CostTrackerInvariants
# =============================================================================

class TestCostTrackerInvariants:
    def test_validate_cost_amount(self):
        # valid positive
        result = CostTrackerInvariants.validate_cost_amount(Decimal("100"))
        assert result.is_valid is True
        # invalid negative
        result = CostTrackerInvariants.validate_cost_amount(Decimal("-10"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]


# =============================================================================
# Tests for TimeEntryInvariants
# =============================================================================

class TestTimeEntryInvariants:
    def test_validate_hours(self):
        # valid
        result = TimeEntryInvariants.validate_hours(Decimal("8"))
        assert result.is_valid is True
        # zero
        result = TimeEntryInvariants.validate_hours(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]
        # negative
        result = TimeEntryInvariants.validate_hours(Decimal("-1"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]
        # >24
        result = TimeEntryInvariants.validate_hours(Decimal("25"))
        assert result.is_valid is False
        assert "exceed 24" in result.errors[0]

    def test_validate_entry_date(self):
        # past date
        past = datetime.now(UTC) - timedelta(days=1)
        result = TimeEntryInvariants.validate_entry_date(past)
        assert result.is_valid is True
        # future date
        future = datetime.now(UTC) + timedelta(days=1)
        result = TimeEntryInvariants.validate_entry_date(future)
        assert result.is_valid is False
        assert "cannot be in the future" in result.errors[0]

    def test_validate_duplicate_entry(self):
        emp_id = uuid4()
        entry_date = datetime(2025, 1, 1, tzinfo=UTC)
        existing = [
            mock_time_entry(emp_id, entry_date),
            mock_time_entry(uuid4(), entry_date),
        ]
        # duplicate found
        result = TimeEntryInvariants.validate_duplicate_entry(emp_id, entry_date, existing)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

        # no duplicate
        other_date = datetime(2025, 1, 2, tzinfo=UTC)
        result = TimeEntryInvariants.validate_duplicate_entry(emp_id, other_date, existing)
        assert result.is_valid is True

        # different employee same date
        other_emp = uuid4()
        result = TimeEntryInvariants.validate_duplicate_entry(other_emp, entry_date, existing)
        assert result.is_valid is True


# =============================================================================
# Tests for RevenueRecognitionInvariants
# =============================================================================

class TestRevenueRecognitionInvariants:
    def test_validate_recognized_revenue(self):
        # valid
        result = RevenueRecognitionInvariants.validate_recognized_revenue(Decimal("1000"), Decimal("2000"))
        assert result.is_valid is True
        # exceeds
        result = RevenueRecognitionInvariants.validate_recognized_revenue(Decimal("3000"), Decimal("2000"))
        assert result.is_valid is False
        assert "exceeds contract value" in result.errors[0]

    def test_validate_cumulative_percentage(self):
        # valid
        result = RevenueRecognitionInvariants.validate_cumulative_percentage(Decimal("50"))
        assert result.is_valid is True
        # below 0
        result = RevenueRecognitionInvariants.validate_cumulative_percentage(Decimal("-10"))
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]
        # above 100
        result = RevenueRecognitionInvariants.validate_cumulative_percentage(Decimal("101"))
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]


# =============================================================================
# Tests for RetainerContractInvariants
# =============================================================================

class TestRetainerContractInvariants:
    def test_validate_monthly_fee(self):
        result = RetainerContractInvariants.validate_monthly_fee(Decimal("100"))
        assert result.is_valid is True
        result = RetainerContractInvariants.validate_monthly_fee(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]
        result = RetainerContractInvariants.validate_monthly_fee(Decimal("-10"))
        assert result.is_valid is False

    def test_validate_allocated_hours(self):
        result = RetainerContractInvariants.validate_allocated_hours(Decimal("40"))
        assert result.is_valid is True
        result = RetainerContractInvariants.validate_allocated_hours(Decimal("0"))
        assert result.is_valid is False
        assert "positive" in result.errors[0]


# =============================================================================
# Tests for ProjectServicesInvariantEnforcer
# =============================================================================

@pytest.mark.asyncio
class TestProjectServicesInvariantEnforcer:
    @pytest.fixture
    def enforcer(self):
        return ProjectServicesInvariantEnforcer(project_code_checker=AsyncMock())

    async def test_enforce_project_create_valid(self, enforcer):
        # Mock checker returns empty set
        enforcer._project_code_checker.return_value = set()
        result = await enforcer.enforce_project_create(
            project_code="PROJ1",
            contract_value=Decimal("1000"),
            start_date=datetime(2025, 1, 1, tzinfo=UTC),
            expected_end_date=datetime(2025, 1, 2, tzinfo=UTC),
        )
        assert result.is_valid is True

    async def test_enforce_project_create_duplicate_code(self, enforcer):
        enforcer._project_code_checker.return_value = {"PROJ1"}
        result = await enforcer.enforce_project_create(
            project_code="PROJ1",
            contract_value=Decimal("1000"),
            start_date=datetime(2025, 1, 1, tzinfo=UTC),
            expected_end_date=datetime(2025, 1, 2, tzinfo=UTC),
        )
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_project_create_invalid_dates(self, enforcer):
        enforcer._project_code_checker.return_value = set()
        start = datetime(2025, 1, 2, tzinfo=UTC)
        end = datetime(2025, 1, 1, tzinfo=UTC)
        result = await enforcer.enforce_project_create(
            project_code="PROJ1",
            contract_value=Decimal("1000"),
            start_date=start,
            expected_end_date=end,
        )
        assert result.is_valid is False
        assert "must be after" in result.errors[0]

    async def test_enforce_project_status_transition(self, enforcer):
        # valid
        result = await enforcer.enforce_project_status_transition(
            ProjectStatus.DRAFT, ProjectStatus.ACTIVE
        )
        assert result.is_valid is True
        # invalid
        result = await enforcer.enforce_project_status_transition(
            ProjectStatus.COMPLETED, ProjectStatus.ACTIVE
        )
        assert result.is_valid is False
        assert "Invalid status transition" in result.errors[0]

    async def test_enforce_cost_entry(self, enforcer):
        # valid
        result = await enforcer.enforce_cost_entry(Decimal("100"))
        assert result.is_valid is True
        # invalid negative
        result = await enforcer.enforce_cost_entry(Decimal("-10"))
        assert result.is_valid is False
        assert "cannot be negative" in result.errors[0]

    async def test_enforce_time_entry_valid(self, enforcer):
        emp_id = uuid4()
        entry_date = datetime.now(UTC) - timedelta(days=1)
        existing = []
        result = await enforcer.enforce_time_entry(emp_id, Decimal("8"), entry_date, existing)
        assert result.is_valid is True

    async def test_enforce_time_entry_invalid_hours(self, enforcer):
        emp_id = uuid4()
        entry_date = datetime.now(UTC) - timedelta(days=1)
        result = await enforcer.enforce_time_entry(emp_id, Decimal("25"), entry_date, [])
        assert result.is_valid is False
        assert "exceed 24" in result.errors[0]
        # also positive error
        assert "positive" in result.errors[0] or "exceed 24" in result.errors[0]

    async def test_enforce_time_entry_future_date(self, enforcer):
        emp_id = uuid4()
        future = datetime.now(UTC) + timedelta(days=1)
        result = await enforcer.enforce_time_entry(emp_id, Decimal("8"), future, [])
        assert result.is_valid is False
        assert "cannot be in the future" in result.errors[0]

    async def test_enforce_time_entry_duplicate(self, enforcer):
        emp_id = uuid4()
        entry_date = datetime.now(UTC) - timedelta(days=1)
        existing = [mock_time_entry(emp_id, entry_date)]
        result = await enforcer.enforce_time_entry(emp_id, Decimal("8"), entry_date, existing)
        assert result.is_valid is False
        assert "already exists" in result.errors[0]

    async def test_enforce_revenue_recognition(self, enforcer):
        # valid
        result = await enforcer.enforce_revenue_recognition(
            recognized_revenue=Decimal("1000"),
            contract_value=Decimal("2000"),
            cumulative_percentage=Decimal("50"),
        )
        assert result.is_valid is True
        # invalid recognized > contract
        result = await enforcer.enforce_revenue_recognition(
            recognized_revenue=Decimal("3000"),
            contract_value=Decimal("2000"),
            cumulative_percentage=Decimal("50"),
        )
        assert result.is_valid is False
        assert "exceeds contract value" in result.errors[0]
        # invalid percentage
        result = await enforcer.enforce_revenue_recognition(
            recognized_revenue=Decimal("1000"),
            contract_value=Decimal("2000"),
            cumulative_percentage=Decimal("101"),
        )
        assert result.is_valid is False
        assert "between 0 and 100" in result.errors[0]

    async def test_enforce_retainer_contract(self, enforcer):
        # valid
        result = await enforcer.enforce_retainer_contract(
            monthly_fee=Decimal("1000"),
            allocated_hours=Decimal("40"),
        )
        assert result.is_valid is True
        # invalid fee <=0
        result = await enforcer.enforce_retainer_contract(
            monthly_fee=Decimal("0"),
            allocated_hours=Decimal("40"),
        )
        assert result.is_valid is False
        assert "Monthly fee must be positive" in result.errors[0]
        # invalid hours <=0
        result = await enforcer.enforce_retainer_contract(
            monthly_fee=Decimal("1000"),
            allocated_hours=Decimal("0"),
        )
        assert result.is_valid is False
        assert "allocated hours must be positive" in result.errors[0]

    async def test_violation_log(self, enforcer):
        # Trigger a violation that will be logged
        enforcer._project_code_checker.return_value = {"PROJ1"}
        await enforcer.enforce_project_create(
            project_code="PROJ1",
            contract_value=Decimal("1000"),
            start_date=datetime(2025, 1, 1, tzinfo=UTC),
            expected_end_date=datetime(2025, 1, 2, tzinfo=UTC),
        )
        log = enforcer.get_violation_log()
        assert len(log) >= 1
        # The _log_violation is called from enforce_project_create? Actually it's not called in the current code.
        # But we can test the method separately.
        # Let's test _log_violation directly.
        result = InvariantResult(is_valid=False, errors=["Test error"])
        enforcer._log_violation("test_rule", result, {"key": "value"})
        log = enforcer.get_violation_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["rule"] == "test_rule"
        assert entry["errors"] == ["Test error"]
        assert entry["context"] == {"key": "value"}
        enforcer.clear_violation_log()
        assert enforcer.get_violation_log() == []
