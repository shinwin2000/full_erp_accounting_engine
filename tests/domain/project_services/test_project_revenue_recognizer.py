# tests/domain/project_services/test_project_revenue_recognizer.py
"""
Comprehensive tests for domain/project_services/project_revenue_recognizer.py.
Covers all public methods, negative paths, edge cases, and uses mocks to avoid flakiness.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from domain.project_services.project_revenue_recognizer import (
    CostType,
    Project,
    ProjectEntity,
    ProjectEntityRepository,
    ProjectRevenueRecognizer,
    ProjectRevenueRecognizerRepository,
    ProjectStatus,
    ProjectType,
    RevenueMethod,
    RevenueRecognitionEntry,
    RevenueRecognitionMethod,
    RevenueRecognitionStatus,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=30)
FIXED_FUTURE = FIXED_NOW + timedelta(days=30)
FIXED_END_PAST = FIXED_NOW - timedelta(days=1)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.project_services.project_revenue_recognizer.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# ============================================================================
# Helper fixtures
# ============================================================================

@pytest.fixture
def sample_project_data():
    project_id = uuid4()
    customer_id = uuid4()
    manager_id = uuid4()
    return {
        "project_id": project_id,
        "project_code": "PRJ-001",
        "project_name": "Test Project",
        "project_type": ProjectType.CONSTRUCTION,
        "status": ProjectStatus.DRAFT,
        "customer_id": customer_id,
        "customer_name": "Acme Corp",
        "contract_value": Decimal("1000000"),
        "currency": "IDR",
        "start_date": FIXED_PAST,
        "expected_end_date": FIXED_FUTURE,
        "actual_end_date": None,
        "contract_number": "CNTR-001",
        "description": "Test description",
        "project_manager_id": manager_id,
        "project_manager_name": "John Doe",
        "budget": Decimal("800000"),
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
        "created_by": "system",
        "version": 1,
    }


@pytest.fixture
def sample_project(sample_project_data):
    return ProjectEntity(**sample_project_data)


@pytest.fixture
def sample_recognizer(sample_project):
    return ProjectRevenueRecognizer.create(sample_project)


@pytest.fixture
def sample_recognizer_with_revenue(sample_project):
    recognizer = ProjectRevenueRecognizer.create(sample_project)
    # Manually set recognized values
    recognizer.total_actual_cost = Decimal("200000")
    recognizer.total_recognized_revenue = Decimal("250000")
    recognizer.total_recognized_cost = Decimal("200000")
    recognizer.total_recognized_profit = Decimal("50000")
    recognizer.cumulative_percentage = 25.0
    recognizer.last_recognized_date = FIXED_NOW
    return recognizer


# ============================================================================
# Enum tests
# ============================================================================

class TestEnums:
    def test_project_status(self):
        assert ProjectStatus.DRAFT.value == "draft"
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.ON_HOLD.value == "on_hold"
        assert ProjectStatus.COMPLETED.value == "completed"
        assert ProjectStatus.CANCELLED.value == "cancelled"
        assert ProjectStatus.from_string("active") == ProjectStatus.ACTIVE
        assert ProjectStatus.from_string("unknown") == ProjectStatus.DRAFT

    def test_project_type(self):
        assert ProjectType.CONSTRUCTION.value == "construction"
        assert ProjectType.CONSULTING.value == "consulting"
        assert ProjectType.from_string("construction") == ProjectType.CONSTRUCTION
        assert ProjectType.from_string("unknown") == ProjectType.OTHER

    def test_cost_type(self):
        assert CostType.LABOR.value == "labor"
        assert CostType.MATERIAL.value == "material"
        assert CostType.EQUIPMENT.value == "equipment"
        assert CostType.SUBCONTRACTOR.value == "subcontractor"
        assert CostType.OTHER.value == "other"

    def test_revenue_method(self):
        assert RevenueMethod.PERCENTAGE_OF_COMPLETION.value == "percentage_of_completion"
        assert RevenueMethod.COMPLETED_CONTRACT.value == "completed_contract"
        assert RevenueMethod.INSTALLMENT.value == "installment"

    def test_revenue_recognition_method(self):
        assert RevenueRecognitionMethod.COST_TO_COST.value == "cost_to_cost"
        assert RevenueRecognitionMethod.EFFORTS_EXPENDED.value == "efforts_expended"
        assert RevenueRecognitionMethod.UNITS_OF_DELIVERY.value == "units_of_delivery"

    def test_revenue_recognition_status(self):
        assert RevenueRecognitionStatus.NOT_STARTED.value == "not_started"
        assert RevenueRecognitionStatus.IN_PROGRESS.value == "in_progress"
        assert RevenueRecognitionStatus.COMPLETED.value == "completed"


# ============================================================================
# ProjectEntity tests
# ============================================================================

class TestProjectEntity:
    def test_construction_valid(self, sample_project):
        assert sample_project.project_id is not None
        assert sample_project.project_code == "PRJ-001"
        assert sample_project.status == ProjectStatus.DRAFT
        assert sample_project.version == 1
        assert sample_project.created_at.tzinfo == UTC
        assert sample_project.updated_at.tzinfo == UTC
        assert sample_project.start_date.tzinfo == UTC
        assert sample_project.expected_end_date.tzinfo == UTC

    # ---- Negative path tests ----
    def test_construction_invalid_code_short(self):
        with pytest.raises(ValueError, match="Project code must be at least 3 characters"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="AB",
                project_name="Test",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
            )

    def test_construction_invalid_code_empty(self):
        with pytest.raises(ValueError, match="Project code must be at least 3 characters"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="",
                project_name="Test",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
            )

    def test_construction_invalid_name_short(self):
        with pytest.raises(ValueError, match="Project name must be at least 2 characters"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="A",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
            )

    def test_construction_invalid_name_empty(self):
        with pytest.raises(ValueError, match="Project name must be at least 2 characters"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
            )

    def test_construction_negative_contract_value(self):
        with pytest.raises(ValueError, match="Contract value cannot be negative"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("-100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
            )

    def test_construction_end_date_before_start(self):
        with pytest.raises(ValueError, match="Expected end date must be after start date"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_NOW - timedelta(days=1),
            )

    def test_construction_invalid_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ProjectEntity(
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                project_type=ProjectType.OTHER,
                status=ProjectStatus.DRAFT,
                customer_id=uuid4(),
                customer_name="Cust",
                contract_value=Decimal("100"),
                currency="IDR",
                start_date=FIXED_NOW,
                expected_end_date=FIXED_FUTURE,
                version=0,
            )

    # ---- Properties ----
    def test_properties(self, sample_project):
        assert sample_project.id == sample_project.project_id
        assert sample_project.is_active is False
        assert sample_project.is_completed is False
        assert sample_project.is_cancelled is False
        assert sample_project.is_on_hold is False
        active = sample_project.activate("user")
        assert active.is_active is True

    def test_is_overdue(self, sample_project):
        # Draft: not overdue
        assert sample_project.is_overdue() is False
        # Active but not past end date
        active = sample_project.activate("user")
        assert active.is_overdue() is False
        # Active and past end date
        project_past = ProjectEntity(
            project_id=uuid4(),
            project_code="PRJ-002",
            project_name="Past",
            project_type=ProjectType.OTHER,
            status=ProjectStatus.ACTIVE,
            customer_id=uuid4(),
            customer_name="Cust",
            contract_value=Decimal("100"),
            currency="IDR",
            start_date=FIXED_NOW - timedelta(days=10),
            expected_end_date=FIXED_END_PAST,
        )
        assert project_past.is_overdue() is True
        # Completed project not overdue
        completed = active.complete("user")
        assert completed.is_overdue() is False

    def test_get_duration_days(self, sample_project):
        duration = sample_project.get_duration_days()
        # start_date FIXED_PAST (30 days ago), expected_end FIXED_FUTURE (30 days ahead) => 60 days
        assert duration == 60

    def test_get_remaining_days(self, sample_project):
        # before end date, remaining > 0
        remaining = sample_project.get_remaining_days()
        # FIXED_NOW is exactly between start and end, so remaining ~30 days (since start 30 days ago, end 30 days ahead)
        assert remaining == 30
        # after end date, remaining = 0
        project_past = ProjectEntity(
            project_id=uuid4(),
            project_code="PRJ-003",
            project_name="Past",
            project_type=ProjectType.OTHER,
            status=ProjectStatus.ACTIVE,
            customer_id=uuid4(),
            customer_name="Cust",
            contract_value=Decimal("100"),
            currency="IDR",
            start_date=FIXED_NOW - timedelta(days=10),
            expected_end_date=FIXED_END_PAST,
        )
        assert project_past.get_remaining_days() == 0

    def test_get_completion_percentage(self, sample_project):
        # draft: 0%
        assert sample_project.get_completion_percentage() == 0.0
        # completed: 100%
        completed = sample_project.complete("user")
        assert completed.get_completion_percentage() == 100.0
        # cancelled: 0%
        cancelled = sample_project.cancel("user", "reason")
        assert cancelled.get_completion_percentage() == 0.0
        # active with some elapsed time: ~50% (30/60)
        active = sample_project.activate("user")
        assert active.get_completion_percentage() == 50.0

    # ---- validate ----
    def test_validate(self, sample_project):
        errors = sample_project.validate()
        assert errors == []
        # invalid project
        invalid = ProjectEntity(
            project_id=uuid4(),
            project_code="",
            project_name="Test",
            project_type=ProjectType.OTHER,
            status=ProjectStatus.DRAFT,
            customer_id=uuid4(),
            customer_name="Cust",
            contract_value=Decimal("100"),
            currency="IDR",
            start_date=FIXED_NOW,
            expected_end_date=FIXED_FUTURE,
        )
        errors = invalid.validate()
        assert len(errors) > 0
        assert any("Project code must be at least 3 characters" in e for e in errors)

    # ---- clone ----
    def test_clone(self, sample_project):
        cloned = sample_project.clone()
        assert cloned.project_id != sample_project.project_id
        assert cloned.project_code == "COPY-PRJ-001"
        assert cloned.project_name == "Copy of Test Project"
        assert cloned.status == ProjectStatus.DRAFT
        assert cloned.version == 1
        assert "Copy of" in cloned.description
        trail = sample_project.get_audit_trail()
        assert any(entry["action"] == "cloned" for entry in trail)

    # ---- Status transitions ----
    def test_activate(self, sample_project):
        active = sample_project.activate("user1")
        assert active.status == ProjectStatus.ACTIVE
        assert active.version == sample_project.version + 1
        assert active.created_by == "user1"
        assert active.updated_at == FIXED_NOW
        trail = active.get_audit_trail()
        assert any(entry["action"] == "activated" for entry in trail)
        with pytest.raises(ValueError, match="Cannot activate project in status active"):
            active.activate("user2")

    def test_deactivate(self, sample_project):
        active = sample_project.activate("user1")
        draft = active.deactivate("user2", "testing")
        assert draft.status == ProjectStatus.DRAFT
        assert draft.version == active.version + 1
        assert "Deactivated: testing" in draft.description
        trail = draft.get_audit_trail()
        assert any(entry["action"] == "deactivated" for entry in trail)
        with pytest.raises(ValueError, match="Cannot deactivate project in status draft"):
            sample_project.deactivate("user")

    def test_put_on_hold(self, sample_project):
        active = sample_project.activate("user1")
        on_hold = active.put_on_hold("user2", "reason")
        assert on_hold.status == ProjectStatus.ON_HOLD
        assert on_hold.version == active.version + 1
        assert "On hold: reason" in on_hold.description
        trail = on_hold.get_audit_trail()
        assert any(entry["action"] == "put_on_hold" for entry in trail)
        with pytest.raises(ValueError, match="Cannot put project on hold in status draft"):
            sample_project.put_on_hold("user", "reason")

    def test_resume(self, sample_project):
        active = sample_project.activate("user1")
        on_hold = active.put_on_hold("user2", "reason")
        resumed = on_hold.resume("user3")
        assert resumed.status == ProjectStatus.ACTIVE
        assert resumed.version == on_hold.version + 1
        assert "Resumed:" in resumed.description
        trail = resumed.get_audit_trail()
        assert any(entry["action"] == "resumed" for entry in trail)
        with pytest.raises(ValueError, match="Cannot resume project in status draft"):
            sample_project.resume("user")

    def test_complete(self, sample_project):
        active = sample_project.activate("user1")
        completed = active.complete("user2")
        assert completed.status == ProjectStatus.COMPLETED
        assert completed.version == active.version + 1
        assert completed.actual_end_date == FIXED_NOW
        trail = completed.get_audit_trail()
        assert any(entry["action"] == "completed" for entry in trail)
        with pytest.raises(ValueError, match="Cannot complete project in status draft"):
            sample_project.complete("user")

    def test_cancel(self, sample_project):
        cancelled = sample_project.cancel("user1", "reason")
        assert cancelled.status == ProjectStatus.CANCELLED
        assert cancelled.version == sample_project.version + 1
        assert "Cancelled: reason" in cancelled.description
        trail = cancelled.get_audit_trail()
        assert any(entry["action"] == "cancelled" for entry in trail)
        completed = sample_project.activate("user").complete("user")
        with pytest.raises(ValueError, match="Cannot cancel completed project"):
            completed.cancel("user", "reason")

    # ---- Update methods ----
    def test_rename(self, sample_project):
        renamed = sample_project.rename("New Name", "user1")
        assert renamed.project_name == "New Name"
        assert renamed.version == sample_project.version + 1
        trail = renamed.get_audit_trail()
        assert any(entry["action"] == "renamed" for entry in trail)
        with pytest.raises(ValueError, match="Project name must be at least 2 characters"):
            sample_project.rename("A", "user")

    def test_update_dates(self, sample_project):
        new_start = FIXED_NOW - timedelta(days=20)
        new_end = FIXED_NOW + timedelta(days=40)
        updated = sample_project.update_dates("user1", new_start, new_end)
        assert updated.start_date == new_start
        assert updated.expected_end_date == new_end
        assert updated.version == sample_project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "dates_updated" for entry in trail)
        with pytest.raises(ValueError, match="Expected end date must be after start date"):
            sample_project.update_dates("user", new_start, new_start - timedelta(days=1))

    def test_update_budget(self, sample_project):
        updated = sample_project.update_budget(Decimal("900000"), "user1")
        assert updated.budget == Decimal("900000")
        assert updated.version == sample_project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "budget_updated" for entry in trail)
        with pytest.raises(ValueError, match="Budget cannot be negative"):
            sample_project.update_budget(Decimal("-100"), "user")

    def test_update_project_manager(self, sample_project):
        new_id = uuid4()
        updated = sample_project.update_project_manager(new_id, "Jane Doe", "user1")
        assert updated.project_manager_id == new_id
        assert updated.project_manager_name == "Jane Doe"
        assert updated.version == sample_project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "project_manager_updated" for entry in trail)

    # ---- Serialization ----
    def test_to_dict(self, sample_project):
        d = sample_project.to_dict()
        assert d["project_id"] == str(sample_project.project_id)
        assert d["project_code"] == "PRJ-001"
        assert d["contract_value"] == "1000000"
        assert d["is_overdue"] is False
        assert d["duration_days"] == 60
        assert d["completion_percentage"] == 0.0

    def test_from_dict(self, sample_project):
        d = sample_project.to_dict()
        restored = ProjectEntity.from_dict(d)
        assert restored.project_id == sample_project.project_id
        assert restored.project_code == sample_project.project_code
        assert restored.contract_value == sample_project.contract_value
        assert restored.status == sample_project.status
        assert restored.project_type == sample_project.project_type
        assert restored.version == sample_project.version
        assert restored.created_at == sample_project.created_at

    # ---- Factory ----
    def test_create_factory(self):
        project = ProjectEntity.create(
            project_code="PRJ-004",
            project_name="New Project",
            project_type=ProjectType.CONSULTING,
            customer_id=uuid4(),
            customer_name="Client",
            contract_value=Decimal("500000"),
            currency="USD",
            start_date=FIXED_NOW,
            expected_end_date=FIXED_NOW + timedelta(days=90),
            created_by="creator",
            budget=Decimal("300000"),
            contract_number="CNTR-002",
            description="New desc",
            project_manager_id=uuid4(),
            project_manager_name="PM",
        )
        assert project.status == ProjectStatus.DRAFT
        assert project.version == 1
        assert project.project_code == "PRJ-004"
        assert project.budget == Decimal("300000")
        assert project.created_at == FIXED_NOW


# ============================================================================
# ProjectRevenueRecognizer tests
# ============================================================================

class TestProjectRevenueRecognizer:
    def test_create(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        assert recognizer.project_id == sample_project.project_id
        assert recognizer.project_code == sample_project.project_code
        assert recognizer.total_contract_value == sample_project.contract_value
        assert recognizer.total_estimated_cost == sample_project.budget
        assert recognizer.total_actual_cost == Decimal(0)
        assert recognizer.cumulative_percentage == 0.0
        assert recognizer.version == 1

    def test_create_with_zero_budget(self, sample_project):
        sample_project.budget = Decimal(0)
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        # estimated_cost = 70% of contract value
        expected = sample_project.contract_value * Decimal("0.7")
        assert recognizer.total_estimated_cost == expected

    def test_validate_negative_contract_value(self):
        with pytest.raises(ValueError, match="Total contract value cannot be negative"):
            ProjectRevenueRecognizer(
                project_id=uuid4(),
                total_contract_value=Decimal("-1"),
            )

    def test_validate_negative_estimated_cost(self):
        with pytest.raises(ValueError, match="Total estimated cost cannot be negative"):
            ProjectRevenueRecognizer(
                project_id=uuid4(),
                total_contract_value=Decimal("100"),
                total_estimated_cost=Decimal("-1"),
            )

    def test_validate_negative_actual_cost(self):
        with pytest.raises(ValueError, match="Total actual cost cannot be negative"):
            ProjectRevenueRecognizer(
                project_id=uuid4(),
                total_contract_value=Decimal("100"),
                total_actual_cost=Decimal("-1"),
            )

    def test_validate_percentage_out_of_range_high(self):
        with pytest.raises(ValueError, match="Cumulative percentage must be between 0 and 100"):
            ProjectRevenueRecognizer(
                project_id=uuid4(),
                total_contract_value=Decimal("100"),
                cumulative_percentage=101.0,
            )

    def test_validate_percentage_out_of_range_low(self):
        with pytest.raises(ValueError, match="Cumulative percentage must be between 0 and 100"):
            ProjectRevenueRecognizer(
                project_id=uuid4(),
                total_contract_value=Decimal("100"),
                cumulative_percentage=-1.0,
            )

    # ---- recognize_revenue ----
    def test_recognize_revenue(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        cost_tracker = MagicMock()
        cost_tracker.total_cost = Decimal("200000")
        as_of = FIXED_NOW
        new_recognizer = recognizer.recognize_revenue(
            project=sample_project,
            cost_tracker=cost_tracker,
            as_of_date=as_of,
            recognized_by="user"
        )
        # percentage = 200000/800000 = 25%
        assert new_recognizer.cumulative_percentage == 25.0
        assert new_recognizer.total_recognized_revenue == Decimal("250000")
        assert new_recognizer.total_recognized_cost == Decimal("200000")
        assert new_recognizer.total_recognized_profit == Decimal("50000")
        assert new_recognizer.version == recognizer.version + 1
        assert new_recognizer.last_recognized_date == as_of
        trail = new_recognizer._audit_trail
        assert any(entry["action"] == "revenue_recognized" for entry in trail)

    def test_recognize_revenue_incremental(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        cost_tracker = MagicMock()
        # First recognition
        cost_tracker.total_cost = Decimal("200000")
        as_of1 = FIXED_NOW
        r1 = recognizer.recognize_revenue(sample_project, cost_tracker, as_of1, "u1")
        assert r1.total_recognized_revenue == Decimal("250000")
        # Second recognition with more cost
        cost_tracker.total_cost = Decimal("500000")
        as_of2 = FIXED_NOW + timedelta(days=10)
        r2 = r1.recognize_revenue(sample_project, cost_tracker, as_of2, "u2")
        # percentage = 500000/800000 = 62.5% => revenue = 625000
        assert r2.cumulative_percentage == 62.5
        assert r2.total_recognized_revenue == Decimal("625000")
        assert r2.total_recognized_cost == Decimal("500000")
        assert r2.total_recognized_profit == Decimal("125000")
        assert r2.version == r1.version + 1

    def test_recognize_revenue_estimated_cost_zero(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        recognizer.total_estimated_cost = Decimal(0)
        cost_tracker = MagicMock()
        cost_tracker.total_cost = Decimal("100")
        as_of = FIXED_NOW
        new = recognizer.recognize_revenue(sample_project, cost_tracker, as_of, "u")
        assert new is recognizer  # returns self

    def test_recognize_revenue_fallback_total_actual_cost(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        # cost_tracker without total_cost attribute
        cost_tracker = MagicMock(spec=object)
        as_of = FIXED_NOW
        new = recognizer.recognize_revenue(sample_project, cost_tracker, as_of, "u")
        # Should use total_actual_cost (0) => no change
        assert new.cumulative_percentage == 0.0
        assert new.total_recognized_revenue == Decimal(0)

    def test_recognize_revenue_normalizes_timezone(self, sample_project):
        recognizer = ProjectRevenueRecognizer.create(sample_project)
        cost_tracker = MagicMock()
        cost_tracker.total_cost = Decimal("100000")
        naive = datetime(2026, 7, 23, 12, 0, 0)  # naive
        new = recognizer.recognize_revenue(sample_project, cost_tracker, naive, "u")
        assert new.last_recognized_date.tzinfo == UTC

    # ---- get_unrecognized_revenue ----
    def test_get_unrecognized_revenue(self, sample_recognizer_with_revenue):
        # total contract = 1,000,000; recognized = 250,000 => unrecognized = 750,000
        assert sample_recognizer_with_revenue.get_unrecognized_revenue() == Decimal("750000")

    # ---- get_unrecognized_cost ----
    def test_get_unrecognized_cost(self, sample_recognizer_with_revenue):
        # estimated = 800,000; actual = 200,000 => unrecognized = 600,000
        assert sample_recognizer_with_revenue.get_unrecognized_cost() == Decimal("600000")

    # ---- Serialization ----
    def test_to_dict(self, sample_recognizer_with_revenue):
        d = sample_recognizer_with_revenue.to_dict()
        assert d["project_id"] == str(sample_recognizer_with_revenue.project_id)
        assert d["total_contract_value"] == "1000000"
        assert d["cumulative_percentage"] == 25.0
        assert d["last_recognized_date"] is not None

    def test_from_dict(self, sample_recognizer_with_revenue):
        d = sample_recognizer_with_revenue.to_dict()
        restored = ProjectRevenueRecognizer.from_dict(d)
        assert restored.project_id == sample_recognizer_with_revenue.project_id
        assert restored.total_contract_value == sample_recognizer_with_revenue.total_contract_value
        assert restored.cumulative_percentage == sample_recognizer_with_revenue.cumulative_percentage
        assert restored.total_recognized_revenue == sample_recognizer_with_revenue.total_recognized_revenue
        assert restored.version == sample_recognizer_with_revenue.version
        assert restored.created_at == sample_recognizer_with_revenue.created_at
        assert restored.updated_at == sample_recognizer_with_revenue.updated_at

    def test_from_dict_missing_last_recognized_date(self, sample_recognizer_with_revenue):
        d = sample_recognizer_with_revenue.to_dict()
        d["last_recognized_date"] = None
        restored = ProjectRevenueRecognizer.from_dict(d)
        assert restored.last_recognized_date is None


# ============================================================================
# RevenueRecognitionEntry tests
# ============================================================================

class TestRevenueRecognitionEntry:
    def test_to_dict(self):
        entry = RevenueRecognitionEntry(
            date=FIXED_NOW,
            amount=Decimal("1500"),
            cumulative_amount=Decimal("3000"),
            percentage=25.5,
            note="test note",
        )
        d = entry.to_dict()
        assert d["date"] == FIXED_NOW.isoformat()
        assert d["amount"] == "1500"
        assert d["cumulative_amount"] == "3000"
        assert d["percentage"] == 25.5
        assert d["note"] == "test note"

    def test_from_dict(self):
        data = {
            "date": FIXED_NOW.isoformat(),
            "amount": "1500",
            "cumulative_amount": "3000",
            "percentage": 25.5,
            "note": "test note",
        }
        entry = RevenueRecognitionEntry.from_dict(data)
        assert entry.date == FIXED_NOW
        assert entry.amount == Decimal("1500")
        assert entry.cumulative_amount == Decimal("3000")
        assert entry.percentage == 25.5
        assert entry.note == "test note"


# ============================================================================
# Repository interface tests
# ============================================================================

@pytest.mark.asyncio
class TestRepositories:
    async def test_project_entity_repository(self):
        repo = ProjectEntityRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_by_code("PRJ", uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_by_status(uuid4(), ProjectStatus.DRAFT)
        with pytest.raises(NotImplementedError):
            await repo.get_overdue(uuid4())
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    async def test_project_revenue_recognizer_repository(self):
        repo = ProjectRevenueRecognizerRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_project_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())


# ============================================================================
# Alias test
# ============================================================================

def test_project_alias():
    assert Project is ProjectEntity
