# test_project_cost_tracker.py
# Comprehensive tests for project_cost_tracker.py

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.project_services.project_cost_tracker import (
    CostEntry,
    CostType,
    ProjectCostTracker,
    ProjectCostTrackerRepository,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def valid_cost_entry_material():
    """Create a valid material cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.MATERIAL,
        amount=Decimal("1500.00"),
        quantity=Decimal("10"),
        unit_rate=Decimal("150.00"),
        date=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        description="Steel beams",
        vendor_id=uuid4(),
        vendor_name="SteelCo Ltd.",
        invoice_number="INV-1001",
        reference_id=uuid4(),
    )


@pytest.fixture
def valid_cost_entry_labor():
    """Create a valid labor cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.LABOR,
        amount=Decimal("2500.00"),
        quantity=Decimal("40"),
        unit_rate=Decimal("62.50"),
        date=datetime(2025, 1, 20, 14, 0, 0, tzinfo=UTC),
        description="Welding labor",
    )


@pytest.fixture
def valid_cost_entry_subcontractor():
    """Create a valid subcontractor cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.SUBCONTRACTOR,
        amount=Decimal("5000.00"),
        quantity=Decimal("1"),
        unit_rate=Decimal("5000.00"),
        date=datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC),
        description="Electrical subcontractor",
        vendor_id=uuid4(),
        vendor_name="Electric Inc.",
        invoice_number="INV-2001",
    )


@pytest.fixture
def valid_cost_entry_equipment():
    """Create a valid equipment cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.EQUIPMENT,
        amount=Decimal("800.00"),
        quantity=Decimal("2"),
        unit_rate=Decimal("400.00"),
        date=datetime(2025, 2, 10, 11, 0, 0, tzinfo=UTC),
        description="Excavator rental",
    )


@pytest.fixture
def valid_cost_entry_travel():
    """Create a valid travel cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.TRAVEL,
        amount=Decimal("300.00"),
        quantity=Decimal("1"),
        unit_rate=Decimal("300.00"),
        date=datetime(2025, 2, 15, 16, 0, 0, tzinfo=UTC),
        description="Site visit transport",
    )


@pytest.fixture
def valid_cost_entry_overhead():
    """Create a valid overhead cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.OVERHEAD,
        amount=Decimal("200.00"),
        quantity=Decimal("1"),
        unit_rate=Decimal("200.00"),
        date=datetime(2025, 2, 20, 12, 0, 0, tzinfo=UTC),
        description="Project management software",
    )


@pytest.fixture
def valid_cost_entry_other():
    """Create a valid other cost entry."""
    return CostEntry(
        entry_id=uuid4(),
        cost_type=CostType.OTHER,
        amount=Decimal("100.00"),
        quantity=Decimal("1"),
        unit_rate=Decimal("100.00"),
        date=datetime(2025, 3, 1, 8, 0, 0, tzinfo=UTC),
        description="Miscellaneous supplies",
    )


@pytest.fixture
def project_cost_tracker(valid_cost_entry_material, valid_cost_entry_labor):
    """Create a ProjectCostTracker with initial costs."""
    tracker = ProjectCostTracker(
        tracker_id=uuid4(),
        project_id=uuid4(),
        project_code="PRJ-001",
        project_name="Bridge Construction",
        created_by="admin",
    )
    # Add some costs to have non-zero totals
    tracker = tracker.add_cost(valid_cost_entry_material, "admin")
    tracker = tracker.add_cost(valid_cost_entry_labor, "admin")
    return tracker


# ============================================================================
# Tests for Enums
# ============================================================================

class TestCostType:
    def test_members(self):
        assert CostType.MATERIAL.value == "material"
        assert CostType.LABOR.value == "labor"
        assert CostType.SUBCONTRACTOR.value == "subcontractor"
        assert CostType.EQUIPMENT.value == "equipment"
        assert CostType.TRAVEL.value == "travel"
        assert CostType.OVERHEAD.value == "overhead"
        assert CostType.OTHER.value == "other"

    def test_from_string(self):
        assert CostType.from_string("material") == CostType.MATERIAL
        assert CostType.from_string("MATERIAL") == CostType.MATERIAL
        assert CostType.from_string("labor") == CostType.LABOR
        assert CostType.from_string("invalid") == CostType.OTHER  # default


