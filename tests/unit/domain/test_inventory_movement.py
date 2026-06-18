#!/usr/bin/env python3

"""
Module: test_inventory_movement.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Inventory aggregate root.
    Menguji movement (inbound/outbound), stock adjustment, FIFO valuation.

Dependencies:
    - domain/inventory/aggregate_root.py
    - domain/inventory/item_entity.py
    - domain/inventory/movement_entity.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.inventory.aggregate_root import InventoryAggregate
from domain.inventory.domain_events import (
    ItemCreated,
    ItemDeactivated,
    ItemUpdated,
    StockAdjusted,
    StockMovementCreated,
)
from domain.inventory.item_entity import Item, ItemStatus, ItemType, UnitOfMeasure
from domain.inventory.movement_entity import MovementType, StockMovement
from domain.inventory.stock_adjustment_entity import AdjustmentReason
from domain.inventory.valuation_method import FIFOValuation


class TestInventoryAggregate:
    """Test suite untuk Inventory aggregate."""

    @pytest.fixture
    def valid_item(self) -> Item:
        """Fixture item valid."""
        return Item(
            id=uuid4(),
            legal_entity_id=uuid4(),
            sku="SKU-001",
            name="Produk A",
            description="Produk contoh",
            item_type=ItemType.FINISHED_GOOD,
            unit_of_measure=UnitOfMeasure.PCS,
            current_stock=Decimal("0"),
            current_stock_value=Decimal("0"),
            average_cost=Decimal("0"),
            last_cost=Decimal("0"),
            reorder_point=Decimal("10"),
            safety_stock=Decimal("5"),
            maximum_stock=Decimal("1000"),
            minimum_stock=Decimal("5"),
            status=ItemStatus.ACTIVE,
            standard_cost=Decimal("10000"),
            selling_price=Decimal("15000"),
            category="Elektronik",
            warehouse_code="WH-01",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
            updated_at=None,
            updated_by=None,
            deactivated_at=None,
            deactivated_by=None,
        )

    @pytest.fixture
    def inbound_movement(self, valid_item) -> StockMovement:
        """Fixture movement inbound."""
        return StockMovement(
            id=uuid4(),
            legal_entity_id=valid_item.legal_entity_id,
            item_id=valid_item.id,
            movement_type=MovementType.PURCHASE_RECEIPT,
            quantity=Decimal("100"),
            unit_cost=Decimal("10000"),
            total_value=Decimal("1000000"),
            movement_date=date.today(),
            reference_document_type="PO",
            reference_document_number="PO-001",
            warehouse_code="WH-01",
            notes="Pembelian",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )

    def test_create_item_success(self, valid_item):
        """Test: Membuat item baru berhasil."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        assert aggregate.item.id == valid_item.id
        assert aggregate.item.current_stock == Decimal("0")
        assert aggregate.version == 1
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ItemCreated)
        assert events[0].item_id == valid_item.id

    def test_receive_stock_inbound(self, valid_item, inbound_movement):
        """Test: Menerima stock inbound."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.clear_events()
        aggregate.receive_stock(movement=inbound_movement, user_id=uuid4())
        assert aggregate.item.current_stock == Decimal("100")
        assert aggregate.item.current_stock_value == Decimal("1000000")
        assert aggregate.item.average_cost == Decimal("10000")
        assert aggregate.item.last_cost == Decimal("10000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], StockMovementCreated)

    def test_issue_stock_outbound(self, valid_item, inbound_movement):
        """Test: Mengeluarkan stock outbound."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.receive_stock(inbound_movement, uuid4())
        aggregate.clear_events()
        out_movement = StockMovement(
            id=uuid4(),
            legal_entity_id=valid_item.legal_entity_id,
            item_id=valid_item.id,
            movement_type=MovementType.SALES_ISSUE,
            quantity=Decimal("30"),
            unit_cost=Decimal("10000"),  # akan dihitung ulang oleh engine
            total_value=Decimal("300000"),
            movement_date=date.today(),
            reference_document_type="SO",
            reference_document_number="SO-001",
            warehouse_code="WH-01",
            notes="Penjualan",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )
        aggregate.issue_stock(movement=out_movement, user_id=uuid4())
        assert aggregate.item.current_stock == Decimal("70")
        assert aggregate.item.current_stock_value == Decimal("700000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], StockMovementCreated)

    def test_insufficient_stock_raises_error(self, valid_item, inbound_movement):
        """Test: Issue stock melebihi stock yang tersedia harus error."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.receive_stock(inbound_movement, uuid4())
        out_movement = StockMovement(
            id=uuid4(),
            legal_entity_id=valid_item.legal_entity_id,
            item_id=valid_item.id,
            movement_type=MovementType.SALES_ISSUE,
            quantity=Decimal("150"),  # >100
            unit_cost=Decimal("10000"),
            total_value=Decimal("1500000"),
            movement_date=date.today(),
            reference_document_type="SO",
            reference_document_number="SO-002",
            warehouse_code="WH-01",
            notes="Penjualan berlebih",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )
        with pytest.raises(ValueError, match="Insufficient stock"):
            aggregate.issue_stock(out_movement, uuid4())

    def test_adjust_stock_positive(self, valid_item):
        """Test: Penyesuaian stock positif (adjustment in)."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.clear_events()
        aggregate.adjust_stock(
            adjustment_amount=Decimal("50"),
            reason=AdjustmentReason.STOCK_OPNAME,
            unit_cost=Decimal("11000"),
            user_id=uuid4(),
        )
        assert aggregate.item.current_stock == Decimal("50")
        assert aggregate.item.current_stock_value == Decimal("550000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], StockAdjusted)

    def test_adjust_stock_negative(self, valid_item):
        """Test: Penyesuaian stock negatif (adjustment out)."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.receive_stock(
            StockMovement(
                id=uuid4(),
                legal_entity_id=valid_item.legal_entity_id,
                item_id=valid_item.id,
                movement_type=MovementType.PURCHASE_RECEIPT,
                quantity=Decimal("100"),
                unit_cost=Decimal("10000"),
                total_value=Decimal("1000000"),
                movement_date=date.today(),
                reference_document_type="PO",
                reference_document_number="PO-001",
                warehouse_code="WH-01",
                notes="",
                created_by=uuid4(),
                created_at=datetime.utcnow(),
            ),
            uuid4(),
        )
        aggregate.clear_events()
        aggregate.adjust_stock(
            adjustment_amount=Decimal("-20"),
            reason=AdjustmentReason.DAMAGED,
            unit_cost=Decimal("10000"),
            user_id=uuid4(),
        )
        assert aggregate.item.current_stock == Decimal("80")
        assert aggregate.item.current_stock_value == Decimal("800000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], StockAdjusted)

    def test_fifo_valuation(self, valid_item):
        """Test: FIFO valuation untuk outbound."""
        # Setup aggregate dengan FIFO engine
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        # Terima stock dengan harga berbeda
        layer1 = StockMovement(
            id=uuid4(),
            legal_entity_id=valid_item.legal_entity_id,
            item_id=valid_item.id,
            movement_type=MovementType.PURCHASE_RECEIPT,
            quantity=Decimal("100"),
            unit_cost=Decimal("10000"),
            total_value=Decimal("1000000"),
            movement_date=date.today(),
            reference_document_type="PO",
            reference_document_number="PO-001",
            warehouse_code="WH-01",
            notes="",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )
        aggregate.receive_stock(layer1, uuid4())
        layer2 = StockMovement(
            id=uuid4(),
            legal_entity_id=valid_item.legal_entity_id,
            item_id=valid_item.id,
            movement_type=MovementType.PURCHASE_RECEIPT,
            quantity=Decimal("50"),
            unit_cost=Decimal("11000"),
            total_value=Decimal("550000"),
            movement_date=date.today(),
            reference_document_type="PO",
            reference_document_number="PO-002",
            warehouse_code="WH-01",
            notes="",
            created_by=uuid4(),
            created_at=datetime.utcnow(),
        )
        aggregate.receive_stock(layer2, uuid4())
        # Issue stock
        out_qty = Decimal("120")
        # FIFO: 100 * 10000 + 20 * 11000 = 1,000,000 + 220,000 = 1,220,000
        expected_value = Decimal("1220000")
        # Gunakan valuation engine
        fifo = FIFOValuation()
        cost = fifo.calculate_cost(aggregate.get_fifo_layers(), out_qty)
        assert cost == expected_value

    def test_weighted_average_valuation(self, valid_item):
        """Test: Weighted average valuation."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        # Terima stock
        aggregate.receive_stock(
            StockMovement(
                id=uuid4(),
                legal_entity_id=valid_item.legal_entity_id,
                item_id=valid_item.id,
                movement_type=MovementType.PURCHASE_RECEIPT,
                quantity=Decimal("100"),
                unit_cost=Decimal("10000"),
                total_value=Decimal("1000000"),
                movement_date=date.today(),
                reference_document_type="PO",
                reference_document_number="PO-001",
                warehouse_code="WH-01",
                notes="",
                created_by=uuid4(),
                created_at=datetime.utcnow(),
            ),
            uuid4(),
        )
        aggregate.receive_stock(
            StockMovement(
                id=uuid4(),
                legal_entity_id=valid_item.legal_entity_id,
                item_id=valid_item.id,
                movement_type=MovementType.PURCHASE_RECEIPT,
                quantity=Decimal("50"),
                unit_cost=Decimal("11000"),
                total_value=Decimal("550000"),
                movement_date=date.today(),
                reference_document_type="PO",
                reference_document_number="PO-002",
                warehouse_code="WH-01",
                notes="",
                created_by=uuid4(),
                created_at=datetime.utcnow(),
            ),
            uuid4(),
        )
        # Weighted average = (1,000,000 + 550,000) / 150 = 10,333.33
        expected_avg = Decimal("10333.33")
        assert aggregate.item.average_cost == expected_avg

    def test_update_reorder_point(self, valid_item):
        """Test: Mengupdate reorder point."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.set_reorder_point(Decimal("20"), uuid4())
        assert aggregate.item.reorder_point == Decimal("20")
        events = aggregate.get_events()
        assert isinstance(events[-1], ItemUpdated)

    def test_deactivate_item_with_zero_stock(self, valid_item):
        """Test: Deaktivasi item yang stocknya nol berhasil."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.deactivate(reason="Tidak dijual lagi", user_id=uuid4())
        assert aggregate.item.status == ItemStatus.INACTIVE
        events = aggregate.get_events()
        assert isinstance(events[-1], ItemDeactivated)

    def test_cannot_deactivate_item_with_stock(self, valid_item, inbound_movement):
        """Test: Tidak bisa deaktivasi item yang masih ada stock."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.receive_stock(inbound_movement, uuid4())
        with pytest.raises(ValueError, match="Cannot deactivate item with current stock"):
            aggregate.deactivate("Alasan", uuid4())

    def test_version_increment(self, valid_item):
        """Test: Version increment pada setiap perubahan."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        assert aggregate.version == 1
        aggregate.rename("Nama Baru", uuid4())
        assert aggregate.version == 2
        aggregate.update_description("Deskripsi baru", uuid4())
        assert aggregate.version == 3

    def test_reconstruct_from_events(self, valid_item, inbound_movement):
        """Test: Rekonstruksi aggregate dari event stream."""
        aggregate = InventoryAggregate.create(valid_item, user_id=uuid4())
        aggregate.receive_stock(inbound_movement, uuid4())
        events = aggregate.get_events()
        new_agg = InventoryAggregate.reconstruct(events)
        assert new_agg.item.id == aggregate.item.id
        assert new_agg.item.current_stock == Decimal("100")
        assert new_agg.version == aggregate.version
        assert new_agg.get_events() == []


if __name__ == "__main__":
    pytest.main([__file__])
