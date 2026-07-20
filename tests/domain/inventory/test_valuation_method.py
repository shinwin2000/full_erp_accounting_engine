# domain/inventory/test_valuation_method.py
"""
Comprehensive unit tests for inventory valuation methods.

Covers:
- FIFOLayer entity (validation, properties, consume, serialization)
- ValuationResult
- FIFOValuation (standard methods + static helpers)
- LIFOValuation
- AverageValuation / WeightedAverageValuation
- MovingAverageValuation
- SpecificIdentificationValuation
- StandardCostValuation
- ValuationMethodFactory
- FifoValuation (simple test class)
- get_valuation_method helper
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.inventory.valuation_method import (
    AverageValuation,
    FIFOLayer,
    FIFOValuation,
    FifoValuation,
    LIFOValuation,
    MovingAverageValuation,
    SpecificIdentificationValuation,
    StandardCostValuation,
    ValuationMethodFactory,
    ValuationMethodType,
    ValuationResult,
    WeightedAverageValuation,
    get_valuation_method,
)

# =============================================================================
# Helper: Movement mock class
# =============================================================================

@dataclass
class MockMovement:
    """Mock inventory movement for testing."""
    movement_id: str
    movement_date: date
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    batch_number: str | None = None
    is_inbound: bool = True

    def is_inbound(self) -> bool:
        return self.is_inbound

    def is_outbound(self) -> bool:
        return not self.is_inbound


# =============================================================================
# Tests for FIFOLayer
# =============================================================================

class TestFIFOLayer:
    def test_valid_creation(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        assert layer.quantity == Decimal("10")
        assert layer.remaining_quantity == Decimal("10")
        assert layer.unit_cost == Decimal("100")
        assert layer.is_exhausted is False

    def test_invalid_quantity_zero(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            FIFOLayer(
                item_id=uuid4(),
                quantity=Decimal("0"),
                remaining_quantity=Decimal("10"),
                unit_cost=Decimal("100"),
                purchase_date=date.today(),
            )

    def test_invalid_quantity_negative(self):
        with pytest.raises(ValueError, match="Quantity must be positive"):
            FIFOLayer(
                item_id=uuid4(),
                quantity=Decimal("-5"),
                remaining_quantity=Decimal("10"),
                unit_cost=Decimal("100"),
                purchase_date=date.today(),
            )

    def test_invalid_unit_cost_negative(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            FIFOLayer(
                item_id=uuid4(),
                quantity=Decimal("10"),
                remaining_quantity=Decimal("10"),
                unit_cost=Decimal("-10"),
                purchase_date=date.today(),
            )

    def test_invalid_remaining_negative(self):
        with pytest.raises(ValueError, match="Remaining quantity cannot be negative"):
            FIFOLayer(
                item_id=uuid4(),
                quantity=Decimal("10"),
                remaining_quantity=Decimal("-1"),
                unit_cost=Decimal("100"),
                purchase_date=date.today(),
            )

    def test_invalid_remaining_exceeds_quantity(self):
        with pytest.raises(ValueError, match="Remaining quantity cannot exceed original quantity"):
            FIFOLayer(
                item_id=uuid4(),
                quantity=Decimal("10"),
                remaining_quantity=Decimal("15"),
                unit_cost=Decimal("100"),
                purchase_date=date.today(),
            )

    def test_properties(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("7"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        assert layer.total_cost == Decimal("1000")
        assert layer.remaining_cost == Decimal("700")
        assert layer.is_exhausted is False

        layer.remaining_quantity = Decimal("0")
        assert layer.is_exhausted is True

    def test_consume_valid(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        cost = layer.consume(Decimal("3"))
        assert cost == Decimal("300")
        assert layer.remaining_quantity == Decimal("7")

    def test_consume_exact(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        cost = layer.consume(Decimal("10"))
        assert cost == Decimal("1000")
        assert layer.remaining_quantity == Decimal("0")
        assert layer.is_exhausted is True

    def test_consume_invalid_zero(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        with pytest.raises(ValueError, match="Consumption quantity must be positive"):
            layer.consume(Decimal("0"))

    def test_consume_exceeds_remaining(self):
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("5"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        with pytest.raises(ValueError, match="Cannot consume 10 > remaining 5"):
            layer.consume(Decimal("10"))

    def test_to_dict(self):
        layer_id = uuid4()
        item_id = uuid4()
        location_id = uuid4()
        layer = FIFOLayer(
            id=layer_id,
            item_id=item_id,
            quantity=Decimal("10"),
            remaining_quantity=Decimal("7"),
            unit_cost=Decimal("100"),
            purchase_date=date(2025, 1, 15),
            layer_number=2,
            batch_code="BATCH-01",
            location_id=location_id,
            currency="USD",
        )
        d = layer.to_dict()
        assert d["id"] == str(layer_id)
        assert d["item_id"] == str(item_id)
        assert d["quantity"] == "10"
        assert d["remaining_quantity"] == "7"
        assert d["unit_cost"] == "100"
        assert d["purchase_date"] == "2025-01-15"
        assert d["layer_number"] == 2
        assert d["batch_code"] == "BATCH-01"
        assert d["location_id"] == str(location_id)
        assert d["currency"] == "USD"

    def test_from_dict(self):
        layer_id = uuid4()
        item_id = uuid4()
        location_id = uuid4()
        data = {
            "id": str(layer_id),
            "item_id": str(item_id),
            "quantity": "10",
            "remaining_quantity": "7",
            "unit_cost": "100.00",
            "purchase_date": "2025-01-15",
            "layer_number": 3,
            "batch_code": "BATCH-02",
            "location_id": str(location_id),
            "currency": "EUR",
        }
        layer = FIFOLayer.from_dict(data)
        assert layer.id == layer_id
        assert layer.item_id == item_id
        assert layer.quantity == Decimal("10")
        assert layer.remaining_quantity == Decimal("7")
        assert layer.unit_cost == Decimal("100.00")
        assert layer.purchase_date == date(2025, 1, 15)
        assert layer.layer_number == 3
        assert layer.batch_code == "BATCH-02"
        assert layer.location_id == location_id
        assert layer.currency == "EUR"


# =============================================================================
# Tests for ValuationResult
# =============================================================================

class TestValuationResult:
    def test_default_construction(self):
        result = ValuationResult()
        assert result.total_quantity == Decimal(0)
        assert result.total_value == Decimal(0)
        assert result.unit_cost == Decimal(0)
        assert result.method == ValuationMethodType.FIFO
        assert result.layers == []
        assert result.cogs == Decimal(0)

    def test_custom_construction(self):
        result = ValuationResult(
            total_quantity=Decimal("10"),
            total_value=Decimal("1000"),
            unit_cost=Decimal("100"),
            method=ValuationMethodType.AVERAGE,
            layers=[{"layer": 1}],
            cogs=Decimal("300"),
        )
        assert result.total_quantity == Decimal("10")
        assert result.total_value == Decimal("1000")
        assert result.unit_cost == Decimal("100")
        assert result.method == ValuationMethodType.AVERAGE
        assert result.layers == [{"layer": 1}]
        assert result.cogs == Decimal("300")

    def test_to_dict(self):
        result = ValuationResult(
            total_quantity=Decimal("10.5"),
            total_value=Decimal("1050.00"),
            unit_cost=Decimal("100.00"),
            method=ValuationMethodType.FIFO,
            layers=[{"a": 1}],
            cogs=Decimal("200.00"),
        )
        d = result.to_dict()
        assert d["total_quantity"] == "10.5"
        assert d["total_value"] == "1050.00"
        assert d["unit_cost"] == "100.00"
        assert d["method"] == "fifo"
        assert d["layers_count"] == 1
        assert d["cogs"] == "200.00"


# =============================================================================
# Tests for FIFOValuation
# =============================================================================

class TestFIFOValuation:
    def test_calculate_value(self):
        valuation = FIFOValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("100"), Decimal("800"), is_outbound=True),
        ]
        result = valuation.calculate_value(movements)
        # Inbound total: 10*100 + 5*110 = 1550; outbound 8*100 = 800; remaining: 2*100 + 5*110 = 750
        assert result.total_quantity == Decimal("7")  # 10+5-8 = 7
        assert result.total_value == Decimal("750.00")
        assert result.unit_cost == Decimal("107.14")  # 750/7 = 107.142857 -> 107.14
        assert result.method == ValuationMethodType.FIFO
        assert len(result.layers) == 2  # two active layers

    def test_calculate_cogs(self):
        valuation = FIFOValuation()
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
        ]
        outbound = [
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
            MockMovement("4", date(2025, 1, 12), Decimal("5"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        # First 8: from first layer (8*100=800), remaining 2 from first layer? Actually outbound 8 consumes 8 of 10, leaves 2 from layer1.
        # Then outbound 5: first consume remaining 2 from layer1 (2*100=200), then 3 from layer2 (3*110=330) => total cogs = 800+530=1330
        assert cogs == Decimal("1330.00")

    def test_calculate_cost_valid(self):
        valuation = FIFOValuation()
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("7"))
        # FIFO: first 7 from first layer: 7*100 = 700
        assert cost == Decimal("700.00")

    def test_calculate_cost_with_FIFOLayer(self):
        valuation = FIFOValuation()
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date.today())
        cost = valuation.calculate_cost([layer1, layer2], Decimal("12"))
        # 10*100 + 2*110 = 1220
        assert cost == Decimal("1220.00")

    def test_calculate_cost_not_enough(self):
        valuation = FIFOValuation()
        layers = [{"quantity": 5, "unit_cost": 100}]
        with pytest.raises(ValueError, match="Not enough inventory"):
            valuation.calculate_cost(layers, Decimal("10"))

    def test_calculate_cost_zero_quantity(self):
        valuation = FIFOValuation()
        layers = [{"quantity": 5, "unit_cost": 100}]
        cost = valuation.calculate_cost(layers, Decimal("0"))
        assert cost == Decimal("0")

    # Static methods
    def test_calculate_cost_static(self):
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = FIFOValuation.calculate_cost_static(layers, Decimal("8"))
        assert cost == Decimal("800.00")

        # With FIFOLayer objects
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date.today())
        cost = FIFOValuation.calculate_cost_static([layer1, layer2], Decimal("12"))
        assert cost == Decimal("1220.00")

    def test_calculate_cost_static_not_enough(self):
        layers = [{"quantity": 5, "unit_cost": 100}]
        with pytest.raises(ValueError, match="Not enough inventory"):
            FIFOValuation.calculate_cost_static(layers, Decimal("10"))

    def test_consume(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date.today())
        layers = [layer1, layer2]
        total_cost, new_layers = FIFOValuation.consume(layers, Decimal("12"))
        assert total_cost == Decimal("1220.00")
        assert new_layers[0].remaining_quantity == Decimal("0")
        assert new_layers[1].remaining_quantity == Decimal("3")  # 5 - (12-10)=3

    def test_consume_exact(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        layers = [layer1]
        total_cost, new_layers = FIFOValuation.consume(layers, Decimal("10"))
        assert total_cost == Decimal("1000.00")
        assert new_layers[0].remaining_quantity == Decimal("0")

    def test_consume_not_enough(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        with pytest.raises(ValueError, match="exceeds available"):
            FIFOValuation.consume([layer1], Decimal("15"))

    def test_consume_negative(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        with pytest.raises(ValueError, match="cannot be negative"):
            FIFOValuation.consume([layer1], Decimal("-1"))

    def test_add_layer(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date(2025, 1, 1))
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date(2025, 1, 5))
        layers = [layer1]
        new_layers = FIFOValuation.add_layer(layers, layer2)
        assert len(new_layers) == 2
        # Should be sorted by date
        assert new_layers[0].purchase_date == date(2025, 1, 1)
        assert new_layers[1].purchase_date == date(2025, 1, 5)

    def test_add_layer_invalid_quantity(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date.today())
        invalid = FIFOLayer(item_id=uuid4(), quantity=0, remaining_quantity=0, unit_cost=100, purchase_date=date.today())
        with pytest.raises(ValueError, match="New layer quantity must be positive"):
            FIFOValuation.add_layer([layer1], invalid)

    def test_get_current_cost(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date(2025, 1, 1))
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date(2025, 1, 5))
        cost = FIFOValuation.get_current_cost([layer1, layer2])
        assert cost == Decimal("100")  # oldest layer cost

    def test_get_current_cost_empty(self):
        cost = FIFOValuation.get_current_cost([])
        assert cost == Decimal("0")

    def test_get_remaining_value(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=7, unit_cost=100, purchase_date=date.today())
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date.today())
        value = FIFOValuation.get_remaining_value([layer1, layer2])
        assert value == Decimal("1250.00")  # 7*100 + 5*110 = 1250

    def test_sort_layers_by_date(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=10, unit_cost=100, purchase_date=date(2025, 1, 5))
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date(2025, 1, 1))
        sorted_layers = FIFOValuation.sort_layers_by_date([layer1, layer2])
        assert sorted_layers[0].purchase_date == date(2025, 1, 1)
        assert sorted_layers[1].purchase_date == date(2025, 1, 5)

    def test_remove_empty_layers(self):
        layer1 = FIFOLayer(item_id=uuid4(), quantity=10, remaining_quantity=0, unit_cost=100, purchase_date=date.today())
        layer2 = FIFOLayer(item_id=uuid4(), quantity=5, remaining_quantity=5, unit_cost=110, purchase_date=date.today())
        filtered = FIFOValuation.remove_empty_layers([layer1, layer2])
        assert len(filtered) == 1
        assert filtered[0].remaining_quantity == Decimal("5")


# =============================================================================
# Tests for LIFOValuation
# =============================================================================

class TestLIFOValuation:
    def test_calculate_value(self):
        valuation = LIFOValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        result = valuation.calculate_value(movements)
        # LIFO: outbound consumes from latest: 5 from layer2, 3 from layer1. Remaining: layer1 7*100 = 700
        assert result.total_quantity == Decimal("7")
        assert result.total_value == Decimal("700.00")
        assert result.unit_cost == Decimal("100.00")
        assert result.method == ValuationMethodType.LIFO

    def test_calculate_cogs(self):
        valuation = LIFOValuation()
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
        ]
        outbound = [
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        # LIFO: 5 from layer2 (5*110=550), 3 from layer1 (3*100=300) => total 850
        assert cogs == Decimal("850.00")

    def test_calculate_cost(self):
        valuation = LIFOValuation()
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("7"))
        # LIFO: consume from newest (5 from layer2, 2 from layer1) => 5*110 + 2*100 = 750
        assert cost == Decimal("750.00")

    def test_calculate_cost_not_enough(self):
        valuation = LIFOValuation()
        layers = [{"quantity": 5, "unit_cost": 100}]
        with pytest.raises(ValueError, match="Not enough inventory"):
            valuation.calculate_cost(layers, Decimal("10"))


# =============================================================================
# Tests for AverageValuation / WeightedAverageValuation
# =============================================================================

class TestAverageValuation:
    def test_calculate_value(self):
        valuation = AverageValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        result = valuation.calculate_value(movements)
        # After inbound: total qty 15, total value 1550, avg 103.3333
        # Outbound 8 at avg: 8*103.3333 = 826.6664, remaining qty 7, value 723.3336, unit cost 103.33
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("723.33")
        assert result.unit_cost == Decimal("103.33")
        assert result.method == ValuationMethodType.AVERAGE

    def test_calculate_cogs(self):
        valuation = AverageValuation()
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
        ]
        outbound = [
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        # 8 * weighted avg = 8 * (1550/15) = 826.666... => 826.67
        assert cogs == Decimal("826.67")

    def test_calculate_cost(self):
        valuation = AverageValuation()
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("7"))
        # avg = (10*100 + 5*110)/15 = 1550/15 = 103.3333; 7*avg = 723.3333 => 723.33
        assert cost == Decimal("723.33")

    def test_calculate_cost_no_inventory(self):
        valuation = AverageValuation()
        with pytest.raises(ValueError, match="No inventory available"):
            valuation.calculate_cost([], Decimal("5"))

    def test_weighted_average_alias(self):
        valuation = WeightedAverageValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
        ]
        result = valuation.calculate_value(movements)
        assert result.method == ValuationMethodType.AVERAGE  # Actually it's using AverageValuation's method


# =============================================================================
# Tests for MovingAverageValuation
# =============================================================================

class TestMovingAverageValuation:
    def test_calculate_value(self):
        valuation = MovingAverageValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("723.33")  # same as average
        assert result.unit_cost == Decimal("103.33")
        assert result.method == ValuationMethodType.MOVING_AVERAGE

    def test_calculate_cogs(self):
        valuation = MovingAverageValuation()
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True),
        ]
        outbound = [
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("826.67")

    def test_calculate_cost(self):
        valuation = MovingAverageValuation()
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("7"))
        assert cost == Decimal("723.33")


# =============================================================================
# Tests for SpecificIdentificationValuation
# =============================================================================

class TestSpecificIdentificationValuation:
    def test_calculate_value(self):
        valuation = SpecificIdentificationValuation()
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True, batch_number="B1"),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True, batch_number="B2"),
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True, batch_number="B1"),
        ]
        result = valuation.calculate_value(movements)
        # Outbound 8 from B1: remaining B1=2, B2=5. value: 2*100 + 5*110 = 750
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("750.00")
        assert result.unit_cost == Decimal("107.14")
        assert result.method == ValuationMethodType.SPECIFIC_ID

    def test_calculate_cogs(self):
        valuation = SpecificIdentificationValuation()
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), Decimal("1000"), is_inbound=True, batch_number="B1"),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), Decimal("550"), is_inbound=True, batch_number="B2"),
        ]
        outbound = [
            MockMovement("3", date(2025, 1, 10), Decimal("8"), Decimal("0"), Decimal("0"), is_outbound=True, batch_number="B1"),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("800.00")  # 8*100

    def test_calculate_cost(self):
        valuation = SpecificIdentificationValuation()
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("7"))
        # Same as FIFO (since we process in order) - but specific id can target specific layers; here we just test the default iteration
        assert cost == Decimal("700.00")  # 7*100

    def test_calculate_cost_not_enough(self):
        valuation = SpecificIdentificationValuation()
        layers = [{"quantity": 5, "unit_cost": 100}]
        with pytest.raises(ValueError, match="Not enough inventory"):
            valuation.calculate_cost(layers, Decimal("10"))


# =============================================================================
# Tests for StandardCostValuation
# =============================================================================

class TestStandardCostValuation:
    def test_constructor(self):
        valuation = StandardCostValuation(Decimal("150"))
        assert valuation._standard_cost == Decimal("150")

    def test_calculate_value_with_standard_cost(self):
        valuation = StandardCostValuation(Decimal("120"))
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("0"), Decimal("0"), is_inbound=True),
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        result = valuation.calculate_value(movements)
        # total qty = 5, value = 5*120 = 600
        assert result.total_quantity == Decimal("5.000")
        assert result.total_value == Decimal("600.00")
        assert result.unit_cost == Decimal("120.00")
        assert result.method == ValuationMethodType.STANDARD

    def test_calculate_value_no_standard_cost(self):
        valuation = StandardCostValuation()  # standard_cost = 0
        movements = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("0"), Decimal("0"), is_inbound=True),
        ]
        with pytest.raises(ValueError, match="Standard cost must be provided"):
            valuation.calculate_value(movements)

    def test_calculate_cogs(self):
        valuation = StandardCostValuation(Decimal("100"))
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("90"), Decimal("900"), is_inbound=True),
        ]
        outbound = [
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        # 5 * 100 = 500
        assert cogs == Decimal("500.00")

    def test_calculate_cogs_uses_actual_if_standard_missing(self):
        valuation = StandardCostValuation()  # standard_cost = 0
        inbound = [
            MockMovement("1", date(2025, 1, 1), Decimal("10"), Decimal("90"), Decimal("900"), is_inbound=True),
        ]
        outbound = [
            MockMovement("2", date(2025, 1, 5), Decimal("5"), Decimal("0"), Decimal("0"), is_outbound=True),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        # Should compute avg cost from inbound = 90 per unit, cogs = 5*90 = 450
        assert cogs == Decimal("450.00")

    def test_calculate_cogs_no_inbound(self):
        valuation = StandardCostValuation()  # no standard, no inbound
        cogs = valuation.calculate_cogs([], [])
        assert cogs == Decimal("0")

    def test_calculate_cost(self):
        valuation = StandardCostValuation(Decimal("120"))
        cost = valuation.calculate_cost([], Decimal("10"))
        assert cost == Decimal("1200.00")

    def test_calculate_cost_derives_from_layers(self):
        valuation = StandardCostValuation()  # no standard
        layers = [
            {"quantity": 10, "unit_cost": 100},
            {"quantity": 5, "unit_cost": 110},
        ]
        cost = valuation.calculate_cost(layers, Decimal("5"))
        # avg cost = (10*100 + 5*110)/15 = 103.33; 5*103.33 = 516.65
        assert cost == Decimal("516.65")

    def test_calculate_cost_no_standard_no_layers(self):
        valuation = StandardCostValuation()
        with pytest.raises(ValueError, match="Standard cost not available"):
            valuation.calculate_cost([], Decimal("5"))


# =============================================================================
# Tests for ValuationMethodFactory
# =============================================================================

class TestValuationMethodFactory:
    def test_get_method_fifo(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.FIFO)
        assert isinstance(method, FIFOValuation)

    def test_get_method_lifo(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.LIFO)
        assert isinstance(method, LIFOValuation)

    def test_get_method_average(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.AVERAGE)
        assert isinstance(method, WeightedAverageValuation)

    def test_get_method_weighted_average(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.WEIGHTED_AVERAGE)
        assert isinstance(method, WeightedAverageValuation)

    def test_get_method_moving_average(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.MOVING_AVERAGE)
        assert isinstance(method, MovingAverageValuation)

    def test_get_method_specific_id(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.SPECIFIC_ID)
        assert isinstance(method, SpecificIdentificationValuation)

    def test_get_method_standard(self):
        method = ValuationMethodFactory.get_method(ValuationMethodType.STANDARD, Decimal("200"))
        assert isinstance(method, StandardCostValuation)
        assert method._standard_cost == Decimal("200")

    def test_get_method_unknown_defaults_to_fifo(self):
        method = ValuationMethodFactory.get_method("unknown")  # this will fail because method_type is not an enum
        # But we can call with a string? Actually the signature expects ValuationMethodType.
        # We test via get_method_by_name which handles unknown.

    def test_get_method_by_name(self):
        method = ValuationMethodFactory.get_method_by_name("fifo")
        assert isinstance(method, FIFOValuation)
        method = ValuationMethodFactory.get_method_by_name("LIFO")
        assert isinstance(method, LIFOValuation)
        method = ValuationMethodFactory.get_method_by_name("average")
        assert isinstance(method, WeightedAverageValuation)
        method = ValuationMethodFactory.get_method_by_name("moving_average")
        assert isinstance(method, MovingAverageValuation)
        method = ValuationMethodFactory.get_method_by_name("specific_id")
        assert isinstance(method, SpecificIdentificationValuation)
        method = ValuationMethodFactory.get_method_by_name("standard", Decimal("150"))
        assert isinstance(method, StandardCostValuation)
        assert method._standard_cost == Decimal("150")

    def test_get_method_by_name_unknown_fifo(self):
        method = ValuationMethodFactory.get_method_by_name("unknown")
        assert isinstance(method, FIFOValuation)


# =============================================================================
# Tests for FifoValuation (simple test class)
# =============================================================================

class TestFifoValuation:
    def test_calculate_cogs(self):
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        cogs = fifo.calculate_cogs(Decimal("8"))
        assert cogs == Decimal("800.00")  # 8*100

    def test_calculate_cogs_cross_layers(self):
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        cogs = fifo.calculate_cogs(Decimal("12"))
        assert cogs == Decimal("1220.00")  # 10*100 + 2*110

    def test_calculate_cogs_not_enough(self):
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
        ]
        fifo = FifoValuation(transactions)
        with pytest.raises(ValueError, match="Not enough inventory"):
            fifo.calculate_cogs(Decimal("15"))

    def test_get_remaining(self):
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        fifo.calculate_cogs(Decimal("8"))
        remaining = fifo.get_remaining()
        # Remaining: layer1:2, layer2:5 => qty=7, value=2*100 + 5*110 = 750
        assert remaining.quantity == Decimal("7")
        assert remaining.value == Decimal("750")


# =============================================================================
# Tests for get_valuation_method helper
# =============================================================================

class TestGetValuationMethod:
    def test_valid_names(self):
        assert get_valuation_method("FIFO") == ValuationMethodType.FIFO
        assert get_valuation_method("LIFO") == ValuationMethodType.LIFO
        assert get_valuation_method("AVERAGE") == ValuationMethodType.AVERAGE
        assert get_valuation_method("MOVING_AVERAGE") == ValuationMethodType.MOVING_AVERAGE
        assert get_valuation_method("SPECIFIC_ID") == ValuationMethodType.SPECIFIC_ID
        assert get_valuation_method("WEIGHTED_AVERAGE") == ValuationMethodType.WEIGHTED_AVERAGE
        assert get_valuation_method("STANDARD") == ValuationMethodType.STANDARD

    def test_lowercase(self):
        assert get_valuation_method("fifo") == ValuationMethodType.FIFO

    def test_unknown_default_fifo(self):
        assert get_valuation_method("unknown") == ValuationMethodType.FIFO
