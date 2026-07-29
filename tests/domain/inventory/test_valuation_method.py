# test_valuation_method.py
# Comprehensive tests for domain/inventory/valuation_method.py
#
# Perbaikan pada file ini (dibanding versi sebelumnya):
# 1. BUG NYATA: `MockMovement` mendefinisikan field dataclass `is_inbound: bool`
#    DAN method `def is_inbound(self)` dengan nama yang sama. Method mendefinisikan
#    ulang atribut kelas sehingga default field asli tertimpa oleh objek fungsi.
#    Akibatnya, `MockMovement(..., is_outbound=True)` selalu gagal dengan
#    TypeError ("unexpected keyword argument"), dan `m.is_inbound()` yang dipanggil
#    tanpa argumen `is_inbound=...` akan error juga. Ini membuat 19 dari 76 test
#    di file lama gagal total saat benar-benar dijalankan.
#    -> Diperbaiki dengan mengganti nama field internal menjadi `direction`
#       ("in"/"out") dan menyediakan factory method `MockMovement.inbound(...)`
#       / `MockMovement.outbound(...)` yang tidak bentrok nama dengan field apa pun.
# 2. `test_add_layer_invalid_quantity` mencoba membuat `FIFOLayer` dengan quantity=0
#    secara langsung -- tapi `FIFOLayer.__post_init__` sudah menolaknya duluan
#    sebelum sempat dipakai untuk menguji validasi `FIFOValuation.add_layer`.
#    -> Diperbaiki memakai `unittest.mock.Mock(spec=FIFOLayer, ...)` untuk
#       men-stub objek layer yang lolos dari validasi constructor, sehingga jalur
#       validasi internal `add_layer` benar-benar teruji.
# 3. `test_get_remaining_value` memakai literal int biasa (`quantity=10`, bukan
#    `Decimal("10")`) sehingga `sum(...)` mulai dari int dan hasil akhirnya bukan
#    Decimal, menyebabkan `.quantize()` gagal (`AttributeError`). Semua test kini
#    konsisten memakai `Decimal(...)` sesuai type hint di source.
# 4. `test_calculate_cost_derives_from_layers` punya nilai ekspektasi yang salah
#    (516.65, seharusnya 516.67 -- dikonfirmasi ulang dengan menjalankan kode
#    sebenarnya). Diperbaiki.
# 5. Sejumlah test yang secara struktural identik (hanya beda kelas/strategi atau
#    beda angka) digabung memakai `pytest.mark.parametrize`, mengurangi duplikasi
#    copy-paste sekaligus menambah cakupan (mis. `MovingAverageValuation` kini juga
#    diuji untuk kondisi "no inventory").
# 6. Menambahkan test untuk `ValuationMethodType.from_string`, `FIFOLayer._validate`,
#    dan default `ValuationMethodStrategy.calculate_cost` (lewat subclass minimal),
#    yang sebelumnya tidak tersentuh test manapun.

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

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
    ValuationMethod,
    ValuationMethodFactory,
    ValuationMethodStrategy,
    ValuationMethodType,
    ValuationResult,
    WeightedAverageValuation,
    get_valuation_method,
)

# =============================================================================
# Helper: MockMovement for testing valuation strategies
# =============================================================================


