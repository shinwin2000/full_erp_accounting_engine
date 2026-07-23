#!/usr/bin/env python3
"""
Comprehensive tests for policy_engine/psak/psak_14_inventories.py

Covers:
- All enums and exceptions
- All data classes (PSAK14InventoryItem, PSAK14FIFOLayer, PSAK14InventoryTransaction,
  PSAK14Inventory, PSAK14ValidationResult)
- Domain services (PSAK14InventoryService)
- Rules (PSAK14Rules)
- Validator (PSAK14Validator) - all operations
- PSAK14 static methods
- Singleton accessor
- All edge cases and negative paths
- No flaky tests (datetime mocked)
- No duplicate tests (parametrized where appropriate)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from policy_engine.psak.psak_14_inventories import (
    PSAK14,
    InsufficientInventoryError,
    InvalidCostFormulaError,
    PSAK14ComplianceLevel,
    PSAK14CostFormula,
    PSAK14Error,
    PSAK14FIFOLayer,
    PSAK14Inventory,
    PSAK14InventoryItem,
    PSAK14InventoryService,
    PSAK14InventoryTransaction,
    PSAK14MovementType,
    PSAK14Rules,
    PSAK14ValidationResult,
    PSAK14ValuationMethod,
    PSAK14Validator,
    get_psak14_validator,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_now():
    """Fixed datetime for deterministic tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now(fixed_now):
    """Mock datetime.now and datetime.utcnow to return fixed_now."""
    with patch("policy_engine.psak.psak_14_inventories.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def validator():
    """Return a fresh PSAK14Validator instance."""
    return PSAK14Validator()


@pytest.fixture
def fifo_item(validator):
    """Create a FIFO inventory item with initial quantity."""
    return validator.create_item(
        item_code="FIFO-001",
        description="FIFO Item",
        unit_of_measure="pcs",
        cost_formula=PSAK14CostFormula.FIFO,
        opening_quantity=Decimal("0"),
        opening_cost=Decimal("0"),
    )


@pytest.fixture
def weighted_avg_item(validator):
    """Create a weighted average inventory item."""
    return validator.create_item(
        item_code="WAVG-001",
        description="Weighted Average Item",
        unit_of_measure="kg",
        cost_formula=PSAK14CostFormula.WEIGHTED_AVERAGE,
        opening_quantity=Decimal("0"),
        opening_cost=Decimal("0"),
    )


@pytest.fixture
def inventory_with_items(validator, fifo_item, weighted_avg_item, fixed_now):
    """Create an inventory with two items."""
    inventory = validator.create_inventory(
        entity_id=uuid4(),
        entity_name="PT Test Inventory",
        reporting_date=fixed_now,
    )
    inventory = validator.add_item(inventory, fifo_item)
    inventory = validator.add_item(inventory, weighted_avg_item)
    return inventory


@pytest.fixture
def fifo_item_with_purchases(validator, inventory_with_items, fixed_now):
    """Return inventory with FIFO item that has multiple purchase layers."""
    inv = inventory_with_items
    fifo_id = inv.items[0].item_id
    # Purchase 100 at 50,000
    inv = validator.record_purchase(
        inv, fifo_id, Decimal("100"), Decimal("50000"),
        fixed_now - timedelta(days=200), "PO-001"
    )
    # Purchase 50 at 52,000
    inv = validator.record_purchase(
        inv, fifo_id, Decimal("50"), Decimal("52000"),
        fixed_now - timedelta(days=100), "PO-002"
    )
    return inv, fifo_id


@pytest.fixture
def weighted_item_with_purchases(validator, inventory_with_items, weighted_avg_item, fixed_now):
    """Return inventory with weighted average item that has purchases."""
    inv = inventory_with_items
    item_id = weighted_avg_item.item_id
    inv = validator.record_purchase(
        inv, item_id, Decimal("1000"), Decimal("10000"),
        fixed_now - timedelta(days=90), "PO-003"
    )
    inv = validator.record_purchase(
        inv, item_id, Decimal("500"), Decimal("10500"),
        fixed_now - timedelta(days=30), "PO-004"
    )
    return inv, item_id


# =============================================================================
# Enums and Exceptions
# =============================================================================

class TestEnums:
    @pytest.mark.parametrize("enum_cls,members", [
        (PSAK14CostFormula, ["FIFO", "WEIGHTED_AVERAGE", "SPECIFIC_IDENTIFICATION"]),
        (PSAK14ValuationMethod, ["LOWER_OF_COST_OR_NRV", "COST", "NRV"]),
        (PSAK14MovementType, ["PURCHASE", "SALE", "RETURN", "ADJUSTMENT", "TRANSFER"]),
        (PSAK14ComplianceLevel, ["FULL", "SUBSTANTIAL", "PARTIAL", "NON_COMPLIANT"]),
    ])
    def test_members_exist(self, enum_cls, members):
        for member in members:
            assert hasattr(enum_cls, member)
        instance = getattr(enum_cls, members[0])
        assert isinstance(instance, enum_cls)


class TestExceptions:
    @pytest.mark.parametrize("exc_class,msg", [
        (PSAK14Error, "test error"),
        (InsufficientInventoryError, "stock shortage"),
        (InvalidCostFormulaError, "invalid formula"),
    ])
    def test_exception_construction(self, exc_class, msg):
        exc = exc_class(msg)
        assert isinstance(exc, Exception)
        assert str(exc) == msg


# =============================================================================
# Data Classes
# =============================================================================

class TestPSAK14InventoryItem:
    def test_unit_cost(self):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
        )
        assert item.unit_cost == Decimal("5000")
        # zero quantity
        item.quantity_on_hand = Decimal("0")
        assert item.unit_cost == Decimal("0")

    def test_carrying_amount(self):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
            nrv_per_unit=Decimal("6000"),
            valuation_basis=PSAK14ValuationMethod.LOWER_OF_COST_OR_NRV,
        )
        # cost=5000/unit, NRV=6000/unit -> carrying=50000
        assert item.carrying_amount == Decimal("50000")
        # NRV lower: 4000/unit -> total NRV=40000, write-down=10000, carrying=40000
        item.nrv_per_unit = Decimal("4000")
        assert item.carrying_amount == Decimal("40000")
        # NRV basis
        item.valuation_basis = PSAK14ValuationMethod.NRV
        assert item.carrying_amount == Decimal("40000")
        # Cost basis
        item.valuation_basis = PSAK14ValuationMethod.COST
        assert item.carrying_amount == Decimal("50000")

    def test_effective_unit_value(self):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
            nrv_per_unit=Decimal("4000"),
        )
        # carrying = 40000, quantity=10 -> effective=4000
        assert item.effective_unit_value == Decimal("4000")
        item.quantity_on_hand = Decimal("0")
        assert item.effective_unit_value == Decimal("0")

    def test_to_dict(self):
        item_id = uuid4()
        item = PSAK14InventoryItem(
            item_id=item_id,
            item_code="TEST",
            description="Test Desc",
            unit_of_measure="box",
            cost_formula=PSAK14CostFormula.WEIGHTED_AVERAGE,
            quantity_on_hand=Decimal("5"),
            total_cost=Decimal("25000"),
            nrv_per_unit=Decimal("6000"),
            write_down_allowance=Decimal("0"),
            valuation_basis=PSAK14ValuationMethod.COST,
        )
        d = item.to_dict()
        assert d["item_code"] == "TEST"
        assert d["description"] == "Test Desc"
        assert d["cost_formula"] == "rata_rata_tertimbang"
        assert d["carrying_amount"] == "25000"


