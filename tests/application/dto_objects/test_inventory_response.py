# tests/application/dto_objects/test_inventory_response.py
"""
Comprehensive unit tests for application/dto_objects/inventory_response.py.

Covers:
- All DTO constructors with valid data and post-init timezone handling
- ItemResponseDTO: is_low_stock, is_out_of_stock, get_stock_value
- StockMovementResponseDTO: is_inbound, is_outbound
- StockCardResponseDTO: net_movement
- ValuationReportDTO: average_value_per_unit
- StockOpnameResponseDTO: needs_approval, is_overage, is_shortage
- TransferResponseDTO: is_completed, is_pending
- InventorySummaryDTO: stock_coverage_days
- to_dict methods for all DTOs
- Edge cases: zero/negative values, None, empty lists
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest

from application.dto_objects.inventory_response import (
    InventorySummaryDTO,
    ItemResponseDTO,
    StockCardResponseDTO,
    StockMovementResponseDTO,
    StockOpnameResponseDTO,
    TransferResponseDTO,
    ValuationReportDTO,
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
def item_id() -> UUID:
    return uuid4()


@pytest.fixture
def item_dto_kwargs(legal_entity_id, user_id, item_id) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": item_id,
        "sku": "SKU-001",
        "name": "Test Item",
        "description": "A test item",
        "item_type": "FINISHED_GOODS",
        "uom": "PCS",
        "current_stock": Decimal("100.00"),
        "current_stock_value": Decimal("5000.00"),
        "average_cost": Decimal("50.00"),
        "last_cost": Decimal("50.00"),
        "reorder_point": Decimal("20.00"),
        "safety_stock": Decimal("10.00"),
        "standard_cost": Decimal("50.00"),
        "selling_price": Decimal("100.00"),
        "category": "Electronics",
        "warehouse_code": "WH-01",
        "status": "ACTIVE",
        "created_at": now,
        "created_by": user_id,
        "updated_at": now,
        "updated_by": user_id,
        "version": 1,
    }


@pytest.fixture
def movement_dto_kwargs(legal_entity_id, user_id, item_id) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "item_id": item_id,
        "sku": "SKU-001",
        "movement_type": "PURCHASE",
        "quantity": Decimal("50.00"),
        "unit_cost": Decimal("60.00"),
        "total_value": Decimal("3000.00"),
        "movement_date": date(2026, 1, 15),
        "reference_document_type": "purchase_order",
        "reference_document_number": "PO-001",
        "warehouse_code": "WH-01",
        "notes": "Test movement",
        "created_at": datetime.now(UTC),
        "created_by": user_id,
    }


@pytest.fixture
def stock_card_dto_kwargs() -> dict[str, Any]:
    return {
        "date": date(2026, 1, 15),
        "movement_type": "PURCHASE",
        "quantity_in": Decimal("50.00"),
        "quantity_out": Decimal("0.00"),
        "unit_cost": Decimal("60.00"),
        "total_value": Decimal("3000.00"),
        "reference": "PO-001",
        "warehouse": "WH-01",
        "running_balance": Decimal("150.00"),
        "running_value": Decimal("8000.00"),
    }


@pytest.fixture
def valuation_dto_kwargs(legal_entity_id) -> dict[str, Any]:
    return {
        "legal_entity_id": legal_entity_id,
        "as_of_date": date(2026, 1, 15),
        "total_value": Decimal("100000.00"),
        "total_quantity": Decimal("2000.00"),
        "items": [{"sku": "SKU-001", "value": Decimal("5000.00")}],
        "valuation_method": "FIFO",
        "currency": "IDR",
    }


@pytest.fixture
def opname_dto_kwargs(user_id) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": uuid4(),
        "item_id": uuid4(),
        "item_name": "Test Item",
        "sku": "SKU-001",
        "opname_date": date(2026, 1, 15),
        "system_quantity": Decimal("100.00"),
        "physical_quantity": Decimal("110.00"),
        "discrepancy": Decimal("10.00"),
        "discrepancy_value": Decimal("500.00"),
        "notes": "Test opname",
        "counted_by": user_id,
        "counted_by_name": "John Counter",
        "counted_at": now,
        "approved_at": None,
        "status": "PENDING",
        "approved_by": None,
        "approved_by_name": None,
        "adjustment_journal_id": None,
    }


@pytest.fixture
def transfer_dto_kwargs(user_id) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "id": uuid4(),
        "item_id": uuid4(),
        "item_name": "Test Item",
        "sku": "SKU-001",
        "from_warehouse": "WH-01",
        "to_warehouse": "WH-02",
        "quantity": Decimal("20.00"),
        "unit_cost": Decimal("50.00"),
        "total_value": Decimal("1000.00"),
        "transfer_date": date(2026, 1, 15),
        "notes": "Test transfer",
        "requested_by": user_id,
        "requested_by_name": "Requester",
        "requested_at": now,
        "completed_by": None,
        "completed_by_name": None,
        "completed_at": None,
        "status": "PENDING",
        "transfer_journal_id": None,
    }


@pytest.fixture
def summary_dto_kwargs(legal_entity_id) -> dict[str, Any]:
    return {
        "legal_entity_id": legal_entity_id,
        "total_items": 10,
        "active_items": 8,
        "total_stock_quantity": Decimal("500.00"),
        "total_stock_value": Decimal("25000.00"),
        "items_below_reorder": 2,
        "items_out_of_stock": 1,
        "as_of_date": date(2026, 1, 15),
        "warehouses": [{"code": "WH-01", "count": 5}],
    }


# -----------------------------------------------------------------------------
# Tests for ItemResponseDTO
# -----------------------------------------------------------------------------

class TestItemResponseDTO:
    def test_construction(self, item_dto_kwargs):
        dto = ItemResponseDTO(**item_dto_kwargs)
        assert dto.id == item_dto_kwargs["id"]
        assert dto.current_stock == Decimal("100.00")
        assert dto.created_at.tzinfo == UTC

    def test_to_dict(self, item_dto_kwargs):
        dto = ItemResponseDTO(**item_dto_kwargs)
        d = dto.to_dict()
        assert d["id"] == str(dto.id)
        assert d["sku"] == dto.sku
        assert d["current_stock"] == float(dto.current_stock)
        assert "created_at" in d

    def test_is_low_stock(self, item_dto_kwargs):
        dto = ItemResponseDTO(**item_dto_kwargs)
        # current_stock=100, reorder_point=20 -> not low
        assert dto.is_low_stock() is False

        # Set current_stock <= reorder_point
        item_dto_kwargs["current_stock"] = Decimal("20")
        dto2 = ItemResponseDTO(**item_dto_kwargs)
        assert dto2.is_low_stock() is True

        # Zero stock
        item_dto_kwargs["current_stock"] = Decimal("0")
        dto3 = ItemResponseDTO(**item_dto_kwargs)
        assert dto3.is_low_stock() is True

    def test_is_out_of_stock(self, item_dto_kwargs):
        dto = ItemResponseDTO(**item_dto_kwargs)
        assert dto.is_out_of_stock() is False

        item_dto_kwargs["current_stock"] = Decimal("0")
        dto2 = ItemResponseDTO(**item_dto_kwargs)
        assert dto2.is_out_of_stock() is True

        item_dto_kwargs["current_stock"] = Decimal("-5")
        dto3 = ItemResponseDTO(**item_dto_kwargs)
        assert dto3.is_out_of_stock() is True  # negative is considered out of stock

    def test_get_stock_value(self, item_dto_kwargs):
        dto = ItemResponseDTO(**item_dto_kwargs)
        # current_stock * average_cost = 100 * 50 = 5000
        assert dto.get_stock_value() == Decimal("5000.00")

        # If average_cost is zero
        item_dto_kwargs["average_cost"] = Decimal("0")
        dto2 = ItemResponseDTO(**item_dto_kwargs)
        assert dto2.get_stock_value() == Decimal("0")

        # If stock is zero
        item_dto_kwargs["current_stock"] = Decimal("0")
        dto3 = ItemResponseDTO(**item_dto_kwargs)
        assert dto3.get_stock_value() == Decimal("0")

    def test_post_init_timezone(self, item_dto_kwargs):
        # Provide naive datetime
        item_dto_kwargs["created_at"] = datetime(2026, 1, 15, 10, 0, 0)  # naive
        dto = ItemResponseDTO(**item_dto_kwargs)
        assert dto.created_at.tzinfo == UTC
        assert dto.created_at == datetime(2026, 1, 15, 10, 0, 0, tzinfo=UTC)


# -----------------------------------------------------------------------------
# Tests for StockMovementResponseDTO
# -----------------------------------------------------------------------------

class TestStockMovementResponseDTO:
    def test_construction(self, movement_dto_kwargs):
        dto = StockMovementResponseDTO(**movement_dto_kwargs)
        assert dto.id is not None
        assert dto.created_at.tzinfo == UTC

    def test_to_dict(self, movement_dto_kwargs):
        dto = StockMovementResponseDTO(**movement_dto_kwargs)
        d = dto.to_dict()
        assert d["id"] == str(dto.id)
        assert d["movement_type"] == dto.movement_type
        assert d["quantity"] == float(dto.quantity)

    def test_is_inbound(self, movement_dto_kwargs):
        dto = StockMovementResponseDTO(**movement_dto_kwargs)
        # movement_type = PURCHASE -> inbound
        assert dto.is_inbound() is True
        assert dto.is_outbound() is False

        # Outbound types
        for mt in ("SALES", "TRANSFER_OUT", "ADJUSTMENT_OUT"):
            movement_dto_kwargs["movement_type"] = mt
            dto2 = StockMovementResponseDTO(**movement_dto_kwargs)
            assert dto2.is_inbound() is False
            assert dto2.is_outbound() is True

        # Inbound types
        for mt in ("PURCHASE", "RETURN", "ADJUSTMENT_IN"):
            movement_dto_kwargs["movement_type"] = mt
            dto3 = StockMovementResponseDTO(**movement_dto_kwargs)
            assert dto3.is_inbound() is True
            assert dto3.is_outbound() is False

        # Unknown type
        movement_dto_kwargs["movement_type"] = "UNKNOWN"
        dto4 = StockMovementResponseDTO(**movement_dto_kwargs)
        assert dto4.is_inbound() is False
        assert dto4.is_outbound() is False


# -----------------------------------------------------------------------------
# Tests for StockCardResponseDTO
# -----------------------------------------------------------------------------

class TestStockCardResponseDTO:
    def test_construction(self, stock_card_dto_kwargs):
        dto = StockCardResponseDTO(**stock_card_dto_kwargs)
        assert dto.date == date(2026, 1, 15)
        assert dto.running_balance == Decimal("150.00")

    def test_to_dict(self, stock_card_dto_kwargs):
        dto = StockCardResponseDTO(**stock_card_dto_kwargs)
        d = dto.to_dict()
        assert d["date"] == dto.date.isoformat()
        assert d["quantity_in"] == float(dto.quantity_in)
        assert d["running_balance"] == float(dto.running_balance)

    def test_net_movement(self, stock_card_dto_kwargs):
        dto = StockCardResponseDTO(**stock_card_dto_kwargs)
        # quantity_in - quantity_out = 50 - 0 = 50
        assert dto.net_movement() == Decimal("50.00")

        stock_card_dto_kwargs["quantity_in"] = Decimal("30")
        stock_card_dto_kwargs["quantity_out"] = Decimal("10")
        dto2 = StockCardResponseDTO(**stock_card_dto_kwargs)
        assert dto2.net_movement() == Decimal("20.00")


# -----------------------------------------------------------------------------
# Tests for ValuationReportDTO
# -----------------------------------------------------------------------------

class TestValuationReportDTO:
    def test_construction(self, valuation_dto_kwargs):
        dto = ValuationReportDTO(**valuation_dto_kwargs)
        assert dto.legal_entity_id is not None
        assert dto.total_value == Decimal("100000.00")

    def test_to_dict(self, valuation_dto_kwargs):
        dto = ValuationReportDTO(**valuation_dto_kwargs)
        d = dto.to_dict()
        assert d["legal_entity_id"] == str(dto.legal_entity_id)
        assert d["total_value"] == float(dto.total_value)
        assert d["items"] == dto.items

    def test_average_value_per_unit(self, valuation_dto_kwargs):
        dto = ValuationReportDTO(**valuation_dto_kwargs)
        # total_value / total_quantity = 100000 / 2000 = 50
        assert dto.average_value_per_unit() == Decimal("50.00")

        # Zero quantity
        valuation_dto_kwargs["total_quantity"] = Decimal("0")
        dto2 = ValuationReportDTO(**valuation_dto_kwargs)
        assert dto2.average_value_per_unit() == Decimal("0")

        # Negative quantity (should return 0)
        valuation_dto_kwargs["total_quantity"] = Decimal("-100")
        dto3 = ValuationReportDTO(**valuation_dto_kwargs)
        assert dto3.average_value_per_unit() == Decimal("0")  # because total_quantity <= 0


# -----------------------------------------------------------------------------
# Tests for StockOpnameResponseDTO
# -----------------------------------------------------------------------------

class TestStockOpnameResponseDTO:
    def test_construction(self, opname_dto_kwargs):
        dto = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto.id is not None
        assert dto.counted_at.tzinfo == UTC
        assert dto.approved_at is None

    def test_to_dict(self, opname_dto_kwargs):
        dto = StockOpnameResponseDTO(**opname_dto_kwargs)
        d = dto.to_dict()
        assert d["id"] == str(dto.id)
        assert d["sku"] == dto.sku
        assert d["discrepancy"] == float(dto.discrepancy)

    def test_needs_approval(self, opname_dto_kwargs):
        dto = StockOpnameResponseDTO(**opname_dto_kwargs)
        # discrepancy=10 -> needs approval
        assert dto.needs_approval() is True

        opname_dto_kwargs["discrepancy"] = Decimal("0")
        dto2 = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto2.needs_approval() is False

        opname_dto_kwargs["discrepancy"] = Decimal("-5")
        dto3 = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto3.needs_approval() is True  # absolute value > 0

    def test_is_overage(self, opname_dto_kwargs):
        # physical > system -> overage
        dto = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto.is_overage() is True
        assert dto.is_shortage() is False

        # physical < system -> shortage
        opname_dto_kwargs["physical_quantity"] = Decimal("90")
        dto2 = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto2.is_overage() is False
        assert dto2.is_shortage() is True

        # equal
        opname_dto_kwargs["physical_quantity"] = Decimal("100")
        dto3 = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto3.is_overage() is False
        assert dto3.is_shortage() is False

    def test_post_init_timezone(self, opname_dto_kwargs):
        # Provide naive counted_at
        opname_dto_kwargs["counted_at"] = datetime(2026, 1, 15, 10, 0, 0)  # naive
        dto = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto.counted_at.tzinfo == UTC

        # Provide naive approved_at
        opname_dto_kwargs["approved_at"] = datetime(2026, 1, 16, 12, 0, 0)  # naive
        dto2 = StockOpnameResponseDTO(**opname_dto_kwargs)
        assert dto2.approved_at.tzinfo == UTC


# -----------------------------------------------------------------------------
# Tests for TransferResponseDTO
# -----------------------------------------------------------------------------

class TestTransferResponseDTO:
    def test_construction(self, transfer_dto_kwargs):
        dto = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto.id is not None
        assert dto.requested_at.tzinfo == UTC
        assert dto.completed_at is None

    def test_to_dict(self, transfer_dto_kwargs):
        dto = TransferResponseDTO(**transfer_dto_kwargs)
        d = dto.to_dict()
        assert d["id"] == str(dto.id)
        assert d["from_warehouse"] == dto.from_warehouse
        assert d["quantity"] == float(dto.quantity)

    def test_is_completed(self, transfer_dto_kwargs):
        dto = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto.is_completed() is False  # status PENDING

        transfer_dto_kwargs["status"] = "COMPLETED"
        dto2 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto2.is_completed() is True

        transfer_dto_kwargs["status"] = "CANCELLED"
        dto3 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto3.is_completed() is False

    def test_is_pending(self, transfer_dto_kwargs):
        dto = TransferResponseDTO(**transfer_dto_kwargs)
        # status PENDING -> True
        assert dto.is_pending() is True

        transfer_dto_kwargs["status"] = "APPROVED"
        dto2 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto2.is_pending() is True

        transfer_dto_kwargs["status"] = "COMPLETED"
        dto3 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto3.is_pending() is False

        transfer_dto_kwargs["status"] = "REJECTED"
        dto4 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto4.is_pending() is False

    def test_post_init_timezone(self, transfer_dto_kwargs):
        transfer_dto_kwargs["requested_at"] = datetime(2026, 1, 15, 10, 0, 0)  # naive
        dto = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto.requested_at.tzinfo == UTC

        transfer_dto_kwargs["completed_at"] = datetime(2026, 1, 16, 12, 0, 0)  # naive
        dto2 = TransferResponseDTO(**transfer_dto_kwargs)
        assert dto2.completed_at.tzinfo == UTC


# -----------------------------------------------------------------------------
# Tests for InventorySummaryDTO
# -----------------------------------------------------------------------------

class TestInventorySummaryDTO:
    def test_construction(self, summary_dto_kwargs):
        dto = InventorySummaryDTO(**summary_dto_kwargs)
        assert dto.legal_entity_id is not None
        assert dto.total_items == 10
        assert dto.as_of_date == date(2026, 1, 15)

    def test_to_dict(self, summary_dto_kwargs):
        dto = InventorySummaryDTO(**summary_dto_kwargs)
        d = dto.to_dict()
        assert d["legal_entity_id"] == str(dto.legal_entity_id)
        assert d["total_items"] == dto.total_items
        assert d["total_stock_quantity"] == float(dto.total_stock_quantity)

    def test_stock_coverage_days(self, summary_dto_kwargs):
        dto = InventorySummaryDTO(**summary_dto_kwargs)
        # total_stock_quantity = 500, daily_consumption = 50 -> 10 days
        assert dto.stock_coverage_days(Decimal("50")) == Decimal("10.00")

        # Zero daily consumption -> returns 0
        assert dto.stock_coverage_days(Decimal("0")) == Decimal("0")

        # Negative daily consumption (should return 0)
        assert dto.stock_coverage_days(Decimal("-10")) == Decimal("0")

        # Zero stock
        summary_dto_kwargs["total_stock_quantity"] = Decimal("0")
        dto2 = InventorySummaryDTO(**summary_dto_kwargs)
        assert dto2.stock_coverage_days(Decimal("10")) == Decimal("0")