# ============================================================================
# Tests for CostEntry
# ============================================================================

class TestCostEntry:
    def test_construction_valid(self, valid_cost_entry_material):
        entry = valid_cost_entry_material
        assert entry.amount == Decimal("1500.00")
        assert entry.cost_type == CostType.MATERIAL
        assert entry.total_amount == Decimal("1500.00")  # property

    def test_validation_negative_amount(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("-100"),
                quantity=Decimal("1"),
                unit_rate=Decimal("100"),
                date=datetime.now(UTC),
                description="Negative",
            )

    def test_validation_negative_quantity(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("-1"),
                unit_rate=Decimal("100"),
                date=datetime.now(UTC),
                description="Negative quantity",
            )

    def test_validation_negative_unit_rate(self):
        with pytest.raises(ValueError, match="cannot be negative"):
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_rate=Decimal("-10"),
                date=datetime.now(UTC),
                description="Negative rate",
            )

    def test_validation_naive_date(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_rate=Decimal("100"),
                date=naive,
                description="Naive date",
            )

    def test_validation_empty_description(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("1"),
                unit_rate=Decimal("100"),
                date=datetime.now(UTC),
                description="",
            )

    def test_to_dict(self, valid_cost_entry_material):
        d = valid_cost_entry_material.to_dict()
        assert d["cost_type"] == "material"
        assert d["amount"] == "1500.00"
        assert d["description"] == "Steel beams"
        assert d["vendor_name"] == "SteelCo Ltd."

    def test_from_dict(self, valid_cost_entry_material):
        data = valid_cost_entry_material.to_dict()
        restored = CostEntry.from_dict(data)
        assert restored.entry_id == valid_cost_entry_material.entry_id
        assert restored.amount == valid_cost_entry_material.amount
        assert restored.cost_type == valid_cost_entry_material.cost_type
        assert restored.date == valid_cost_entry_material.date


# ============================================================================
# Tests for ProjectCostTracker
# ============================================================================