class TestPSAK14FIFOLayer:
    def test_remaining_value(self, fixed_now):
        layer = PSAK14FIFOLayer(
            purchase_date=fixed_now,
            quantity=Decimal("100"),
            unit_cost=Decimal("5000"),
            remaining_quantity=Decimal("80"),
        )
        assert layer.remaining_value == Decimal("400000")

    def test_to_dict(self, fixed_now):
        layer = PSAK14FIFOLayer(
            purchase_date=fixed_now,
            quantity=Decimal("100"),
            unit_cost=Decimal("5000"),
            remaining_quantity=Decimal("80"),
        )
        d = layer.to_dict()
        assert d["purchase_date"] == fixed_now.isoformat()
        assert d["quantity"] == "100"
        assert d["unit_cost"] == "5000"
        assert d["remaining_quantity"] == "80"
        assert d["remaining_value"] == "400000"


class TestPSAK14InventoryTransaction:
    def test_to_dict(self, fixed_now):
        tid = uuid4()
        iid = uuid4()
        trans = PSAK14InventoryTransaction(
            transaction_id=tid,
            item_id=iid,
            movement_type=PSAK14MovementType.PURCHASE,
            quantity=Decimal("10"),
            unit_cost=Decimal("5000"),
            total_value=Decimal("50000"),
            transaction_date=fixed_now,
            reference_document="PO-123",
            notes="Test note",
        )
        d = trans.to_dict()
        assert d["transaction_id"] == str(tid)
        assert d["item_id"] == str(iid)
        assert d["movement_type"] == "pembelian"
        assert d["quantity"] == "10"
        assert d["unit_cost"] == "5000"
        assert d["total_value"] == "50000"
        assert d["transaction_date"] == fixed_now.isoformat()
        assert d["reference"] == "PO-123"


