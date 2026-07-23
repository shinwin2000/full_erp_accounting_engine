# test_bill_of_materials_entity.py
"""
Comprehensive tests for domain/manufacturing/bill_of_materials_entity.py
Covers all enums, value objects, entity, and repository stub.
Uses fixed datetime fixtures and parameterization to avoid duplication.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from domain.manufacturing.bill_of_materials_entity import (
    BillOfMaterialsEntity,
    BillOfMaterialsRepository,
    BOMItem,
    BOMStatus,
    BOMType,
)
from domain.manufacturing.cost_element_enum import CostElement


# ============================================================================
# FIXED DATETIME FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    return datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_past():
    return datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def fixed_future():
    return datetime(2026, 7, 1, 10, 0, 0, tzinfo=UTC)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_bom_item(
    item_id: uuid.UUID | None = None,
    item_code: str = "COMP-001",
    item_name: str = "Component 1",
    quantity: Decimal = Decimal("2.5"),
    unit_of_measure: str = "kg",
    unit_cost: Decimal = Decimal("10000"),
    scrap_percentage: Decimal = Decimal("5"),
    cost_element: CostElement = CostElement.MATERIAL,
    sub_bom_id: uuid.UUID | None = None,
    notes: str = "",
) -> BOMItem:
    if item_id is None:
        item_id = uuid.uuid4()
    return BOMItem(
        item_id=item_id,
        item_code=item_code,
        item_name=item_name,
        quantity=quantity,
        unit_of_measure=unit_of_measure,
        unit_cost=unit_cost,
        scrap_percentage=scrap_percentage,
        cost_element=cost_element,
        sub_bom_id=sub_bom_id,
        notes=notes,
    )


def create_bom(
    bom_id: uuid.UUID | None = None,
    bom_code: str = "BOM-001",
    product_id: uuid.UUID | None = None,
    product_code: str = "PROD-001",
    product_name: str = "Finished Product",
    version: int = 1,
    quantity_per_assembly: Decimal = Decimal("1"),
    unit_of_measure: str = "pcs",
    items: list[BOMItem] | None = None,
    status: BOMStatus = BOMStatus.DRAFT,
    routing_id: uuid.UUID | None = None,
    effective_date: datetime | None = None,
    expiry_date: datetime | None = None,
    notes: str = "",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    created_by: str = "system",
    version_counter: int = 1,
) -> BillOfMaterialsEntity:
    if bom_id is None:
        bom_id = uuid.uuid4()
    if product_id is None:
        product_id = uuid.uuid4()
    if items is None:
        items = []
    if created_at is None:
        created_at = datetime.now(UTC)
    if updated_at is None:
        updated_at = datetime.now(UTC)
    return BillOfMaterialsEntity(
        bom_id=bom_id,
        bom_code=bom_code,
        product_id=product_id,
        product_code=product_code,
        product_name=product_name,
        version=version,
        quantity_per_assembly=quantity_per_assembly,
        unit_of_measure=unit_of_measure,
        items=items,
        status=status,
        routing_id=routing_id,
        effective_date=effective_date,
        expiry_date=expiry_date,
        notes=notes,
        created_at=created_at,
        updated_at=updated_at,
        created_by=created_by,
        version_counter=version_counter,
    )


# ============================================================================
# ENUM TESTS
# ============================================================================

class TestBOMType:
    def test_members(self):
        assert BOMType.SINGLE_LEVEL.value == "single_level"
        assert BOMType.MULTI_LEVEL.value == "multi_level"
        assert BOMType.PLANNING.value == "planning"

    def test_from_string(self):
        assert BOMType.from_string("single_level") == BOMType.SINGLE_LEVEL
        assert BOMType.from_string("MULTI_LEVEL") == BOMType.MULTI_LEVEL
        assert BOMType.from_string("planning") == BOMType.PLANNING
        assert BOMType.from_string("unknown") == BOMType.SINGLE_LEVEL

    def test_from_string_case_insensitive(self):
        assert BOMType.from_string("Single_Level") == BOMType.SINGLE_LEVEL


class TestBOMStatus:
    def test_members(self):
        assert BOMStatus.DRAFT.value == "draft"
        assert BOMStatus.ACTIVE.value == "active"
        assert BOMStatus.OBSOLETE.value == "obsolete"

    def test_from_string(self):
        assert BOMStatus.from_string("draft") == BOMStatus.DRAFT
        assert BOMStatus.from_string("ACTIVE") == BOMStatus.ACTIVE
        assert BOMStatus.from_string("obsolete") == BOMStatus.OBSOLETE
        assert BOMStatus.from_string("unknown") == BOMStatus.DRAFT


# ============================================================================
# BOMItem TESTS
# ============================================================================

class TestBOMItem:
    def test_construction_valid(self):
        item = create_bom_item()
        assert item.item_id is not None
        assert item.item_code == "COMP-001"
        assert item.quantity == Decimal("2.5")
        assert item.unit_cost == Decimal("10000")
        assert item.scrap_percentage == Decimal("5")

    def test_validation_quantity_negative(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            create_bom_item(quantity=Decimal("-1"))

    def test_validation_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            create_bom_item(quantity=Decimal("0"))

    def test_validation_unit_cost_negative(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            create_bom_item(unit_cost=Decimal("-10"))

    def test_validation_scrap_percentage_too_high(self):
        with pytest.raises(ValueError, match="Scrap percentage must be between 0 and 100"):
            create_bom_item(scrap_percentage=Decimal("101"))

    def test_validation_scrap_percentage_negative(self):
        with pytest.raises(ValueError, match="Scrap percentage must be between 0 and 100"):
            create_bom_item(scrap_percentage=Decimal("-5"))

    def test_validation_item_code_too_short(self):
        with pytest.raises(ValueError, match="Item code must be at least 2 characters"):
            create_bom_item(item_code="A")

    def test_validation_item_name_too_short(self):
        with pytest.raises(ValueError, match="Item name must be at least 2 characters"):
            create_bom_item(item_name="X")

    def test_validation_unit_of_measure_empty(self):
        with pytest.raises(ValueError, match="Unit of measure cannot be empty"):
            create_bom_item(unit_of_measure="")

    def test_total_cost(self):
        item = create_bom_item(quantity=Decimal("2"), unit_cost=Decimal("100"), scrap_percentage=Decimal("10"))
        # effective_quantity = 2 * (1 + 10/100) = 2.2
        # total_cost = 2.2 * 100 = 220
        assert item.total_cost == Decimal("220")

    def test_effective_quantity(self):
        item = create_bom_item(quantity=Decimal("3"), scrap_percentage=Decimal("20"))
        assert item.effective_quantity == Decimal("3.6")  # 3 * 1.2

    def test_clone(self):
        item = create_bom_item()
        cloned = item.clone()
        assert cloned is not item
        assert cloned.item_id != item.item_id
        assert cloned.item_code == item.item_code
        assert cloned.quantity == item.quantity
        assert cloned.unit_cost == item.unit_cost

    def test_normalize(self):
        item = create_bom_item(
            item_code="  comp-001  ",
            item_name="  component 1  ",
            quantity=Decimal("2.1234"),
            unit_of_measure="  KG  ",
            unit_cost=Decimal("100.123"),
            scrap_percentage=Decimal("5.678"),
            notes="  some notes  ",
        )
        normalized = item.normalize()
        assert normalized.item_code == "COMP-001"
        assert normalized.item_name == "Component 1"
        assert normalized.quantity == Decimal("2.123")
        assert normalized.unit_of_measure == "kg"
        assert normalized.unit_cost == Decimal("100.12")
        assert normalized.scrap_percentage == Decimal("5.68")
        assert normalized.notes == "some notes"

    def test_to_dict(self):
        item = create_bom_item()
        d = item.to_dict()
        assert d["item_id"] == str(item.item_id)
        assert d["item_code"] == item.item_code
        assert d["quantity"] == str(item.quantity)
        assert d["unit_cost"] == str(item.unit_cost)
        assert d["scrap_percentage"] == str(item.scrap_percentage)
        assert d["total_cost"] == str(item.total_cost)
        assert d["effective_quantity"] == str(item.effective_quantity)

    def test_from_dict(self):
        data = {
            "item_id": str(uuid.uuid4()),
            "item_code": "COMP-002",
            "item_name": "Component 2",
            "quantity": "1.5",
            "unit_of_measure": "liter",
            "unit_cost": "20000",
            "scrap_percentage": "3",
            "cost_element": "labor",
            "sub_bom_id": str(uuid.uuid4()),
            "notes": "test note",
        }
        item = BOMItem.from_dict(data)
        assert item.item_code == "COMP-002"
        assert item.quantity == Decimal("1.5")
        assert item.unit_cost == Decimal("20000")
        assert item.scrap_percentage == Decimal("3")
        assert item.cost_element == CostElement.LABOR
        assert item.notes == "test note"

    def test_from_dict_defaults(self):
        data = {
            "item_code": "COMP",
            "item_name": "Comp",
            "quantity": "1",
            "unit_of_measure": "pcs",
            "unit_cost": "100",
        }
        item = BOMItem.from_dict(data)
        assert item.item_id is not None
        assert item.scrap_percentage == Decimal("0")
        assert item.cost_element == CostElement.MATERIAL
        assert item.sub_bom_id is None
        assert item.notes == ""

    def test_equality(self):
        id1 = uuid.uuid4()
        id2 = uuid.uuid4()
        item1 = create_bom_item(item_id=id1)
        item2 = create_bom_item(item_id=id1)
        item3 = create_bom_item(item_id=id2)
        assert item1 == item2
        assert item1 != item3
        assert item1 != "not an item"

    def test_hash(self):
        id1 = uuid.uuid4()
        item1 = create_bom_item(item_id=id1)
        item2 = create_bom_item(item_id=id1)
        assert hash(item1) == hash(item2)


# ============================================================================
# FIXTURES FOR BILL OF MATERIALS
# ============================================================================

@pytest.fixture
def sample_items():
    return [
        create_bom_item(item_code="MAT-001", quantity=Decimal("2"), unit_cost=Decimal("1000"), cost_element=CostElement.MATERIAL),
        create_bom_item(item_code="LAB-001", quantity=Decimal("1.5"), unit_cost=Decimal("5000"), cost_element=CostElement.LABOR),
        create_bom_item(item_code="OH-001", quantity=Decimal("0.5"), unit_cost=Decimal("8000"), cost_element=CostElement.OVERHEAD),
    ]


@pytest.fixture
def sample_bom(sample_items, fixed_now):
    return create_bom(
        bom_code="BOM-FINAL",
        product_name="Final Product",
        quantity_per_assembly=Decimal("1"),
        items=sample_items,
        status=BOMStatus.ACTIVE,
        effective_date=fixed_now,
        expiry_date=fixed_now + timedelta(days=365),
        created_at=fixed_now,
        updated_at=fixed_now,
        version_counter=1,
    )


@pytest.fixture
def draft_bom(sample_items, fixed_now):
    return create_bom(
        bom_code="BOM-DRAFT",
        product_name="Draft Product",
        items=sample_items,
        status=BOMStatus.DRAFT,
        created_at=fixed_now,
        updated_at=fixed_now,
        version_counter=1,
    )


# ============================================================================
# BILL OF MATERIALS ENTITY TESTS
# ============================================================================

class TestBillOfMaterialsEntity:
    # --- Construction & Validation ---
    def test_construction_valid(self, sample_bom):
        assert sample_bom.bom_id is not None
        assert sample_bom.bom_code == "BOM-FINAL"
        assert sample_bom.version == 1
        assert sample_bom.status == BOMStatus.ACTIVE
        assert sample_bom.version_counter == 1
        assert sample_bom.created_at is not None

    def test_validation_bom_code_too_short(self):
        with pytest.raises(ValueError, match="BOM code must be at least 3 characters"):
            create_bom(bom_code="AB")

    def test_validation_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            create_bom(version=0)

    def test_validation_quantity_per_assembly_zero(self):
        with pytest.raises(ValueError, match="Quantity per assembly must be positive"):
            create_bom(quantity_per_assembly=Decimal("0"))

    def test_validation_quantity_per_assembly_negative(self):
        with pytest.raises(ValueError, match="Quantity per assembly must be positive"):
            create_bom(quantity_per_assembly=Decimal("-1"))

    def test_validation_version_counter_zero(self):
        with pytest.raises(ValueError, match="Version counter must be >= 1"):
            create_bom(version_counter=0)

    def test_validation_created_at_naive_raises(self, fixed_now):
        naive = datetime(2026, 6, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="created_at must be timezone-aware"):
            create_bom(created_at=naive)

    def test_validation_updated_at_naive_raises(self, fixed_now):
        naive = datetime(2026, 6, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="updated_at must be timezone-aware"):
            create_bom(updated_at=naive)

    def test_validation_effective_date_naive_raises(self, fixed_now):
        naive = datetime(2026, 6, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="effective_date must be timezone-aware"):
            create_bom(effective_date=naive)

    def test_validation_expiry_date_naive_raises(self, fixed_now):
        naive = datetime(2026, 6, 15, 10, 0, 0)
        with pytest.raises(ValueError, match="expiry_date must be timezone-aware"):
            create_bom(expiry_date=naive)

    # --- Audit Trail ---
    def test_record_audit(self, sample_bom):
        sample_bom._record_audit("test_action", "user1", {"key": "value"})
        trail = sample_bom.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test_action"
        assert trail[0]["user_id"] == "user1"
        assert trail[0]["details"] == {"key": "value"}

    # --- Cost Calculations ---
    def test_get_total_material_cost(self, sample_bom):
        # Items: MAT-001: 2 * 1000 = 2000, LAB: 1.5*5000=7500, OH: 0.5*8000=4000
        # Material only: 2000
        assert sample_bom.get_total_material_cost() == Decimal("2000")

    def test_get_total_labor_cost(self, sample_bom):
        assert sample_bom.get_total_labor_cost() == Decimal("7500")

    def test_get_total_overhead_cost(self, sample_bom):
        assert sample_bom.get_total_overhead_cost() == Decimal("4000")

    def test_get_total_cost(self, sample_bom):
        assert sample_bom.get_total_cost() == Decimal("13500")

    def test_get_cost_by_element(self, sample_bom):
        assert sample_bom.get_cost_by_element(CostElement.MATERIAL) == Decimal("2000")
        assert sample_bom.get_cost_by_element(CostElement.LABOR) == Decimal("7500")
        assert sample_bom.get_cost_by_element(CostElement.OVERHEAD) == Decimal("4000")

    def test_get_item_count(self, sample_bom):
        assert sample_bom.get_item_count() == 3

    def test_get_effective_quantity(self, sample_bom):
        # MAT-001: 2 * 1.05 = 2.1 (scrap 5% default), LAB: 1.5 * 1.05 = 1.575, OH: 0.5 * 1.05 = 0.525
        # total = 4.2
        # But our sample items have scrap 5% by default, so effective_quantity = quantity * 1.05
        total = sum(item.effective_quantity for item in sample_bom.items)
        assert sample_bom.get_effective_quantity() == total

    # --- Item Management ---
    def test_add_item(self, sample_bom, fixed_now):
        new_item = create_bom_item(item_code="NEW-001")
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            new_bom = sample_bom.add_item(new_item, "user1")
        assert len(new_bom.items) == len(sample_bom.items) + 1
        assert new_bom.items[-1] is new_item
        assert new_bom.version_counter == sample_bom.version_counter + 1
        assert new_bom.updated_at == fixed_now
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "item_added"
        assert trail[-1]["user_id"] == "user1"

    def test_add_item_duplicate_raises(self, sample_bom):
        existing = sample_bom.items[0]
        with pytest.raises(ValueError, match="already exists"):
            sample_bom.add_item(existing, "user1")

    def test_add_items_batch(self, sample_bom, fixed_now):
        items = [create_bom_item(item_code=f"BATCH-{i}") for i in range(3)]
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_bom = sample_bom.add_items_batch(items, "user1")
        assert len(new_bom.items) == len(sample_bom.items) + 3
        assert new_bom.version_counter == sample_bom.version_counter + 3  # each add increments

    def test_remove_item(self, sample_bom, fixed_now):
        item_to_remove = sample_bom.items[0]
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_bom = sample_bom.remove_item(item_to_remove.item_id, "user1")
        assert len(new_bom.items) == len(sample_bom.items) - 1
        assert item_to_remove not in new_bom.items
        assert new_bom.version_counter == sample_bom.version_counter + 1
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "item_removed"

    def test_remove_item_not_found_raises(self, sample_bom):
        with pytest.raises(ValueError, match="not found"):
            sample_bom.remove_item(uuid.uuid4(), "user1")

    def test_update_item_quantity(self, sample_bom, fixed_now):
        item_id = sample_bom.items[0].item_id
        old_qty = sample_bom.items[0].quantity
        new_qty = Decimal("5")
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_bom = sample_bom.update_item_quantity(item_id, new_qty, "user1")
        updated_item = new_bom.get_item_by_id(item_id)
        assert updated_item.quantity == new_qty
        assert new_bom.version_counter == sample_bom.version_counter + 1
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "item_quantity_updated"
        assert trail[-1]["details"]["old_quantity"] == str(old_qty)

    def test_update_item_quantity_zero_raises(self, sample_bom):
        item_id = sample_bom.items[0].item_id
        with pytest.raises(ValueError, match="positive"):
            sample_bom.update_item_quantity(item_id, Decimal("0"), "user1")

    def test_update_item_quantity_not_found_raises(self, sample_bom):
        with pytest.raises(ValueError, match="not found"):
            sample_bom.update_item_quantity(uuid.uuid4(), Decimal("1"), "user1")

    def test_update_item_unit_cost(self, sample_bom, fixed_now):
        item_id = sample_bom.items[0].item_id
        old_cost = sample_bom.items[0].unit_cost
        new_cost = Decimal("999")
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_bom = sample_bom.update_item_unit_cost(item_id, new_cost, "user1")
        updated_item = new_bom.get_item_by_id(item_id)
        assert updated_item.unit_cost == new_cost
        assert new_bom.version_counter == sample_bom.version_counter + 1
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "item_cost_updated"

    def test_update_item_unit_cost_negative_raises(self, sample_bom):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_bom.update_item_unit_cost(sample_bom.items[0].item_id, Decimal("-10"), "user1")

    def test_update_item_scrap(self, sample_bom, fixed_now):
        item_id = sample_bom.items[0].item_id
        old_scrap = sample_bom.items[0].scrap_percentage
        new_scrap = Decimal("15")
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_bom = sample_bom.update_item_scrap(item_id, new_scrap, "user1")
        updated_item = new_bom.get_item_by_id(item_id)
        assert updated_item.scrap_percentage == new_scrap
        assert new_bom.version_counter == sample_bom.version_counter + 1
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "item_scrap_updated"

    def test_update_item_scrap_out_of_range(self, sample_bom):
        with pytest.raises(ValueError, match="between 0 and 100"):
            sample_bom.update_item_scrap(sample_bom.items[0].item_id, Decimal("101"), "user1")

    # --- Status Transitions ---
    def test_activate(self, draft_bom, fixed_now):
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            activated = draft_bom.activate("user1")
        assert activated.status == BOMStatus.ACTIVE
        assert activated.effective_date == fixed_now
        assert activated.version_counter == draft_bom.version_counter + 1
        trail = activated.get_audit_trail()
        assert trail[-1]["action"] == "activated"

    def test_activate_already_active(self, sample_bom):
        with pytest.raises(ValueError, match="Cannot activate BOM in status active"):
            sample_bom.activate("user1")

    def test_activate_empty_items(self, fixed_now):
        bom = create_bom(status=BOMStatus.DRAFT, items=[], effective_date=fixed_now)
        with pytest.raises(ValueError, match="Cannot activate BOM with no items"):
            bom.activate("user1")

    def test_deactivate(self, sample_bom, fixed_now):
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            deactivated = sample_bom.deactivate("user1", "test reason")
        assert deactivated.status == BOMStatus.DRAFT
        assert deactivated.effective_date is None
        assert deactivated.expiry_date is None
        assert "Deactivated: test reason" in deactivated.notes
        assert deactivated.version_counter == sample_bom.version_counter + 1
        trail = deactivated.get_audit_trail()
        assert trail[-1]["action"] == "deactivated"

    def test_deactivate_already_draft(self, draft_bom):
        with pytest.raises(ValueError, match="Cannot deactivate BOM in status draft"):
            draft_bom.deactivate("user1")

    def test_obsoleted(self, sample_bom, fixed_now):
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mock_dt.UTC = UTC
            obs = sample_bom.obsoleted("user1", "replaced by new version")
        assert obs.status == BOMStatus.OBSOLETE
        assert obs.expiry_date == fixed_now
        assert "Obsoleted: replaced by new version" in obs.notes
        assert obs.version_counter == sample_bom.version_counter + 1
        trail = obs.get_audit_trail()
        assert trail[-1]["action"] == "obsoleted"

    def test_increment_version(self, sample_bom, fixed_now):
        with patch("domain.manufacturing.bill_of_materials_entity.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            new_version = sample_bom.version + 2
            new_bom = sample_bom.increment_version(new_version, "user1")
        assert new_bom.version == new_version
        assert new_bom.status == BOMStatus.DRAFT
        assert new_bom.effective_date is None
        assert new_bom.expiry_date is None
        assert new_bom.version_counter == sample_bom.version_counter + 1
        assert f"Version {new_version} created from v{sample_bom.version}" in new_bom.notes
        trail = new_bom.get_audit_trail()
        assert trail[-1]["action"] == "version_incremented"

    def test_increment_version_not_greater(self, sample_bom):
        with pytest.raises(ValueError, match="must be greater"):
            sample_bom.increment_version(sample_bom.version, "user1")

    # --- Validation ---
    def test_validate_valid(self, sample_bom):
        errors = sample_bom.validate()
        assert errors == []

    def test_validate_no_items(self):
        bom = create_bom(items=[])
        errors = bom.validate()
        assert "BOM must have at least one component" in errors

    def test_validate_negative_quantity(self):
        item = create_bom_item(quantity=Decimal("-1"))
        bom = create_bom(items=[item])
        errors = bom.validate()
        assert any("non-positive quantity" in e for e in errors)

    def test_validate_duplicate_item_codes(self):
        item1 = create_bom_item(item_code="DUPLICATE")
        item2 = create_bom_item(item_code="DUPLICATE")
        bom = create_bom(items=[item1, item2])
        errors = bom.validate()
        assert any("Duplicate item codes" in e for e in errors)

    # --- Snapshot ---
    def test_snapshot(self, sample_bom):
        snap = sample_bom.snapshot()
        assert snap["bom_id"] == str(sample_bom.bom_id)
        assert snap["bom_code"] == sample_bom.bom_code
        assert snap["version"] == sample_bom.version
        assert snap["status"] == "active"
        assert "total_cost" in snap
        assert "timestamp" in snap

    # --- Clone ---
    def test_clone(self, sample_bom):
        cloned = sample_bom.clone()
        assert cloned.bom_id != sample_bom.bom_id
        assert cloned.bom_code == "COPY-BOM-FINAL"
        assert cloned.version == 1
        assert cloned.status == BOMStatus.DRAFT
        assert cloned.effective_date is None
        assert cloned.expiry_date is None
        assert len(cloned.items) == len(sample_bom.items)
        # Items are cloned, not same objects
        assert cloned.items[0].item_id != sample_bom.items[0].item_id
        assert cloned.items[0].item_code == sample_bom.items[0].item_code
        trail = cloned.get_audit_trail()
        assert trail[0]["action"] == "cloned"

    # --- Query Methods ---
    def test_is_active_at_active_within_range(self, sample_bom, fixed_now):
        assert sample_bom.is_active_at(fixed_now) is True
        assert sample_bom.is_active_at(fixed_now + timedelta(days=30)) is True

    def test_is_active_at_outside_effective(self, sample_bom, fixed_past, fixed_future):
        # Before effective
        before = fixed_past - timedelta(days=1)
        assert sample_bom.is_active_at(before) is False
        # After expiry
        after = fixed_future + timedelta(days=1)
        assert sample_bom.is_active_at(after) is False

    def test_is_active_at_non_active_status(self, draft_bom, fixed_now):
        assert draft_bom.is_active_at(fixed_now) is False

    def test_get_item_by_id(self, sample_bom):
        target = sample_bom.items[0]
        assert sample_bom.get_item_by_id(target.item_id) is target
        assert sample_bom.get_item_by_id(uuid.uuid4()) is None

    def test_get_item_by_code(self, sample_bom):
        target = sample_bom.items[0]
        assert sample_bom.get_item_by_code(target.item_code) is target
        assert sample_bom.get_item_by_code("NONEXISTENT") is None

    def test_get_summary(self, sample_bom):
        summary = sample_bom.get_summary()
        assert summary["bom_code"] == "BOM-FINAL"
        assert summary["product_name"] == "Final Product"
        assert summary["version"] == 1
        assert summary["status"] == "active"
        assert summary["total_cost"] == "13500"
        assert summary["item_count"] == 3

    # --- Serialization ---
    def test_to_dict(self, sample_bom):
        d = sample_bom.to_dict()
        assert d["bom_id"] == str(sample_bom.bom_id)
        assert d["bom_code"] == sample_bom.bom_code
        assert d["version"] == sample_bom.version
        assert d["total_cost"] == "13500"
        assert len(d["items"]) == 3
        assert "summary" in d

    def test_from_dict(self, sample_bom):
        d = sample_bom.to_dict()
        reconstructed = BillOfMaterialsEntity.from_dict(d)
        assert reconstructed.bom_id == sample_bom.bom_id
        assert reconstructed.bom_code == sample_bom.bom_code
        assert reconstructed.version == sample_bom.version
        assert reconstructed.status == sample_bom.status
        assert len(reconstructed.items) == len(sample_bom.items)
        assert reconstructed.items[0].item_id == sample_bom.items[0].item_id
        assert reconstructed.items[0].quantity == sample_bom.items[0].quantity

    def test_from_dict_without_optional_fields(self):
        data = {
            "bom_id": str(uuid.uuid4()),
            "bom_code": "BOM-002",
            "product_id": str(uuid.uuid4()),
            "product_code": "P002",
            "product_name": "Product 2",
            "version": 1,
            "quantity_per_assembly": "1",
            "unit_of_measure": "pcs",
            "items": [],
            "status": "active",
            "created_at": datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC).isoformat(),
            "updated_at": datetime(2026, 6, 15, 10, 0, 0, tzinfo=UTC).isoformat(),
        }
        bom = BillOfMaterialsEntity.from_dict(data)
        assert bom.routing_id is None
        assert bom.effective_date is None
        assert bom.expiry_date is None
        assert bom.notes == ""
        assert bom.created_by == "system"
        assert bom.version_counter == 1


# ============================================================================
# REPOSITORY TESTS
# ============================================================================

class TestBillOfMaterialsRepository:
    @pytest.mark.asyncio
    async def test_methods_raise_not_implemented(self):
        repo = BillOfMaterialsRepository()
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_by_code("code", uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_by_product(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.get_active_bom(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.list_by_product(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.save(MagicMock(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid.uuid4(), uuid.uuid4())
        with pytest.raises(NotImplementedError):
            await repo.exists("code", uuid.uuid4())