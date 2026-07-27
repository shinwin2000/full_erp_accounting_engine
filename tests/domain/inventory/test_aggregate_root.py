#!/usr/bin/env python3
"""
tests/domain/inventory/test_aggregate_root.py
Comprehensive tests for domain/inventory/aggregate_root.py

Covers:
- InventoryAggregate initialization and properties
- Item management: rename, update_description, set_reorder_point, set_safety_stock,
  set_standard_cost, set_selling_price, set_category, update_standard_cost, deactivate_item
- Stock movements: receive_stock, issue_stock, adjust_stock (including validation)
- Lock/Unlock, Activate/Deactivate
- Event methods: add_event, clear_events, get_events, pop_events, pull_events, register_event, apply
- Audit trail: _record_audit_trail, _record_audit, audit_trail
- Snapshot and restore, _compute_hash
- Reconcile (dummy)
- Validate
- Version, increment_version, touch
- Clone
- Factory methods: create, reconstruct, from_events, replay, replay_events
- to_dict, from_dict
- FIFO layers logic and validation
- All edge cases and negative paths
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from domain.inventory.aggregate_root import (
    InventoryAggregate,
    InventoryItemAggregate,
    StockMovementType,
)
from domain.inventory.domain_events import (
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockAdjusted,
    StockMovementCreated,
)
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure
from domain.inventory.movement_entity import MovementType, StockMovement
from domain.inventory.stock_adjustment_entity import AdjustmentReason, AdjustmentStatus, AdjustmentType
from domain.inventory.valuation_method import FIFOValuation

# =============================================================================
# Fixtures
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return fixed datetime."""
    with patch("domain.inventory.aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.utcnow.return_value = FIXED_DATETIME
        # We don't need side_effect that interferes
        yield mock_dt


@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def sample_item(legal_entity_id):
    return Item(
        id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        sku="SKU-001",
        name="Test Item",
        description="Test Description",
        item_type=ItemType.FINISHED_GOODS,
        unit_of_measure=UnitOfMeasure.PCS,
        current_stock=Decimal("100"),
        current_stock_value=Decimal("5000"),
        average_cost=Decimal("50"),
        last_cost=Decimal("50"),
        reorder_point=Decimal("20"),
        safety_stock=Decimal("10"),
        maximum_stock=Decimal("200"),
        minimum_stock=Decimal("5"),
        status=ItemStatus.ACTIVE,
        standard_cost=Decimal("50"),
        selling_price=Decimal("100"),
        category="Electronics",
        warehouse_code="WH-01",
        created_by=uuid.uuid4(),
        created_at=FIXED_DATETIME,
        updated_at=None,
        updated_by=None,
        deactivated_at=None,
        deactivated_by=None,
        version=1,
    )


@pytest.fixture
def sample_aggregate(sample_item, legal_entity_id, user_id):
    return InventoryAggregate.create(sample_item, user_id)


@pytest.fixture
def stock_movement(legal_entity_id, user_id):
    return StockMovement(
        id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        item_id=uuid.uuid4(),
        sku="SKU-001",
        movement_type=MovementType.PURCHASE,
        quantity=Decimal("50"),
        unit_cost=Decimal("60"),
        total_value=Decimal("3000"),
        warehouse_id=uuid.uuid4(),
        warehouse_name="WH-01",
        transaction_date=FIXED_DATETIME,
        reference_document="PO-001",
        reference_document_type="purchase_order",
        created_by=user_id,
        created_at=FIXED_DATETIME,
        approved_at=None,
        approved_by=None,
        status="draft",
        notes=None,
        cost_center=None,
        department=None,
        project_id=None,
        source_location=None,
        destination_location=None,
        from_warehouse_id=None,
        to_warehouse_id=None,
        batch_number=None,
        serial_numbers=None,
    )


# =============================================================================
# Test Class: TestInventoryAggregate
# =============================================================================

class TestInventoryAggregate:
    def test_init(self, legal_entity_id):
        agg = InventoryAggregate(id=None, legal_entity_id=legal_entity_id, version=0)
        assert agg.id is not None
        assert agg.legal_entity_id == legal_entity_id
        assert agg.version == 0
        assert agg._item is None
        assert agg._is_active is True
        assert agg._is_locked is False
        assert agg._warehouse_id is None

    def test_create_factory(self, sample_item, user_id):
        agg = InventoryAggregate.create(sample_item, user_id)
        assert agg.id == sample_item.id
        assert agg.legal_entity_id == sample_item.legal_entity_id
        assert agg.version == 1
        assert agg._item is not None
        assert agg._item.sku == sample_item.sku
        assert agg._is_active is True
        # FIFO layers should be created if initial stock > 0
        assert len(agg._fifo_layers) == 1
        assert agg._fifo_layers[0]["quantity"] == sample_item.current_stock
        # Domain events
        events = agg.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ItemCreated)
        # Audit trail
        trail = agg.audit_trail()
        assert any(e["action"] == "created" for e in trail)

    def test_create_invalid_negative_stock(self, sample_item, user_id):
        sample_item.current_stock = Decimal("-10")
        with pytest.raises(ValueError, match="Initial stock cannot be negative"):
            InventoryAggregate.create(sample_item, user_id)

    def test_create_invalid_negative_cost(self, sample_item, user_id):
        sample_item.standard_cost = Decimal("-1")
        with pytest.raises(ValueError, match="Standard cost cannot be negative"):
            InventoryAggregate.create(sample_item, user_id)

    def test_properties(self, sample_aggregate, sample_item):
        agg = sample_aggregate
        assert agg.item == sample_item
        assert agg.current_stock == sample_item.current_stock
        assert agg.current_stock_value == sample_item.current_stock_value
        assert agg.average_cost == sample_item.average_cost
        assert agg.reorder_point == sample_item.reorder_point
        assert agg.safety_stock == sample_item.safety_stock
        assert agg.warehouse_id is None
        assert agg.is_locked is False
        assert agg.is_active is True

    def test_property_item_not_set(self):
        agg = InventoryAggregate(id=uuid.uuid4(), legal_entity_id=uuid.uuid4(), version=0)
        with pytest.raises(ValueError, match="Item not set"):
            _ = agg.item

    # ---- Lock / Unlock ----
    def test_lock_unlock(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "audit")
        assert agg.is_locked is True
        assert agg._locked_by == user_id
        assert agg._locked_at == FIXED_DATETIME
        trail = agg.audit_trail()
        assert any(e["action"] == "locked" for e in trail)

        # Unlock
        agg.unlock(user_id)
        assert agg.is_locked is False
        assert agg._locked_by is None
        assert agg._locked_at is None
        trail = agg.audit_trail()
        assert any(e["action"] == "unlocked" for e in trail)

    def test_lock_already_locked(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "audit")
        with pytest.raises(ValueError, match="already locked"):
            agg.lock(user_id, "again")

    def test_unlock_not_locked(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="not locked"):
            sample_aggregate.unlock(user_id)

    def test_unlock_wrong_user(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "audit")
        other = uuid.uuid4()
        with pytest.raises(ValueError, match="cannot unlock"):
            agg.unlock(other)

    # ---- Activate / Deactivate ----
    def test_activate_deactivate(self, sample_aggregate, user_id):
        agg = sample_aggregate
        # Deactivate
        agg.deactivate(user_id, "no need")
        assert agg.is_active is False
        assert agg._deactivated_at == FIXED_DATETIME
        assert agg._deactivated_by == user_id
        trail = agg.audit_trail()
        assert any(e["action"] == "deactivated" for e in trail)

        # Reactivate
        agg.activate(user_id)
        assert agg.is_active is True
        assert agg._deactivated_at is None
        assert agg._deactivated_by is None
        trail = agg.audit_trail()
        assert any(e["action"] == "activated" for e in trail)

    def test_deactivate_with_stock(self, sample_aggregate, user_id):
        agg = sample_aggregate
        # Give stock
        agg._item.current_stock = Decimal("10")
        with pytest.raises(ValueError, match="Cannot deactivate item with current stock"):
            agg.deactivate(user_id, "reason")

    def test_activate_already_active(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="already active"):
            sample_aggregate.activate(user_id)

    def test_deactivate_already_inactive(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.deactivate(user_id, "test")
        with pytest.raises(ValueError, match="already inactive"):
            agg.deactivate(user_id, "again")

    # ---- Rename, update_description, set_* ----
    def test_rename(self, sample_aggregate, user_id):
        agg = sample_aggregate
        new_name = "Renamed Item"
        agg.rename(new_name, user_id)
        assert agg.item.name == new_name
        assert agg.item.version == 2
        assert agg.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and e.changes.get("name") == new_name for e in events)
        trail = agg.audit_trail()
        assert any(e["action"] == "rename" for e in trail)

    def test_rename_short_name(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="at least 3 characters"):
            sample_aggregate.rename("AB", user_id)

    def test_rename_locked(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.rename("New", user_id)

    def test_update_description(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.update_description("New desc", user_id)
        assert agg.item.description == "New desc"
        assert agg.item.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and "description" in e.changes for e in events)

    def test_set_reorder_point(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.set_reorder_point(Decimal("30"), user_id)
        assert agg.item.reorder_point == Decimal("30")
        assert agg.item.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and "reorder_point" in e.changes for e in events)

    def test_set_reorder_point_negative(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_aggregate.set_reorder_point(Decimal("-1"), user_id)

    def test_set_safety_stock(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.set_safety_stock(Decimal("15"), user_id)
        assert agg.item.safety_stock == Decimal("15")
        assert agg.item.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and "safety_stock" in e.changes for e in events)

    def test_set_safety_stock_negative(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_aggregate.set_safety_stock(Decimal("-1"), user_id)

    def test_set_standard_cost(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.set_standard_cost(Decimal("55"), user_id)
        assert agg.item.standard_cost == Decimal("55")
        assert agg.item.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and "standard_cost" in e.changes for e in events)

    def test_set_standard_cost_negative(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_aggregate.set_standard_cost(Decimal("-1"), user_id)

    def test_set_selling_price(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.set_selling_price(Decimal("120"), user_id)
        assert agg.item.selling_price == Decimal("120")
        assert agg.item.version == 2

    def test_set_selling_price_negative(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_aggregate.set_selling_price(Decimal("-1"), user_id)

    def test_set_category(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.set_category("New Category", user_id)
        assert agg.item.category == "New Category"
        assert agg.item.version == 2
        events = agg.get_events()
        assert any(isinstance(e, ItemUpdated) and "category" in e.changes for e in events)

    def test_update_standard_cost_alias(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.update_standard_cost(Decimal("60"), user_id)
        assert agg.item.standard_cost == Decimal("60")
        assert agg.item.version == 2

    # ---- Deactivate Item ----
    def test_deactivate_item(self, sample_aggregate, user_id):
        agg = sample_aggregate
        # Set stock to 0
        agg._item.current_stock = Decimal("0")
        agg.deactivate_item("discontinued", user_id)
        assert agg.item.status == ItemStatus.INACTIVE
        assert agg.is_active is False
        assert agg.item.deactivated_at == FIXED_DATETIME
        assert agg.item.deactivated_by == user_id
        events = agg.get_events()
        assert any(isinstance(e, ItemDeactivated) for e in events)
        trail = agg.audit_trail()
        assert any(e["action"] == "deactivate_item" for e in trail)

    def test_deactivate_item_with_stock(self, sample_aggregate, user_id):
        with pytest.raises(ValueError, match="Cannot deactivate item with current stock"):
            sample_aggregate.deactivate_item("reason", user_id)

    def test_deactivate_item_locked(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.deactivate_item("reason", user_id)

    # ---- Stock Movements ----
    def test_receive_stock(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        initial_stock = agg.current_stock
        initial_value = agg.current_stock_value
        initial_avg = agg.average_cost

        agg.receive_stock(stock_movement, user_id)

        expected_stock = initial_stock + stock_movement.quantity
        expected_value = initial_value + (stock_movement.quantity * stock_movement.unit_cost)
        expected_avg = expected_value / expected_stock if expected_stock > 0 else Decimal(0)

        assert agg.current_stock == expected_stock
        assert agg.current_stock_value == expected_value
        assert agg.average_cost == expected_avg.quantize(Decimal("0.01"))
        assert agg.item.version == 2
        assert agg.version == 2

        # FIFO layers
        layers = agg.get_fifo_layers()
        assert len(layers) == 2  # initial + new
        assert layers[-1]["quantity"] == stock_movement.quantity
        assert layers[-1]["remaining_quantity"] == stock_movement.quantity

        events = agg.get_events()
        assert any(isinstance(e, StockMovementCreated) and e.quantity == stock_movement.quantity for e in events)

    def test_receive_stock_zero_quantity(self, sample_aggregate, stock_movement, user_id):
        stock_movement.quantity = Decimal("0")
        with pytest.raises(ValueError, match="Quantity must be positive"):
            sample_aggregate.receive_stock(stock_movement, user_id)

    def test_receive_stock_negative_unit_cost(self, sample_aggregate, stock_movement, user_id):
        stock_movement.unit_cost = Decimal("-10")
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            sample_aggregate.receive_stock(stock_movement, user_id)

    def test_receive_stock_locked(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.receive_stock(stock_movement, user_id)

    def test_receive_stock_item_not_set(self, legal_entity_id, stock_movement, user_id):
        agg = InventoryAggregate(id=uuid.uuid4(), legal_entity_id=legal_entity_id, version=0)
        with pytest.raises(ValueError, match="No item loaded"):
            agg.receive_stock(stock_movement, user_id)

    def test_receive_stock_warehouse_mismatch(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        # Set warehouse_id on aggregate to a specific value
        agg._warehouse_id = uuid.uuid4()
        # Set movement warehouse to a different one
        stock_movement.warehouse_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Warehouse mismatch"):
            agg.receive_stock(stock_movement, user_id)

    # ---- Issue Stock ----
    def test_issue_stock(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        # Use FIFO to calculate expected cost
        initial_stock = agg.current_stock
        initial_value = agg.current_stock_value

        # FIFO cost for quantity: initial layer 100 at 50, consuming 50 costs 2500
        stock_movement.quantity = Decimal("50")
        stock_movement.unit_cost = Decimal("50")  # Not used in FIFO, but for record
        agg.issue_stock(stock_movement, user_id)

        expected_stock = initial_stock - stock_movement.quantity
        expected_value = initial_value - Decimal("2500")
        assert agg.current_stock == expected_stock
        assert agg.current_stock_value == expected_value
        # average_cost unchanged
        assert agg.average_cost == Decimal("50")

        # FIFO layers: initial layer remaining 50, no new layer
        layers = agg.get_fifo_layers()
        assert len(layers) == 1
        assert layers[0]["remaining_quantity"] == Decimal("50")

        events = agg.get_events()
        assert any(isinstance(e, StockMovementCreated) and e.quantity == -stock_movement.quantity for e in events)

    def test_issue_stock_insufficient_stock(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        stock_movement.quantity = Decimal("200")  # more than current
        with pytest.raises(ValueError, match="Insufficient stock"):
            agg.issue_stock(stock_movement, user_id)

    def test_issue_stock_zero_quantity(self, sample_aggregate, stock_movement, user_id):
        stock_movement.quantity = Decimal("0")
        with pytest.raises(ValueError, match="Quantity must be positive"):
            sample_aggregate.issue_stock(stock_movement, user_id)

    def test_issue_stock_locked(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.issue_stock(stock_movement, user_id)

    def test_issue_stock_item_not_set(self, legal_entity_id, stock_movement, user_id):
        agg = InventoryAggregate(id=uuid.uuid4(), legal_entity_id=legal_entity_id, version=0)
        with pytest.raises(ValueError, match="No item loaded"):
            agg.issue_stock(stock_movement, user_id)

    def test_issue_stock_warehouse_mismatch(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        agg._warehouse_id = uuid.uuid4()
        stock_movement.warehouse_id = uuid.uuid4()
        with pytest.raises(ValueError, match="Warehouse mismatch"):
            agg.issue_stock(stock_movement, user_id)

    # ---- Adjust Stock ----
    def test_adjust_stock_increase(self, sample_aggregate, user_id):
        agg = sample_aggregate
        initial_stock = agg.current_stock
        initial_value = agg.current_stock_value

        adjustment_amount = Decimal("20")
        unit_cost = Decimal("55")
        agg.adjust_stock(adjustment_amount, AdjustmentReason.RETURN_FROM_CUSTOMER, unit_cost, user_id)

        expected_stock = initial_stock + adjustment_amount
        expected_value = initial_value + (adjustment_amount * unit_cost)
        expected_avg = expected_value / expected_stock if expected_stock > 0 else Decimal(0)

        assert agg.current_stock == expected_stock
        assert agg.current_stock_value == expected_value
        assert agg.average_cost == expected_avg.quantize(Decimal("0.01"))
        # FIFO layer added
        layers = agg.get_fifo_layers()
        assert len(layers) == 2
        assert layers[-1]["quantity"] == adjustment_amount

        events = agg.get_events()
        assert any(isinstance(e, StockAdjusted) for e in events)

    def test_adjust_stock_decrease(self, sample_aggregate, user_id):
        agg = sample_aggregate
        initial_stock = agg.current_stock
        initial_value = agg.current_stock_value

        adjustment_amount = Decimal("-30")
        unit_cost = Decimal("50")  # Not used for decrease, FIFO takes cost
        agg.adjust_stock(adjustment_amount, AdjustmentReason.SPOILAGE, unit_cost, user_id)

        expected_stock = initial_stock + adjustment_amount  # 100 - 30 = 70
        # FIFO cost: 30 * 50 = 1500
        expected_value = initial_value - Decimal("1500")
        assert agg.current_stock == Decimal("70")
        assert agg.current_stock_value == expected_value
        # FIFO layer remaining 70
        layers = agg.get_fifo_layers()
        assert len(layers) == 1
        assert layers[0]["remaining_quantity"] == Decimal("70")

        events = agg.get_events()
        assert any(isinstance(e, StockAdjusted) for e in events)

    def test_adjust_stock_insufficient(self, sample_aggregate, user_id):
        adjustment_amount = Decimal("-150")  # more than stock
        with pytest.raises(ValueError, match="Insufficient stock for adjustment"):
            sample_aggregate.adjust_stock(adjustment_amount, AdjustmentReason.SPOILAGE, Decimal("50"), user_id)

    def test_adjust_stock_zero_amount(self, sample_aggregate, user_id):
        # Should return without changes
        agg = sample_aggregate
        initial_version = agg.version
        agg.adjust_stock(Decimal("0"), AdjustmentReason.RETURN_FROM_CUSTOMER, Decimal("50"), user_id)
        assert agg.version == initial_version  # no change

    def test_adjust_stock_locked(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.adjust_stock(Decimal("10"), AdjustmentReason.RETURN_FROM_CUSTOMER, Decimal("50"), user_id)

    def test_adjust_stock_item_not_set(self, legal_entity_id, user_id):
        agg = InventoryAggregate(id=uuid.uuid4(), legal_entity_id=legal_entity_id, version=0)
        with pytest.raises(ValueError, match="No item loaded"):
            agg.adjust_stock(Decimal("10"), AdjustmentReason.RETURN_FROM_CUSTOMER, Decimal("50"), user_id)

    # ---- FIFO Layers ----
    def test_fifo_layers_after_multiple_transactions(self, sample_aggregate, stock_movement, user_id):
        agg = sample_aggregate
        # Initial layer: 100 at 50
        # Receive 50 at 60
        agg.receive_stock(stock_movement, user_id)
        # Issue 80 (should consume 50 from first layer and 30 from second)
        issue_movement = StockMovement(
            id=uuid.uuid4(),
            legal_entity_id=agg.legal_entity_id,
            item_id=agg.item.id,
            sku=agg.item.sku,
            movement_type=MovementType.SALES,
            quantity=Decimal("80"),
            unit_cost=Decimal("55"),
            total_value=Decimal("0"),
            warehouse_id=agg._warehouse_id or uuid.uuid4(),
            warehouse_name="WH-01",
            transaction_date=FIXED_DATETIME,
            reference_document="SO-001",
            reference_document_type="sales_order",
            created_by=user_id,
            created_at=FIXED_DATETIME,
            approved_at=None,
            approved_by=None,
            status="draft",
            notes=None,
            cost_center=None,
            department=None,
            project_id=None,
            source_location=None,
            destination_location=None,
            from_warehouse_id=None,
            to_warehouse_id=None,
            batch_number=None,
            serial_numbers=None,
        )
        agg.issue_stock(issue_movement, user_id)

        layers = agg.get_fifo_layers()
        # First layer fully consumed (remaining 0), second layer remaining 20 (50-30)
        assert len(layers) == 1
        assert layers[0]["remaining_quantity"] == Decimal("20")
        assert layers[0]["unit_cost"] == Decimal("60")
        # Total stock = 100 - 80 + 50 = 70, but after issue: initial 100 + received 50 - issued 80 = 70
        assert agg.current_stock == Decimal("70")
        # Value: initial 5000 + 3000 - (50*50 + 30*60) = 8000 - (2500+1800) = 3700
        assert agg.current_stock_value == Decimal("3700")

    # ---- Validate ----
    def test_validate_ok(self, sample_aggregate):
        errors = sample_aggregate.validate()
        assert errors == []

    def test_validate_item_not_set(self):
        agg = InventoryAggregate(id=uuid.uuid4(), legal_entity_id=uuid.uuid4(), version=0)
        errors = agg.validate()
        assert errors == ["Item not set"]

    def test_validate_negative_stock(self, sample_aggregate):
        agg = sample_aggregate
        agg._item.current_stock = Decimal("-5")
        errors = agg.validate()
        assert any("negative" in e for e in errors)

    def test_validate_negative_value(self, sample_aggregate):
        agg = sample_aggregate
        agg._item.current_stock_value = Decimal("-10")
        errors = agg.validate()
        assert any("negative" in e for e in errors)

    def test_validate_value_mismatch(self, sample_aggregate):
        agg = sample_aggregate
        agg._item.current_stock = Decimal("10")
        agg._item.average_cost = Decimal("50")
        agg._item.current_stock_value = Decimal("400")  # should be 500
        errors = agg.validate()
        assert any("mismatch" in e for e in errors)

    # ---- Reconcile (dummy) ----
    def test_reconcile(self, sample_aggregate):
        system_qty = Decimal("100")
        physical_qty = Decimal("95")
        diff = sample_aggregate.reconcile(system_qty, physical_qty)
        assert diff == physical_qty - system_qty

    # ---- Snapshot ----
    def test_snapshot_and_restore(self, sample_aggregate):
        agg = sample_aggregate
        snap = agg.snapshot()
        assert snap["aggregate_id"] == str(agg.id)
        assert snap["version"] == agg.version
        assert "state" in snap
        assert snap["hash"] == agg._compute_hash()

        # Restore into a new aggregate
        new_agg = InventoryAggregate(id=agg.id, legal_entity_id=agg.legal_entity_id, version=0)
        new_agg.restore_from_snapshot(snap)
        assert new_agg._item.sku == agg._item.sku
        assert new_agg._fifo_layers == agg._fifo_layers
        assert new_agg._is_locked == agg._is_locked
        assert new_agg._is_active == agg._is_active
        assert new_agg.version == agg.version

    def test_restore_wrong_aggregate(self, sample_aggregate):
        agg = sample_aggregate
        snap = agg.snapshot()
        snap["aggregate_id"] = str(uuid.uuid4())  # change id
        new_agg = InventoryAggregate(id=agg.id, legal_entity_id=agg.legal_entity_id, version=0)
        with pytest.raises(ValueError, match="different aggregate"):
            new_agg.restore_from_snapshot(snap)

    # ---- Version ----
    def test_version_increment(self, sample_aggregate):
        agg = sample_aggregate
        old = agg.version
        agg.increment_version()
        assert agg.version == old + 1

    # ---- Touch ----
    def test_touch(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.touch(user_id)
        trail = agg.audit_trail()
        assert any(e["action"] == "touched" for e in trail)

    # ---- Clone ----
    def test_clone(self, sample_aggregate):
        agg = sample_aggregate
        cloned = agg.clone()
        assert cloned.id != agg.id
        assert cloned.legal_entity_id == agg.legal_entity_id
        assert cloned.version == 1
        assert cloned._item.sku == agg._item.sku
        assert cloned._fifo_layers == agg._fifo_layers
        assert cloned._is_active == agg._is_active
        assert cloned._is_locked == agg._is_locked
        trail = cloned.audit_trail()
        assert any(e["action"] == "cloned" for e in trail)

    # ---- Event Methods ----
    def test_event_methods(self, sample_aggregate):
        agg = sample_aggregate
        # Initially has one event (ItemCreated)
        assert len(agg.get_events()) == 1
        # Add custom event
        event = MagicMock()
        agg.register_event(event)
        assert len(agg.get_events()) == 2
        agg.clear_events()
        assert len(agg.get_events()) == 0
        # pop_events returns and clears
        agg.register_event(event)
        popped = agg.pop_events()
        assert len(popped) == 1
        assert popped[0] == event
        assert len(agg.get_events()) == 0
        # pull_events alias
        agg.register_event(event)
        pulled = agg.pull_events()
        assert len(pulled) == 1
        assert len(agg.get_events()) == 0
        # apply
        agg.apply(event)
        assert len(agg.get_events()) == 1

    # ---- Reconstruct / Replay ----
    def test_reconstruct_from_events(self, sample_item, user_id):
        # Create events
        agg = InventoryAggregate.create(sample_item, user_id)
        events = agg.pop_events()  # includes ItemCreated

        # Add a StockMovementCreated event
        stock_event = StockMovementCreated(
            aggregate_id=agg.id,
            movement_id=uuid.uuid4(),
            item_id=sample_item.id,
            sku=sample_item.sku,
            movement_type="purchase",
            quantity=Decimal("10"),
            unit_cost=Decimal("60"),
            total_value=Decimal("600"),
            user_id=user_id,
            occurred_at=FIXED_DATETIME,
        )
        events.append(stock_event)

        # Reconstruct
        new_agg = InventoryAggregate.reconstruct(events)
        assert new_agg.id == agg.id
        assert new_agg.legal_entity_id == agg.legal_entity_id
        assert new_agg.version == len(events)
        # Check that state updated
        assert new_agg._item.current_stock == sample_item.current_stock + Decimal("10")
        assert new_agg._item.current_stock_value == sample_item.current_stock_value + Decimal("600")

        # Replay into existing aggregate
        agg2 = InventoryAggregate(id=agg.id, legal_entity_id=agg.legal_entity_id, version=0)
        agg2.replay(events)
        assert agg2._item.current_stock == new_agg._item.current_stock
        assert agg2.version == len(events)

    def test_replay_events_alias(self, sample_item, user_id):
        """Test replay_events alias specifically."""
        agg = InventoryAggregate.create(sample_item, user_id)
        events = agg.pop_events()  # ItemCreated

        # Create a new aggregate and replay using replay_events
        agg2 = InventoryAggregate(id=agg.id, legal_entity_id=agg.legal_entity_id, version=0)
        agg2.replay_events(events)
        assert agg2._item.sku == sample_item.sku
        assert agg2.version == len(events)

    def test_reconstruct_no_events(self):
        with pytest.raises(ValueError, match="No events provided"):
            InventoryAggregate.reconstruct([])

    def test_from_events_alias(self, sample_aggregate):
        events = sample_aggregate.pop_events()
        agg = InventoryAggregate.from_events(events)
        assert agg.id == sample_aggregate.id

    # ---- to_dict / from_dict ----
    def test_to_dict_from_dict(self, sample_aggregate):
        agg = sample_aggregate
        d = agg.to_dict()
        assert d["id"] == str(agg.id)
        assert d["version"] == agg.version
        assert "item" in d
        assert d["current_stock"] == str(agg.current_stock)

        new_agg = InventoryAggregate.from_dict(d)
        assert new_agg.id == agg.id
        assert new_agg.legal_entity_id == agg.legal_entity_id
        assert new_agg.version == agg.version
        assert new_agg._item.sku == agg._item.sku
        assert new_agg._fifo_layers == agg._fifo_layers

    # ---- pop_domain_events alias ----
    def test_pop_domain_events(self, sample_aggregate):
        agg = sample_aggregate
        events = agg.pop_domain_events()
        assert len(events) == 1
        assert len(agg.get_events()) == 0

    # ---- update_stock helper ----
    def test_update_stock(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.update_stock(Decimal("200"), Decimal("10000"), Decimal("50"), user_id)
        assert agg.current_stock == Decimal("200")
        assert agg.current_stock_value == Decimal("10000")
        assert agg.average_cost == Decimal("50")
        assert agg.version == 2
        trail = agg.audit_trail()
        assert any(e["action"] == "update_stock" for e in trail)

    def test_update_stock_locked(self, sample_aggregate, user_id):
        agg = sample_aggregate
        agg.lock(user_id, "test")
        with pytest.raises(ValueError, match="locked"):
            agg.update_stock(Decimal("200"), Decimal("10000"), Decimal("50"), user_id)

    # ---- _record_audit wrapper ----
    def test_record_audit_wrapper(self, sample_aggregate):
        agg = sample_aggregate
        agg._record_audit("test_action", {"key": "value"})
        trail = agg.audit_trail()
        assert any(e["action"] == "test_action" for e in trail)

    # ---- get_fifo_layers ----
    def test_get_fifo_layers(self, sample_aggregate):
        layers = sample_aggregate.get_fifo_layers()
        assert len(layers) == 1
        assert layers[0]["quantity"] == Decimal("100")

    # ---- property warehouse_id ----
    def test_warehouse_id_property(self, sample_aggregate):
        assert sample_aggregate.warehouse_id is None
        sample_aggregate._warehouse_id = uuid.uuid4()
        assert sample_aggregate.warehouse_id is not None