class TestPSAK14Inventory:
    def test_total_inventory_value(self, fixed_now):
        item1 = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="A",
            description="A",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
            nrv_per_unit=Decimal("6000"),
        )
        item2 = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="B",
            description="B",
            unit_of_measure="kg",
            cost_formula=PSAK14CostFormula.WEIGHTED_AVERAGE,
            quantity_on_hand=Decimal("5"),
            total_cost=Decimal("25000"),
            nrv_per_unit=Decimal("4000"),
        )
        inv = PSAK14Inventory(
            inventory_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_date=fixed_now,
            items=[item1, item2],
        )
        # item1 carrying=50000 (cost < NRV), item2 carrying=20000 (NRV lower)
        assert inv.total_inventory_value() == Decimal("70000")

    def test_total_write_down(self, fixed_now):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
            nrv_per_unit=Decimal("4000"),
            write_down_allowance=Decimal("10000"),
        )
        inv = PSAK14Inventory(
            inventory_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_date=fixed_now,
            items=[item],
        )
        assert inv.total_write_down() == Decimal("10000")

    def test_to_dict(self, inventory_with_items):
        d = inventory_with_items.to_dict()
        assert d["entity_name"] == "PT Test Inventory"
        assert "items" in d
        assert len(d["items"]) == 2
        assert "total_inventory_value" in d
        assert "total_write_down" in d


