# test_aggregate_root.py
# Comprehensive tests for aggregate_root.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.project_services.aggregate_root import ProjectAggregate, ProjectRepository
from domain.project_services.cost_entry_vo import CostType
from domain.project_services.domain_events import (
    DomainEvent,
    ProjectActivatedEvent,
    ProjectCompletedEvent,
    ProjectCreatedEvent,
    RevenueRecognizedEvent,
    TimeEntrySubmittedEvent,
)
from domain.project_services.project_billing_schedule import (
    BillingMilestone,
    BillingMilestoneStatus,
    BillingType,
    ProjectBillingSchedule,
)
from domain.project_services.project_cost_tracker import CostEntry, ProjectCostTracker
from domain.project_services.project_entity import ProjectEntity, ProjectStatus, ProjectType
from domain.project_services.project_revenue_recognizer import ProjectRevenueRecognizer
from domain.project_services.retainer_contract_entity import (
    RetainerContractEntity,
    RetainerContractStatus,
)
from domain.project_services.time_entry_entity import TimeEntryEntity, TimeEntryStatus


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def project_entity(legal_entity_id):
    """Create a valid ProjectEntity."""
    return ProjectEntity(
        project_id=uuid4(),
        legal_entity_id=legal_entity_id,
        project_code="PRJ-001",
        project_name="Bridge Construction",
        project_type=ProjectType.FIXED_PRICE,
        status=ProjectStatus.DRAFT,
        start_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        end_date=datetime(2025, 12, 31, 0, 0, 0, tzinfo=UTC),
        contract_value=Decimal("1000000"),
        created_by="system",
        customer_id=uuid4(),
        customer_name="Client A",
    )


@pytest.fixture
def another_project(legal_entity_id):
    """Another project entity."""
    return ProjectEntity(
        project_id=uuid4(),
        legal_entity_id=legal_entity_id,
        project_code="PRJ-002",
        project_name="Road Construction",
        project_type=ProjectType.FIXED_PRICE,
        status=ProjectStatus.DRAFT,
        start_date=datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC),
        end_date=datetime(2025, 11, 30, 0, 0, 0, tzinfo=UTC),
        contract_value=Decimal("2000000"),
        created_by="system",
        customer_id=uuid4(),
        customer_name="Client B",
    )