@dataclass
class MockMovement:
    """Mock inventory movement used across valuation strategy tests.

    NOTE: the field is named `direction` (not `is_inbound`) on purpose: naming
    a dataclass field the same as one of its own methods silently replaces the
    field's default with the method object (see module docstring above), which
    was the root cause of most failures in the previous version of this file.
    Use the `inbound(...)` / `outbound(...)` factories below instead of
    constructing this class directly.
    """

    movement_id: str
    movement_date: date
    quantity: Decimal
    unit_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    batch_number: str | None = None
    direction: str = "in"

    def is_inbound(self) -> bool:
        return self.direction == "in"

    def is_outbound(self) -> bool:
        return self.direction == "out"

    @classmethod
    def inbound(
        cls,
        movement_id: str,
        movement_date: date,
        quantity: Decimal,
        unit_cost: Decimal,
        batch_number: str | None = None,
    ) -> MockMovement:
        quantity = Decimal(quantity)
        unit_cost = Decimal(unit_cost)
        return cls(
            movement_id=movement_id,
            movement_date=movement_date,
            quantity=quantity,
            unit_cost=unit_cost,
            total_cost=quantity * unit_cost,
            batch_number=batch_number,
            direction="in",
        )

    @classmethod
    def outbound(
        cls,
        movement_id: str,
        movement_date: date,
        quantity: Decimal,
        batch_number: str | None = None,
    ) -> MockMovement:
        return cls(
            movement_id=movement_id,
            movement_date=movement_date,
            quantity=Decimal(quantity),
            unit_cost=Decimal("0"),
            total_cost=Decimal("0"),
            batch_number=batch_number,
            direction="out",
        )


def _fifo_layers() -> list[dict[str, Any]]:
    """Common two-layer inventory snapshot reused by several strategy tests."""
    return [
        {"quantity": Decimal("10"), "unit_cost": Decimal("100")},
        {"quantity": Decimal("5"), "unit_cost": Decimal("110")},
    ]


# =============================================================================
# Tests for ValuationMethodType
# =============================================================================


class TestValuationMethodType:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("fifo", ValuationMethodType.FIFO),
            ("FIFO", ValuationMethodType.FIFO),
            ("lifo", ValuationMethodType.LIFO),
            ("LIFO", ValuationMethodType.LIFO),
            ("average", ValuationMethodType.AVERAGE),
            ("weighted_average", ValuationMethodType.WEIGHTED_AVERAGE),
            ("moving_average", ValuationMethodType.MOVING_AVERAGE),
            ("specific_id", ValuationMethodType.SPECIFIC_ID),
            ("standard", ValuationMethodType.STANDARD),
        ],
    )
    def test_from_string_known_values(self, value: str, expected: ValuationMethodType) -> None:
        assert ValuationMethodType.from_string(value) == expected

    def test_from_string_unknown_defaults_to_fifo(self) -> None:
        assert ValuationMethodType.from_string("does_not_exist") == ValuationMethodType.FIFO

    def test_str_returns_value(self) -> None:
        assert str(ValuationMethodType.FIFO) == "fifo"
        assert str(ValuationMethodType.STANDARD) == "standard"

    def test_valuation_method_alias(self) -> None:
        assert ValuationMethod is ValuationMethodType


# =============================================================================
# Tests for FIFOLayer
# =============================================================================