class TestPSAK14ValidationResult:
    def test_initial_state(self):
        result = PSAK14ValidationResult(
            is_compliant=True,
            compliance_level=PSAK14ComplianceLevel.FULL
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK14ValidationResult(
            is_compliant=True,
            compliance_level=PSAK14ComplianceLevel.FULL
        )
        result.add_error("Invalid cost")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK14ComplianceLevel.NON_COMPLIANT
        assert "Invalid cost" in result.errors

    def test_add_warning(self):
        result = PSAK14ValidationResult(
            is_compliant=True,
            compliance_level=PSAK14ComplianceLevel.FULL
        )
        result.add_warning("Potential issue")
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "Potential issue" in result.warnings

    def test_add_warning_already_substantial(self):
        result = PSAK14ValidationResult(
            is_compliant=True,
            compliance_level=PSAK14ComplianceLevel.SUBSTANTIAL
        )
        result.add_warning("Another warning")
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL

    def test_to_dict(self):
        result = PSAK14ValidationResult(
            is_compliant=False,
            compliance_level=PSAK14ComplianceLevel.NON_COMPLIANT,
            errors=["Error1"],
            warnings=["Warning1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["Error1"]
        assert d["warnings"] == ["Warning1"]
        assert "hash" in d


# =============================================================================
# Domain Services
# =============================================================================

class TestPSAK14InventoryService:
    @pytest.mark.parametrize("current_cost,current_qty,new_cost,new_qty,expected", [
        (Decimal("100000"), Decimal("20"), Decimal("60000"), Decimal("10"), Decimal("5333.33")),
        (Decimal("0"), Decimal("0"), Decimal("50000"), Decimal("10"), Decimal("5000.00")),
        (Decimal("100000"), Decimal("20"), Decimal("0"), Decimal("0"), Decimal("0")),
    ])
    def test_calculate_weighted_average_cost(self, current_cost, current_qty, new_cost, new_qty, expected):
        result = PSAK14InventoryService.calculate_weighted_average_cost(
            current_cost, current_qty, new_cost, new_qty
        )
        assert result == expected

    def test_calculate_fifo_cogs(self):
        layers = [
            PSAK14FIFOLayer(
                purchase_date=datetime(2026, 1, 1, tzinfo=UTC),
                quantity=Decimal("100"),
                unit_cost=Decimal("5000"),
                remaining_quantity=Decimal("100"),
            ),
            PSAK14FIFOLayer(
                purchase_date=datetime(2026, 2, 1, tzinfo=UTC),
                quantity=Decimal("50"),
                unit_cost=Decimal("5200"),
                remaining_quantity=Decimal("50"),
            ),
        ]
        # Sell 80 -> 80*5000 = 400000, remaining first layer 20
        cogs, new_layers = PSAK14InventoryService.calculate_fifo_cogs(layers, Decimal("80"))
        assert cogs == Decimal("400000")
        assert len(new_layers) == 1
        assert new_layers[0].remaining_quantity == Decimal("20")
        assert new_layers[0].unit_cost == Decimal("5000")

        # Sell 120 -> 100*5000 + 20*5200 = 604000, remaining second layer 30
        cogs, new_layers = PSAK14InventoryService.calculate_fifo_cogs(layers, Decimal("120"))
        assert cogs == Decimal("604000")
        assert len(new_layers) == 1
        assert new_layers[0].remaining_quantity == Decimal("30")
        assert new_layers[0].unit_cost == Decimal("5200")

        # Sell exactly 150 -> 100*5000 + 50*5200 = 760000, no layers left
        cogs, new_layers = PSAK14InventoryService.calculate_fifo_cogs(layers, Decimal("150"))
        assert cogs == Decimal("760000")
        assert new_layers == []

        # Insufficient
        with pytest.raises(InsufficientInventoryError, match="Insufficient inventory"):
            PSAK14InventoryService.calculate_fifo_cogs(layers, Decimal("200"))

    def test_calculate_nrv(self):
        nrv = PSAK14InventoryService.calculate_nrv(
            estimated_selling_price=Decimal("60000"),
            estimated_costs_to_complete=Decimal("5000"),
            estimated_costs_to_sell=Decimal("2000"),
        )
        assert nrv == Decimal("53000")


# =============================================================================
# Rules
# =============================================================================

class TestPSAK14Rules:
    def test_validate_cost_formula(self):
        # FIFO full compliant
        result = PSAK14Rules.validate_cost_formula(PSAK14CostFormula.FIFO)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.FULL
        # Weighted average full compliant
        result = PSAK14Rules.validate_cost_formula(PSAK14CostFormula.WEIGHTED_AVERAGE)
        assert result.is_compliant is True
        # Specific identification warning
        result = PSAK14Rules.validate_cost_formula(PSAK14CostFormula.SPECIFIC_IDENTIFICATION)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "Metode identifikasi khusus" in result.warnings[0]

    def test_validate_nrv(self):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("10"),
            total_cost=Decimal("50000"),
            nrv_per_unit=Decimal("6000"),
            write_down_allowance=Decimal("0"),
        )
        # NRV > cost -> no warning
        result = PSAK14Rules.validate_nrv(item)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.FULL

        # NRV < cost but no allowance -> warning
        item.nrv_per_unit = Decimal("4000")
        result = PSAK14Rules.validate_nrv(item)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "NRV lebih rendah dari biaya" in result.warnings[0]

        # NRV negative -> error
        item.nrv_per_unit = Decimal("-1000")
        result = PSAK14Rules.validate_nrv(item)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK14ComplianceLevel.NON_COMPLIANT
        assert "NRV per unit negatif" in result.errors[0]

    def test_validate_consistency(self, fixed_now):
        # Single formula -> FULL
        item1 = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="A",
            description="A",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
        )
        item2 = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="B",
            description="B",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
        )
        inv = PSAK14Inventory(
            inventory_id=uuid4(),
            entity_id=uuid4(),
            entity_name="Test",
            reporting_date=fixed_now,
            items=[item1, item2],
        )
        result = PSAK14Rules.validate_consistency(inv)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.FULL
        assert result.warnings == []

        # Multiple formulas -> warning
        item2.cost_formula = PSAK14CostFormula.WEIGHTED_AVERAGE
        result = PSAK14Rules.validate_consistency(inv)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "Beberapa item menggunakan formula biaya yang berbeda" in result.warnings[0]


