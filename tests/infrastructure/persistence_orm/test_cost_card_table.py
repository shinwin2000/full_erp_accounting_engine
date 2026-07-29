# tests/infrastructure/persistence_orm/test_cost_card_table.py
"""
Comprehensive tests for infrastructure/persistence_orm/cost_card_table.py.
Covers all properties, methods, and edge cases of CostCardTable.
Uses direct instantiation without a DB session for testing model behavior.
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from infrastructure.persistence_orm.cost_card_table import CostCardTable

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_cost_card():
    """Create a CostCardTable instance with default values."""
    return CostCardTable(
        cost_card_code="CC-001",
        product_id=uuid4(),
        product_name="Test Product",
        effective_date=date(2026, 1, 1),
        expiry_date=date(2026, 12, 31),
        version=1,
        material_cost=Decimal("100.00"),
        labor_cost=Decimal("50.00"),
        overhead_cost=Decimal("25.00"),
        other_cost=Decimal("5.00"),
        total_cost=Decimal("180.00"),
        currency="IDR",
        quantity_base=Decimal("1.00"),
        unit_of_measure="pcs",
        status="draft",
        is_active=True,
        notes="Test notes",
        breakdown=[{"component": "raw material", "cost": 100}],
        legal_entity_id=uuid4(),
        created_by=uuid4(),
    )


@pytest.fixture
def active_cost_card(sample_cost_card):
    """Return an active cost card."""
    card = sample_cost_card
    card.status = "active"
    card.is_active = True
    return card


# ============================================================================
# Tests for Table Metadata
# ============================================================================

class TestCostCardTableMetadata:
    def test_tablename_defined(self):
        assert hasattr(CostCardTable, "__tablename__")
        assert isinstance(CostCardTable.__tablename__, str)
        assert len(CostCardTable.__tablename__) > 0


# ============================================================================
# Tests for Instantiation
# ============================================================================

class TestCostCardTableInstantiation:
    def test_instantiation(self, sample_cost_card):
        assert isinstance(sample_cost_card, CostCardTable)
        assert sample_cost_card.cost_card_code == "CC-001"
        assert sample_cost_card.material_cost == Decimal("100.00")
        assert sample_cost_card.labor_cost == Decimal("50.00")
        assert sample_cost_card.overhead_cost == Decimal("25.00")
        assert sample_cost_card.other_cost == Decimal("5.00")
        assert sample_cost_card.total_cost == Decimal("180.00")
        assert sample_cost_card.quantity_base == Decimal("1.00")
        assert sample_cost_card.status == "draft"
        assert sample_cost_card.is_active is True


# ============================================================================
# Tests for Properties
# ============================================================================

class TestCostCardTableProperties:
    def test_cost_per_unit_with_base_one(self, sample_cost_card):
        # quantity_base = 1, total_cost = 180 => cost_per_unit = 180
        assert sample_cost_card.cost_per_unit == Decimal("180.00")

    def test_cost_per_unit_with_base_two(self, sample_cost_card):
        # quantity_base = 2, total_cost = 180 => cost_per_unit = 90
        sample_cost_card.quantity_base = Decimal("2.00")
        assert sample_cost_card.cost_per_unit == Decimal("90.00")

    def test_cost_per_unit_with_zero_quantity_base(self, sample_cost_card):
        sample_cost_card.quantity_base = Decimal("0")
        assert sample_cost_card.cost_per_unit == Decimal(0)

    def test_is_active_card_true(self, active_cost_card):
        # status="active" and is_active=True -> True
        assert active_cost_card.is_active_card is True

    def test_is_active_card_false_draft(self, sample_cost_card):
        # status="draft" -> False
        assert sample_cost_card.is_active_card is False

    def test_is_active_card_false_inactive(self, sample_cost_card):
        # status="inactive" -> False
        sample_cost_card.status = "inactive"
        sample_cost_card.is_active = False
        assert sample_cost_card.is_active_card is False

    def test_is_active_card_false_obsolete(self, sample_cost_card):
        # status="obsolete" -> False
        sample_cost_card.status = "obsolete"
        sample_cost_card.is_active = False
        assert sample_cost_card.is_active_card is False


# ============================================================================
# Tests for Methods
# ============================================================================

class TestCostCardTableMethods:
    def test_activate_success(self, sample_cost_card):
        sample_cost_card.activate()
        assert sample_cost_card.status == "active"
        assert sample_cost_card.is_active is True
        # Version should be incremented (from 1 to 2)
        assert sample_cost_card.version == 2

    def test_activate_not_draft_raises(self, sample_cost_card):
        sample_cost_card.status = "active"
        with pytest.raises(ValueError, match="Cannot activate cost card with status active"):
            sample_cost_card.activate()

    def test_deactivate(self, active_cost_card):
        active_cost_card.deactivate()
        assert active_cost_card.status == "inactive"
        assert active_cost_card.is_active is False
        # Version should be incremented
        assert active_cost_card.version == 2

    def test_deactivate_from_draft(self, sample_cost_card):
        # Should work even from draft
        sample_cost_card.deactivate()
        assert sample_cost_card.status == "inactive"
        assert sample_cost_card.is_active is False
        assert sample_cost_card.version == 2

    def test_calculate_total(self, sample_cost_card):
        # Set individual costs
        sample_cost_card.material_cost = Decimal("10.00")
        sample_cost_card.labor_cost = Decimal("20.00")
        sample_cost_card.overhead_cost = Decimal("30.00")
        sample_cost_card.other_cost = Decimal("40.00")
        sample_cost_card.total_cost = Decimal("0")  # reset
        initial_version = sample_cost_card.version

        sample_cost_card.calculate_total()

        expected = Decimal("100.00")
        assert sample_cost_card.total_cost == expected
        # Version should be incremented
        assert sample_cost_card.version == initial_version + 1

    def test_calculate_total_with_zeros(self, sample_cost_card):
        sample_cost_card.material_cost = Decimal("0")
        sample_cost_card.labor_cost = Decimal("0")
        sample_cost_card.overhead_cost = Decimal("0")
        sample_cost_card.other_cost = Decimal("0")
        sample_cost_card.total_cost = Decimal("999")  # to verify it gets overwritten
        initial_version = sample_cost_card.version

        sample_cost_card.calculate_total()

        assert sample_cost_card.total_cost == Decimal("0")
        assert sample_cost_card.version == initial_version + 1


# ============================================================================
# Tests for Edge Cases and Additional Coverage
# ============================================================================

class TestCostCardTableEdgeCases:
    def test_cost_per_unit_with_decimal_precision(self, sample_cost_card):
        # Ensure Decimal precision is maintained
        sample_cost_card.quantity_base = Decimal("3.00")
        sample_cost_card.total_cost = Decimal("10.00")
        # 10 / 3 = 3.3333..., but Decimal will retain scale
        # We'll just check that it's a Decimal and roughly correct
        result = sample_cost_card.cost_per_unit
        assert isinstance(result, Decimal)
        # We don't assert exact because of rounding, but we can check approximate
        assert result > Decimal("3.33") and result < Decimal("3.34")

    def test_is_active_card_with_active_false(self, active_cost_card):
        active_cost_card.is_active = False
        assert active_cost_card.is_active_card is False

    def test_activate_after_deactivate_raises(self, sample_cost_card):
        # Once deactivated, status is "inactive", so activate should raise
        sample_cost_card.deactivate()
        with pytest.raises(ValueError, match="Cannot activate cost card with status inactive"):
            sample_cost_card.activate()

    def test_version_increment_on_calculate_total(self, sample_cost_card):
        initial_version = sample_cost_card.version
        sample_cost_card.calculate_total()
        assert sample_cost_card.version == initial_version + 1

    def test_version_increment_on_activate(self, sample_cost_card):
        initial_version = sample_cost_card.version
        sample_cost_card.activate()
        assert sample_cost_card.version == initial_version + 1

    def test_version_increment_on_deactivate(self, active_cost_card):
        initial_version = active_cost_card.version
        active_cost_card.deactivate()
        assert active_cost_card.version == initial_version + 1

    def test_activation_twice_raises(self, sample_cost_card):
        sample_cost_card.activate()
        with pytest.raises(ValueError, match="Cannot activate cost card with status active"):
            sample_cost_card.activate()

    def test_deactivate_already_inactive(self, sample_cost_card):
        sample_cost_card.deactivate()  # now inactive
        # deactivating again should just set to inactive again (it doesn't raise)
        sample_cost_card.deactivate()
        assert sample_cost_card.status == "inactive"
        assert sample_cost_card.is_active is False
        # Version should increment each time
        assert sample_cost_card.version == 3  # initial 1, first deactivate to 2, second to 3