class TestProjectCostTrackerConstruction:
    def test_create(self):
        project_id = uuid4()
        tracker = ProjectCostTracker.create(project_id)  # expects a ProjectEntity, but create takes project
        # Actually create expects a ProjectEntity object. In the code, it uses project.project_id, project.project_code, etc.
        # We'll create a mock ProjectEntity with attributes.
        from unittest.mock import MagicMock
        project = MagicMock()
        project.project_id = uuid4()
        project.project_code = "PRJ-002"
        project.project_name = "New Project"
        tracker = ProjectCostTracker.create(project)
        assert tracker.project_id == project.project_id
        assert tracker.project_code == "PRJ-002"
        assert tracker.project_name == "New Project"
        assert tracker.total_cost == Decimal("0")
        assert tracker.version == 1
        assert tracker.created_by == "system"
        assert tracker.tracker_id is not None

    def test_validation_version(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            ProjectCostTracker(
                tracker_id=uuid4(),
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                version=0,
            )

    def test_validation_naive_timestamps(self):
        naive = datetime(2025, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            ProjectCostTracker(
                tracker_id=uuid4(),
                project_id=uuid4(),
                project_code="PRJ-001",
                project_name="Test",
                created_at=naive,
                updated_at=datetime.now(UTC),
            )


class TestProjectCostTrackerOperations:
    def test_add_cost(self, project_cost_tracker, valid_cost_entry_subcontractor):
        tracker = project_cost_tracker
        initial_total = tracker.total_cost
        initial_material = tracker.material_cost
        initial_labor = tracker.labor_cost
        initial_entries = len(tracker.entries)

        updated = tracker.add_cost(valid_cost_entry_subcontractor, "user1")
        assert len(updated.entries) == initial_entries + 1
        assert updated.total_cost == initial_total + valid_cost_entry_subcontractor.amount
        assert updated.subcontractor_cost == Decimal("5000.00")  # first subcontractor
        assert updated.material_cost == initial_material  # unchanged
        assert updated.labor_cost == initial_labor      # unchanged
        assert updated.version == tracker.version + 1
        # Audit trail
        trail = updated.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cost_added"
        assert trail[0]["user_id"] == "user1"
        assert trail[0]["details"]["cost_type"] == "subcontractor"

    def test_add_cost_all_types(self):
        # Create a tracker and add one of each type, verify totals
        tracker = ProjectCostTracker(
            tracker_id=uuid4(),
            project_id=uuid4(),
            project_code="PRJ-003",
            project_name="Test All",
            created_by="admin",
        )
        entries = [
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.MATERIAL,
                amount=Decimal("1000"),
                quantity=Decimal("1"),
                unit_rate=Decimal("1000"),
                date=datetime.now(UTC),
                description="Material",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.LABOR,
                amount=Decimal("2000"),
                quantity=Decimal("1"),
                unit_rate=Decimal("2000"),
                date=datetime.now(UTC),
                description="Labor",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.SUBCONTRACTOR,
                amount=Decimal("3000"),
                quantity=Decimal("1"),
                unit_rate=Decimal("3000"),
                date=datetime.now(UTC),
                description="Subcon",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.EQUIPMENT,
                amount=Decimal("4000"),
                quantity=Decimal("1"),
                unit_rate=Decimal("4000"),
                date=datetime.now(UTC),
                description="Equipment",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.TRAVEL,
                amount=Decimal("500"),
                quantity=Decimal("1"),
                unit_rate=Decimal("500"),
                date=datetime.now(UTC),
                description="Travel",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.OVERHEAD,
                amount=Decimal("600"),
                quantity=Decimal("1"),
                unit_rate=Decimal("600"),
                date=datetime.now(UTC),
                description="Overhead",
            ),
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.OTHER,
                amount=Decimal("700"),
                quantity=Decimal("1"),
                unit_rate=Decimal("700"),
                date=datetime.now(UTC),
                description="Other",
            ),
        ]
        for e in entries:
            tracker = tracker.add_cost(e, "admin")
        # Check totals
        assert tracker.material_cost == Decimal("1000")
        assert tracker.labor_cost == Decimal("2000")
        assert tracker.subcontractor_cost == Decimal("3000")
        assert tracker.equipment_cost == Decimal("4000")
        assert tracker.travel_cost == Decimal("500")
        assert tracker.overhead_cost == Decimal("600")
        assert tracker.other_cost == Decimal("700")
        assert tracker.total_cost == Decimal("11800")

    def test_get_cost_by_type(self, project_cost_tracker):
        tracker = project_cost_tracker
        # After adding material and labor, material_cost should be set.
        assert tracker.get_cost_by_type(CostType.MATERIAL) == tracker.material_cost
        assert tracker.get_cost_by_type(CostType.LABOR) == tracker.labor_cost
        assert tracker.get_cost_by_type(CostType.SUBCONTRACTOR) == Decimal("0")
        assert tracker.get_cost_by_type(CostType.EQUIPMENT) == Decimal("0")
        assert tracker.get_cost_by_type(CostType.TRAVEL) == Decimal("0")
        assert tracker.get_cost_by_type(CostType.OVERHEAD) == Decimal("0")
        assert tracker.get_cost_by_type(CostType.OTHER) == Decimal("0")

    def test_get_cost_breakdown(self, project_cost_tracker):
        breakdown = project_cost_tracker.get_cost_breakdown()
        assert breakdown["material"] == project_cost_tracker.material_cost
        assert breakdown["labor"] == project_cost_tracker.labor_cost
        assert breakdown["subcontractor"] == Decimal("0")
        assert breakdown["equipment"] == Decimal("0")
        assert breakdown["travel"] == Decimal("0")
        assert breakdown["overhead"] == Decimal("0")
        assert breakdown["other"] == Decimal("0")
        assert breakdown["total"] == project_cost_tracker.total_cost

    def test_get_entries_by_date_range(self, project_cost_tracker):
        # Add entries with different dates
        now = datetime.now(UTC)
        entry1 = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.MATERIAL,
            amount=Decimal("100"),
            quantity=Decimal("1"),
            unit_rate=Decimal("100"),
            date=now - timedelta(days=5),
            description="Past",
        )
        entry2 = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.LABOR,
            amount=Decimal("200"),
            quantity=Decimal("1"),
            unit_rate=Decimal("200"),
            date=now + timedelta(days=2),
            description="Future",
        )
        tracker = project_cost_tracker.add_cost(entry1, "admin").add_cost(entry2, "admin")
        from_date = now - timedelta(days=10)
        to_date = now + timedelta(days=1)
        filtered = tracker.get_entries_by_date_range(from_date, to_date)
        # Should include entry1 but not entry2
        assert len(filtered) == 1
        assert filtered[0].entry_id == entry1.entry_id

        # Including all
        from_date2 = now - timedelta(days=10)
        to_date2 = now + timedelta(days=10)
        filtered2 = tracker.get_entries_by_date_range(from_date2, to_date2)
        assert len(filtered2) == 2

    def test_get_entries_by_type(self, project_cost_tracker):
        # Already has material and labor entries
        material_entries = project_cost_tracker.get_entries_by_type(CostType.MATERIAL)
        assert len(material_entries) == 1
        assert material_entries[0].cost_type == CostType.MATERIAL

        labor_entries = project_cost_tracker.get_entries_by_type(CostType.LABOR)
        assert len(labor_entries) == 1
        assert labor_entries[0].cost_type == CostType.LABOR

        # Add subcontractor
        subcon_entry = CostEntry(
            entry_id=uuid4(),
            cost_type=CostType.SUBCONTRACTOR,
            amount=Decimal("3000"),
            quantity=Decimal("1"),
            unit_rate=Decimal("3000"),
            date=datetime.now(UTC),
            description="Sub",
        )
        tracker = project_cost_tracker.add_cost(subcon_entry, "admin")
        subcon_entries = tracker.get_entries_by_type(CostType.SUBCONTRACTOR)
        assert len(subcon_entries) == 1