# =============================================================================
# Validator - Basic Operations
# =============================================================================

class TestPSAK14Validator:
    def test_create_item(self, validator):
        item = validator.create_item(
            item_code="ITEM-001",
            description="New Item",
            unit_of_measure="unit",
            cost_formula=PSAK14CostFormula.FIFO,
            opening_quantity=Decimal("50"),
            opening_cost=Decimal("250000"),
        )
        assert item.item_code == "ITEM-001"
        assert item.quantity_on_hand == Decimal("50")
        assert item.total_cost == Decimal("250000")
        assert item.unit_cost == Decimal("5000")
        assert item.weighted_average_cost == Decimal("5000")

    def test_create_inventory(self, validator, fixed_now):
        entity_id = uuid4()
        inventory = validator.create_inventory(
            entity_id=entity_id,
            entity_name="PT ABC",
            reporting_date=fixed_now,
        )
        assert inventory.entity_id == entity_id
        assert inventory.entity_name == "PT ABC"
        assert inventory.reporting_date == fixed_now

    def test_add_item(self, validator, fixed_now):
        inv = validator.create_inventory(uuid4(), "Test", fixed_now)
        item = validator.create_item("CODE", "Desc", "unit")
        new_inv = validator.add_item(inv, item)
        assert len(new_inv.items) == 1
        assert new_inv.items[0].item_code == "CODE"

    # ---- Record Purchase ----
    def test_record_purchase_fifo(self, fifo_item_with_purchases):
        inv, fifo_id = fifo_item_with_purchases
        item = next(i for i in inv.items if i.item_id == fifo_id)
        # After 2 purchases: 100 at 50k + 50 at 52k = 150 total, cost = 7,600,000
        assert item.quantity_on_hand == Decimal("150")
        assert item.total_cost == Decimal("7600000")
        # FIFO layers
        layers = inv.fifo_layers[fifo_id]
        assert len(layers) == 2
        assert layers[0].quantity == Decimal("100")
        assert layers[0].unit_cost == Decimal("50000")
        assert layers[1].quantity == Decimal("50")
        assert layers[1].unit_cost == Decimal("52000")

    def test_record_purchase_weighted_average(self, weighted_item_with_purchases):
        inv, item_id = weighted_item_with_purchases
        item = next(i for i in inv.items if i.item_id == item_id)
        # Total quantity = 1500, total cost = 15,250,000, weighted avg = 10,166.67
        assert item.quantity_on_hand == Decimal("1500")
        assert item.total_cost == Decimal("15250000")
        assert item.weighted_average_cost == Decimal("10166.67")

    def test_record_purchase_item_not_found_raises(self, validator, inventory_with_items, fixed_now):
        with pytest.raises(PSAK14Error, match="not found"):
            validator.record_purchase(
                inventory_with_items,
                uuid4(),
                Decimal("10"),
                Decimal("1000"),
                fixed_now,
            )

    # ---- Record Sale ----
    def test_record_sale_fifo(self, fifo_item_with_purchases, fixed_now):
        inv, fifo_id = fifo_item_with_purchases
        new_inv, cogs = validator.record_sale(
            inv, fifo_id, Decimal("80"), fixed_now, "SO-001"
        )
        item = next(i for i in new_inv.items if i.item_id == fifo_id)
        # Remaining qty = 150 - 80 = 70
        assert item.quantity_on_hand == Decimal("70")
        # COGS: 80 * 50,000 = 4,000,000
        assert cogs == Decimal("4000000")
        layers = new_inv.fifo_layers[fifo_id]
        assert layers[0].remaining_quantity == Decimal("20")
        assert layers[1].remaining_quantity == Decimal("50")
        # Remaining cost = 20*50000 + 50*52000 = 3,600,000
        assert item.total_cost == Decimal("3600000")

    def test_record_sale_fifo_spanning_layers(self, fifo_item_with_purchases, fixed_now):
        inv, fifo_id = fifo_item_with_purchases
        new_inv, cogs = validator.record_sale(
            inv, fifo_id, Decimal("120"), fixed_now, "SO-002"
        )
        # COGS: 100*50000 + 20*52000 = 6,040,000
        assert cogs == Decimal("6040000")
        item = next(i for i in new_inv.items if i.item_id == fifo_id)
        assert item.quantity_on_hand == Decimal("30")
        layers = new_inv.fifo_layers[fifo_id]
        assert len(layers) == 1
        assert layers[0].remaining_quantity == Decimal("30")
        assert layers[0].unit_cost == Decimal("52000")
        assert item.total_cost == Decimal("1560000")

    def test_record_sale_insufficient_raises(self, fifo_item_with_purchases, fixed_now):
        inv, fifo_id = fifo_item_with_purchases
        with pytest.raises(InsufficientInventoryError, match="Insufficient stock"):
            validator.record_sale(inv, fifo_id, Decimal("200"), fixed_now)

    def test_record_sale_weighted_average(self, weighted_item_with_purchases, fixed_now):
        inv, item_id = weighted_item_with_purchases
        new_inv, cogs = validator.record_sale(
            inv, item_id, Decimal("800"), fixed_now, "SO-003"
        )
        # Weighted avg = 10,166.67, COGS = 800 * 10,166.67 = 8,133,336
        expected_cogs = Decimal("800") * Decimal("10166.67")
        assert cogs == expected_cogs
        item = next(i for i in new_inv.items if i.item_id == item_id)
        assert item.quantity_on_hand == Decimal("700")
        assert item.total_cost == Decimal("15250000") - expected_cogs

    # ---- Update NRV ----
    def test_update_nrv(self, validator, inventory_with_items, fifo_item, fixed_now):
        inv = inventory_with_items
        item_id = fifo_item.item_id
        # Add purchase
        inv = validator.record_purchase(inv, item_id, Decimal("100"), Decimal("50000"), fixed_now - timedelta(days=10))
        # Update NRV (NRV > cost, no write-down)
        inv = validator.update_nrv(
            inv,
            item_id,
            estimated_selling_price=Decimal("55000"),
            estimated_costs_to_complete=Decimal("2000"),
            estimated_costs_to_sell=Decimal("1000"),
            valuation_date=fixed_now,
        )
        item = next(i for i in inv.items if i.item_id == item_id)
        # NRV = 55,000 - 2,000 - 1,000 = 52,000 > cost 50,000, write-down 0
        assert item.nrv_per_unit == Decimal("52000")
        assert item.write_down_allowance == Decimal("0")

    def test_update_nrv_with_write_down(self, validator, inventory_with_items, fifo_item, fixed_now):
        inv = inventory_with_items
        item_id = fifo_item.item_id
        inv = validator.record_purchase(inv, item_id, Decimal("100"), Decimal("50000"), fixed_now - timedelta(days=10))
        inv = validator.update_nrv(
            inv,
            item_id,
            estimated_selling_price=Decimal("40000"),
            estimated_costs_to_complete=Decimal("2000"),
            estimated_costs_to_sell=Decimal("1000"),
            valuation_date=fixed_now,
        )
        item = next(i for i in inv.items if i.item_id == item_id)
        # NRV = 40,000 - 2,000 - 1,000 = 37,000 < 50,000, write-down = (50,000 - 37,000)*100 = 1,300,000
        assert item.nrv_per_unit == Decimal("37000")
        assert item.write_down_allowance == Decimal("1300000")

    def test_nrv_reversal(self, validator, inventory_with_items, fifo_item, fixed_now):
        inv = inventory_with_items
        item_id = fifo_item.item_id
        inv = validator.record_purchase(inv, item_id, Decimal("100"), Decimal("50000"), fixed_now - timedelta(days=10))
        # Write down
        inv = validator.update_nrv(
            inv, item_id, Decimal("40000"), Decimal("2000"), Decimal("1000"), fixed_now
        )
        item = next(i for i in inv.items if i.item_id == item_id)
        assert item.write_down_allowance == Decimal("1300000")
        # NRV increases
        inv = validator.update_nrv(
            inv, item_id, Decimal("60000"), Decimal("2000"), Decimal("1000"), fixed_now
        )
        item = next(i for i in inv.items if i.item_id == item_id)
        # New NRV = 57,000 > cost, write-down reversed to 0
        assert item.write_down_allowance == Decimal("0")
        assert item.nrv_per_unit == Decimal("57000")

    # ---- Validate Inventory ----
    def test_validate_inventory_full_compliant(self, fifo_item_with_purchases):
        inv, _ = fifo_item_with_purchases
        result = validator.validate_inventory(inv)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.FULL
        assert result.errors == []

    def test_validate_inventory_with_nrv_warning(self, validator, fifo_item, fixed_now):
        inv = validator.create_inventory(uuid4(), "Test", fixed_now)
        item = validator.create_item("ITEM", "Desc", "pcs", cost_formula=PSAK14CostFormula.FIFO,
                                     opening_quantity=Decimal("10"), opening_cost=Decimal("50000"))
        inv = validator.add_item(inv, item)
        # Directly modify to set NRV lower than cost
        item.nrv_per_unit = Decimal("4000")
        inv.items[0] = item
        result = validator.validate_inventory(inv)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "NRV lebih rendah dari biaya" in result.warnings[0]

    def test_validate_inventory_multiple_formulas_warning(self, inventory_with_items):
        result = validator.validate_inventory(inventory_with_items)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert "Beberapa item menggunakan formula biaya yang berbeda" in result.warnings[0]

    # ---- Get requirements summary ----
    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "cost_formulas" in summary
        assert "disallowed_method" in summary
        assert "LIFO (dilarang)" in summary["disallowed_method"]
        assert "nrv_definition" in summary
        assert isinstance(summary["disclosures"], list)


