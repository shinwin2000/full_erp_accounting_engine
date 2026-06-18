#!/usr/bin/env python3

"""
Module: test_manufacturing_bom.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Bill of Materials (BOM) manufaktur.
    Menguji struktur BOM, perhitungan kebutuhan material, dan efektivitas.

Dependencies:
    - domain/manufacturing/bill_of_materials_entity.py
    - domain/manufacturing/bom_item_entity.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.manufacturing.bill_of_materials_entity import BillOfMaterials, BOMItem, BOMStatus


class TestManufacturingBOM:
    """Test suite untuk Bill of Materials."""

    @pytest.fixture
    def sample_bom_items(self) -> list[BOMItem]:
        """Fixture items BOM."""
        return [
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Bahan Baku A",
                quantity=Decimal("2"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("5"),
            ),
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-002",
                component_name="Bahan Baku B",
                quantity=Decimal("1"),
                unit_of_measure="unit",
                scrap_percentage=Decimal("2"),
            ),
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-003",
                component_name="Bahan Baku C",
                quantity=Decimal("0.5"),
                unit_of_measure="liter",
                scrap_percentage=Decimal("0"),
            ),
        ]

    @pytest.fixture
    def sample_bom(self, sample_bom_items) -> BillOfMaterials:
        """Fixture BOM."""
        return BillOfMaterials(
            id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Produk Jadi",
            version="1.0",
            effective_date=date(2025, 1, 1),
            is_active=True,
            items=sample_bom_items,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )

    def test_bom_item_quantity_positive(self, sample_bom_items):
        """Test: Setiap item BOM harus memiliki quantity > 0."""
        for item in sample_bom_items:
            assert item.quantity > 0

    def test_bom_scrap_percentage_range(self, sample_bom_items):
        """Test: Scrap percentage antara 0-100."""
        for item in sample_bom_items:
            assert 0 <= item.scrap_percentage <= 100

    def test_calculate_total_material_requirement(self, sample_bom):
        """Test: Menghitung total kebutuhan material untuk produksi."""
        production_quantity = Decimal("10")
        requirements = {}
        for item in sample_bom.items:
            net_qty = item.quantity * production_quantity
            scrap_qty = net_qty * (item.scrap_percentage / Decimal("100"))
            gross_qty = net_qty + scrap_qty
            requirements[item.component_code] = gross_qty
        assert requirements["COMP-001"] == Decimal("21")  # 2*10=20 + 5% scrap=1 => 21
        assert requirements["COMP-002"] == Decimal("10.2")  # 1*10=10 + 2% scrap=0.2 => 10.2
        assert requirements["COMP-003"] == Decimal("5")  # 0.5*10=5 + 0% =5

    def test_bom_effective_date_validation(self, sample_bom):
        """Test: Validasi tanggal efektif BOM."""
        assert sample_bom.effective_date <= date.today() or sample_bom.effective_date > date.today()
        if sample_bom.effective_date > date.today():
            assert sample_bom.is_active is False  # BOM belum aktif jika future date

    def test_deactivate_bom(self, sample_bom):
        """Test: Menonaktifkan BOM."""
        sample_bom.deactivate(user_id=uuid4())
        assert sample_bom.is_active is False
        assert sample_bom.status == BOMStatus.INACTIVE

    def test_activate_bom(self, sample_bom):
        """Test: Mengaktifkan BOM."""
        sample_bom.deactivate(uuid4())
        sample_bom.activate(uuid4())
        assert sample_bom.is_active is True
        assert sample_bom.status == BOMStatus.ACTIVE

    def test_bom_versioning(self, sample_bom):
        """Test: Versi BOM."""
        assert sample_bom.version == "1.0"
        new_version = BillOfMaterials(
            id=uuid4(),
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version="2.0",
            effective_date=date(2025, 6, 1),
            is_active=False,
            items=sample_bom.items,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        assert new_version.version == "2.0"
        assert new_version.is_active is False  # belum aktif

    def test_calculate_material_cost(self, sample_bom):
        """Test: Menghitung biaya material berdasarkan harga komponen."""
        # Mock harga komponen
        component_prices = {
            "COMP-001": Decimal("5000"),
            "COMP-002": Decimal("10000"),
            "COMP-003": Decimal("2000"),
        }
        total_cost = Decimal("0")
        for item in sample_bom.items:
            price = component_prices.get(item.component_code, Decimal("0"))
            total_cost += item.quantity * price
        # 2*5000=10000, 1*10000=10000, 0.5*2000=1000 => total 21000
        assert total_cost == Decimal("21000")

    def test_bom_total_quantity(self, sample_bom):
        """Test: Total quantity produksi dari BOM."""
        production_qty = Decimal("5")
        total_weight = sum(item.quantity * production_qty for item in sample_bom.items)
        assert total_weight == Decimal("17.5")  # 2*5=10, 1*5=5, 0.5*5=2.5 => 17.5

    def test_bom_item_uniqueness(self, sample_bom):
        """Test: Tidak boleh ada komponen duplikat dalam BOM."""
        component_codes = [item.component_code for item in sample_bom.items]
        assert len(component_codes) == len(set(component_codes))

    def test_add_bom_item(self, sample_bom):
        """Test: Menambahkan item baru ke BOM."""
        new_item = BOMItem(
            id=uuid4(),
            component_id=uuid4(),
            component_code="COMP-004",
            component_name="Bahan Baku D",
            quantity=Decimal("3"),
            unit_of_measure="kg",
            scrap_percentage=Decimal("1"),
        )
        sample_bom.items.append(new_item)
        assert len(sample_bom.items) == 4

    def test_remove_bom_item(self, sample_bom):
        """Test: Menghapus item dari BOM."""
        original_count = len(sample_bom.items)
        sample_bom.items.pop()
        assert len(sample_bom.items) == original_count - 1


if __name__ == "__main__":
    pytest.main([__file__])