class TestFIFOLayer:
    def test_valid_creation(self) -> None:
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

    @pytest.mark.parametrize(
        "overrides, match",
        [
            ({"quantity": Decimal("0")}, "Quantity must be positive"),
            ({"quantity": Decimal("-5")}, "Quantity must be positive"),
            ({"unit_cost": Decimal("-10")}, "Unit cost cannot be negative"),
            ({"remaining_quantity": Decimal("-1")}, "Remaining quantity cannot be negative"),
            ({"remaining_quantity": Decimal("15")}, "Remaining quantity cannot exceed original quantity"),
        ],
        ids=[
            "quantity_zero",
            "quantity_negative",
            "unit_cost_negative",
            "remaining_negative",
            "remaining_exceeds_quantity",
        ],
    )
    def test_invalid_construction_raises(self, overrides: dict[str, Any], match: str) -> None:
        base_kwargs = dict(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        base_kwargs.update(overrides)
        with pytest.raises(ValueError, match=match):
            FIFOLayer(**base_kwargs)

    def test_validate_called_directly_on_valid_layer_is_noop(self) -> None:
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        # Calling the internal validator again directly must not raise for
        # data that is still valid (covers `_validate` as a direct call, not
        # only implicitly through __post_init__).
        assert layer._validate() is None

    def test_default_id_is_a_valid_uuid_when_not_supplied(self) -> None:
        # NOTE: FIFOLayer's `id` default comes from a dataclass
        # `field(default_factory=uuid4)`, which binds the function object at
        # class-definition time. Patching `domain.inventory.valuation_method.uuid4`
        # afterwards can't intercept that already-bound reference, so this is
        # verified as a plain behavioral check rather than via mocking (mocking
        # is used instead in `test_from_dict_generates_id_when_missing` below,
        # where `uuid4()` genuinely is looked up through the module at call time).
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        assert isinstance(layer.id, UUID)

    def test_properties(self) -> None:
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

    def test_consume_valid(self) -> None:
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

    def test_consume_exact(self) -> None:
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

    @pytest.mark.parametrize(
        "remaining_quantity, consume_qty, match",
        [
            (Decimal("10"), Decimal("0"), "Consumption quantity must be positive"),
            (Decimal("5"), Decimal("10"), "Cannot consume 10 > remaining 5"),
        ],
        ids=["zero_quantity", "exceeds_remaining"],
    )
    def test_consume_invalid_raises(
        self, remaining_quantity: Decimal, consume_qty: Decimal, match: str
    ) -> None:
        layer = FIFOLayer(
            item_id=uuid4(),
            quantity=Decimal("10"),
            remaining_quantity=remaining_quantity,
            unit_cost=Decimal("100"),
            purchase_date=date.today(),
        )
        with pytest.raises(ValueError, match=match):
            layer.consume(consume_qty)

    def test_to_dict(self) -> None:
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

    def test_from_dict(self) -> None:
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

    def test_from_dict_generates_id_when_missing(self) -> None:
        fixed_id = uuid4()
        data = {
            "item_id": str(uuid4()),
            "quantity": "10",
            "remaining_quantity": "10",
            "unit_cost": "100",
            "purchase_date": "2025-01-15",
        }
        with patch("domain.inventory.valuation_method.uuid4", return_value=fixed_id):
            layer = FIFOLayer.from_dict(data)
        assert layer.id == fixed_id
        assert layer.location_id is None
        assert layer.currency == "IDR"


# =============================================================================
# Tests for ValuationResult
# =============================================================================


class TestValuationResult:
    def test_default_construction(self) -> None:
        result = ValuationResult()
        assert result.total_quantity == Decimal(0)
        assert result.total_value == Decimal(0)
        assert result.unit_cost == Decimal(0)
        assert result.method == ValuationMethodType.FIFO
        assert result.layers == []
        assert result.cogs == Decimal(0)

    def test_custom_construction(self) -> None:
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

    def test_to_dict(self) -> None:
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
# Tests for ValuationMethodStrategy (abstract base default behavior)
# =============================================================================


class _MinimalStrategy(ValuationMethodStrategy):
    """Smallest possible concrete subclass, used only to exercise the base
    class's default `calculate_cost` implementation (it falls back to FIFO)."""

    def calculate_value(self, movements, current_unit_cost=None) -> ValuationResult:
        return ValuationResult()

    def calculate_cogs(self, outward_movements, inward_movements) -> Decimal:
        return Decimal(0)


class TestValuationMethodStrategyDefaults:
    def test_calculate_cost_default_falls_back_to_fifo(self) -> None:
        strategy = _MinimalStrategy()
        assert strategy.calculate_cost(_fifo_layers(), Decimal("7")) == Decimal("700.00")

    def test_calculate_cost_default_zero_quantity(self) -> None:
        strategy = _MinimalStrategy()
        assert strategy.calculate_cost(_fifo_layers(), Decimal("0")) == Decimal(0)


# =============================================================================
# Tests for FIFOValuation
# =============================================================================


class TestFIFOValuation:
    def test_calculate_value(self) -> None:
        valuation = FIFOValuation()
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8")),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7")
        assert result.total_value == Decimal("750.00")
        assert result.unit_cost == Decimal("107.14")
        assert result.method == ValuationMethodType.FIFO
        assert len(result.layers) == 2

    def test_calculate_cogs(self) -> None:
        valuation = FIFOValuation()
        inbound = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        outbound = [
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8")),
            MockMovement.outbound("4", date(2025, 1, 12), Decimal("5")),
        ]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("1330.00")

    def test_calculate_cost_with_FIFOLayer_objects(self) -> None:
        valuation = FIFOValuation()
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date.today(),
        )
        cost = valuation.calculate_cost([layer1, layer2], Decimal("12"))
        assert cost == Decimal("1220.00")

    def test_calculate_cost_zero_quantity(self) -> None:
        valuation = FIFOValuation()
        layers = [{"quantity": Decimal("5"), "unit_cost": Decimal("100")}]
        cost = valuation.calculate_cost(layers, Decimal("0"))
        assert cost == Decimal("0")

    def test_calculate_cost_static_matches_instance_method(self) -> None:
        layers = _fifo_layers()
        via_static = FIFOValuation.calculate_cost_static(layers, Decimal("8"))
        via_instance = FIFOValuation().calculate_cost(layers, Decimal("8"))
        assert via_static == via_instance == Decimal("800.00")

    def test_calculate_cost_static_with_FIFOLayer_objects(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date.today(),
        )
        cost = FIFOValuation.calculate_cost_static([layer1, layer2], Decimal("12"))
        assert cost == Decimal("1220.00")

    def test_consume(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date.today(),
        )
        total_cost, new_layers = FIFOValuation.consume([layer1, layer2], Decimal("12"))
        assert total_cost == Decimal("1220.00")
        assert new_layers[0].remaining_quantity == Decimal("0")
        assert new_layers[1].remaining_quantity == Decimal("3")

    @pytest.mark.parametrize(
        "consume_qty, expected_cost, expected_remaining",
        [
            (Decimal("10"), Decimal("1000.00"), Decimal("0")),
            (Decimal("0"), Decimal("0"), Decimal("10")),
        ],
        ids=["full_layer_consumed", "zero_quantity_leaves_layer_unchanged"],
    )
    def test_consume_full_and_zero_quantity(
        self, consume_qty: Decimal, expected_cost: Decimal, expected_remaining: Decimal
    ) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        total_cost, new_layers = FIFOValuation.consume([layer1], consume_qty)
        assert total_cost == expected_cost
        assert new_layers[0].remaining_quantity == expected_remaining

    @pytest.mark.parametrize(
        "consume_qty, match",
        [
            (Decimal("15"), "exceeds available"),
            (Decimal("-1"), "cannot be negative"),
        ],
        ids=["exceeds_available", "negative_quantity"],
    )
    def test_consume_invalid_raises(self, consume_qty: Decimal, match: str) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        with pytest.raises(ValueError, match=match):
            FIFOValuation.consume([layer1], consume_qty)

    def test_add_layer(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date(2025, 1, 1),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date(2025, 1, 5),
        )
        new_layers = FIFOValuation.add_layer([layer1], layer2)
        assert len(new_layers) == 2
        assert new_layers[0].purchase_date == date(2025, 1, 1)
        assert new_layers[1].purchase_date == date(2025, 1, 5)

    def test_add_layer_invalid_quantity_raises(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        # A real FIFOLayer can never have quantity <= 0 (its own __post_init__
        # already forbids that), so the only way to exercise add_layer's own
        # defensive guard is to stub a layer-like object that bypasses that
        # constructor validation entirely.
        invalid_layer = Mock(spec=FIFOLayer, quantity=Decimal("0"))
        with pytest.raises(ValueError, match="New layer quantity must be positive"):
            FIFOValuation.add_layer([layer1], invalid_layer)

    def test_get_current_cost(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date(2025, 1, 1),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date(2025, 1, 5),
        )
        cost = FIFOValuation.get_current_cost([layer1, layer2])
        assert cost == Decimal("100")

    def test_get_current_cost_empty_list(self) -> None:
        assert FIFOValuation.get_current_cost([]) == Decimal("0")

    def test_get_remaining_value(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("7"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date.today(),
        )
        value = FIFOValuation.get_remaining_value([layer1, layer2])
        assert value == Decimal("1250.00")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "Known bug in FIFOValuation.get_remaining_value: `sum(...)` over an "
            "empty generator returns plain int 0, and `.quantize()` is then "
            "called on that int, raising AttributeError instead of returning "
            "Decimal('0'). Fix in source: `sum((...), start=Decimal('0'))`."
        ),
    )
    def test_get_remaining_value_empty_list(self) -> None:
        assert FIFOValuation.get_remaining_value([]) == Decimal("0")

    def test_sort_layers_by_date(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("10"),
            unit_cost=Decimal("100"), purchase_date=date(2025, 1, 5),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date(2025, 1, 1),
        )
        sorted_layers = FIFOValuation.sort_layers_by_date([layer1, layer2])
        assert sorted_layers[0].purchase_date == date(2025, 1, 1)
        assert sorted_layers[1].purchase_date == date(2025, 1, 5)

    def test_remove_empty_layers(self) -> None:
        layer1 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("10"), remaining_quantity=Decimal("0"),
            unit_cost=Decimal("100"), purchase_date=date.today(),
        )
        layer2 = FIFOLayer(
            item_id=uuid4(), quantity=Decimal("5"), remaining_quantity=Decimal("5"),
            unit_cost=Decimal("110"), purchase_date=date.today(),
        )
        filtered = FIFOValuation.remove_empty_layers([layer1, layer2])
        assert len(filtered) == 1
        assert filtered[0].remaining_quantity == Decimal("5")