class TestProjectCostTrackerSerialization:
    def test_to_dict(self, project_cost_tracker):
        d = project_cost_tracker.to_dict()
        assert d["tracker_id"] == str(project_cost_tracker.tracker_id)
        assert d["project_code"] == "PRJ-001"
        assert d["total_cost"] == str(project_cost_tracker.total_cost)
        assert "cost_breakdown" in d
        assert d["entries_count"] == len(project_cost_tracker.entries)
        assert d["version"] == project_cost_tracker.version

    def test_from_dict(self, project_cost_tracker):
        data = project_cost_tracker.to_dict()
        # to_dict doesn't include all fields needed for from_dict (e.g., entries details, material_cost, etc.)
        # We need to add them manually for a round-trip.
        # Actually the from_dict expects entries, material_cost, labor_cost, etc. We need to include them.
        data.update({
            "material_cost": str(project_cost_tracker.material_cost),
            "labor_cost": str(project_cost_tracker.labor_cost),
            "subcontractor_cost": str(project_cost_tracker.subcontractor_cost),
            "equipment_cost": str(project_cost_tracker.equipment_cost),
            "travel_cost": str(project_cost_tracker.travel_cost),
            "overhead_cost": str(project_cost_tracker.overhead_cost),
            "other_cost": str(project_cost_tracker.other_cost),
            "entries": [e.to_dict() for e in project_cost_tracker.entries],
            "created_by": project_cost_tracker.created_by,
        })
        restored = ProjectCostTracker.from_dict(data)
        assert restored.tracker_id == project_cost_tracker.tracker_id
        assert restored.project_code == project_cost_tracker.project_code
        assert restored.total_cost == project_cost_tracker.total_cost
        assert len(restored.entries) == len(project_cost_tracker.entries)
        assert restored.material_cost == project_cost_tracker.material_cost
        assert restored.labor_cost == project_cost_tracker.labor_cost
        assert restored.version == project_cost_tracker.version


class TestProjectCostTrackerAudit:
    def test_audit_trail(self, project_cost_tracker):
        # Initial creation has no audit trail
        assert len(project_cost_tracker.get_audit_trail()) == 0
        # Add a cost
        tracker = project_cost_tracker.add_cost(
            CostEntry(
                entry_id=uuid4(),
                cost_type=CostType.OTHER,
                amount=Decimal("50"),
                quantity=Decimal("1"),
                unit_rate=Decimal("50"),
                date=datetime.now(UTC),
                description="Extra",
            ),
            "userX"
        )
        trail = tracker.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "cost_added"
        assert trail[0]["user_id"] == "userX"


# ============================================================================
# Tests for Repository (abstract)
# ============================================================================

class TestProjectCostTrackerRepository:
    def test_abstract_methods_raise(self):
        repo = ProjectCostTrackerRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_project(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
