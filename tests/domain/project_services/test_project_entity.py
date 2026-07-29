# tests/domain/project_services/test_project_entity.py
"""
Comprehensive unit tests for Project Entity.

Covers:
- Entity construction, validation, and serialization
- Factory method `create`
- Computed properties: id, is_active, is_completed, is_cancelled, is_on_hold, is_locked
- Query methods: is_overdue, get_duration_days, get_remaining_days, get_completion_percentage
- Validation
- Lock / unlock
- Clone
- Status transitions: activate, deactivate, put_on_hold, resume, complete, cancel
- Update methods: rename, update_dates, update_budget, update_project_manager, update_contract_value
- Audit trail and snapshot
- Repository protocol (abstract methods)
- Enums: ProjectStatus, ProjectType
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.project_services.project_entity import (
    ProjectEntity,
    ProjectEntityRepository,
    ProjectStatus,
    ProjectType,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def customer_id() -> UUID:
    return uuid4()


@pytest.fixture
def project_manager_id() -> UUID:
    return uuid4()


@pytest.fixture
def project_kwargs(customer_id, project_manager_id) -> dict[str, Any]:
    """Valid keyword arguments for creating a ProjectEntity."""
    now = datetime.now(UTC)
    return {
        "project_id": uuid4(),
        "project_code": "PRJ-2026-001",
        "project_name": "Test Project",
        "project_type": ProjectType.CONSULTING,
        "status": ProjectStatus.DRAFT,
        "customer_id": customer_id,
        "customer_name": "Acme Corp",
        "contract_value": Decimal("50000.00"),
        "currency": "IDR",
        "start_date": now,
        "expected_end_date": now + timedelta(days=90),
        "actual_end_date": None,
        "contract_number": "CNT-001",
        "description": "Initial project description",
        "project_manager_id": project_manager_id,
        "project_manager_name": "John Manager",
        "budget": Decimal("45000.00"),
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def project(project_kwargs) -> ProjectEntity:
    """A fully initialized project in DRAFT state."""
    return ProjectEntity(**project_kwargs)


@pytest.fixture
def active_project(project) -> ProjectEntity:
    """Project in ACTIVE state."""
    return project.activate("activator")


@pytest.fixture
def on_hold_project(active_project) -> ProjectEntity:
    """Project in ON_HOLD state."""
    return active_project.put_on_hold("holder", "Client delay")


@pytest.fixture
def completed_project(active_project) -> ProjectEntity:
    """Project in COMPLETED state."""
    return active_project.complete("completer", datetime.now(UTC))


@pytest.fixture
def locked_project(project) -> ProjectEntity:
    """Project that is locked."""
    return project.lock("locker", "Locked for audit")


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestProjectStatus:
    def test_members(self):
        assert ProjectStatus.DRAFT.value == "draft"
        assert ProjectStatus.ACTIVE.value == "active"
        assert ProjectStatus.ON_HOLD.value == "on_hold"
        assert ProjectStatus.COMPLETED.value == "completed"
        assert ProjectStatus.CANCELLED.value == "cancelled"

    def test_from_string(self):
        assert ProjectStatus.from_string("active") == ProjectStatus.ACTIVE
        assert ProjectStatus.from_string("DRAFT") == ProjectStatus.DRAFT
        assert ProjectStatus.from_string("unknown") == ProjectStatus.DRAFT  # fallback


class TestProjectType:
    def test_members(self):
        assert ProjectType.CONSTRUCTION.value == "construction"
        assert ProjectType.CONSULTING.value == "consulting"
        assert ProjectType.DEVELOPMENT.value == "development"
        assert ProjectType.MAINTENANCE.value == "maintenance"
        assert ProjectType.RESEARCH.value == "research"
        assert ProjectType.OTHER.value == "other"

    def test_from_string(self):
        assert ProjectType.from_string("consulting") == ProjectType.CONSULTING
        assert ProjectType.from_string("CONSTRUCTION") == ProjectType.CONSTRUCTION
        assert ProjectType.from_string("unknown") == ProjectType.OTHER  # fallback


# -----------------------------------------------------------------------------
# Tests for ProjectEntity
# -----------------------------------------------------------------------------

class TestProjectEntity:
    """Test the project entity."""

    def test_construction_success(self, project):
        assert project.project_id is not None
        assert project.project_code == "PRJ-2026-001"
        assert project.status == ProjectStatus.DRAFT
        assert project.version == 1
        assert project.start_date.tzinfo is not None
        assert project.expected_end_date.tzinfo is not None
        assert project.created_at.tzinfo is not None

    def test_validation_raises_for_short_code(self, project_kwargs):
        project_kwargs["project_code"] = "AB"
        with pytest.raises(ValueError, match="Project code must be at least 3"):
            ProjectEntity(**project_kwargs)

    def test_validation_raises_for_short_name(self, project_kwargs):
        project_kwargs["project_name"] = "A"
        with pytest.raises(ValueError, match="Project name must be at least 2"):
            ProjectEntity(**project_kwargs)

    def test_validation_raises_for_negative_contract_value(self, project_kwargs):
        project_kwargs["contract_value"] = Decimal("-1")
        with pytest.raises(ValueError, match="Contract value cannot be negative"):
            ProjectEntity(**project_kwargs)

    def test_validation_raises_for_end_date_before_start(self, project_kwargs):
        project_kwargs["expected_end_date"] = project_kwargs["start_date"] - timedelta(days=1)
        with pytest.raises(ValueError, match="Expected end date must be after start date"):
            ProjectEntity(**project_kwargs)

    def test_validation_raises_for_version_zero(self, project_kwargs):
        project_kwargs["version"] = 0
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ProjectEntity(**project_kwargs)

    def test_validation_raises_for_naive_datetime(self, project_kwargs):
        project_kwargs["start_date"] = datetime.now()  # naive
        with pytest.raises(ValueError):
            ProjectEntity(**project_kwargs)

        project_kwargs["start_date"] = datetime.now(UTC)
        project_kwargs["expected_end_date"] = datetime.now()  # naive
        with pytest.raises(ValueError):
            ProjectEntity(**project_kwargs)

    # ---- Audit trail and snapshots ----

    def test_audit_trail(self, project):
        assert project.get_audit_trail() == []

        project._record_audit("test_action", "tester", {"key": "value"})
        trail = project.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["user_id"] == "tester"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == project.version

    def test_snapshot(self, project):
        # _take_snapshot is called on construction, so there should be at least one snapshot
        # We can't directly access _snapshots (it's private), but we can check it exists.
        assert hasattr(project, "_snapshots")
        # The method is tested indirectly through status changes

    # ---- Properties ----

    def test_id_property(self, project):
        assert project.id == project.project_id

    def test_status_properties(self, project, active_project, on_hold_project, completed_project):
        assert project.is_active is False
        assert project.is_completed is False
        assert project.is_cancelled is False
        assert project.is_on_hold is False

        assert active_project.is_active is True
        assert active_project.is_completed is False
        assert active_project.is_cancelled is False
        assert active_project.is_on_hold is False

        assert on_hold_project.is_on_hold is True
        assert on_hold_project.is_active is False

        assert completed_project.is_completed is True
        assert completed_project.is_active is False

        cancelled = active_project.cancel("tester", "test")
        assert cancelled.is_cancelled is True

    def test_is_locked_property(self, project, locked_project):
        assert project.is_locked is False
        assert locked_project.is_locked is True

    # ---- Query methods ----

    def test_is_overdue(self, project, active_project, completed_project):
        # DRAFT project not overdue
        assert project.is_overdue() is False

        # Active with future end not overdue
        assert active_project.is_overdue() is False

        # Active with past end -> overdue
        now = datetime.now(UTC)
        past_end = now - timedelta(days=5)
        overdue_project = ProjectEntity(
            project_id=uuid4(),
            project_code="OVERDUE",
            project_name="Overdue Project",
            project_type=ProjectType.OTHER,
            status=ProjectStatus.ACTIVE,
            customer_id=uuid4(),
            customer_name="Test",
            contract_value=Decimal("1000"),
            currency="IDR",
            start_date=now - timedelta(days=30),
            expected_end_date=past_end,
            created_by="tester",
        )
        assert overdue_project.is_overdue(as_of=now) is True

        # Completed project not overdue even if past end
        assert completed_project.is_overdue() is False

    def test_get_duration_days(self, project):
        # 90 days between start and expected_end
        assert project.get_duration_days() == 90

        # With actual_end_date
        actual_end = project.start_date + timedelta(days=85)
        completed = project.complete("tester", actual_end)
        assert completed.get_duration_days() == 85

    def test_get_remaining_days(self, project, active_project, completed_project):
        # DRAFT project: remaining days based on expected_end - now
        # We can't assert exact number, but it should be positive.
        remaining = project.get_remaining_days()
        assert remaining > 0

        # Completed project returns 0
        assert completed_project.get_remaining_days() == 0

        # Cancelled project returns 0
        cancelled = active_project.cancel("tester", "test")
        assert cancelled.get_remaining_days() == 0

        # Past expected end -> 0
        now = datetime.now(UTC)
        past_end = now - timedelta(days=5)
        overdue_project = ProjectEntity(
            project_id=uuid4(),
            project_code="OVERDUE",
            project_name="Overdue",
            project_type=ProjectType.OTHER,
            status=ProjectStatus.ACTIVE,
            customer_id=uuid4(),
            customer_name="Test",
            contract_value=Decimal("1000"),
            currency="IDR",
            start_date=now - timedelta(days=30),
            expected_end_date=past_end,
            created_by="tester",
        )
        assert overdue_project.get_remaining_days(as_of=now) == 0

    def test_get_completion_percentage(self, project, completed_project):
        # DRAFT -> 0%
        assert project.get_completion_percentage() == 0.0

        # Completed -> 100%
        assert completed_project.get_completion_percentage() == 100.0

        # Cancelled -> 0%
        cancelled = project.cancel("tester", "test")
        assert cancelled.get_completion_percentage() == 0.0

        # Active with some elapsed time
        # We can't easily test exact percentage, but we can ensure it's > 0 and < 100
        active = project.activate("tester")
        # The project's start_date is now - 90 days, so it should be near 100%
        # But we'll just check it's not negative and not > 100
        pct = active.get_completion_percentage()
        assert 0.0 <= pct <= 100.0

    # ---- Validation ----

    def test_validate(self, project):
        errors = project.validate()
        assert errors == []

        # Invalid project
        invalid = ProjectEntity(
            project_id=uuid4(),
            project_code="AB",  # too short
            project_name="X",   # too short
            project_type=ProjectType.OTHER,
            status=ProjectStatus.DRAFT,
            customer_id=uuid4(),
            customer_name="Test",
            contract_value=Decimal("-1"),  # negative
            currency="IDR",
            start_date=datetime.now(UTC),
            expected_end_date=datetime.now(UTC) - timedelta(days=1),  # end before start
            created_by="tester",
        )
        errors = invalid.validate()
        assert len(errors) >= 4
        assert any("at least 3" in e for e in errors)
        assert any("at least 2" in e for e in errors)
        assert any("cannot be negative" in e for e in errors)
        assert any("after start date" in e for e in errors)

    # ---- Lock / Unlock ----

    def test_lock(self, project):
        locked = project.lock("locker", "Audit reason")
        assert locked.is_locked is True
        assert locked._locked_by == "locker"
        assert locked._locked_at is not None
        assert locked.version == project.version + 1
        assert locked.updated_at > project.updated_at
        trail = locked.get_audit_trail()
        assert any(entry["action"] == "locked" for entry in trail)

    def test_lock_raises_if_already_locked(self, locked_project):
        with pytest.raises(ValueError, match="Project is already locked"):
            locked_project.lock("another", "reason")

    def test_unlock(self, locked_project):
        unlocked = locked_project.unlock("locker")
        assert unlocked.is_locked is False
        assert unlocked._locked_by is None
        assert unlocked._locked_at is None
        assert unlocked.version == locked_project.version + 1
        trail = unlocked.get_audit_trail()
        assert any(entry["action"] == "unlocked" for entry in trail)

    def test_unlock_raises_if_not_locked(self, project):
        with pytest.raises(ValueError, match="Project is not locked"):
            project.unlock("tester")

    def test_unlock_raises_if_wrong_user(self, locked_project):
        with pytest.raises(ValueError, match="cannot unlock by"):
            locked_project.unlock("wrong_user")

    # ---- Clone ----

    def test_clone(self, project):
        cloned = project.clone()
        assert cloned.project_id != project.project_id
        assert cloned.project_code == f"COPY-{project.project_code}"
        assert cloned.project_name == f"Copy of {project.project_name}"
        assert cloned.status == ProjectStatus.DRAFT
        assert cloned.version == 1
        assert cloned.created_at != project.created_at
        assert cloned.updated_at != project.updated_at
        assert cloned.is_locked is False
        assert cloned._audit_trail == []
        assert cloned._snapshots == []
        assert "Copy of" in cloned.description
        trail = cloned.get_audit_trail()
        assert any(entry["action"] == "cloned" for entry in trail)

    # ---- Status transitions ----

    def test_activate(self, project):
        activated = project.activate("activator")
        assert activated.status == ProjectStatus.ACTIVE
        assert activated.version == project.version + 1
        assert activated.updated_at > project.updated_at
        assert activated.created_by == "activator"
        trail = activated.get_audit_trail()
        assert any(entry["action"] == "activated" for entry in trail)

    def test_activate_raises_if_not_draft(self, active_project):
        with pytest.raises(ValueError, match="Cannot activate project in status active"):
            active_project.activate("activator")

    def test_activate_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot activate locked project"):
            locked_project.activate("activator")

    def test_deactivate(self, active_project):
        deactivated = active_project.deactivate("deactivator", "Test reason")
        assert deactivated.status == ProjectStatus.DRAFT
        assert "Deactivated: Test reason" in deactivated.description
        assert deactivated.version == active_project.version + 1
        trail = deactivated.get_audit_trail()
        assert any(entry["action"] == "deactivated" for entry in trail)

    def test_deactivate_raises_if_not_active(self, project):
        with pytest.raises(ValueError, match="Cannot deactivate project in status draft"):
            project.deactivate("tester")

    def test_deactivate_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot deactivate locked project"):
            locked_project.deactivate("tester")

    def test_put_on_hold(self, active_project):
        held = active_project.put_on_hold("holder", "Client delay")
        assert held.status == ProjectStatus.ON_HOLD
        assert "On hold: Client delay" in held.description
        assert held.version == active_project.version + 1
        trail = held.get_audit_trail()
        assert any(entry["action"] == "put_on_hold" for entry in trail)

    def test_put_on_hold_raises_if_not_active(self, project):
        with pytest.raises(ValueError, match="Cannot put project on hold in status draft"):
            project.put_on_hold("holder", "reason")

    def test_put_on_hold_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot put locked project on hold"):
            locked_project.put_on_hold("holder", "reason")

    def test_resume(self, on_hold_project):
        resumed = on_hold_project.resume("resumer")
        assert resumed.status == ProjectStatus.ACTIVE
        assert "Resumed:" in resumed.description
        assert resumed.version == on_hold_project.version + 1
        trail = resumed.get_audit_trail()
        assert any(entry["action"] == "resumed" for entry in trail)

    def test_resume_raises_if_not_on_hold(self, active_project):
        with pytest.raises(ValueError, match="Cannot resume project in status active"):
            active_project.resume("resumer")

    def test_resume_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot resume locked project"):
            locked_project.resume("resumer")

    def test_complete(self, active_project):
        now = datetime.now(UTC)
        completed = active_project.complete("completer", now)
        assert completed.status == ProjectStatus.COMPLETED
        assert completed.actual_end_date == now
        assert completed.version == active_project.version + 1
        trail = completed.get_audit_trail()
        assert any(entry["action"] == "completed" for entry in trail)

    def test_complete_raises_if_not_active_or_on_hold(self, project):
        with pytest.raises(ValueError, match="Cannot complete project in status draft"):
            project.complete("tester")

    def test_complete_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot complete locked project"):
            locked_project.complete("tester")

    def test_cancel(self, active_project):
        cancelled = active_project.cancel("canceller", "No longer needed")
        assert cancelled.status == ProjectStatus.CANCELLED
        assert "Cancelled: No longer needed" in cancelled.description
        assert cancelled.version == active_project.version + 1
        trail = cancelled.get_audit_trail()
        assert any(entry["action"] == "cancelled" for entry in trail)

    def test_cancel_raises_if_completed(self, completed_project):
        with pytest.raises(ValueError, match="Cannot cancel completed project"):
            completed_project.cancel("tester", "reason")

    def test_cancel_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot cancel locked project"):
            locked_project.cancel("tester", "reason")

    # ---- Update methods ----

    def test_rename(self, project):
        new_name = "Updated Project Name"
        renamed = project.rename(new_name, "renamer")
        assert renamed.project_name == new_name
        assert renamed.version == project.version + 1
        assert renamed.updated_at > project.updated_at
        trail = renamed.get_audit_trail()
        assert any(entry["action"] == "renamed" for entry in trail)
        # Check audit details
        action_entry = next(e for e in trail if e["action"] == "renamed")
        assert action_entry["details"]["old_name"] == project.project_name
        assert action_entry["details"]["new_name"] == new_name

    def test_rename_raises_for_short_name(self, project):
        with pytest.raises(ValueError, match="Project name must be at least 2"):
            project.rename("A", "tester")

    def test_rename_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot rename locked project"):
            locked_project.rename("New", "tester")

    def test_update_dates(self, project):
        new_start = project.start_date + timedelta(days=5)
        new_end = project.expected_end_date + timedelta(days=10)
        updated = project.update_dates("dater", new_start, new_end)
        assert updated.start_date == new_start
        assert updated.expected_end_date == new_end
        assert updated.version == project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "dates_updated" for entry in trail)

    def test_update_dates_raises_if_end_before_start(self, project):
        new_start = project.start_date + timedelta(days=10)
        new_end = project.start_date + timedelta(days=5)  # end before start
        with pytest.raises(ValueError, match="Expected end date must be after start date"):
            project.update_dates("dater", new_start, new_end)

    def test_update_dates_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot update dates of locked project"):
            locked_project.update_dates("dater", datetime.now(UTC), datetime.now(UTC) + timedelta(days=10))

    def test_update_budget(self, project):
        new_budget = Decimal("60000.00")
        updated = project.update_budget(new_budget, "budgeter")
        assert updated.budget == new_budget
        assert updated.version == project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "budget_updated" for entry in trail)

    def test_update_budget_raises_for_negative(self, project):
        with pytest.raises(ValueError, match="Budget cannot be negative"):
            project.update_budget(Decimal("-1"), "tester")

    def test_update_budget_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot update budget of locked project"):
            locked_project.update_budget(Decimal("1000"), "tester")

    def test_update_project_manager(self, project):
        new_manager_id = uuid4()
        new_manager_name = "New Manager"
        updated = project.update_project_manager(new_manager_id, new_manager_name, "manager_updater")
        assert updated.project_manager_id == new_manager_id
        assert updated.project_manager_name == new_manager_name
        assert updated.version == project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "project_manager_updated" for entry in trail)

    def test_update_project_manager_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot update project manager of locked project"):
            locked_project.update_project_manager(uuid4(), "New", "tester")

    def test_update_contract_value(self, project):
        new_value = Decimal("75000.00")
        updated = project.update_contract_value(new_value, "valuer")
        assert updated.contract_value == new_value
        assert updated.version == project.version + 1
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "contract_value_updated" for entry in trail)

    def test_update_contract_value_raises_for_negative(self, project):
        with pytest.raises(ValueError, match="Contract value cannot be negative"):
            project.update_contract_value(Decimal("-1"), "tester")

    def test_update_contract_value_raises_if_locked(self, locked_project):
        with pytest.raises(ValueError, match="Cannot update contract value of locked project"):
            locked_project.update_contract_value(Decimal("1000"), "tester")

    # ---- Factory method ----

    def test_create_factory(self, customer_id, project_manager_id):
        now = datetime.now(UTC)
        project = ProjectEntity.create(
            project_code="PRJ-2026-002",
            project_name="New Project",
            project_type=ProjectType.DEVELOPMENT,
            customer_id=customer_id,
            customer_name="Beta Corp",
            contract_value=Decimal("100000"),
            currency="USD",
            start_date=now,
            expected_end_date=now + timedelta(days=120),
            created_by="creator",
            budget=Decimal("80000"),
            contract_number="CNT-002",
            description="New development project",
            project_manager_id=project_manager_id,
            project_manager_name="Dev Manager",
        )
        assert project.project_id is not None
        assert project.project_code == "PRJ-2026-002"
        assert project.status == ProjectStatus.DRAFT
        assert project.created_by == "creator"
        assert project.version == 1
        assert project.budget == Decimal("80000")
        assert project.contract_number == "CNT-002"

    # ---- Serialization ----

    def test_to_dict(self, project):
        d = project.to_dict()
        assert d["project_id"] == str(project.project_id)
        assert d["project_code"] == project.project_code
        assert d["status"] == project.status.value
        assert d["contract_value"] == str(project.contract_value)
        assert d["is_overdue"] == project.is_overdue()
        assert d["duration_days"] == project.get_duration_days()
        assert d["completion_percentage"] == project.get_completion_percentage()
        assert "remaining_days" in d
        assert d["is_locked"] == project.is_locked

    def test_from_dict(self, project):
        d = project.to_dict()
        restored = ProjectEntity.from_dict(d)
        assert restored.project_id == project.project_id
        assert restored.project_code == project.project_code
        assert restored.status == project.status
        assert restored.contract_value == project.contract_value
        assert restored.created_at == project.created_at
        assert restored.version == project.version

    def test_from_dict_with_defaults(self, project_kwargs):
        # Test missing optional fields
        data = {
            "project_id": str(uuid4()),
            "project_code": "TEST",
            "project_name": "Test",
            "project_type": "consulting",
            "status": "draft",
            "customer_id": str(uuid4()),
            "customer_name": "Test",
            "contract_value": "1000",
            "currency": "IDR",
            "start_date": datetime.now(UTC).isoformat(),
            "expected_end_date": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        restored = ProjectEntity.from_dict(data)
        assert restored.actual_end_date is None
        assert restored.contract_number is None
        assert restored.description == ""
        assert restored.project_manager_id is None
        assert restored.project_manager_name is None
        assert restored.budget == Decimal("0")
        assert restored.created_by == "system"
        assert restored.version == 1


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestProjectEntityRepository:
    """Test the abstract repository protocol."""

    def test_methods_raise_not_implemented(self):
        repo = ProjectEntityRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_code("PRJ-123", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_customer(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_status(uuid4(), ProjectStatus.DRAFT)
        with pytest.raises(NotImplementedError):
            repo.get_overdue(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