# =============================================================================
# Tests for LIFOValuation
# =============================================================================


class TestLIFOValuation:
    def test_calculate_value(self) -> None:
        valuation = LIFOValuation()
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8")),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7")
        assert result.total_value == Decimal("700.00")
        assert result.unit_cost == Decimal("100.00")
        assert result.method == ValuationMethodType.LIFO

    def test_calculate_cogs(self) -> None:
        valuation = LIFOValuation()
        inbound = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        outbound = [MockMovement.outbound("3", date(2025, 1, 10), Decimal("8"))]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("850.00")


# =============================================================================
# Cross-strategy tests: same scenario exercised against each strategy class.
#
# These replace what used to be several near-identical, copy-pasted tests
# (one per strategy) with a single parametrized test per behavior. This keeps
# every strategy individually covered while removing the structural
# duplication, and picks up a couple of previously-untested combinations
# along the way (e.g. MovingAverageValuation's "no inventory" error path).
# =============================================================================


class TestCalculateCostAcrossStrategies:
    @pytest.mark.parametrize(
        "strategy, expected",
        [
            (FIFOValuation(), Decimal("700.00")),
            (LIFOValuation(), Decimal("750.00")),
            (AverageValuation(), Decimal("723.33")),
            (WeightedAverageValuation(), Decimal("723.33")),
            (MovingAverageValuation(), Decimal("723.33")),
            (SpecificIdentificationValuation(), Decimal("700.00")),
        ],
        ids=["fifo", "lifo", "average", "weighted_average", "moving_average", "specific_id"],
    )
    def test_calculate_cost_seven_units(
        self, strategy: ValuationMethodStrategy, expected: Decimal
    ) -> None:
        assert strategy.calculate_cost(_fifo_layers(), Decimal("7")) == expected

    @pytest.mark.parametrize(
        "strategy",
        [FIFOValuation(), LIFOValuation(), SpecificIdentificationValuation()],
        ids=["fifo", "lifo", "specific_id"],
    )
    def test_calculate_cost_insufficient_inventory_raises(
        self, strategy: ValuationMethodStrategy
    ) -> None:
        layers = [{"quantity": Decimal("5"), "unit_cost": Decimal("100")}]
        with pytest.raises(ValueError, match="Not enough inventory"):
            strategy.calculate_cost(layers, Decimal("10"))

    @pytest.mark.parametrize(
        "strategy, match",
        [
            (AverageValuation(), "No inventory available"),
            (MovingAverageValuation(), "No inventory available"),
            (StandardCostValuation(), "Standard cost not available"),
        ],
        ids=["average", "moving_average", "standard"],
    )
    def test_calculate_cost_raises_when_no_inventory_data(
        self, strategy: ValuationMethodStrategy, match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            strategy.calculate_cost([], Decimal("5"))


class TestCalculateCogsAcrossStrategies:
    @pytest.mark.parametrize(
        "strategy, expected",
        [
            (FIFOValuation(), Decimal("800.00")),
            (LIFOValuation(), Decimal("850.00")),
            (AverageValuation(), Decimal("826.67")),
            (MovingAverageValuation(), Decimal("826.67")),
        ],
        ids=["fifo", "lifo", "average", "moving_average"],
    )
    def test_calculate_cogs_single_outbound(
        self, strategy: ValuationMethodStrategy, expected: Decimal
    ) -> None:
        inbound = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        outbound = [MockMovement.outbound("3", date(2025, 1, 10), Decimal("8"))]
        assert strategy.calculate_cogs(outbound, inbound) == expected


# =============================================================================
# Tests for AverageValuation / WeightedAverageValuation
# =============================================================================


class TestAverageValuation:
    def test_calculate_value(self) -> None:
        valuation = AverageValuation()
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8")),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("723.33")
        assert result.unit_cost == Decimal("103.33")
        assert result.method == ValuationMethodType.AVERAGE


class TestWeightedAverageValuation:
    def test_calculate_value_uses_average_method_label(self) -> None:
        valuation = WeightedAverageValuation()
        movements = [MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100"))]
        result = valuation.calculate_value(movements)
        assert result.method == ValuationMethodType.AVERAGE

    def test_is_subclass_of_average_valuation(self) -> None:
        assert issubclass(WeightedAverageValuation, AverageValuation)


# =============================================================================
# Tests for MovingAverageValuation
# =============================================================================


class TestMovingAverageValuation:
    def test_calculate_value(self) -> None:
        valuation = MovingAverageValuation()
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100")),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110")),
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8")),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("723.33")
        assert result.unit_cost == Decimal("103.33")
        assert result.method == ValuationMethodType.MOVING_AVERAGE


