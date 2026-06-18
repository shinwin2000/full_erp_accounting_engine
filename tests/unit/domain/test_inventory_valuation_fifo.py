#!/usr/bin/env python3

"""
Module: test_inventory_valuation_fifo.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk inventory valuation metode FIFO (First-In-First-Out).
    Menguji perhitungan cost of goods sold, persediaan akhir, dan layer management.

Dependencies:
    - domain/inventory/valuation_method.py (FIFOValuation)
    - domain/inventory/fifo_layer_entity.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.inventory.fifo_layer_entity import FIFOLayer
from domain.inventory.valuation_method import FIFOValuation


class TestInventoryValuationFIFO:
    """Test suite untuk inventory valuation metode FIFO."""

    @pytest.fixture
    def fifo_engine(self) -> FIFOValuation:
        """Fixture FIFO valuation engine."""
        return FIFOValuation()

    @pytest.fixture
    def sample_layers(self) -> list[FIFOLayer]:
        """Fixture layers FIFO sampel."""
        return [
            FIFOLayer(
                id=uuid4(),
                item_id=uuid4(),
                quantity=Decimal("100"),
                unit_cost=Decimal("10000"),
                remaining_quantity=Decimal("100"),
                purchase_date=date(2025, 1, 15),
                layer_number=1,
            ),
            FIFOLayer(
                id=uuid4(),
                item_id=uuid4(),
                quantity=Decimal("50"),
                unit_cost=Decimal("11000"),
                remaining_quantity=Decimal("50"),
                purchase_date=date(2025, 2, 10),
                layer_number=2,
            ),
            FIFOLayer(
                id=uuid4(),
                item_id=uuid4(),
                quantity=Decimal("80"),
                unit_cost=Decimal("10500"),
                remaining_quantity=Decimal("80"),
                purchase_date=date(2025, 3, 5),
                layer_number=3,
            ),
        ]

    def test_initial_layers(self, fifo_engine, sample_layers):
        """Test: Inisialisasi layers."""
        assert len(sample_layers) == 3
        assert sample_layers[0].unit_cost == Decimal("10000")
        assert sample_layers[1].unit_cost == Decimal("11000")
        assert sample_layers[2].unit_cost == Decimal("10500")

    def test_consume_from_fifo_single_layer(self, fifo_engine, sample_layers):
        """Test: Konsumsi dari layer pertama (FIFO)."""
        quantity_to_consume = Decimal("80")
        consumed_cost, remaining_layers = fifo_engine.consume(
            layers=sample_layers, quantity=quantity_to_consume
        )
        expected_cost = Decimal("80") * Decimal("10000")  # 800.000
        assert consumed_cost == expected_cost
        # Layer pertama sisa 20, layer lain tetap
        assert remaining_layers[0].remaining_quantity == Decimal("20")
        assert remaining_layers[1].remaining_quantity == Decimal("50")
        assert remaining_layers[2].remaining_quantity == Decimal("80")

    def test_consume_multiple_layers(self, fifo_engine, sample_layers):
        """Test: Konsumsi melebihi layer pertama, menggunakan layer kedua."""
        quantity_to_consume = Decimal("120")
        consumed_cost, remaining_layers = fifo_engine.consume(
            layers=sample_layers, quantity=quantity_to_consume
        )
        # Layer pertama habis: 100 * 10000 = 1.000.000
        # Layer kedua sebagian: 20 * 11000 = 220.000
        expected_cost = Decimal("1000000") + Decimal("220000")
        assert consumed_cost == expected_cost
        assert remaining_layers[0].remaining_quantity == Decimal("0")
        assert remaining_layers[1].remaining_quantity == Decimal("30")
        assert remaining_layers[2].remaining_quantity == Decimal("80")

    def test_consume_exact_layer_boundary(self, fifo_engine, sample_layers):
        """Test: Konsumsi tepat menghabiskan layer pertama."""
        quantity_to_consume = Decimal("100")
        consumed_cost, remaining_layers = fifo_engine.consume(
            layers=sample_layers, quantity=quantity_to_consume
        )
        expected_cost = Decimal("100") * Decimal("10000")  # 1.000.000
        assert consumed_cost == expected_cost
        assert remaining_layers[0].remaining_quantity == Decimal("0")
        assert remaining_layers[1].remaining_quantity == Decimal("50")
        assert remaining_layers[2].remaining_quantity == Decimal("80")

    def test_consume_all_layers(self, fifo_engine, sample_layers):
        """Test: Konsumsi semua stok."""
        total_quantity = sum(l.remaining_quantity for l in sample_layers)
        quantity_to_consume = total_quantity
        consumed_cost, remaining_layers = fifo_engine.consume(
            layers=sample_layers, quantity=quantity_to_consume
        )
        expected_cost = (100 * 10000) + (50 * 11000) + (80 * 10500)
        expected_cost = Decimal("1000000") + Decimal("550000") + Decimal("840000")
        assert consumed_cost == expected_cost
        assert all(l.remaining_quantity == 0 for l in remaining_layers)

    def test_consume_exceeds_total_raises_error(self, fifo_engine, sample_layers):
        """Test: Konsumsi melebihi total stok harus error."""
        total_quantity = sum(l.remaining_quantity for l in sample_layers)
        with pytest.raises(ValueError, match="exceeds available quantity"):
            fifo_engine.consume(sample_layers, total_quantity + Decimal("1"))

    def test_add_new_layer(self, fifo_engine, sample_layers):
        """Test: Menambahkan layer baru (pembelian baru)."""
        new_layer = FIFOLayer(
            id=uuid4(),
            item_id=uuid4(),
            quantity=Decimal("60"),
            unit_cost=Decimal("12000"),
            remaining_quantity=Decimal("60"),
            purchase_date=date(2025, 4, 1),
            layer_number=4,
        )
        updated_layers = fifo_engine.add_layer(sample_layers, new_layer)
        assert len(updated_layers) == 4
        assert updated_layers[-1].unit_cost == Decimal("12000")

    def test_get_current_cost_from_oldest_layer(self, fifo_engine, sample_layers):
        """Test: Mendapatkan biaya dari layer tertua (untuk costing outbound)."""
        current_cost = fifo_engine.get_current_cost(sample_layers)
        assert current_cost == Decimal("10000")

    def test_get_current_cost_empty_layers_returns_zero(self, fifo_engine):
        """Test: Jika tidak ada layer, current cost = 0."""
        current_cost = fifo_engine.get_current_cost([])
        assert current_cost == Decimal("0")

    def test_remaining_value_calculation(self, fifo_engine, sample_layers):
        """Test: Menghitung total nilai persediaan yang tersisa."""
        remaining_value = fifo_engine.get_remaining_value(sample_layers)
        expected = (100 * 10000) + (50 * 11000) + (80 * 10500)
        assert remaining_value == expected

    def test_layer_order_maintained(self, fifo_engine):
        """Test: Layer diurutkan berdasarkan tanggal pembelian."""
        layer1 = FIFOLayer(
            id=uuid4(),
            item_id=uuid4(),
            quantity=10,
            unit_cost=100,
            remaining_quantity=10,
            purchase_date=date(2025, 3, 1),
            layer_number=1,
        )
        layer2 = FIFOLayer(
            id=uuid4(),
            item_id=uuid4(),
            quantity=20,
            unit_cost=90,
            remaining_quantity=20,
            purchase_date=date(2025, 2, 1),
            layer_number=2,
        )
        layer3 = FIFOLayer(
            id=uuid4(),
            item_id=uuid4(),
            quantity=15,
            unit_cost=110,
            remaining_quantity=15,
            purchase_date=date(2025, 1, 1),
            layer_number=3,
        )
        unsorted = [layer1, layer2, layer3]
        sorted_layers = fifo_engine.sort_layers_by_date(unsorted)
        # Urutan seharusnya layer3 (Jan), layer2 (Feb), layer1 (Mar)
        assert sorted_layers[0].purchase_date == date(2025, 1, 1)
        assert sorted_layers[1].purchase_date == date(2025, 2, 1)
        assert sorted_layers[2].purchase_date == date(2025, 3, 1)

    def test_remove_zero_quantity_layers(self, fifo_engine, sample_layers):
        """Test: Layer dengan remaining_quantity = 0 dihapus."""
        sample_layers[0].remaining_quantity = Decimal("0")
        cleaned = fifo_engine.remove_empty_layers(sample_layers)
        assert len(cleaned) == 2
        assert cleaned[0].layer_number == 2

    def test_fifo_with_partial_layer_consumption_tracking(self, fifo_engine, sample_layers):
        """Test: Pelacakan partial consumption pada layer."""
        _consumed, remaining = fifo_engine.consume(sample_layers, Decimal("75"))
        assert remaining[0].remaining_quantity == Decimal("25")  # 100 - 75 = 25
        assert remaining[0].unit_cost == Decimal("10000")
        # Konsumsi tambahan 30 dari sisa layer pertama
        _consumed2, remaining2 = fifo_engine.consume(remaining, Decimal("30"))
        # Layer pertama habis (25), layer kedua terpakai 5
        assert remaining2[0].remaining_quantity == Decimal("0")
        assert remaining2[1].remaining_quantity == Decimal("45")  # 50 - 5 = 45


if __name__ == "__main__":
    pytest.main([__file__])
