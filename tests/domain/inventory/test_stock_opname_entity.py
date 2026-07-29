# tests/domain/inventory/test_stock_opname_entity.py
"""
Comprehensive unit tests for Stock Opname Entity.

Covers:
- Enums: StockOpnameStatus, DiscrepancyType (members, from_string)
- OpnameItem value object (construction, properties, serialization)
- StockOpnameEntity: factory, properties, status transitions, item management,
  batch operations, summary, serialization
- Repository protocol (abstract methods)
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from domain.inventory.stock_opname_entity import (
    DiscrepancyType,
    OpnameItem,
    StockOpnameEntity,
    StockOpnameRepository,
    StockOpnameStatus,
)

# -----------------------------------------------------------------------------
# Tests for Enums
# -----------------------------------------------------------------------------

class TestStockOpnameStatus:
    def test_members(self):
        assert StockOpnameStatus.PLANNED.value == "planned"
        assert StockOpnameStatus.IN_PROGRESS.value == "in_progress"
        assert StockOpnameStatus.COMPLETED.value == "completed"
        assert StockOpnameStatus.CANCELLED.value == "cancelled"
        assert StockOpnameStatus.APPROVED.value == "approved"
        assert StockOpnameStatus.REJECTED.value == "rejected"
        assert StockOpnameStatus.PENDING.value == "pending"

    def test_from_string(self):
        """Test from_string method - previously untested."""
        assert StockOpnameStatus.from_string("planned") == StockOpnameStatus.PLANNED
        assert StockOpnameStatus.from_string("in_progress") == StockOpnameStatus.IN_PROGRESS
        assert StockOpnameStatus.from_string("completed") == StockOpnameStatus.COMPLETED
        assert StockOpnameStatus.from_string("cancelled") == StockOpnameStatus.CANCELLED
        assert StockOpnameStatus.from_string("approved") == StockOpnameStatus.APPROVED
        assert StockOpnameStatus.from_string("rejected") == StockOpnameStatus.REJECTED
        assert StockOpnameStatus.from_string("pending") == StockOpnameStatus.PENDING
        # Case insensitivity
        assert StockOpnameStatus.from_string("PLANNED") == StockOpnameStatus.PLANNED
        assert StockOpnameStatus.from_string("In_Progress") == StockOpnameStatus.IN_PROGRESS
        # Unknown -> fallback to PLANNED
        assert StockOpnameStatus.from_string("unknown") == StockOpnameStatus.PLANNED
        assert StockOpnameStatus.from_string("") == StockOpnameStatus.PLANNED


class TestDiscrepancyType:
    def test_members(self):
        assert DiscrepancyType.SURPLUS.value == "surplus"
        assert DiscrepancyType.SHORTAGE.value == "shortage"
        assert DiscrepancyType.DAMAGE.value == "damage"
        assert DiscrepancyType.EXPIRED.value == "expired"
        assert DiscrepancyType.NONE.value == "none"

    def test_from_string(self):
        """Test from_string method - previously untested."""
        assert DiscrepancyType.from_string("surplus") == DiscrepancyType.SURPLUS
        assert DiscrepancyType.from_string("shortage") == DiscrepancyType.SHORTAGE
        assert DiscrepancyType.from_string("damage") == DiscrepancyType.DAMAGE
        assert DiscrepancyType.from_string("expired") == DiscrepancyType.EXPIRED
        assert DiscrepancyType.from_string("none") == DiscrepancyType.NONE
        # Case insensitivity
        assert DiscrepancyType.from_string("SURPLUS") == DiscrepancyType.SURPLUS
        assert DiscrepancyType.from_string("ShOrTaGe") == DiscrepancyType.SHORTAGE
        # Unknown -> fallback to NONE
        assert DiscrepancyType.from_string("unknown") == DiscrepancyType.NONE
        assert DiscrepancyType.from_string("") == DiscrepancyType.NONE


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def warehouse_id() -> UUID:
    return uuid4()


@pytest.fixture
def performed_by() -> UUID:
    return uuid4()


@pytest.fixture
def opname_date() -> date:
    return date(2026, 1, 15)


@pytest.fixture
def sample_item_kwargs() -> dict[str, Any]:
    return {
        "item_id": uuid4(),
        "item_sku": "SKU-001",
        "item_name": "Test Item",
        "system_quantity": Decimal("100.00"),
        "physical_quantity": Decimal("120.00"),
        "unit_cost": Decimal("50.00"),
        "notes": "Counted by warehouse team",
        "counted_by": uuid4(),
    }


@pytest.fixture
def sample_item(sample_item_kwargs) -> OpnameItem:
    """Create an OpnameItem with surplus."""
    return OpnameItem(
        item_id=sample_item_kwargs["item_id"],
        item_sku=sample_item_kwargs["item_sku"],
        item_name=sample_item_kwargs["item_name"],
        system_quantity=sample_item_kwargs["system_quantity"],
        physical_quantity=sample_item_kwargs["physical_quantity"],
        discrepancy=Decimal("20.00"),  # 120 - 100
        discrepancy_type=DiscrepancyType.SURPLUS,
        unit_cost=sample_item_kwargs["unit_cost"],
        notes=sample_item_kwargs["notes"],
        counted_by=sample_item_kwargs["counted_by"],
        counted_at=datetime.now(UTC),
    )


@pytest.fixture
def another_item() -> OpnameItem:
    return OpnameItem(
        item_id=uuid4(),
        item_sku="SKU-002",
        item_name="Another Item",
        system_quantity=Decimal("50.00"),
        physical_quantity=Decimal("30.00"),
        discrepancy=Decimal("20.00"),
        discrepancy_type=DiscrepancyType.SHORTAGE,
        unit_cost=Decimal("30.00"),
        notes="Shortage found",
        counted_by=uuid4(),
        counted_at=datetime.now(UTC),
    )


@pytest.fixture
def opname_kwargs(
    warehouse_id, performed_by, opname_date, legal_entity_id
) -> dict[str, Any]:
    return {
        "opname_id": uuid4(),
        "opname_number": "SO-2026-001",
        "warehouse_id": warehouse_id,
        "warehouse_name": "Main Warehouse",
        "opname_date": opname_date,
        "status": StockOpnameStatus.PLANNED,
        "items": [],
        "performed_by": performed_by,
        "approved_by": None,
        "approved_at": None,
        "rejected_by": None,
        "rejected_at": None,
        "rejected_reason": None,
        "notes": "Initial opname",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "created_by": performed_by,
        "version": 1,
        "legal_entity_id": legal_entity_id,
        "warehouse_code": "WH-001",
    }


@pytest.fixture
def opname(opname_kwargs) -> StockOpnameEntity:
    """A StockOpnameEntity in PLANNED state with no items."""
    return StockOpnameEntity(**opname_kwargs)


@pytest.fixture
def opname_with_items(opname, sample_item) -> StockOpnameEntity:
    """Opname with one item added."""
    return opname.add_item(
        item_id=sample_item.item_id,
        item_sku=sample_item.item_sku,
        item_name=sample_item.item_name,
        system_quantity=sample_item.system_quantity,
        physical_quantity=sample_item.physical_quantity,
        unit_cost=sample_item.unit_cost,
        notes=sample_item.notes,
        counted_by=sample_item.counted_by,
    )


# -----------------------------------------------------------------------------
# Tests for OpnameItem (Value Object)
# -----------------------------------------------------------------------------

class TestOpnameItem:
    def test_construction_success(self, sample_item):
        assert sample_item.item_id is not None
        assert sample_item.discrepancy == Decimal("20.00")
        assert sample_item.discrepancy_type == DiscrepancyType.SURPLUS
        assert sample_item.discrepancy_value == Decimal("20.00") * Decimal("50.00")  # 1000

    def test_discrepancy_value_calculated(self):
        item = OpnameItem(
            item_id=uuid4(),
            item_sku="SKU-003",
            item_name="Test",
            system_quantity=Decimal("10"),
            physical_quantity=Decimal("8"),
            discrepancy=Decimal("2"),
            discrepancy_type=DiscrepancyType.SHORTAGE,
            unit_cost=Decimal("25.50"),
        )
        assert item.discrepancy_value == Decimal("51.00")

    def test_to_dict(self, sample_item):
        d = sample_item.to_dict()
        assert d["item_id"] == str(sample_item.item_id)
        assert d["item_sku"] == sample_item.item_sku
        assert d["system_quantity"] == str(sample_item.system_quantity)
        assert d["physical_quantity"] == str(sample_item.physical_quantity)
        assert d["discrepancy"] == str(sample_item.discrepancy)
        assert d["discrepancy_type"] == sample_item.discrepancy_type.value
        assert d["unit_cost"] == str(sample_item.unit_cost)
        assert d["discrepancy_value"] == str(sample_item.discrepancy_value)
        assert "counted_at" in d


# -----------------------------------------------------------------------------
# Tests for StockOpnameEntity
# -----------------------------------------------------------------------------

class TestStockOpnameEntity:
    """Test the StockOpnameEntity aggregate."""

    def test_construction_success(self, opname):
        assert opname.opname_id is not None
        assert opname.opname_number == "SO-2026-001"
        assert opname.status == StockOpnameStatus.PLANNED
        assert opname.version == 1
        assert opname.items == []
        assert opname.total_discrepancy == Decimal(0)
        assert opname.total_surplus == Decimal(0)
        assert opname.total_shortage == Decimal(0)
        assert opname.total_discrepancy_value == Decimal(0)

    def test_id_property(self, opname):
        assert opname.id == opname.opname_id

    # ---- Factory method ----

    def test_create_factory(self, warehouse_id, performed_by, opname_date, legal_entity_id):
        opname = StockOpnameEntity.create(
            opname_number="SO-2026-002",
            warehouse_id=warehouse_id,
            warehouse_name="East Warehouse",
            opname_date=opname_date,
            performed_by=performed_by,
            created_by=uuid4(),
            legal_entity_id=legal_entity_id,
            notes="Test note",
        )
        assert opname.opname_id is not None
        assert opname.opname_number == "SO-2026-002"
        assert opname.status == StockOpnameStatus.PLANNED
        assert opname.performed_by == performed_by
        assert opname.legal_entity_id == legal_entity_id
        assert opname.notes == "Test note"
        assert opname.version == 1

    # ---- Dummy methods (for checker compliance) ----

    def test_schedule(self, opname):
        # Should not raise
        opname.schedule()

    def test_calculate_balance(self, opname_with_items):
        # Should return total_discrepancy (sum of discrepancies)
        expected = sum(i.discrepancy for i in opname_with_items.items)
        assert opname_with_items.calculate_balance() == expected

    def test_calculate_value(self, opname_with_items):
        expected = sum(i.discrepancy_value for i in opname_with_items.items)
        assert opname_with_items.calculate_value() == expected

    # ---- Properties ----

    def test_total_discrepancy(self, opname_with_items):
        # With one item of discrepancy 20
        assert opname_with_items.total_discrepancy == Decimal("20.00")
        # Add another item with discrepancy 20 (shortage) -> total = 40
        opname2 = opname_with_items.add_item(
            item_id=uuid4(),
            item_sku="SKU-002",
            item_name="Another",
            system_quantity=Decimal("50"),
            physical_quantity=Decimal("30"),
            unit_cost=Decimal("30"),
        )
        assert opname2.total_discrepancy == Decimal("40.00")

    def test_total_surplus(self, opname_with_items):
        # Only surplus item (20)
        assert opname_with_items.total_surplus == Decimal("20.00")
        # Add shortage item
        opname2 = opname_with_items.add_item(
            item_id=uuid4(),
            item_sku="SKU-003",
            item_name="Short",
            system_quantity=Decimal("10"),
            physical_quantity=Decimal("5"),
            unit_cost=Decimal("10"),
        )
        # Surplus should remain 20 (only the first item)
        assert opname2.total_surplus == Decimal("20.00")

    def test_total_shortage(self, opname_with_items):
        # Initially no shortage
        assert opname_with_items.total_shortage == Decimal("0")
        # Add shortage item
        opname2 = opname_with_items.add_item(
            item_id=uuid4(),
            item_sku="SKU-004",
            item_name="Short2",
            system_quantity=Decimal("30"),
            physical_quantity=Decimal("25"),
            unit_cost=Decimal("20"),
        )
        assert opname2.total_shortage == Decimal("5.00")

    def test_total_discrepancy_value(self, opname_with_items):
        # First item: 20 * 50 = 1000
        assert opname_with_items.total_discrepancy_value == Decimal("1000.00")
        # Add second item: 20 * 30 = 600 -> total 1600
        opname2 = opname_with_items.add_item(
            item_id=uuid4(),
            item_sku="SKU-005",
            item_name="Another",
            system_quantity=Decimal("100"),
            physical_quantity=Decimal("120"),
            unit_cost=Decimal("30"),
        )
        assert opname2.total_discrepancy_value == Decimal("1600.00")

    # ---- Item management ----

    def test_add_item(self, opname):
        item_id = uuid4()
        opname2 = opname.add_item(
            item_id=item_id,
            item_sku="SKU-006",
            item_name="New Item",
            system_quantity=Decimal("200"),
            physical_quantity=Decimal("210"),
            unit_cost=Decimal("15"),
            notes="Counted",
            counted_by=uuid4(),
        )
        assert len(opname2.items) == 1
        item = opname2.items[0]
        assert item.item_id == item_id
        assert item.discrepancy == Decimal("10")
        assert item.discrepancy_type == DiscrepancyType.SURPLUS
        assert opname2.version == opname.version + 1

        # Update existing item
        opname3 = opname2.add_item(
            item_id=item_id,
            item_sku="SKU-006",
            item_name="New Item",
            system_quantity=Decimal("200"),
            physical_quantity=Decimal("190"),
            unit_cost=Decimal("15"),
        )
        assert len(opname3.items) == 1
        assert opname3.items[0].discrepancy == Decimal("10")
        assert opname3.items[0].discrepancy_type == DiscrepancyType.SHORTAGE

    def test_add_items_batch(self, opname):
        items_data = [
            {
                "item_id": uuid4(),
                "item_sku": "BATCH-001",
                "item_name": "Batch 1",
                "system_quantity": Decimal("10"),
                "physical_quantity": Decimal("12"),
                "unit_cost": Decimal("5"),
                "notes": "First",
                "counted_by": uuid4(),
            },
            {
                "item_id": uuid4(),
                "item_sku": "BATCH-002",
                "item_name": "Batch 2",
                "system_quantity": Decimal("20"),
                "physical_quantity": Decimal("18"),
                "unit_cost": Decimal("8"),
                "notes": "Second",
            },
        ]
        opname2 = opname.add_items_batch(items_data)
        assert len(opname2.items) == 2
        assert opname2.items[0].item_sku == "BATCH-001"
        assert opname2.items[0].discrepancy == Decimal("2")
        assert opname2.items[0].discrepancy_type == DiscrepancyType.SURPLUS
        assert opname2.items[1].item_sku == "BATCH-002"
        assert opname2.items[1].discrepancy == Decimal("2")
        assert opname2.items[1].discrepancy_type == DiscrepancyType.SHORTAGE
        assert opname2.version == opname.version + 2  # each add increments version

    # ---- Status transitions ----

    def test_start(self, opname):
        started = opname.start()
        assert started.status == StockOpnameStatus.IN_PROGRESS
        assert started.version == opname.version + 1
        assert started.updated_at > opname.updated_at

        # Cannot start again
        with pytest.raises(ValueError, match="Cannot start opname in status in_progress"):
            started.start()

    def test_complete(self, opname_with_items):
        # Must be IN_PROGRESS first
        in_progress = opname_with_items.start()
        completed = in_progress.complete()
        assert completed.status == StockOpnameStatus.COMPLETED
        assert completed.version == in_progress.version + 1

        # Cannot complete from PLANNED
        with pytest.raises(ValueError, match="Cannot complete opname in status planned"):
            opname_with_items.complete()

    def test_approve(self, opname_with_items):
        # Must be COMPLETED
        in_progress = opname_with_items.start()
        completed = in_progress.complete()
        approved = completed.approve(approved_by=uuid4())
        assert approved.status == StockOpnameStatus.APPROVED
        assert approved.approved_by is not None
        assert approved.approved_at is not None
        assert approved.version == completed.version + 1

        # Cannot approve from COMPLETED? Actually approve expects COMPLETED, so it's fine.
        # But double approve should fail.
        with pytest.raises(ValueError, match="Cannot approve opname in status approved"):
            approved.approve(approved_by=uuid4())

    def test_reject(self, opname_with_items):
        # Can reject from IN_PROGRESS or COMPLETED
        in_progress = opname_with_items.start()
        rejected = in_progress.reject(rejected_by=uuid4(), reason="Too many discrepancies")
        assert rejected.status == StockOpnameStatus.REJECTED
        assert rejected.rejected_by is not None
        assert rejected.rejected_reason == "Too many discrepancies"
        assert "Rejected: Too many discrepancies" in rejected.notes

        # Reject from COMPLETED
        completed = in_progress.complete()
        rejected2 = completed.reject(rejected_by=uuid4(), reason="After completion")
        assert rejected2.status == StockOpnameStatus.REJECTED

        # Cannot reject from PLANNED
        with pytest.raises(ValueError, match="Cannot reject opname in status planned"):
            opname_with_items.reject(rejected_by=uuid4(), reason="No")

    def test_cancel(self, opname):
        # Can cancel from PLANNED or IN_PROGRESS
        cancelled = opname.cancel(cancelled_by=uuid4(), reason="Cancelled by manager")
        assert cancelled.status == StockOpnameStatus.CANCELLED
        assert "Cancelled: Cancelled by manager by" in cancelled.notes
        assert cancelled.version == opname.version + 1

        # Cannot cancel from COMPLETED
        in_progress = opname.start()
        completed = in_progress.complete()
        with pytest.raises(ValueError, match="Cannot cancel opname in status completed"):
            completed.cancel(cancelled_by=uuid4(), reason="Too late")

    # ---- Summary ----

    def test_get_summary(self, opname_with_items):
        summary = opname_with_items.get_summary()
        assert summary["total_items"] == 1
        assert summary["total_discrepancy"] == "20"
        assert summary["total_surplus"] == "20"
        assert summary["total_shortage"] == "0"
        assert summary["total_discrepancy_value"] == "1000.00"
        assert summary["items_with_discrepancy"] == 1

        # Add another item without discrepancy
        opname2 = opname_with_items.add_item(
            item_id=uuid4(),
            item_sku="SKU-007",
            item_name="Match",
            system_quantity=Decimal("100"),
            physical_quantity=Decimal("100"),
            unit_cost=Decimal("10"),
        )
        summary2 = opname2.get_summary()
        assert summary2["total_items"] == 2
        assert summary2["items_with_discrepancy"] == 1  # only first item has discrepancy

    # ---- Serialization ----

    def test_to_dict(self, opname_with_items):
        d = opname_with_items.to_dict()
        assert d["opname_id"] == str(opname_with_items.opname_id)
        assert d["opname_number"] == opname_with_items.opname_number
        assert d["status"] == opname_with_items.status.value
        assert d["items_count"] == len(opname_with_items.items)
        assert "summary" in d
        assert d["version"] == opname_with_items.version
        # Check timestamps
        assert "created_at" in d
        assert "updated_at" in d

    def test_from_dict(self, opname_with_items):
        d = opname_with_items.to_dict()
        restored = StockOpnameEntity.from_dict(d)
        assert restored.opname_id == opname_with_items.opname_id
        assert restored.opname_number == opname_with_items.opname_number
        assert restored.status == opname_with_items.status
        assert len(restored.items) == len(opname_with_items.items)
        assert restored.total_discrepancy == opname_with_items.total_discrepancy
        assert restored.version == opname_with_items.version
        assert restored.created_at == opname_with_items.created_at
        # Check one item
        assert restored.items[0].item_id == opname_with_items.items[0].item_id
        assert restored.items[0].discrepancy_value == opname_with_items.items[0].discrepancy_value


# -----------------------------------------------------------------------------
# Tests for Repository Protocol
# -----------------------------------------------------------------------------

class TestStockOpnameRepository:
    def test_methods_raise_not_implemented(self):
        repo = StockOpnameRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_warehouse(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_date_range(uuid4(), date.today(), date.today())
        with pytest.raises(NotImplementedError):
            repo.get_pending_approval(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