# =============================================================================
# Tests for SpecificIdentificationValuation
# =============================================================================


class TestSpecificIdentificationValuation:
    def test_calculate_value(self) -> None:
        valuation = SpecificIdentificationValuation()
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), batch_number="B1"),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), batch_number="B2"),
            MockMovement.outbound("3", date(2025, 1, 10), Decimal("8"), batch_number="B1"),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("7.000")
        assert result.total_value == Decimal("750.00")
        assert result.unit_cost == Decimal("107.14")
        assert result.method == ValuationMethodType.SPECIFIC_ID

    @pytest.mark.parametrize(
        "outbound_batch, outbound_qty, expected",
        [
            ("B1", Decimal("8"), Decimal("800.00")),
            # No batch match -> falls back to simple average of inbound unit
            # costs: (100 + 110) / 2 = 105
            ("UNKNOWN", Decimal("4"), Decimal("420.00")),
        ],
        ids=["batch_match", "unknown_batch_falls_back_to_average"],
    )
    def test_calculate_cogs(
        self, outbound_batch: str, outbound_qty: Decimal, expected: Decimal
    ) -> None:
        valuation = SpecificIdentificationValuation()
        inbound = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("100"), batch_number="B1"),
            MockMovement.inbound("2", date(2025, 1, 5), Decimal("5"), Decimal("110"), batch_number="B2"),
        ]
        outbound = [MockMovement.outbound("3", date(2025, 1, 10), outbound_qty, batch_number=outbound_batch)]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == expected


