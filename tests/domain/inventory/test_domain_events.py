# tests/domain/inventory/test_domain_events.py
"""
Comprehensive unit tests for inventory domain events.

Covers:
- DomainEvent base class: to_json, from_json, serialize, deserialize
- All concrete event classes: constructors, properties, dummy methods
- Aliases (ItemCreated, etc.) are tested via their original classes
- DomainEventPublisher protocol (abstract methods raise NotImplementedError)
- Edge cases: optional fields, default values, timezone handling
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from domain.inventory.domain_events import (
    COGSCalculated,
    COGSCalculatedEvent,
    DomainEvent,
    DomainEventPublisher,
    DomainEventType,
    InterWarehouseTransferCreated,
    InterWarehouseTransferCreatedEvent,
    InventoryValuationUpdated,
    InventoryValuationUpdatedEvent,
    ItemCreated,
    ItemCreatedEvent,
    ItemDeactivated,
    ItemDeactivatedEvent,
    ItemUpdated,
    ItemUpdatedEvent,
    StockAdjusted,
    StockAdjustedEvent,
    StockLevelAlert,
    StockLevelAlertEvent,
    StockMovementCreated,
    StockMovementCreatedEvent,
    StockOpnameApproved,
    StockOpnameApprovedEvent,
    StockOpnameCreated,
    StockOpnameCreatedEvent,
    TransferCompleted,
    TransferCompletedEvent,
)
from domain.inventory.stock_adjustment_entity import (
    AdjustmentStatus,
    AdjustmentType,
    StockAdjustmentEntity,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def legal_entity_id() -> UUID:
    return uuid4()


@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def aggregate_id() -> UUID:
    return uuid4()


@pytest.fixture
def sample_adjustment(legal_entity_id, user_id) -> StockAdjustmentEntity:
    return StockAdjustmentEntity(
        adjustment_id=uuid4(),
        adjustment_number="ADJ-001",
        adjustment_type=AdjustmentType.CORRECTION,
        warehouse_id=uuid4(),
        warehouse_name="WH-01",
        item_id=uuid4(),
        item_sku="SKU-001",
        item_name="Test Item",
        quantity=Decimal("10"),
        unit_cost=Decimal("50"),
        total_value=Decimal("500"),
        adjustment_date=datetime.now(UTC).date(),
        status=AdjustmentStatus.DRAFT,
        reason="Correction",
        created_by=user_id,
        legal_entity_id=legal_entity_id,
    )


# -----------------------------------------------------------------------------
# Tests for DomainEventType Enum
# -----------------------------------------------------------------------------

class TestDomainEventType:
    def test_members(self):
        assert DomainEventType.ITEM_CREATED.value == "item_created"
        assert DomainEventType.ITEM_UPDATED.value == "item_updated"
        assert DomainEventType.ITEM_DEACTIVATED.value == "item_deactivated"
        assert DomainEventType.GOODS_RECEIVED.value == "goods_received"
        assert DomainEventType.GOODS_ISSUED.value == "goods_issued"
        assert DomainEventType.STOCK_TRANSFERRED.value == "stock_transferred"
        assert DomainEventType.STOCK_ADJUSTED.value == "stock_adjusted"
        assert DomainEventType.STOCK_OPNAME_PLANNED.value == "stock_opname_planned"
        assert DomainEventType.STOCK_OPNAME_COMPLETED.value == "stock_opname_completed"
        assert DomainEventType.STOCK_OPNAME_APPROVED.value == "stock_opname_approved"
        assert DomainEventType.INTER_WAREHOUSE_TRANSFER_CREATED.value == "inter_warehouse_transfer_created"
        assert DomainEventType.TRANSFER_COMPLETED.value == "transfer_completed"
        assert DomainEventType.COGS_CALCULATED.value == "cogs_calculated"
        assert DomainEventType.STOCK_LEVEL_ALERT.value == "stock_level_alert"
        assert DomainEventType.INVENTORY_VALUATION_UPDATED.value == "inventory_valuation_updated"


# -----------------------------------------------------------------------------
# Tests for DomainEvent (Base)
# -----------------------------------------------------------------------------

class TestDomainEvent:
    def test_construction(self):
        event = DomainEvent(
            event_type=DomainEventType.ITEM_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            user_id="user123",
            event_data={"key": "value"},
        )
        assert event.event_id is not None
        assert event.event_type == DomainEventType.ITEM_CREATED
        assert event.aggregate_version == 1
        assert event.user_id == "user123"
        assert event.event_data == {"key": "value"}
        assert event.correlation_id is None
        assert event.causation_id is None

    def test_to_json(self):
        event = DomainEvent(
            event_type=DomainEventType.ITEM_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            user_id="user123",
            event_data={"key": "value"},
        )
        json_str = event.to_json()
        assert isinstance(json_str, str)
        import json
        data = json.loads(json_str)
        assert data["event_type"] == "item_created"
        assert data["aggregate_version"] == 1
        assert data["user_id"] == "user123"
        assert data["event_data"] == {"key": "value"}

    def test_from_json(self):
        original = DomainEvent(
            event_type=DomainEventType.ITEM_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=5,
            user_id="user456",
            event_data={"foo": "bar"},
        )
        json_str = original.to_json()
        restored = DomainEvent.from_json(json_str)
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.aggregate_id == original.aggregate_id
        assert restored.aggregate_version == original.aggregate_version
        assert restored.user_id == original.user_id
        assert restored.event_data == original.event_data
        assert restored.correlation_id == original.correlation_id
        assert restored.causation_id == original.causation_id

    def test_serialize_deserialize(self):
        original = DomainEvent(
            event_type=DomainEventType.ITEM_CREATED,
            aggregate_id=uuid4(),
            aggregate_version=1,
            user_id="user789",
            event_data={"num": 42},
        )
        data = original.serialize()
        restored = DomainEvent.deserialize(data)
        assert restored.event_id == original.event_id
        assert restored.event_data == original.event_data


# -----------------------------------------------------------------------------
# Tests for ItemCreatedEvent (and alias ItemCreated)
# -----------------------------------------------------------------------------

class TestItemCreatedEvent:
    def test_construction_minimal(self, aggregate_id, legal_entity_id, user_id):
        item_id = uuid4()
        event = ItemCreatedEvent(
            item_id=item_id,
            sku="SKU-001",
            name="Test Item",
            item_type="finished_goods",
            unit_cost=Decimal("50.00"),
            aggregate_id=aggregate_id,
            aggregate_version=1,
            created_by=str(user_id),
            legal_entity_id=legal_entity_id,
            user_id=str(user_id),
        )
        assert event.event_type == DomainEventType.ITEM_CREATED
        assert event.aggregate_id == aggregate_id
        assert event.aggregate_version == 1
        assert event.user_id == str(user_id)
        assert event.item_id == item_id
        assert event.event_data["sku"] == "SKU-001"
        assert event.event_data["unit_cost"] == "50.00"

    def test_with_initial_stock(self, aggregate_id, user_id):
        item_id = uuid4()
        event = ItemCreatedEvent(
            item_id=item_id,
            sku="SKU-002",
            name="Item with stock",
            item_type="raw_material",
            unit_cost=Decimal("10.00"),
            aggregate_id=aggregate_id,
            aggregate_version=1,
            created_by=str(user_id),
            user_id=str(user_id),
            initial_stock=Decimal("100"),
            initial_value=Decimal("1000"),
        )
        assert event.event_data["initial_stock"] == "100"
        assert event.event_data["initial_value"] == "1000"

    def test_item_id_property(self, aggregate_id, user_id):
        item_id = uuid4()
        event = ItemCreatedEvent(
            item_id=item_id,
            sku="SKU-003",
            name="Test",
            item_type="finished_goods",
            unit_cost=Decimal("20.00"),
            aggregate_id=aggregate_id,
            created_by=str(user_id),
        )
        assert event.item_id == item_id

    def test_serialization_roundtrip(self, aggregate_id, user_id):
        item_id = uuid4()
        original = ItemCreatedEvent(
            item_id=item_id,
            sku="SKU-004",
            name="Serialization Test",
            item_type="finished_goods",
            unit_cost=Decimal("100.00"),
            aggregate_id=aggregate_id,
            aggregate_version=2,
            created_by=str(user_id),
            user_id=str(user_id),
            correlation_id="corr-123",
        )
        json_str = original.to_json()
        restored = DomainEvent.from_json(json_str)
        # Since from_json returns DomainEvent, we need to check fields
        assert restored.event_type == DomainEventType.ITEM_CREATED
        assert restored.aggregate_id == aggregate_id
        assert restored.aggregate_version == 2
        assert restored.user_id == str(user_id)
        assert restored.event_data["item_id"] == str(item_id)
        assert restored.event_data["sku"] == "SKU-004"
        assert restored.correlation_id == "corr-123"


# -----------------------------------------------------------------------------
# Tests for ItemUpdatedEvent
# -----------------------------------------------------------------------------

class TestItemUpdatedEvent:
    def test_construction(self, legal_entity_id, user_id, aggregate_id):
        changes = {"name": "New Name", "standard_cost": "60.00"}
        event = ItemUpdatedEvent(
            legal_entity_id=legal_entity_id,
            sku="SKU-001",
            changes=changes,
            user_id=user_id,
            aggregate_id=aggregate_id,
            aggregate_version=3,
            correlation_id="corr-abc",
        )
        assert event.event_type == DomainEventType.ITEM_UPDATED
        assert event.aggregate_id == aggregate_id
        assert event.aggregate_version == 3
        assert event.user_id == str(user_id)
        assert event.event_data["sku"] == "SKU-001"
        assert event.event_data["changes"] == changes
        assert event.correlation_id == "corr-abc"

    def test_serialization_roundtrip(self, legal_entity_id, user_id, aggregate_id):
        changes = {"description": "Updated desc", "category": "Electronics"}
        original = ItemUpdatedEvent(
            legal_entity_id=legal_entity_id,
            sku="SKU-002",
            changes=changes,
            user_id=user_id,
            aggregate_id=aggregate_id,
            aggregate_version=4,
        )
        data = original.serialize()
        restored = DomainEvent.deserialize(data)
        assert restored.event_type == DomainEventType.ITEM_UPDATED
        assert restored.aggregate_id == aggregate_id
        assert restored.aggregate_version == 4
        assert restored.user_id == str(user_id)
        assert restored.event_data["sku"] == "SKU-002"
        assert restored.event_data["changes"] == changes


# -----------------------------------------------------------------------------
# Tests for ItemDeactivatedEvent
# -----------------------------------------------------------------------------

class TestItemDeactivatedEvent:
    def test_construction(self, user_id, aggregate_id):
        event = ItemDeactivatedEvent(
            sku="SKU-001",
            reason="Discontinued",
            user_id=user_id,
            aggregate_id=aggregate_id,
            correlation_id="corr-xyz",
        )
        assert event.event_type == DomainEventType.ITEM_DEACTIVATED
        assert event.aggregate_id == aggregate_id
        assert event.user_id == str(user_id)
        assert event.event_data["sku"] == "SKU-001"
        assert event.event_data["reason"] == "Discontinued"

    def test_serialization(self, user_id):
        original = ItemDeactivatedEvent(
            sku="SKU-002",
            reason="No longer used",
            user_id=user_id,
        )
        json_str = original.to_json()
        restored = DomainEvent.from_json(json_str)
        assert restored.event_data["sku"] == "SKU-002"
        assert restored.event_data["reason"] == "No longer used"


# -----------------------------------------------------------------------------
# Tests for StockMovementCreatedEvent
# -----------------------------------------------------------------------------

class TestStockMovementCreatedEvent:
    def test_construction_receipt(self, aggregate_id, user_id):
        movement_id = uuid4()
        item_id = uuid4()
        event = StockMovementCreatedEvent(
            movement_id=movement_id,
            item_id=item_id,
            sku="SKU-001",
            movement_type="PURCHASE_RECEIPT",
            quantity=Decimal("50"),
            unit_cost=Decimal("60.00"),
            total_value=Decimal("3000"),
            user_id=user_id,
            aggregate_id=aggregate_id,
            correlation_id="corr-123",
        )
        # For receipt, event_type should be GOODS_RECEIVED
        assert event.event_type == DomainEventType.GOODS_RECEIVED
        assert event.aggregate_id == aggregate_id
        assert event.user_id == str(user_id)
        assert event.event_data["movement_id"] == str(movement_id)
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["sku"] == "SKU-001"
        assert event.event_data["quantity"] == "50"
        assert event.event_data["unit_cost"] == "60.00"
        assert event.event_data["total_value"] == "3000"

    def test_construction_issue(self, aggregate_id, user_id):
        event = StockMovementCreatedEvent(
            movement_id=uuid4(),
            item_id=uuid4(),
            sku="SKU-002",
            movement_type="SALES",
            quantity=Decimal("10"),
            unit_cost=Decimal("80.00"),
            total_value=Decimal("800"),
            user_id=user_id,
            aggregate_id=aggregate_id,
        )
        assert event.event_type == DomainEventType.GOODS_ISSUED

    def test_movement_identifier_and_properties(self, aggregate_id, user_id):
        movement_id = uuid4()
        event = StockMovementCreatedEvent(
            movement_id=movement_id,
            item_id=uuid4(),
            sku="SKU-003",
            movement_type="TRANSFER_IN",
            quantity=Decimal("25"),
            unit_cost=Decimal("70.00"),
            total_value=Decimal("1750"),
            user_id=user_id,
            aggregate_id=aggregate_id,
        )
        assert event.movement_identifier() == movement_id
        assert event.movement_id == movement_id
        assert event.quantity == Decimal("25")


# -----------------------------------------------------------------------------
# Tests for StockAdjustedEvent
# -----------------------------------------------------------------------------

class TestStockAdjustedEvent:
    def test_construction(self, sample_adjustment, aggregate_id, user_id):
        event = StockAdjustedEvent(
            adjustment=sample_adjustment,
            adjusted_by=str(user_id),
            aggregate_id=aggregate_id,
            aggregate_version=2,
            user_id=str(user_id),
            correlation_id="corr-456",
        )
        assert event.event_type == DomainEventType.STOCK_ADJUSTED
        assert event.aggregate_id == aggregate_id
        assert event.aggregate_version == 2
        assert event.user_id == str(user_id)
        assert event.event_data["adjustment_id"] == str(sample_adjustment.adjustment_id)
        assert event.event_data["adjustment_number"] == sample_adjustment.adjustment_number
        assert event.event_data["item_id"] == str(sample_adjustment.item_id)
        assert event.event_data["quantity"] == str(sample_adjustment.quantity)
        assert event.event_data["adjusted_by"] == str(user_id)

    def test_serialization(self, sample_adjustment, aggregate_id):
        original = StockAdjustedEvent(
            adjustment=sample_adjustment,
            adjusted_by="admin",
            aggregate_id=aggregate_id,
        )
        data = original.serialize()
        restored = DomainEvent.deserialize(data)
        assert restored.event_type == DomainEventType.STOCK_ADJUSTED
        assert restored.aggregate_id == aggregate_id
        assert restored.event_data["adjustment_number"] == sample_adjustment.adjustment_number


# -----------------------------------------------------------------------------
# Tests for StockOpnameCreatedEvent
# -----------------------------------------------------------------------------

class TestStockOpnameCreatedEvent:
    def test_construction(self, aggregate_id, user_id):
        item_id = uuid4()
        event = StockOpnameCreatedEvent(
            item_id=item_id,
            sku="SKU-001",
            discrepancy=Decimal("5.00"),
            user_id=user_id,
            aggregate_id=aggregate_id,
            correlation_id="corr-789",
        )
        assert event.event_type == DomainEventType.STOCK_OPNAME_PLANNED
        assert event.aggregate_id == aggregate_id
        assert event.user_id == str(user_id)
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["sku"] == "SKU-001"
        assert event.event_data["discrepancy"] == "5.00"

    def test_schedule_dummy(self, aggregate_id, user_id):
        event = StockOpnameCreatedEvent(
            item_id=uuid4(),
            sku="SKU-002",
            discrepancy=Decimal("1.00"),
            user_id=user_id,
        )
        # Should not raise
        event.schedule()


# -----------------------------------------------------------------------------
# Tests for StockOpnameApprovedEvent
# -----------------------------------------------------------------------------

class TestStockOpnameApprovedEvent:
    def test_construction(self, aggregate_id, user_id):
        item_id = uuid4()
        event = StockOpnameApprovedEvent(
            item_id=item_id,
            discrepancy=Decimal("3.50"),
            user_id=user_id,
            aggregate_id=aggregate_id,
        )
        assert event.event_type == DomainEventType.STOCK_OPNAME_APPROVED
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["discrepancy"] == "3.50"

    def test_schedule_dummy(self, aggregate_id, user_id):
        event = StockOpnameApprovedEvent(
            item_id=uuid4(),
            discrepancy=Decimal("0.00"),
            user_id=user_id,
        )
        event.schedule()  # no-op


# -----------------------------------------------------------------------------
# Tests for InterWarehouseTransferCreatedEvent
# -----------------------------------------------------------------------------

class TestInterWarehouseTransferCreatedEvent:
    def test_construction(self, aggregate_id, user_id):
        item_id = uuid4()
        event = InterWarehouseTransferCreatedEvent(
            item_id=item_id,
            sku="SKU-001",
            quantity=Decimal("100"),
            from_warehouse="WH-01",
            to_warehouse="WH-02",
            user_id=user_id,
            aggregate_id=aggregate_id,
            correlation_id="corr-555",
        )
        assert event.event_type == DomainEventType.INTER_WAREHOUSE_TRANSFER_CREATED
        assert event.aggregate_id == aggregate_id
        assert event.user_id == str(user_id)
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["quantity"] == "100"
        assert event.event_data["from_warehouse"] == "WH-01"
        assert event.event_data["to_warehouse"] == "WH-02"


# -----------------------------------------------------------------------------
# Tests for TransferCompletedEvent
# -----------------------------------------------------------------------------

class TestTransferCompletedEvent:
    def test_construction(self, aggregate_id, user_id):
        item_id = uuid4()
        event = TransferCompletedEvent(
            item_id=item_id,
            quantity=Decimal("50"),
            user_id=user_id,
            aggregate_id=aggregate_id,
        )
        assert event.event_type == DomainEventType.TRANSFER_COMPLETED
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["quantity"] == "50"


# -----------------------------------------------------------------------------
# Tests for COGSCalculatedEvent
# -----------------------------------------------------------------------------

class TestCOGSCalculatedEvent:
    def test_construction(self, legal_entity_id, user_id):
        period_start = date(2026, 1, 1)
        period_end = date(2026, 1, 31)
        event = COGSCalculatedEvent(
            legal_entity_id=legal_entity_id,
            period_start=period_start,
            period_end=period_end,
            total_cogs=Decimal("15000.00"),
            user_id=user_id,
            correlation_id="corr-111",
        )
        assert event.event_type == DomainEventType.COGS_CALCULATED
        assert event.aggregate_id == legal_entity_id
        assert event.user_id == str(user_id)
        assert event.event_data["legal_entity_id"] == str(legal_entity_id)
        assert event.event_data["period_start"] == period_start.isoformat()
        assert event.event_data["period_end"] == period_end.isoformat()
        assert event.event_data["total_cogs"] == "15000.00"


# -----------------------------------------------------------------------------
# Tests for InventoryValuationUpdated (and alias InventoryValuationUpdatedEvent)
# -----------------------------------------------------------------------------

class TestInventoryValuationUpdated:
    def test_construction(self, legal_entity_id, user_id):
        valuation_date = date(2026, 1, 15)
        event = InventoryValuationUpdated(
            legal_entity_id=legal_entity_id,
            valuation_date=valuation_date,
            total_value=Decimal("250000.00"),
            valuation_method="FIFO",
            user_id=user_id,
            correlation_id="corr-222",
        )
        assert event.event_type == DomainEventType.INVENTORY_VALUATION_UPDATED
        assert event.event_data["legal_entity_id"] == str(legal_entity_id)
        assert event.event_data["valuation_date"] == valuation_date.isoformat()
        assert event.event_data["total_value"] == "250000.00"
        assert event.event_data["valuation_method"] == "FIFO"

    def test_alias(self):
        # InventoryValuationUpdatedEvent is an alias; ensure it exists
        assert InventoryValuationUpdatedEvent is InventoryValuationUpdated


# -----------------------------------------------------------------------------
# Tests for StockLevelAlertEvent
# -----------------------------------------------------------------------------

class TestStockLevelAlertEvent:
    def test_construction(self, aggregate_id, user_id):
        item_id = uuid4()
        event = StockLevelAlertEvent(
            item_id=item_id,
            sku="SKU-001",
            item_name="Test Item",
            current_stock=Decimal("5"),
            reorder_point=Decimal("20"),
            safety_stock=Decimal("10"),
            alert_type="REORDER",
            aggregate_id=aggregate_id,
            correlation_id="corr-333",
        )
        assert event.event_type == DomainEventType.STOCK_LEVEL_ALERT
        assert event.aggregate_id == aggregate_id
        assert event.user_id is None  # not set
        assert event.event_data["item_id"] == str(item_id)
        assert event.event_data["current_stock"] == "5"
        assert event.event_data["reorder_point"] == "20"
        assert event.event_data["safety_stock"] == "10"
        assert event.event_data["alert_type"] == "REORDER"

    def test_serialization(self, aggregate_id, user_id):
        item_id = uuid4()
        original = StockLevelAlertEvent(
            item_id=item_id,
            sku="SKU-002",
            item_name="Another",
            current_stock=Decimal("0"),
            reorder_point=Decimal("30"),
            safety_stock=Decimal("15"),
            alert_type="CRITICAL",
            aggregate_id=aggregate_id,
        )
        data = original.serialize()
        restored = DomainEvent.deserialize(data)
        assert restored.event_data["sku"] == "SKU-002"
        assert restored.event_data["alert_type"] == "CRITICAL"


# -----------------------------------------------------------------------------
# Tests for Aliases
# -----------------------------------------------------------------------------

class TestAliases:
    def test_aliases_exist(self):
        # Ensure they are the same classes
        assert ItemCreated is ItemCreatedEvent
        assert ItemUpdated is ItemUpdatedEvent
        assert ItemDeactivated is ItemDeactivatedEvent
        assert StockMovementCreated is StockMovementCreatedEvent
        assert StockAdjusted is StockAdjustedEvent
        assert StockOpnameCreated is StockOpnameCreatedEvent
        assert StockOpnameApproved is StockOpnameApprovedEvent
        assert InterWarehouseTransferCreated is InterWarehouseTransferCreatedEvent
        assert TransferCompleted is TransferCompletedEvent
        assert COGSCalculated is COGSCalculatedEvent
        assert StockLevelAlert is StockLevelAlertEvent


# -----------------------------------------------------------------------------
# Tests for DomainEventPublisher (Protocol)
# -----------------------------------------------------------------------------

class TestDomainEventPublisher:
    def test_construction(self):
        publisher = DomainEventPublisher()
        assert isinstance(publisher, DomainEventPublisher)

    @pytest.mark.asyncio
    async def test_publish_not_implemented(self):
        publisher = DomainEventPublisher()
        event = DomainEvent(event_type=DomainEventType.ITEM_CREATED)
        with pytest.raises(NotImplementedError):
            await publisher.publish(event)

    @pytest.mark.asyncio
    async def test_publish_many_not_implemented(self):
        publisher = DomainEventPublisher()
        events = [DomainEvent(event_type=DomainEventType.ITEM_CREATED)]
        with pytest.raises(NotImplementedError):
            await publisher.publish_many(events)
