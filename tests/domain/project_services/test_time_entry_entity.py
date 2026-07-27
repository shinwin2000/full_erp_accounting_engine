# tests/domain/project_services/test_time_entry_entity.py
"""
Comprehensive unit tests for Time Entry Entity.

Covers:
- Entity construction, validation, and serialization
- Factory method `create`
- Computed properties: amount, billable_amount
- Status transitions: submit, approve, reject, mark_billed
- update_hours with validation
- Audit trail and utility methods
- Repository protocol (abstract methods)
- Enums: TimeEntryStatus, WorkType
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from domain.project_services.time_entry_entity import (
    TimeEntryEntity,
    TimeEntryRepository,
    TimeEntryStatus,
    WorkType,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def employee_id() -> UUID:
    return uuid4()


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def entry_kwargs(employee_id, project_id) -> dict[str, Any]:
    """Valid keyword arguments for creating a TimeEntryEntity."""
    now = datetime.now(UTC)
    return {
        "entry_id": uuid4(),
        "entry_number": "TE-2026-001",
        "project_id": project_id,
        "project_code": "PRJ-123",
        "project_name": "Project Alpha",
        "employee_id": employee_id,
        "employee_name": "John Doe",
        "entry_date": now,
        "hours": Decimal("8.00"),
        "hourly_rate": Decimal("150.00"),
        "work_type": WorkType.REGULAR,
        "status": TimeEntryStatus.DRAFT,
        "description": "Development work",
        "billable": True,
        "created_by": "tester",
        "version": 1,
    }


@pytest.fixture
def time_entry(entry_kwargs) -> TimeEntryEntity:
    """A fully initialized time entry in DRAFT state."""
    return TimeEntryEntity(**entry_kwargs)


@pytest.fixture
def submitted_entry(time_entry) -> TimeEntryEntity:
    """Time entry in SUBMITTED state."""
    return time_entry.submit("submitter")


@pytest.fixture
def approved_entry(submitted_entry) -> TimeEntryEntity:
    """Time entry in APPROVED state."""
    return submitted_entry.approve("approver")


# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestTimeEntryStatus:
    def test_members(self):
        assert TimeEntryStatus.DRAFT.value == "draft"
        assert TimeEntryStatus.SUBMITTED.value == "submitted"
        assert TimeEntryStatus.APPROVED.value == "approved"
        assert TimeEntryStatus.REJECTED.value == "rejected"
        assert TimeEntryStatus.BILLED.value == "billed"

    def test_from_string(self):
        assert TimeEntryStatus.from_string("approved") == TimeEntryStatus.APPROVED
        assert TimeEntryStatus.from_string("DRAFT") == TimeEntryStatus.DRAFT
        assert TimeEntryStatus.from_string("unknown") == TimeEntryStatus.DRAFT  # fallback


class TestWorkType:
    def test_members(self):
        assert WorkType.REGULAR.value == "regular"
        assert WorkType.OVERTIME.value == "overtime"
        assert WorkType.HOLIDAY.value == "holiday"
        assert WorkType.TRAVEL.value == "travel"

    def test_from_string(self):
        assert WorkType.from_string("overtime") == WorkType.OVERTIME
        assert WorkType.from_string("REGULAR") == WorkType.REGULAR
        assert WorkType.from_string("unknown") == WorkType.REGULAR  # fallback


# -----------------------------------------------------------------------------
# Tests for TimeEntryEntity
# -----------------------------------------------------------------------------

class TestTimeEntryEntity:
    """Test the time entry entity."""

    def test_construction_success(self, time_entry):
        assert time_entry.entry_id is not None
        assert time_entry.entry_number == "TE-2026-001"
        assert time_entry.status == TimeEntryStatus.DRAFT
        assert time_entry.version == 1
        assert time_entry.entry_date.tzinfo is not None
        assert time_entry.created_at.tzinfo is not None

    def test_validation_raises_for_short_number(self, entry_kwargs):
        entry_kwargs["entry_number"] = "AB"
        with pytest.raises(ValueError, match="Entry number must be at least 3"):
            TimeEntryEntity(**entry_kwargs)

    def test_validation_raises_for_non_positive_hours(self, entry_kwargs):
        entry_kwargs["hours"] = Decimal("0")
        with pytest.raises(ValueError, match="Hours must be positive"):
            TimeEntryEntity(**entry_kwargs)

    def test_validation_raises_for_hours_exceeding_24(self, entry_kwargs):
        entry_kwargs["hours"] = Decimal("25")
        with pytest.raises(ValueError, match="Hours cannot exceed 24 per day"):
            TimeEntryEntity(**entry_kwargs)

    def test_validation_raises_for_negative_hourly_rate(self, entry_kwargs):
        entry_kwargs["hourly_rate"] = Decimal("-1")
        with pytest.raises(ValueError, match="Hourly rate cannot be negative"):
            TimeEntryEntity(**entry_kwargs)

    def test_validation_raises_for_version_zero(self, entry_kwargs):
        entry_kwargs["version"] = 0
        with pytest.raises(ValueError, match="Version must be >= 1"):
            TimeEntryEntity(**entry_kwargs)

    def test_validation_raises_for_naive_datetime(self, entry_kwargs):
        entry_kwargs["entry_date"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="entry_date must be timezone-aware"):
            TimeEntryEntity(**entry_kwargs)

        entry_kwargs["entry_date"] = datetime.now(UTC)
        entry_kwargs["approved_at"] = datetime.now()  # naive
        with pytest.raises(ValueError, match="approved_at must be timezone-aware"):
            TimeEntryEntity(**entry_kwargs)

    # ---- Audit trail ----

    def test_audit_trail(self, time_entry):
        assert time_entry.get_audit_trail() == []

        time_entry._record_audit("test_action", "tester", {"key": "value"})
        trail = time_entry.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["user_id"] == "tester"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == time_entry.version

    # ---- Computed properties ----

    def test_amount(self, time_entry):
        # 8 hours * 150 = 1200
        assert time_entry.amount == Decimal("1200.00")

    def test_billable_amount(self, time_entry):
        # billable = True => amount
        assert time_entry.billable_amount == Decimal("1200.00")

        # Non-billable
        non_billable = TimeEntryEntity(
            entry_id=uuid4(),
            entry_number="TE-NB",
            project_id=uuid4(),
            project_code="PRJ",
            project_name="Test",
            employee_id=uuid4(),
            employee_name="Tester",
            entry_date=datetime.now(UTC),
            hours=Decimal("5"),
            hourly_rate=Decimal("100"),
            work_type=WorkType.REGULAR,
            status=TimeEntryStatus.DRAFT,
            billable=False,
            created_by="tester",
        )
        assert non_billable.billable_amount == Decimal(0)

    # ---- Status transitions ----

    def test_submit(self, time_entry):
        submitted = time_entry.submit("submitter")
        assert submitted.status == TimeEntryStatus.SUBMITTED
        assert submitted.version == time_entry.version + 1
        assert submitted.updated_at > time_entry.updated_at
        assert submitted.created_by == "submitter"
        trail = submitted.get_audit_trail()
        assert any(entry["action"] == "submitted" for entry in trail)

    def test_submit_raises_if_not_draft(self, submitted_entry):
        with pytest.raises(ValueError, match="Cannot submit time entry in status submitted"):
            submitted_entry.submit("submitter")

    def test_approve(self, submitted_entry):
        approved = submitted_entry.approve("approver")
        assert approved.status == TimeEntryStatus.APPROVED
        assert approved.approved_by == "approver"
        assert approved.approved_at is not None
        assert approved.version == submitted_entry.version + 1
        trail = approved.get_audit_trail()
        assert any(entry["action"] == "approved" for entry in trail)

    def test_approve_raises_if_not_submitted(self, time_entry):
        with pytest.raises(ValueError, match="Cannot approve time entry in status draft"):
            time_entry.approve("approver")

    def test_reject(self, submitted_entry):
        rejected = submitted_entry.reject("rejecter", "Invalid data")
        assert rejected.status == TimeEntryStatus.REJECTED
        assert "Rejected: Invalid data" in rejected.description
        assert rejected.version == submitted_entry.version + 1
        trail = rejected.get_audit_trail()
        assert any(entry["action"] == "rejected" for entry in trail)

    def test_reject_raises_if_not_submitted(self, time_entry):
        with pytest.raises(ValueError, match="Cannot reject time entry in status draft"):
            time_entry.reject("rejecter", "reason")

    def test_mark_billed(self, approved_entry):
        billed = approved_entry.mark_billed("biller")
        assert billed.status == TimeEntryStatus.BILLED
        assert billed.version == approved_entry.version + 1
        trail = billed.get_audit_trail()
        assert any(entry["action"] == "marked_billed" for entry in trail)

    def test_mark_billed_raises_if_not_approved(self, submitted_entry):
        with pytest.raises(ValueError, match="Cannot mark time entry as billed in status submitted"):
            submitted_entry.mark_billed("biller")

    # ---- update_hours ----

    def test_update_hours(self, time_entry):
        new_hours = Decimal("10")
        updated = time_entry.update_hours(new_hours, "updater")
        assert updated.hours == new_hours
        assert updated.version == time_entry.version + 1
        assert updated.updated_at > time_entry.updated_at
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "hours_updated" for entry in trail)
        # Check audit details
        action_entry = next(e for e in trail if e["action"] == "hours_updated")
        assert action_entry["details"]["old_hours"] == str(time_entry.hours)
        assert action_entry["details"]["new_hours"] == str(new_hours)

    def test_update_hours_raises_for_zero(self, time_entry):
        with pytest.raises(ValueError, match="Hours must be positive"):
            time_entry.update_hours(Decimal("0"), "updater")

    def test_update_hours_raises_for_exceeding_24(self, time_entry):
        with pytest.raises(ValueError, match="Hours cannot exceed 24 per day"):
            time_entry.update_hours(Decimal("25"), "updater")

    # ---- Factory method ----

    def test_create_factory(self, employee_id, project_id):
        now = datetime.now(UTC)
        entry = TimeEntryEntity.create(
            entry_number="TE-2026-002",
            project_id=project_id,
            project_code="PRJ-456",
            project_name="Project Beta",
            employee_id=employee_id,
            employee_name="Jane Smith",
            entry_date=now,
            hours=Decimal("7.5"),
            hourly_rate=Decimal("200.00"),
            created_by="creator",
            work_type=WorkType.OVERTIME,
            description="Overtime work",
            billable=False,
        )
        assert entry.entry_id is not None
        assert entry.entry_number == "TE-2026-002"
        assert entry.status == TimeEntryStatus.DRAFT
        assert entry.work_type == WorkType.OVERTIME
        assert entry.billable is False
        assert entry.created_by == "creator"
        assert entry.version == 1

    # ---- Serialization ----

    def test_to_dict(self, time_entry):
        d = time_entry.to_dict()
        assert d["entry_id"] == str(time_entry.entry_id)
        assert d["entry_number"] == time_entry.entry_number
        assert d["status"] == time_entry.status.value
        assert d["hours"] == str(time_entry.hours)
        assert d["amount"] == str(time_entry.amount)
        assert d["billable_amount"] == str(time_entry.billable_amount)

    def test_from_dict(self, time_entry):
        d = time_entry.to_dict()
        restored = TimeEntryEntity.from_dict(d)
        assert restored.entry_id == time_entry.entry_id
        assert restored.entry_number == time_entry.entry_number
        assert restored.status == time_entry.status
        assert restored.hours == time_entry.hours
        assert restored.hourly_rate == time_entry.hourly_rate
        assert restored.work_type == time_entry.work_type
        assert restored.created_at == time_entry.created_at
        assert restored.version == time_entry.version

    def test_from_dict_with_defaults(self, entry_kwargs):
        # Test missing optional fields
        data = {
            "entry_id": str(uuid4()),
            "entry_number": "TE-DEF",
            "project_id": str(uuid4()),
            "project_code": "PRJ",
            "project_name": "Default",
            "employee_id": str(uuid4()),
            "employee_name": "Default User",
            "entry_date": datetime.now(UTC).isoformat(),
            "hours": "8",
            "hourly_rate": "100",
            "work_type": "regular",
            "status": "draft",
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        restored = TimeEntryEntity.from_dict(data)
        assert restored.description == ""
        assert restored.billable is True
        assert restored.approved_by is None
        assert restored.approved_at is None
        assert restored.created_by == "system"
        assert restored.version == 1


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestTimeEntryRepository:
    """Test the abstract repository protocol."""

    def test_methods_raise_not_implemented(self):
        repo = TimeEntryRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_employee(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_project(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_date_range(uuid4(), datetime.now(UTC), datetime.now(UTC))
        with pytest.raises(NotImplementedError):
            repo.get_pending_approval(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())