# =============================================================================
# Tests for StandardCostValuation
# =============================================================================


class TestStandardCostValuation:
    def test_constructor_stores_standard_cost(self) -> None:
        valuation = StandardCostValuation(Decimal("150"))
        assert valuation._standard_cost == Decimal("150")

    def test_constructor_defaults_to_zero(self) -> None:
        valuation = StandardCostValuation()
        assert valuation._standard_cost == Decimal("0")

    def test_calculate_value_with_standard_cost(self) -> None:
        valuation = StandardCostValuation(Decimal("120"))
        movements = [
            MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("0")),
            MockMovement.outbound("2", date(2025, 1, 5), Decimal("5")),
        ]
        result = valuation.calculate_value(movements)
        assert result.total_quantity == Decimal("5.000")
        assert result.total_value == Decimal("600.00")
        assert result.unit_cost == Decimal("120.00")
        assert result.method == ValuationMethodType.STANDARD

    def test_calculate_value_without_standard_cost_raises(self) -> None:
        valuation = StandardCostValuation()  # standard_cost = 0
        movements = [MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("0"))]
        with pytest.raises(ValueError, match="Standard cost must be provided"):
            valuation.calculate_value(movements)

    def test_calculate_cogs_with_standard_cost(self) -> None:
        valuation = StandardCostValuation(Decimal("100"))
        inbound = [MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("90"))]
        outbound = [MockMovement.outbound("2", date(2025, 1, 5), Decimal("5"))]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("500.00")

    def test_calculate_cogs_derives_cost_when_standard_missing(self) -> None:
        valuation = StandardCostValuation()  # standard_cost = 0
        inbound = [MockMovement.inbound("1", date(2025, 1, 1), Decimal("10"), Decimal("90"))]
        outbound = [MockMovement.outbound("2", date(2025, 1, 5), Decimal("5"))]
        cogs = valuation.calculate_cogs(outbound, inbound)
        assert cogs == Decimal("450.00")

    def test_calculate_cogs_no_inbound_returns_zero(self) -> None:
        valuation = StandardCostValuation()
        assert valuation.calculate_cogs([], []) == Decimal("0")

    def test_calculate_cost_with_explicit_standard_cost(self) -> None:
        valuation = StandardCostValuation(Decimal("120"))
        cost = valuation.calculate_cost([], Decimal("10"))
        assert cost == Decimal("1200.00")

    def test_calculate_cost_derives_from_layers_when_standard_missing(self) -> None:
        valuation = StandardCostValuation()
        cost = valuation.calculate_cost(_fifo_layers(), Decimal("5"))
        assert cost == Decimal("516.67")