@pytest.fixture
def cost_entry():
    """Create a valid CostEntry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.MATERIAL,
        amount=Decimal("500"),
        quantity=Decimal("5"),
        unit_rate=Decimal("100"),
        date=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        description="Steel beams",
    )


@pytest.fixture
def time_entry(project_entity):
    """Create a valid TimeEntryEntity."""
    return TimeEntryEntity(
        entry_id=uuid4(),
        project_id=project_entity.project_id,
        project_code=project_entity.project_code,
        employee_id=uuid4(),
        employee_name="John Doe",
        entry_date=datetime(2025, 1, 20, 9, 0, 0, tzinfo=UTC),
        hours=Decimal("8"),
        hourly_rate=Decimal("50"),
        billable=True,
        billable_amount=Decimal("400"),
        description="Foundation work",
        status=TimeEntryStatus.SUBMITTED,
        created_by="employee1",
    )


@pytest.fixture
def retainer_contract(legal_entity_id):
    """Create a valid RetainerContractEntity."""
    return RetainerContractEntity(
        contract_id=uuid4(),
        legal_entity_id=legal_entity_id,
        contract_number="RET-001",
        customer_id=uuid4(),
        customer_name="Client C",
        start_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        end_date=datetime(2025, 12, 31, 0, 0, 0, tzinfo=UTC),
        retainer_amount=Decimal("50000"),
        consumed_amount=Decimal("0"),
        status=RetainerContractStatus.ACTIVE,
        created_by="system",
    )


@pytest.fixture
def billing_schedule(project_entity):
    """Create a valid ProjectBillingSchedule."""
    milestone = BillingMilestone(
        milestone_id=uuid4(),
        milestone_name="Phase 1",
        milestone_order=1,
        amount=Decimal("250000"),
        percentage=Decimal("25"),
        due_date=datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC),
        status=BillingMilestoneStatus.PENDING,
        description="Initial payment",
    )
    return ProjectBillingSchedule.create_milestone_schedule(
        project_id=project_entity.project_id,
        project_code=project_entity.project_code,
        project_name=project_entity.project_name,
        milestones=[milestone],
        created_by="admin",
    )


@pytest.fixture
def project_aggregate(legal_entity_id, project_entity):
    """Create a ProjectAggregate with one project."""
    agg = ProjectAggregate(
        project_id=uuid4(),
        legal_entity_id=legal_entity_id,
    )
    # Add project via the method
    agg = agg.add_project(project_entity, "system")
    return agg


@pytest.fixture
def locked_aggregate(project_aggregate):
    """Return a locked aggregate."""
    return project_aggregate.lock("user1", "Testing lock")


# ============================================================================
# Tests for ProjectAggregate - Construction and Properties
# ============================================================================

class TestProjectAggregateConstruction:
    def test_initial_creation(self, legal_entity_id):
        agg = ProjectAggregate(
            project_id=uuid4(),
            legal_entity_id=legal_entity_id,
        )
        assert agg.project_id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.projects == {}
        assert agg.version == 1
        assert agg.is_locked is False
        assert agg._events == []
        assert agg._audit_trail == []

    def test_validation_version(self, legal_entity_id):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ProjectAggregate(
                project_id=uuid4(),
                legal_entity_id=legal_entity_id,
                version=0,
            )

    def test_validation_naive_timestamps(self, legal_entity_id):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            ProjectAggregate(
                project_id=uuid4(),
                legal_entity_id=legal_entity_id,
                created_at=naive,
                updated_at=datetime.now(UTC),
            )

    def test_properties(self, project_aggregate):
        assert project_aggregate.id == project_aggregate.project_id
        assert project_aggregate.is_locked is False
        assert isinstance(project_aggregate.audit_trail, list)


# ============================================================================
# Tests for Event Methods
# ============================================================================

class TestEventMethods:
    def test_add_event(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate._add_event(event)
        assert len(project_aggregate._events) == 1
        assert project_aggregate._events[0] == event
        # Audit trail should have event_added entry
        assert any(e["action"] == "event_added" for e in project_aggregate._audit_trail)

    def test_clear_events(self, project_aggregate):
        # Add an event first
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate._add_event(event)
        assert len(project_aggregate._events) == 1
        project_aggregate.clear_events()
        assert len(project_aggregate._events) == 0

    def test_get_events(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate._add_event(event)
        events = project_aggregate.get_events()
        assert len(events) == 1
        # Should be a copy
        assert events is not project_aggregate._events

    def test_pop_events(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate._add_event(event)
        events = project_aggregate.pop_events()
        assert len(events) == 1
        assert len(project_aggregate._events) == 0

    def test_pull_events(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate._add_event(event)
        events = project_aggregate.pull_events()
        assert len(events) == 1
        assert len(project_aggregate._events) == 0

    def test_register_event(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate.register_event(event)
        assert len(project_aggregate._events) == 1

    def test_apply(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate.apply(event)
        assert len(project_aggregate._events) == 1

    def test_replay(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate.replay([event])
        assert len(project_aggregate._events) == 1
        # version should be incremented
        assert project_aggregate.version == 2  # initial 1 + 1

    def test_reconstruct(self, project_aggregate):
        event = ProjectCreatedEvent(
            aggregate_id=project_aggregate.project_id,
            aggregate_version=2,
            project=project_aggregate.projects[next(iter(project_aggregate.projects))],
            created_by="system",
        )
        project_aggregate.reconstruct([event])
        assert len(project_aggregate._events) == 1
        assert project_aggregate.version == 2


# ============================================================================
# Tests for Audit Trail
# ============================================================================

class TestAuditTrail:
    def test_record_audit(self, project_aggregate):
        project_aggregate._record_audit("test_action", {"key": "value"})
        trail = project_aggregate.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["details"] == {"key": "value"}
        assert trail[0]["version"] == project_aggregate.version

    def test_clear_audit_trail(self, project_aggregate):
        project_aggregate._record_audit("test", {})
        assert len(project_aggregate._audit_trail) == 1
        project_aggregate.clear_audit_trail()
        assert len(project_aggregate._audit_trail) == 0


# ============================================================================
# Tests for Snapshot
# ============================================================================

class TestSnapshot:
    def test_snapshot(self, project_aggregate):
        snap = project_aggregate.snapshot()
        assert snap["aggregate_id"] == str(project_aggregate.project_id)
        assert snap["aggregate_type"] == "ProjectAggregate"
        assert snap["version"] == project_aggregate.version
        assert "state" in snap
        assert snap["state"]["total_projects"] == len(project_aggregate.projects)
        assert "hash" in snap
        # Check that it was added to _snapshots
        assert len(project_aggregate._snapshots) == 1
        assert project_aggregate._snapshots[0] == snap

    def test_restore_from_snapshot(self, project_aggregate):
        snap = project_aggregate.snapshot()
        # Create a new aggregate to restore into
        new_agg = ProjectAggregate(
            project_id=project_aggregate.project_id,
            legal_entity_id=project_aggregate.legal_entity_id,
        )
        new_agg.restore_from_snapshot(snap)
        # Should add an audit entry
        assert any(e["action"] == "restored_from_snapshot" for e in new_agg._audit_trail)

    def test_restore_from_snapshot_wrong_id(self, project_aggregate):
        snap = project_aggregate.snapshot()
        new_agg = ProjectAggregate(
            project_id=uuid4(),  # different id
            legal_entity_id=project_aggregate.legal_entity_id,
        )
        with pytest.raises(ValueError, match="Snapshot belongs to different aggregate"):
            new_agg.restore_from_snapshot(snap)


# ============================================================================
# Tests for Lock / Unlock
# ============================================================================

class TestLockUnlock:
    def test_lock(self, project_aggregate):
        locked = project_aggregate.lock("user1", "Reason")
        assert locked.is_locked is True
        assert locked._locked_by == "user1"
        assert locked._locked_at is not None
        # Check audit trail
        assert any(e["action"] == "locked" and e["details"]["user_id"] == "user1"
                   for e in locked._audit_trail)

    def test_lock_already_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="already locked"):
            locked_aggregate.lock("user2", "Another")

    def test_unlock(self, locked_aggregate):
        unlocked = locked_aggregate.unlock("user1")
        assert unlocked.is_locked is False
        assert unlocked._locked_by is None
        assert unlocked._locked_at is None
        assert any(e["action"] == "unlocked" for e in unlocked._audit_trail)

    def test_unlock_not_locked(self, project_aggregate):
        with pytest.raises(ValueError, match="not locked"):
            project_aggregate.unlock("user1")

    def test_unlock_wrong_user(self, locked_aggregate):
        with pytest.raises(ValueError, match="locked by user1, cannot unlock by user2"):
            locked_aggregate.unlock("user2")


# ============================================================================
# Tests for validate, version, touch, clone
# ============================================================================

class TestValidationAndUtils:
    def test_validate(self, project_aggregate):
        errors = project_aggregate.validate()
        # Should be empty because project has positive contract value
        assert errors == []

        # Add a project with negative contract value
        bad_project = ProjectEntity(
            project_id=uuid4(),
            legal_entity_id=project_aggregate.legal_entity_id,
            project_code="BAD-001",
            project_name="Bad",
            project_type=ProjectType.FIXED_PRICE,
            status=ProjectStatus.DRAFT,
            start_date=datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
            end_date=datetime(2025, 12, 31, 0, 0, 0, tzinfo=UTC),
            contract_value=Decimal("-1000"),
            created_by="system",
            customer_id=uuid4(),
            customer_name="Bad Client",
        )
        agg_with_bad = project_aggregate.add_project(bad_project, "system")
        errors2 = agg_with_bad.validate()
        assert len(errors2) == 1
        assert "negative contract value" in errors2[0]

    def test_get_version(self, project_aggregate):
        assert project_aggregate.get_version() == project_aggregate.version

    def test_increment_version(self, project_aggregate):
        old_version = project_aggregate.version
        project_aggregate.increment_version()
        assert project_aggregate.version == old_version + 1
        assert any(e["action"] == "version_incremented" for e in project_aggregate._audit_trail)

    def test_touch(self, project_aggregate):
        old_updated = project_aggregate.updated_at
        # sleep a tiny bit to ensure updated_at changes? Not needed if we check audit.
        project_aggregate.touch("user1")
        assert project_aggregate.updated_at >= old_updated  # not exactly equal, but we can check audit
        assert any(e["action"] == "touched" and e["details"]["user_id"] == "user1"
                   for e in project_aggregate._audit_trail)

    def test_clone(self, project_aggregate):
        cloned = project_aggregate.clone()
        assert cloned.project_id != project_aggregate.project_id
        assert cloned.legal_entity_id == project_aggregate.legal_entity_id
        assert cloned.projects == project_aggregate.projects  # same content but different dict?
        # Actually it's a copy, so they should be equal.
        assert cloned.projects == project_aggregate.projects
        assert cloned.version == 1
        # Check audit
        assert any(e["action"] == "cloned" for e in cloned._audit_trail)


# ============================================================================
# Tests for Project Management
# ============================================================================

class TestProjectManagement:
    def test_add_project(self, project_aggregate, another_project):
        old_count = len(project_aggregate.projects)
        # Add another project
        new_agg = project_aggregate.add_project(another_project, "admin")
        assert len(new_agg.projects) == old_count + 1
        assert another_project.project_id in new_agg.projects
        # Cost tracker and revenue recognizer should be created
        assert another_project.project_id in new_agg.cost_trackers
        assert another_project.project_id in new_agg.revenue_recognizers
        # Version incremented
        assert new_agg.version == project_aggregate.version + 1
        # Check event
        events = new_agg.get_events()
        assert any(isinstance(e, ProjectCreatedEvent) for e in events)
        # Audit trail
        assert any(e["action"] == "add_project" for e in new_agg._audit_trail)

    def test_add_project_duplicate_id(self, project_aggregate, project_entity):
        # Try to add same project again
        with pytest.raises(ValueError, match="already exists"):
            project_aggregate.add_project(project_entity, "admin")

    def test_add_project_duplicate_code(self, project_aggregate, another_project):
        # Change another_project code to match existing
        another_project.project_code = "PRJ-001"  # same as existing
        with pytest.raises(ValueError, match="already exists"):
            project_aggregate.add_project(another_project, "admin")

    def test_add_project_to_locked(self, locked_aggregate, another_project):
        with pytest.raises(ValueError, match="Cannot add project to locked aggregate"):
            locked_aggregate.add_project(another_project, "admin")

    def test_update_project(self, project_aggregate, project_entity):
        # Modify project name and update
        updated_project = project_entity.update(updated_by="admin", project_name="New Name")
        new_agg = project_aggregate.update_project(updated_project, "admin")
        assert new_agg.projects[updated_project.project_id].project_name == "New Name"
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "project_updated" for e in new_agg._audit_trail)

    def test_update_project_not_found(self, project_aggregate):
        non_existent = ProjectEntity(
            project_id=uuid4(),
            legal_entity_id=project_aggregate.legal_entity_id,
            project_code="NON",
            project_name="Non",
            project_type=ProjectType.FIXED_PRICE,
            status=ProjectStatus.DRAFT,
            start_date=datetime.now(UTC),
            end_date=datetime.now(UTC) + timedelta(days=365),
            contract_value=Decimal("1000"),
            created_by="system",
            customer_id=uuid4(),
            customer_name="Non",
        )
        with pytest.raises(ValueError, match="not found"):
            project_aggregate.update_project(non_existent, "admin")

    def test_update_project_locked(self, locked_aggregate, project_entity):
        with pytest.raises(ValueError, match="Cannot update project in locked aggregate"):
            locked_aggregate.update_project(project_entity, "admin")

    def test_remove_project(self, project_aggregate, project_entity):
        old_count = len(project_aggregate.projects)
        new_agg = project_aggregate.remove_project(project_entity.project_id, "admin")
        assert len(new_agg.projects) == old_count - 1
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "project_removed" for e in new_agg._audit_trail)

    def test_remove_project_not_found(self, project_aggregate):
        with pytest.raises(ValueError, match="not found"):
            project_aggregate.remove_project(uuid4(), "admin")

    def test_remove_project_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="Cannot remove project from locked aggregate"):
            locked_aggregate.remove_project(uuid4(), "admin")

    def test_activate_project(self, project_aggregate, project_entity):
        # project is DRAFT, activate it
        new_agg = project_aggregate.activate_project(project_entity.project_id, "manager")
        activated = new_agg.projects[project_entity.project_id]
        assert activated.status == ProjectStatus.ACTIVE
        assert new_agg.version == project_aggregate.version + 1
        # Event
        events = new_agg.get_events()
        assert any(isinstance(e, ProjectActivatedEvent) for e in events)
        # Audit
        assert any(e["action"] == "activate_project" for e in new_agg._audit_trail)

    def test_activate_project_not_found(self, project_aggregate):
        with pytest.raises(ValueError, match="not found"):
            project_aggregate.activate_project(uuid4(), "manager")

    def test_activate_project_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="Cannot activate project in locked aggregate"):
            locked_aggregate.activate_project(uuid4(), "manager")

    def test_complete_project(self, project_aggregate, project_entity):
        # First activate
        agg = project_aggregate.activate_project(project_entity.project_id, "manager")
        # Then complete
        end_date = datetime(2025, 6, 30, 0, 0, 0, tzinfo=UTC)
        new_agg = agg.complete_project(project_entity.project_id, "manager", end_date)
        completed = new_agg.projects[project_entity.project_id]
        assert completed.status == ProjectStatus.COMPLETED
        assert completed.actual_end_date == end_date
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, ProjectCompletedEvent) for e in events)

    def test_complete_project_not_found(self, project_aggregate):
        with pytest.raises(ValueError, match="not found"):
            project_aggregate.complete_project(uuid4(), "manager")

    def test_complete_project_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="Cannot complete project in locked aggregate"):
            locked_aggregate.complete_project(uuid4(), "manager")

    def test_cancel_project(self, project_aggregate, project_entity):
        new_agg = project_aggregate.cancel_project(project_entity.project_id, "Budget overrun", "manager")
        cancelled = new_agg.projects[project_entity.project_id]
        assert cancelled.status == ProjectStatus.CANCELLED
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "project_cancelled" for e in new_agg._audit_trail)

    def test_cancel_project_not_found(self, project_aggregate):
        with pytest.raises(ValueError, match="not found"):
            project_aggregate.cancel_project(uuid4(), "reason", "manager")

    def test_cancel_project_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="Cannot cancel project in locked aggregate"):
            locked_aggregate.cancel_project(uuid4(), "reason", "manager")

    def test_get_project(self, project_aggregate, project_entity):
        proj = project_aggregate.get_project(project_entity.project_id)
        assert proj == project_entity
        assert project_aggregate.get_project(uuid4()) is None

    def test_get_project_by_code(self, project_aggregate, project_entity):
        proj = project_aggregate.get_project_by_code(project_entity.project_code)
        assert proj == project_entity
        assert project_aggregate.get_project_by_code("NONEXISTENT") is None

    def test_get_active_projects(self, project_aggregate, project_entity):
        # Initially project is DRAFT, so none active
        assert len(project_aggregate.get_active_projects()) == 0
        # Activate it
        agg = project_aggregate.activate_project(project_entity.project_id, "manager")
        active = agg.get_active_projects()
        assert len(active) == 1
        assert active[0].project_id == project_entity.project_id


# ============================================================================
# Tests for Cost Management
# ============================================================================

class TestCostManagement:
    def test_add_cost_entry(self, project_aggregate, project_entity, cost_entry):
        old_tracker = project_aggregate.cost_trackers[project_entity.project_id]
        old_total = old_tracker.total_cost
        new_agg = project_aggregate.add_cost_entry(project_entity.project_id, cost_entry, "admin")
        new_tracker = new_agg.cost_trackers[project_entity.project_id]
        assert new_tracker.total_cost == old_total + cost_entry.amount
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "cost_added" for e in new_agg._audit_trail)

    def test_add_cost_entry_project_not_found(self, project_aggregate, cost_entry):
        with pytest.raises(ValueError, match="Project .* not found"):
            project_aggregate.add_cost_entry(uuid4(), cost_entry, "admin")

    def test_add_cost_entry_locked(self, locked_aggregate, cost_entry):
        with pytest.raises(ValueError, match="Cannot add cost entry to locked aggregate"):
            locked_aggregate.add_cost_entry(uuid4(), cost_entry, "admin")

    def test_get_cost_tracker(self, project_aggregate, project_entity):
        tracker = project_aggregate.get_cost_tracker(project_entity.project_id)
        assert tracker is not None
        assert tracker.project_id == project_entity.project_id
        assert project_aggregate.get_cost_tracker(uuid4()) is None

    def test_get_total_projects_cost(self, project_aggregate, project_entity, another_project, cost_entry):
        # Add another project with cost
        agg = project_aggregate.add_project(another_project, "admin")
        # Add cost to both
        agg = agg.add_cost_entry(project_entity.project_id, cost_entry, "admin")
        # add another cost entry to second project
        cost2 = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.LABOR,
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_rate=Decimal("100"),
            date=datetime.now(UTC),
            description="Labor",
        )
        agg = agg.add_cost_entry(another_project.project_id, cost2, "admin")
        total = agg.get_total_projects_cost()
        expected = cost_entry.amount + cost2.amount
        assert total == expected


# ============================================================================
# Tests for Revenue Recognition
# ============================================================================

class TestRevenueRecognition:
    def test_recognize_revenue(self, project_aggregate, project_entity):
        # First add a cost entry to have some progress
        cost_entry = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.MATERIAL,
            amount=Decimal("10000"),
            quantity=Decimal("1"),
            unit_rate=Decimal("10000"),
            date=datetime.now(UTC),
            description="Material",
        )
        agg = project_aggregate.add_cost_entry(project_entity.project_id, cost_entry, "admin")
        # Also activate project to make it eligible
        agg = agg.activate_project(project_entity.project_id, "manager")
        # Now recognize revenue
        as_of = datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)
        new_agg = agg.recognize_revenue(project_entity.project_id, as_of, "finance")
        recognizer = new_agg.revenue_recognizers[project_entity.project_id]
        assert recognizer.total_recognized_revenue > 0
        assert new_agg.version == agg.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, RevenueRecognizedEvent) for e in events)
        assert any(e["action"] == "recognize_revenue" for e in new_agg._audit_trail)

    def test_recognize_revenue_project_not_found(self, project_aggregate):
        with pytest.raises(ValueError, match="Project .* not found"):
            project_aggregate.recognize_revenue(uuid4(), datetime.now(UTC), "finance")

    def test_recognize_revenue_locked(self, locked_aggregate):
        with pytest.raises(ValueError, match="Cannot recognize revenue in locked aggregate"):
            locked_aggregate.recognize_revenue(uuid4(), datetime.now(UTC), "finance")

    def test_get_revenue_recognizer(self, project_aggregate, project_entity):
        recognizer = project_aggregate.get_revenue_recognizer(project_entity.project_id)
        assert recognizer is not None
        assert project_aggregate.get_revenue_recognizer(uuid4()) is None

    def test_get_total_recognized_revenue(self, project_aggregate, project_entity, another_project):
        # Add second project with revenue recognized
        agg = project_aggregate.add_project(another_project, "admin")
        # Activate both and recognize revenue
        agg = agg.activate_project(project_entity.project_id, "manager")
        agg = agg.activate_project(another_project.project_id, "manager")
        # Add cost to both
        cost1 = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.MATERIAL,
            amount=Decimal("5000"),
            quantity=Decimal("1"),
            unit_rate=Decimal("5000"),
            date=datetime.now(UTC),
            description="Mat1",
        )
        agg = agg.add_cost_entry(project_entity.project_id, cost1, "admin")
        cost2 = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.LABOR,
            amount=Decimal("8000"),
            quantity=Decimal("1"),
            unit_rate=Decimal("8000"),
            date=datetime.now(UTC),
            description="Labor2",
        )
        agg = agg.add_cost_entry(another_project.project_id, cost2, "admin")
        # Recognize for both
        as_of = datetime(2025, 2, 1, 0, 0, 0, tzinfo=UTC)
        agg = agg.recognize_revenue(project_entity.project_id, as_of, "finance")
        agg = agg.recognize_revenue(another_project.project_id, as_of, "finance")
        total = agg.get_total_recognized_revenue()
        # Should be sum of recognized revenues of both
        r1 = agg.revenue_recognizers[project_entity.project_id].total_recognized_revenue
        r2 = agg.revenue_recognizers[another_project.project_id].total_recognized_revenue
        assert total == r1 + r2

    def test_get_unbilled_revenue(self, project_aggregate, project_entity):
        # Add billing schedule and recognized revenue
        # First add a billing schedule
        billing = project_aggregate.billing_schedules.get(project_entity.project_id)
        if not billing:
            # Create one
            milestone = BillingMilestone(
                milestone_id=uuid4(),
                milestone_name="Phase 1",
                milestone_order=1,
                amount=Decimal("10000"),
                percentage=Decimal("10"),
                due_date=datetime.now(UTC) + timedelta(days=30),
                status=BillingMilestoneStatus.PENDING,
                description="Phase 1",
            )
            schedule = ProjectBillingSchedule.create_milestone_schedule(
                project_id=project_entity.project_id,
                project_code=project_entity.project_code,
                project_name=project_entity.project_name,
                milestones=[milestone],
                created_by="admin",
            )
            agg = project_aggregate.add_billing_schedule(project_entity.project_id, schedule, "admin")
        else:
            agg = project_aggregate
        # Activate project, add cost, recognize revenue
        agg = agg.activate_project(project_entity.project_id, "manager")
        cost_entry = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.MATERIAL,
            amount=Decimal("5000"),
            quantity=Decimal("1"),
            unit_rate=Decimal("5000"),
            date=datetime.now(UTC),
            description="Mat",
        )
        agg = agg.add_cost_entry(project_entity.project_id, cost_entry, "admin")
        as_of = datetime.now(UTC)
        agg = agg.recognize_revenue(project_entity.project_id, as_of, "finance")
        # Mark milestone ready and bill to have some billed amount
        # For simplicity, we'll just check unbilled revenue = total recognized - total billed
        recognizer = agg.revenue_recognizers[project_entity.project_id]
        total_recognized = recognizer.total_recognized_revenue
        # No billing yet, so unbilled should be total_recognized
        unbilled = agg.get_unbilled_revenue()
        # Since only one project, total recognized = total_recognized, total_billed = 0
        assert unbilled == total_recognized


# ============================================================================
# Tests for Time Entry Management
# ============================================================================

class TestTimeEntryManagement:
    def test_add_time_entry(self, project_aggregate, project_entity, time_entry):
        old_time_count = len(project_aggregate.time_entries)
        old_cost = project_aggregate.cost_trackers[project_entity.project_id].total_cost
        new_agg = project_aggregate.add_time_entry(time_entry, "employee")
        assert len(new_agg.time_entries) == old_time_count + 1
        # Should also add a cost entry
        new_cost = new_agg.cost_trackers[project_entity.project_id].total_cost
        assert new_cost == old_cost + time_entry.billable_amount
        assert new_agg.version == project_aggregate.version + 1
        events = new_agg.get_events()
        assert any(isinstance(e, TimeEntrySubmittedEvent) for e in events)
        assert any(e["action"] == "add_time_entry" for e in new_agg._audit_trail)

    def test_add_time_entry_project_not_found(self, project_aggregate, time_entry):
        time_entry.project_id = uuid4()  # change to non-existent
        with pytest.raises(ValueError, match="Project .* not found"):
            project_aggregate.add_time_entry(time_entry, "employee")

    def test_add_time_entry_locked(self, locked_aggregate, time_entry):
        with pytest.raises(ValueError, match="Cannot add time entry to locked aggregate"):
            locked_aggregate.add_time_entry(time_entry, "employee")

    def test_get_time_entries_by_project(self, project_aggregate, time_entry):
        agg = project_aggregate.add_time_entry(time_entry, "employee")
        entries = agg.get_time_entries_by_project(time_entry.project_id)
        assert len(entries) == 1
        assert entries[0] == time_entry

    def test_get_time_entries_by_employee(self, project_aggregate, time_entry):
        agg = project_aggregate.add_time_entry(time_entry, "employee")
        entries = agg.get_time_entries_by_employee(time_entry.employee_id)
        assert len(entries) == 1
        assert entries[0] == time_entry


# ============================================================================
# Tests for Billing Schedule Management
# ============================================================================

class TestBillingScheduleManagement:
    def test_add_billing_schedule(self, project_aggregate, project_entity, billing_schedule):
        old_count = len(project_aggregate.billing_schedules)
        new_agg = project_aggregate.add_billing_schedule(project_entity.project_id, billing_schedule, "admin")
        assert len(new_agg.billing_schedules) == old_count + 1
        assert new_agg.billing_schedules[project_entity.project_id] == billing_schedule
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "billing_schedule_added" for e in new_agg._audit_trail)

    def test_add_billing_schedule_project_not_found(self, project_aggregate, billing_schedule):
        with pytest.raises(ValueError, match="Project .* not found"):
            project_aggregate.add_billing_schedule(uuid4(), billing_schedule, "admin")

    def test_add_billing_schedule_locked(self, locked_aggregate, billing_schedule):
        with pytest.raises(ValueError, match="Cannot add billing schedule to locked aggregate"):
            locked_aggregate.add_billing_schedule(uuid4(), billing_schedule, "admin")

    def test_get_billing_schedule(self, project_aggregate, project_entity, billing_schedule):
        agg = project_aggregate.add_billing_schedule(project_entity.project_id, billing_schedule, "admin")
        schedule = agg.get_billing_schedule(project_entity.project_id)
        assert schedule == billing_schedule
        assert agg.get_billing_schedule(uuid4()) is None


# ============================================================================
# Tests for Retainer Contract Management
# ============================================================================

class TestRetainerContractManagement:
    def test_add_retainer_contract(self, project_aggregate, retainer_contract):
        old_count = len(project_aggregate.retainer_contracts)
        new_agg = project_aggregate.add_retainer_contract(retainer_contract, "admin")
        assert len(new_agg.retainer_contracts) == old_count + 1
        assert new_agg.retainer_contracts[retainer_contract.contract_id] == retainer_contract
        assert new_agg.version == project_aggregate.version + 1
        assert any(e["action"] == "retainer_contract_added" for e in new_agg._audit_trail)

    def test_add_retainer_contract_locked(self, locked_aggregate, retainer_contract):
        with pytest.raises(ValueError, match="Cannot add retainer contract to locked aggregate"):
            locked_aggregate.add_retainer_contract(retainer_contract, "admin")

    def test_get_retainer_contract(self, project_aggregate, retainer_contract):
        agg = project_aggregate.add_retainer_contract(retainer_contract, "admin")
        contract = agg.get_retainer_contract(retainer_contract.contract_id)
        assert contract == retainer_contract
        assert agg.get_retainer_contract(uuid4()) is None

    def test_get_active_retainer_contracts(self, project_aggregate, retainer_contract):
        agg = project_aggregate.add_retainer_contract(retainer_contract, "admin")
        # Also add an inactive one
        inactive = retainer_contract.update(updated_by="admin", status=RetainerContractStatus.EXPIRED)
        agg = agg.add_retainer_contract(inactive, "admin")
        active = agg.get_active_retainer_contracts()
        assert len(active) == 1
        assert active[0].contract_id == retainer_contract.contract_id


# ============================================================================
# Tests for Serialization and Factory
# ============================================================================

class TestSerializationAndFactory:
    def test_to_dict(self, project_aggregate):
        d = project_aggregate.to_dict()
        assert d["project_id"] == str(project_aggregate.project_id)
        assert d["legal_entity_id"] == str(project_aggregate.legal_entity_id)
        assert d["total_projects"] == len(project_aggregate.projects)
        assert d["total_cost"] == str(project_aggregate.get_total_projects_cost())
        assert d["version"] == project_aggregate.version
        assert d["is_locked"] is False

    def test_create(self, legal_entity_id):
        agg = ProjectAggregate.create(legal_entity_id, "system")
        assert agg.legal_entity_id == legal_entity_id
        assert agg.project_id is not None
        assert agg.projects == {}
        assert agg.version == 1


# ============================================================================
# Tests for Repository (abstract)
# ============================================================================

class TestProjectRepository:
    def test_abstract_methods_raise(self):
        repo = ProjectRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_legal_entity(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())