# =============================================================================
# PSAK14 Static Methods
# =============================================================================

class TestPSAK14:
    def test_calculate_inventory_cost(self):
        cost = PSAK14.calculate_inventory_cost(
            purchase_price=Decimal("1000"),
            freight=Decimal("100"),
            import_duties=Decimal("50"),
            handling=Decimal("20"),
        )
        assert cost == Decimal("1170")

    def test_net_realizable_value(self):
        nrv = PSAK14.net_realizable_value(
            selling_price=Decimal("2000"),
            cost_to_complete=Decimal("200"),
            cost_to_sell=Decimal("50"),
        )
        assert nrv == Decimal("1750")

    @pytest.mark.parametrize("cost,nrv,expected", [
        (Decimal("1000"), Decimal("800"), True),
        (Decimal("1000"), Decimal("1200"), False),
    ])
    def test_is_write_down_required(self, cost, nrv, expected):
        assert PSAK14.is_write_down_required(cost, nrv) is expected


# =============================================================================
# Singleton
# =============================================================================

def test_get_psak14_validator():
    v1 = get_psak14_validator()
    v2 = get_psak14_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK14Validator)


# =============================================================================
# Additional Negative Paths and Edge Cases
# =============================================================================

class TestNegativePaths:
    def test_record_sale_item_not_found(self, validator, inventory_with_items, fixed_now):
        with pytest.raises(PSAK14Error, match="not found"):
            validator.record_sale(inventory_with_items, uuid4(), Decimal("1"), fixed_now)

    def test_record_purchase_negative_quantity(self, validator, inventory_with_items, fifo_item, fixed_now):
        # Negative quantity should still work? The code doesn't validate, but we can check
        inv = inventory_with_items
        item_id = fifo_item.item_id
        inv = validator.record_purchase(inv, item_id, Decimal("-10"), Decimal("5000"), fixed_now)
        item = next(i for i in inv.items if i.item_id == item_id)
        # Quantity decreased, cost decreased
        assert item.quantity_on_hand == Decimal("-10")
        assert item.total_cost == Decimal("-50000")

    def test_update_nrv_item_not_found(self, validator, inventory_with_items, fixed_now):
        with pytest.raises(PSAK14Error, match="not found"):
            validator.update_nrv(
                inventory_with_items,
                uuid4(),
                Decimal("10000"),
                Decimal("0"),
                Decimal("0"),
                fixed_now
            )

    def test_validate_inventory_with_negative_nrv(self, validator, fifo_item, fixed_now):
        inv = validator.create_inventory(uuid4(), "Test", fixed_now)
        item = validator.create_item("ITEM", "Desc", "pcs", cost_formula=PSAK14CostFormula.FIFO,
                                     opening_quantity=Decimal("10"), opening_cost=Decimal("50000"))
        inv = validator.add_item(inv, item)
        item.nrv_per_unit = Decimal("-1000")
        inv.items[0] = item
        result = validator.validate_inventory(inv)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK14ComplianceLevel.NON_COMPLIANT
        assert any("NRV per unit negatif" in e for e in result.errors)

    def test_validate_inventory_with_specific_id_and_other_warning(self, validator, fifo_item, fixed_now):
        inv = validator.create_inventory(uuid4(), "Test", fixed_now)
        item1 = validator.create_item("A", "A", "pcs", cost_formula=PSAK14CostFormula.FIFO,
                                      opening_quantity=Decimal("1"), opening_cost=Decimal("100"))
        item2 = validator.create_item("B", "B", "pcs", cost_formula=PSAK14CostFormula.SPECIFIC_IDENTIFICATION,
                                      opening_quantity=Decimal("1"), opening_cost=Decimal("200"))
        inv = validator.add_item(inv, item1)
        inv = validator.add_item(inv, item2)
        result = validator.validate_inventory(inv)
        # Should have warning for specific identification and also multiple formulas
        assert result.is_compliant is True
        assert result.compliance_level == PSAK14ComplianceLevel.SUBSTANTIAL
        assert any("Metode identifikasi khusus" in w for w in result.warnings)
        assert any("Beberapa item menggunakan formula biaya yang berbeda" in w for w in result.warnings)

    def test_carrying_amount_with_zero_quantity(self):
        item = PSAK14InventoryItem(
            item_id=uuid4(),
            item_code="TEST",
            description="Test",
            unit_of_measure="pcs",
            cost_formula=PSAK14CostFormula.FIFO,
            quantity_on_hand=Decimal("0"),
            total_cost=Decimal("0"),
            nrv_per_unit=Decimal("5000"),
            valuation_basis=PSAK14ValuationMethod.LOWER_OF_COST_OR_NRV,
        )
        assert item.carrying_amount == Decimal("0")
        assert item.effective_unit_value == Decimal("0")

    def test_weighted_average_cost_with_no_purchase(self):
        # When no purchase quantity, weighted avg should be 0
        result = PSAK14InventoryService.calculate_weighted_average_cost(
            Decimal("1000"), Decimal("10"), Decimal("0"), Decimal("0")
        )
        assert result == Decimal("0")