# =============================================================================
# Tests for ValuationMethodFactory
# =============================================================================


class TestValuationMethodFactory:
    @pytest.mark.parametrize(
        "method_type, expected_cls",
        [
            (ValuationMethodType.FIFO, FIFOValuation),
            (ValuationMethodType.LIFO, LIFOValuation),
            (ValuationMethodType.AVERAGE, WeightedAverageValuation),
            (ValuationMethodType.WEIGHTED_AVERAGE, WeightedAverageValuation),
            (ValuationMethodType.MOVING_AVERAGE, MovingAverageValuation),
            (ValuationMethodType.SPECIFIC_ID, SpecificIdentificationValuation),
        ],
    )
    def test_get_method_returns_expected_strategy(
        self, method_type: ValuationMethodType, expected_cls: type
    ) -> None:
        method = ValuationMethodFactory.get_method(method_type)
        assert isinstance(method, expected_cls)

    def test_get_method_standard_passes_through_standard_cost(self) -> None:
        method = ValuationMethodFactory.get_method(ValuationMethodType.STANDARD, Decimal("200"))
        assert isinstance(method, StandardCostValuation)
        assert method._standard_cost == Decimal("200")

    @pytest.mark.parametrize(
        "name, expected_cls",
        [
            ("fifo", FIFOValuation),
            ("LIFO", LIFOValuation),
            ("average", WeightedAverageValuation),
            ("moving_average", MovingAverageValuation),
            ("specific_id", SpecificIdentificationValuation),
            ("unknown_method_name", FIFOValuation),
        ],
    )
    def test_get_method_by_name(self, name: str, expected_cls: type) -> None:
        assert isinstance(ValuationMethodFactory.get_method_by_name(name), expected_cls)

    def test_get_method_by_name_standard_passes_through_standard_cost(self) -> None:
        method = ValuationMethodFactory.get_method_by_name("standard", Decimal("150"))
        assert isinstance(method, StandardCostValuation)
        assert method._standard_cost == Decimal("150")


