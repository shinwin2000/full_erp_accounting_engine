# test_project_billing_schedule.py
# Comprehensive tests for project_billing_schedule.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.project_services.project_billing_schedule import (
    BillingMilestone,
    BillingMilestoneStatus,
    BillingType,
    ProjectBillingSchedule,
    ProjectBillingScheduleRepository,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_milestone():
    """Create a valid BillingMilestone."""
    return BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Phase 1",
        milestone_order=1,
        amount=Decimal("10000"),
        percentage=Decimal("25"),
        due_date=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.PENDING,
        description="Initial phase",
    )


@pytest.fixture
def another_milestone():
    """Another valid BillingMilestone."""
    return BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Phase 2",
        milestone_order=2,
        amount=Decimal("15000"),
        percentage=Decimal("37.5"),
        due_date=datetime(2025, 7, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.PENDING,
        description="Second phase",
    )


@pytest.fixture
def ready_milestone():
    """A milestone in READY status."""
    return BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Ready Phase",
        milestone_order=3,
        amount=Decimal("8000"),
        percentage=Decimal("20"),
        due_date=datetime(2025, 5, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.READY,
        description="Ready to bill",
    )


@pytest.fixture
def billed_milestone():
    """A milestone in BILLED status."""
    return BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Billed Phase",
        milestone_order=4,
        amount=Decimal("5000"),
        percentage=Decimal("12.5"),
        due_date=datetime(2025, 4, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.BILLED,
        description="Already billed",
        invoice_id=uuid4(),
        invoice_number="INV-001",
        billed_at=datetime(2025, 4, 10, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def paid_milestone():
    """A milestone in PAID status."""
    return BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Paid Phase",
        milestone_order=5,
        amount=Decimal("3000"),
        percentage=Decimal("7.5"),
        due_date=datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.PAID,
        description="Already paid",
        invoice_id=uuid4(),
        invoice_number="INV-000",
        billed_at=datetime(2025, 3, 5, 12, 0, 0, tzinfo=UTC),
        paid_at=datetime(2025, 3, 15, 12, 0, 0, tzinfo=UTC),
    )


@pytest.fixture
def billing_schedule(valid_milestone, another_milestone):
    """A ProjectBillingSchedule with two pending milestones."""
    return ProjectBillingSchedule.create_milestone_schedule(
        project_id=uuid4(),
        project_code="PRJ-001",
        project_name="Test Project",
        milestones=[valid_milestone, another_milestone],
        created_by="admin",
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestBillingType:
    def test_members(self):
        assert BillingType.MILESTONE.value == "milestone"
        assert BillingType.TIME_BASED.value == "time_based"
        assert BillingType.PROGRESS_BASED.value == "progress_based"
        assert BillingType.RETAINER.value == "retainer"

    def test_from_string(self):
        assert BillingType.from_string("milestone") == BillingType.MILESTONE
        assert BillingType.from_string("MILESTONE") == BillingType.MILESTONE
        assert BillingType.from_string("time_based") == BillingType.TIME_BASED
        assert BillingType.from_string("invalid") == BillingType.MILESTONE  # default


class TestBillingMilestoneStatus:
    def test_members(self):
        assert BillingMilestoneStatus.PENDING.value == "pending"
        assert BillingMilestoneStatus.READY.value == "ready"
        assert BillingMilestoneStatus.BILLED.value == "billed"
        assert BillingMilestoneStatus.PAID.value == "paid"
        assert BillingMilestoneStatus.CANCELLED.value == "cancelled"

    def test_from_string(self):
        assert BillingMilestoneStatus.from_string("pending") == BillingMilestoneStatus.PENDING
        assert BillingMilestoneStatus.from_string("READY") == BillingMilestoneStatus.READY
        assert BillingMilestoneStatus.from_string("invalid") == BillingMilestoneStatus.PENDING


# ============================================================================
# Tests for BillingMilestone
# ============================================================================

class TestBillingMilestone:
    def test_construction_valid(self, valid_milestone):
        assert valid_milestone.milestone_name == "Phase 1"
        assert valid_milestone.amount == Decimal("10000")
        assert valid_milestone.percentage == Decimal("25")
        assert valid_milestone.status == BillingMilestoneStatus.PENDING

    def test_validation_amount_zero(self):
        with pytest.raises(ValueError, match="positive"):
            BillingMilestone(
                milestone_id=uuid4(),
                milestone_name="Zero",
                milestone_order=1,
                amount=Decimal("0"),
                percentage=Decimal("0"),
                due_date=datetime.now(UTC),
                status=BillingMilestoneStatus.PENDING,
            )

    def test_validation_amount_negative(self):
        with pytest.raises(ValueError, match="positive"):
            BillingMilestone(
                milestone_id=uuid4(),
                milestone_name="Negative",
                milestone_order=1,
                amount=Decimal("-100"),
                percentage=Decimal("0"),
                due_date=datetime.now(UTC),
                status=BillingMilestoneStatus.PENDING,
            )

    def test_validation_percentage_out_of_range(self):
        with pytest.raises(ValueError, match="between 0 and 100"):
            BillingMilestone(
                milestone_id=uuid4(),
                milestone_name="Invalid",
                milestone_order=1,
                amount=Decimal("100"),
                percentage=Decimal("150"),
                due_date=datetime.now(UTC),
                status=BillingMilestoneStatus.PENDING,
            )

    def test_validation_due_date_timezone_naive(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            BillingMilestone(
                milestone_id=uuid4(),
                milestone_name="Naive",
                milestone_order=1,
                amount=Decimal("100"),
                percentage=Decimal("10"),
                due_date=naive,
                status=BillingMilestoneStatus.PENDING,
            )

    def test_to_dict(self, valid_milestone):
        d = valid_milestone.to_dict()
        assert d["milestone_name"] == "Phase 1"
        assert d["amount"] == "10000"
        assert d["percentage"] == "25"
        assert d["status"] == "pending"
        assert d["invoice_id"] is None

    def test_from_dict(self, valid_milestone):
        data = valid_milestone.to_dict()
        restored = BillingMilestone.from_dict(data)
        assert restored.milestone_id == valid_milestone.milestone_id
        assert restored.amount == valid_milestone.amount
        assert restored.status == valid_milestone.status
        assert restored.due_date == valid_milestone.due_date


# ============================================================================
# Tests for ProjectBillingSchedule
# ============================================================================

class TestProjectBillingScheduleCreation:
    def test_create_milestone_schedule(self, valid_milestone, another_milestone):
        project_id = uuid4()
        schedule = ProjectBillingSchedule.create_milestone_schedule(
            project_id=project_id,
            project_code="PRJ-001",
            project_name="Test Project",
            milestones=[valid_milestone, another_milestone],
            created_by="admin",
        )
        assert schedule.project_id == project_id
        assert schedule.total_amount == Decimal("25000")
        assert schedule.total_billed == Decimal("0")
        assert schedule.total_paid == Decimal("0")
        assert schedule.billing_type == BillingType.MILESTONE
        assert len(schedule.milestones) == 2
        assert schedule.version == 1
        # Audit trail
        trail = schedule.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "created"
        assert trail[0]["user_id"] == "admin"

    def test_validation_version(self, valid_milestone):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ProjectBillingSchedule(
                schedule_id=uuid4(),
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                billing_type=BillingType.MILESTONE,
                milestones=[valid_milestone],
                version=0,
            )

    def test_validation_timezone_naive(self, valid_milestone):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            ProjectBillingSchedule(
                schedule_id=uuid4(),
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                billing_type=BillingType.MILESTONE,
                milestones=[valid_milestone],
                created_at=naive,
                updated_at=datetime.now(UTC),
            )


class TestProjectBillingScheduleOperations:
    def test_add_milestone(self, billing_schedule, valid_milestone):
        new_milestone = BillingMilestone(
            milestone_id=uuid4(),
            milestone_name="Phase 3",
            milestone_order=3,
            amount=Decimal("5000"),
            percentage=Decimal("12.5"),
            due_date=datetime(2025, 8, 1, 12, 0, 0, tzinfo=UTC),
            status=BillingMilestoneStatus.PENDING,
        )
        updated = billing_schedule.add_milestone(new_milestone, added_by="user1")
        assert len(updated.milestones) == 3
        assert updated.total_amount == Decimal("30000")  # 10000+15000+5000
        assert updated.version == billing_schedule.version + 1
        trail = updated.get_audit_trail()
        assert len(trail) == 1  # Only the latest action is stored on new instance? Actually audit trail is not copied.
        # The new instance has its own _audit_trail; we recorded only the add_milestone.
        assert trail[0]["action"] == "milestone_added"
        assert trail[0]["details"]["milestone_name"] == "Phase 3"

    def test_remove_milestone(self, billing_schedule, valid_milestone):
        # Remove the first milestone
        milestone_id = valid_milestone.milestone_id
        updated = billing_schedule.remove_milestone(milestone_id, removed_by="user2")
        assert len(updated.milestones) == 1
        assert updated.total_amount == Decimal("15000")
        assert updated.version == billing_schedule.version + 1
        trail = updated.get_audit_trail()
        assert trail[0]["action"] == "milestone_removed"
        assert trail[0]["details"]["milestone_name"] == valid_milestone.milestone_name

    def test_remove_milestone_not_found(self, billing_schedule):
        with pytest.raises(ValueError, match="not found"):
            billing_schedule.remove_milestone(uuid4(), removed_by="admin")

    def test_mark_milestone_ready(self, billing_schedule, valid_milestone):
        milestone_id = valid_milestone.milestone_id
        updated = billing_schedule.mark_milestone_ready(milestone_id, marked_by="manager")
        # Find the milestone; it should be READY
        milestone = next(m for m in updated.milestones if m.milestone_id == milestone_id)
        assert milestone.status == BillingMilestoneStatus.READY
        assert updated.version == billing_schedule.version + 1
        trail = updated.get_audit_trail()
        assert trail[0]["action"] == "milestone_marked_ready"

    def test_mark_milestone_ready_not_pending(self, billing_schedule, ready_milestone):
        # This milestone is already READY
        # Add it to the schedule
        schedule_with_ready = billing_schedule.add_milestone(ready_milestone, "admin")
        with pytest.raises(ValueError, match="not found or not in PENDING"):
            schedule_with_ready.mark_milestone_ready(ready_milestone.milestone_id, "manager")

    def test_record_billing(self, billing_schedule, ready_milestone):
        # First add a READY milestone
        schedule_with_ready = billing_schedule.add_milestone(ready_milestone, "admin")
        # Then mark it ready? Actually the fixture is already READY, but we added it as READY.
        # But the record_billing requires status READY. Our ready_milestone is already READY.
        # Now we record billing for it.
        invoice_id = uuid4()
        invoice_number = "INV-002"
        updated = schedule_with_ready.record_billing(
            milestone_id=ready_milestone.milestone_id,
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            billed_by="biller",
        )
        # Find the milestone
        milestone = next(m for m in updated.milestones if m.milestone_id == ready_milestone.milestone_id)
        assert milestone.status == BillingMilestoneStatus.BILLED
        assert milestone.invoice_id == invoice_id
        assert milestone.invoice_number == invoice_number
        assert milestone.billed_at is not None
        assert updated.total_billed == Decimal("8000")  # only this one
        assert updated.version == schedule_with_ready.version + 1
        trail = updated.get_audit_trail()
        assert trail[0]["action"] == "billing_recorded"

    def test_record_billing_milestone_not_ready(self, billing_schedule, valid_milestone):
        # valid_milestone is PENDING, not READY
        with pytest.raises(ValueError, match="not found or not in READY"):
            billing_schedule.record_billing(
                milestone_id=valid_milestone.milestone_id,
                invoice_id=uuid4(),
                invoice_number="INV-003",
                billed_by="biller",
            )

    def test_record_payment(self, billing_schedule, billed_milestone):
        # Add a BILLED milestone
        schedule_with_billed = billing_schedule.add_milestone(billed_milestone, "admin")
        # Record payment for it
        updated = schedule_with_billed.record_payment(
            milestone_id=billed_milestone.milestone_id,
            paid_by="collector",
        )
        milestone = next(m for m in updated.milestones if m.milestone_id == billed_milestone.milestone_id)
        assert milestone.status == BillingMilestoneStatus.PAID
        assert milestone.paid_at is not None
        assert updated.total_paid == Decimal("5000")
        assert updated.version == schedule_with_billed.version + 1
        trail = updated.get_audit_trail()
        assert trail[0]["action"] == "payment_recorded"

    def test_record_payment_milestone_not_billed(self, billing_schedule, valid_milestone):
        with pytest.raises(ValueError, match="not found or not in BILLED"):
            billing_schedule.record_payment(valid_milestone.milestone_id, "collector")

    def test_get_outstanding_billing(self, billing_schedule):
        # Initially zero
        assert billing_schedule.get_outstanding_billing() == Decimal("0")
        # Add a billed milestone (not paid)
        schedule_with_billed = billing_schedule.add_milestone(billed_milestone, "admin")
        # Billed amount 5000, paid 0 -> outstanding 5000
        assert schedule_with_billed.get_outstanding_billing() == Decimal("5000")
        # Record payment for it
        schedule_with_paid = schedule_with_billed.record_payment(
            billed_milestone.milestone_id,
            paid_by="collector",
        )
        # Now outstanding should be 0
        assert schedule_with_paid.get_outstanding_billing() == Decimal("0")

    def test_get_ready_to_bill(self, billing_schedule):
        # Initially no READY milestones
        assert billing_schedule.get_ready_to_bill() == Decimal("0")
        # Add a READY milestone
        schedule_with_ready = billing_schedule.add_milestone(ready_milestone, "admin")
        assert schedule_with_ready.get_ready_to_bill() == Decimal("8000")
        # Mark another as ready
        # We'll take the first pending milestone and mark it ready
        first_pending = next(m for m in schedule_with_ready.milestones if m.status == BillingMilestoneStatus.PENDING)
        schedule_with_two_ready = schedule_with_ready.mark_milestone_ready(first_pending.milestone_id, "manager")
        # Total ready: 8000 + first_pending.amount (which is 10000) = 18000
        assert schedule_with_two_ready.get_ready_to_bill() == Decimal("18000")

    def test_get_upcoming_billing(self, billing_schedule):
        # Create milestones with due dates in the future
        today = datetime.now(UTC)
        future1 = today + timedelta(days=10)
        future2 = today + timedelta(days=25)
        future3 = today + timedelta(days=40)  # beyond 30 days
        m1 = BillingMilestone(
            milestone_id=uuid4(),
            milestone_name="Future 1",
            milestone_order=10,
            amount=Decimal("1000"),
            percentage=Decimal("2.5"),
            due_date=future1,
            status=BillingMilestoneStatus.PENDING,
        )
        m2 = BillingMilestone(
            milestone_id=uuid4(),
            milestone_name="Future 2",
            milestone_order=11,
            amount=Decimal("2000"),
            percentage=Decimal("5"),
            due_date=future2,
            status=BillingMilestoneStatus.PENDING,
        )
        m3 = BillingMilestone(
            milestone_id=uuid4(),
            milestone_name="Future 3",
            milestone_order=12,
            amount=Decimal("3000"),
            percentage=Decimal("7.5"),
            due_date=future3,
            status=BillingMilestoneStatus.PENDING,
        )
        schedule = billing_schedule.add_milestone(m1, "admin").add_milestone(m2, "admin").add_milestone(m3, "admin")
        upcoming = schedule.get_upcoming_billing(days_ahead=30)
        # Should return m1 and m2, not m3 (due beyond 30 days)
        assert len(upcoming) == 2
        assert m1 in upcoming
        assert m2 in upcoming
        assert m3 not in upcoming

        # Also, only PENDING milestones should be included; a READY milestone with due date within range should NOT be included
        ready_in_range = BillingMilestone(
            milestone_id=uuid4(),
            milestone_name="Ready in range",
            milestone_order=13,
            amount=Decimal("500"),
            percentage=Decimal("1.25"),
            due_date=today + timedelta(days=5),
            status=BillingMilestoneStatus.READY,
        )
        schedule_with_ready = schedule.add_milestone(ready_in_range, "admin")
        upcoming2 = schedule_with_ready.get_upcoming_billing(days_ahead=30)
        # The READY milestone should NOT be included
        assert ready_in_range not in upcoming2


# ============================================================================
# Tests for Serialization
# ============================================================================

class TestProjectBillingScheduleSerialization:
    def test_to_dict(self, billing_schedule):
        d = billing_schedule.to_dict()
        assert d["project_code"] == "PRJ-001"
        assert d["total_amount"] == "25000"
        assert d["billing_type"] == "milestone"
        assert len(d["milestones"]) == 2
        assert d["outstanding_billing"] == "0"
        assert d["ready_to_bill"] == "0"

    def test_from_dict(self, billing_schedule):
        data = billing_schedule.to_dict()
        restored = ProjectBillingSchedule.from_dict(data)
        assert restored.schedule_id == billing_schedule.schedule_id
        assert restored.project_code == billing_schedule.project_code
        assert restored.total_amount == billing_schedule.total_amount
        assert len(restored.milestones) == len(billing_schedule.milestones)
        assert restored.version == billing_schedule.version
        # Check a milestone
        assert restored.milestones[0].milestone_id == billing_schedule.milestones[0].milestone_id


# ============================================================================
# Tests for Repository (abstract)
# ============================================================================

class TestProjectBillingScheduleRepository:
    def test_abstract_methods_raise_not_implemented(self):
        repo = ProjectBillingScheduleRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_project(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())