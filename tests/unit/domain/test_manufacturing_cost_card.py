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

    # ============================================================================
    # Test untuk BOM Item
    # ============================================================================

    def test_bom_item_quantity_positive(self, sample_bom_items):
        """Test: Setiap item BOM harus memiliki quantity > 0."""
        for item in sample_bom_items:
            assert item.quantity > 0

    def test_bom_item_quantity_zero(self):
        """Test: Quantity 0 harus di-reject."""
        with pytest.raises(ValueError, match="Quantity must be greater than zero"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Bahan Baku A",
                quantity=Decimal("0"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("5"),
            )

    def test_bom_item_quantity_negative(self):
        """Test: Quantity negatif harus di-reject."""
        with pytest.raises(ValueError, match="Quantity must be greater than zero"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Bahan Baku A",
                quantity=Decimal("-2"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("5"),
            )

    def test_bom_scrap_percentage_range(self, sample_bom_items):
        """Test: Scrap percentage antara 0-100."""
        for item in sample_bom_items:
            assert 0 <= item.scrap_percentage <= 100

    def test_bom_scrap_percentage_out_of_range(self):
        """Test: Scrap percentage di luar rentang 0-100 harus di-reject."""
        with pytest.raises(ValueError, match="Scrap percentage must be between 0 and 100"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Bahan Baku A",
                quantity=Decimal("2"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("101"),
            )

        with pytest.raises(ValueError, match="Scrap percentage must be between 0 and 100"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Bahan Baku A",
                quantity=Decimal("2"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("-5"),
            )

    # ============================================================================
    # Test untuk perhitungan BOM
    # ============================================================================

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

    # ============================================================================
    # Test untuk status dan siklus hidup BOM
    # ============================================================================

    def test_deactivate_bom(self, sample_bom):
        """Test: Menonaktifkan BOM."""
        sample_bom.deactivate(user_id=uuid4())
        assert sample_bom.is_active is False
        assert sample_bom.status == BOMStatus.INACTIVE

    def test_activate_bom(self, sample_bom):
        """Test: Mengaktifkan BOM."""
        sample_bom.deactivate(uuid4())
        # BOM harus di-deactivate dulu
        assert sample_bom.is_active is False
        sample_bom.activate(uuid4())
        assert sample_bom.is_active is True
        assert sample_bom.status == BOMStatus.ACTIVE

    def test_activate_inactive_bom(self):
        """Test: Aktivasi BOM yang tidak aktif."""
        bom = BillOfMaterials(
            id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Produk Jadi",
            version="1.0",
            effective_date=date.today(),
            is_active=False,
            items=[],
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        bom.activate(uuid4())
        assert bom.is_active is True
        assert bom.status == BOMStatus.ACTIVE

    def test_activate_already_active_bom(self, sample_bom):
        """Test: Aktivasi BOM yang sudah aktif harus raise error."""
        with pytest.raises(ValueError, match="BOM is already active"):
            sample_bom.activate(uuid4())

    def test_deactivate_inactive_bom(self):
        """Test: Deaktivasi BOM yang sudah tidak aktif."""
        bom = BillOfMaterials(
            id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Produk Jadi",
            version="1.0",
            effective_date=date.today(),
            is_active=False,
            items=[],
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        with pytest.raises(ValueError, match="BOM is already inactive"):
            bom.deactivate(uuid4())

    def test_bom_effective_date_validation(self, sample_bom):
        """Test: Validasi tanggal efektif BOM."""
        # BOM dengan effective date di masa depan harus tidak aktif
        future_bom = BillOfMaterials(
            id=uuid4(),
            product_id=uuid4(),
            product_code="PROD-002",
            product_name="Future Product",
            version="1.0",
            effective_date=date(2030, 6, 1),
            is_active=True,
            items=[],
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        # Simulasi validasi di service layer
        if future_bom.effective_date > date.today():
            future_bom.is_active = False
        assert future_bom.is_active is False

    # ============================================================================
    # Test untuk versi BOM
    # ============================================================================

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

    # ============================================================================
    # Test untuk manajemen item BOM
    # ============================================================================

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
        assert any(item.component_code == "COMP-004" for item in sample_bom.items)

    def test_remove_bom_item(self, sample_bom):
        """Test: Menghapus item dari BOM."""
        original_count = len(sample_bom.items)
        sample_bom.items.pop()
        assert len(sample_bom.items) == original_count - 1

    def test_bom_item_null_handling(self):
        """Test: Null handling pada BOMItem."""
        with pytest.raises(ValueError, match="component_code cannot be empty"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="",
                component_name="Test Component",
                quantity=Decimal("1"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("0"),
            )

        with pytest.raises(ValueError, match="component_name cannot be empty"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="",
                quantity=Decimal("1"),
                unit_of_measure="kg",
                scrap_percentage=Decimal("0"),
            )

        with pytest.raises(ValueError, match="unit_of_measure cannot be empty"):
            BOMItem(
                id=uuid4(),
                component_id=uuid4(),
                component_code="COMP-001",
                component_name="Test Component",
                quantity=Decimal("1"),
                unit_of_measure="",
                scrap_percentage=Decimal("0"),
            )

    # ============================================================================
    # Test untuk validasi BOM
    # ============================================================================

    def test_bom_validation_empty_items(self):
        """Test: BOM tanpa items harus di-reject."""
        with pytest.raises(ValueError, match="BOM must contain at least one item"):
            BillOfMaterials(
                id=uuid4(),
                product_id=uuid4(),
                product_code="PROD-001",
                product_name="Test Product",
                version="1.0",
                effective_date=date.today(),
                is_active=True,
                items=[],
                created_by=uuid4(),
                created_at=datetime.now(UTC),
                updated_at=None,
            )

    def test_bom_validation_version_format(self):
        """Test: Validasi format versi BOM."""
        item = BOMItem(
            id=uuid4(),
            component_id=uuid4(),
            component_code="COMP-001",
            component_name="Test",
            quantity=Decimal("1"),
            unit_of_measure="kg",
            scrap_percentage=Decimal("0"),
        )
        with pytest.raises(ValueError, match="Version must follow semver format"):
            BillOfMaterials(
                id=uuid4(),
                product_id=uuid4(),
                product_code="PROD-001",
                product_name="Test",
                version="invalid",
                effective_date=date.today(),
                is_active=True,
                items=[item],
                created_by=uuid4(),
                created_at=datetime.now(UTC),
                updated_at=None,
            )

    # ============================================================================
    # Test untuk serialisasi
    # ============================================================================

    def test_bom_to_dict(self, sample_bom):
        """Test: Serialisasi BOM ke dictionary."""
        bom_dict = sample_bom.to_dict()
        assert bom_dict["product_code"] == "PROD-001"
        assert bom_dict["version"] == "1.0"
        assert len(bom_dict["items"]) == 3
        assert bom_dict["items"][0]["component_code"] == "COMP-001"
        assert bom_dict["items"][0]["quantity"] == "2"
        assert bom_dict["items"][0]["scrap_percentage"] == "5"

    def test_bom_item_to_dict(self, sample_bom_items):
        """Test: Serialisasi BOMItem ke dictionary."""
        item_dict = sample_bom_items[0].to_dict()
        assert item_dict["component_code"] == "COMP-001"
        assert item_dict["quantity"] == "2"
        assert item_dict["scrap_percentage"] == "5"

    # ============================================================================
    # Test untuk MRP calculations
    # ============================================================================

    def test_mrp_net_requirement(self, sample_bom):
        """Test: Perhitungan net requirement untuk MRP."""
        production_qty = Decimal("100")
        on_hand_inventory = {
            "COMP-001": Decimal("50"),
            "COMP-002": Decimal("20"),
            "COMP-003": Decimal("100"),
        }

        net_requirements = {}
        for item in sample_bom.items:
            gross = item.quantity * production_qty
            net = max(
                gross - on_hand_inventory.get(item.component_code, Decimal("0")), Decimal("0")
            )
            net_requirements[item.component_code] = net

        assert net_requirements["COMP-001"] == Decimal("150")  # (2*100=200) - 50 = 150
        assert net_requirements["COMP-002"] == Decimal("80")  # (1*100=100) - 20 = 80
        assert net_requirements["COMP-003"] == Decimal("0")  # (0.5*100=50) - 100 = -50 -> 0

    # ============================================================================
    # Test untuk kalkulasi biaya dengan scrap
    # ============================================================================

    def test_cost_calculation_with_scrap(self, sample_bom):
        """Test: Kalkulasi biaya dengan mempertimbangkan scrap."""
        component_prices = {
            "COMP-001": Decimal("5000"),
            "COMP-002": Decimal("10000"),
            "COMP-003": Decimal("2000"),
        }
        production_qty = Decimal("100")

        total_cost = Decimal("0")
        for item in sample_bom.items:
            net_qty = item.quantity * production_qty
            scrap_qty = net_qty * (item.scrap_percentage / Decimal("100"))
            gross_qty = net_qty + scrap_qty
            price = component_prices.get(item.component_code, Decimal("0"))
            total_cost += gross_qty * price

        # Perhitungan manual:
        # COMP-001: 2*100=200 + 5% scrap=10 → 210 * 5000 = 1,050,000
        # COMP-002: 1*100=100 + 2% scrap=2 → 102 * 10000 = 1,020,000
        # COMP-003: 0.5*100=50 + 0% scrap=0 → 50 * 2000 = 100,000
        # Total = 2,170,000
        assert total_cost == Decimal("2170000")

    # ============================================================================
    # Test untuk BOM comparison
    # ============================================================================

    def test_bom_comparison(self, sample_bom):
        """Test: Perbandingan antara dua BOM."""
        same_bom = BillOfMaterials(
            id=sample_bom.id,
            product_id=sample_bom.product_id,
            product_code=sample_bom.product_code,
            product_name=sample_bom.product_name,
            version=sample_bom.version,
            effective_date=sample_bom.effective_date,
            is_active=sample_bom.is_active,
            items=sample_bom.items,
            created_by=sample_bom.created_by,
            created_at=sample_bom.created_at,
            updated_at=sample_bom.updated_at,
        )
        assert sample_bom == same_bom

        different_bom = BillOfMaterials(
            id=uuid4(),
            product_id=sample_bom.product_id,
            product_code="PROD-002",
            product_name="Different Product",
            version="2.0",
            effective_date=date.today(),
            is_active=True,
            items=sample_bom.items,
            created_by=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=None,
        )
        assert sample_bom != different_bom


if __name__ == "__main__":
    pytest.main([__file__])