# =============================================================================
# Tests for FifoValuation (simple test-helper class)
# =============================================================================


class TestFifoValuation:
    def test_constructor_sorts_transactions_by_date(self) -> None:
        transactions = [
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
        ]
        fifo = FifoValuation(transactions)
        assert [layer["date"] for layer in fifo._inbound] == [date(2025, 1, 1), date(2025, 1, 5)]

    @pytest.mark.parametrize(
        "quantity, expected",
        [
            (Decimal("8"), Decimal("800.00")),
            (Decimal("12"), Decimal("1220.00")),
        ],
        ids=["within_first_layer", "spanning_two_layers"],
    )
    def test_calculate_cogs(self, quantity: Decimal, expected: Decimal) -> None:
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        assert fifo.calculate_cogs(quantity) == expected

    def test_calculate_cogs_not_enough_raises(self) -> None:
        transactions = [(date(2025, 1, 1), Decimal("10"), Decimal("100"))]
        fifo = FifoValuation(transactions)
        with pytest.raises(ValueError, match="Not enough inventory"):
            fifo.calculate_cogs(Decimal("15"))

    def test_get_remaining_before_any_consumption(self) -> None:
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        remaining = fifo.get_remaining()
        assert remaining.quantity == Decimal("15")
        assert remaining.value == Decimal("1550")

    def test_get_remaining_after_consumption(self) -> None:
        transactions = [
            (date(2025, 1, 1), Decimal("10"), Decimal("100")),
            (date(2025, 1, 5), Decimal("5"), Decimal("110")),
        ]
        fifo = FifoValuation(transactions)
        fifo.calculate_cogs(Decimal("8"))
        remaining = fifo.get_remaining()
        assert remaining.quantity == Decimal("7")
        assert remaining.value == Decimal("750")


# =============================================================================
# Tests for get_valuation_method helper
# =============================================================================


class TestGetValuationMethod:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("FIFO", ValuationMethodType.FIFO),
            ("LIFO", ValuationMethodType.LIFO),
            ("AVERAGE", ValuationMethodType.AVERAGE),
            ("MOVING_AVERAGE", ValuationMethodType.MOVING_AVERAGE),
            ("SPECIFIC_ID", ValuationMethodType.SPECIFIC_ID),
            ("WEIGHTED_AVERAGE", ValuationMethodType.WEIGHTED_AVERAGE),
            ("STANDARD", ValuationMethodType.STANDARD),
            ("fifo", ValuationMethodType.FIFO),
            ("unknown_name", ValuationMethodType.FIFO),
        ],
        ids=[
            "fifo_upper", "lifo_upper", "average_upper", "moving_average_upper",
            "specific_id_upper", "weighted_average_upper", "standard_upper",
            "fifo_lower", "unknown_defaults_to_fifo",
        ],
    )
    def test_get_valuation_method(self, name: str, expected: ValuationMethodType) -> None:
        assert get_valuation_method(name) == expected
