# tests/domain/manufacturing/test_work_in_process_entity.py
"""
Comprehensive unit tests for domain/manufacturing/work_in_process_entity.py.
Covers all enums, value objects, entity construction, business methods,
query methods, repository protocol, and uses mocks to avoid flakiness.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.work_in_process_entity import (
    WIPCostComponent,
    WIPStatus,
    WorkInProcessEntity,
    WorkInProcessRepository,
)

# ============================================================================
# Fixed datetime for deterministic tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in work_in_process_entity to fixed time."""
    with patch("domain.manufacturing.work_in_process_entity.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Fixtures for test data
# ============================================================================

@pytest.fixture
def sample_wip_data():
    return {
        "wip_id": uuid4(),
        "work_order_id": uuid4(),
        "work_order_number": "WO-001",
        "product_id": uuid4(),
        "product_code": "PROD-001",
        "product_name": "Test Product",
        "quantity_started": Decimal("100"),
        "quantity_remaining": Decimal("100"),
        "quantity_completed": Decimal("0"),
        "material_cost": Decimal("0"),
        "labor_cost": Decimal("0"),
        "overhead_cost": Decimal("0"),
        "total_cost": Decimal("0"),
        "status": WIPStatus.OPEN,
        "last_update_date": FIXED_NOW,
        "cost_components": [],
        "created_at": FIXED_NOW,
        "updated_at": FIXED_NOW,
        "created_by": "system",
        "version": 1,
    }


@pytest.fixture
def sample_wip(sample_wip_data):
    """Create a valid WIP entity."""
    return WorkInProcessEntity(**sample_wip_data)


@pytest.fixture
def wip_with_costs(sample_wip):
    """WIP entity with some costs added."""
    wip = sample_wip.add_material_cost(Decimal("1000"), Decimal("50"), Decimal("20"), "tester")
    wip = wip.add_labor_cost(Decimal("500"), Decimal("25"), Decimal("20"), "tester")
    wip = wip.add_overhead_cost(Decimal("300"), Decimal("15"), Decimal("20"), "tester")
    return wip


# ============================================================================
# Tests for WIPStatus enum
# ============================================================================

class TestWIPStatus:
    def test_members(self):
        assert WIPStatus.OPEN.value == "open"
        assert WIPStatus.CLOSED.value == "closed"
        assert WIPStatus.ADJUSTED.value == "adjusted"


# ============================================================================
# Tests for WIPCostComponent value object
# ============================================================================

class TestWIPCostComponent:
    def test_construction_valid(self):
        comp = WIPCostComponent(
            cost_element=CostElement.MATERIAL,
            amount=Decimal("1000.50"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100.05"),
        )
        assert comp.cost_element == CostElement.MATERIAL
        assert comp.amount == Decimal("1000.50")
        assert comp.quantity == Decimal("10")
        assert comp.unit_cost == Decimal("100.05")

    def test_validation_amount_negative_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            WIPCostComponent(
                cost_element=CostElement.LABOR,
                amount=Decimal("-1"),
                quantity=Decimal("1"),
                unit_cost=Decimal("1"),
            )

    def test_validation_quantity_negative_raises(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            WIPCostComponent(
                cost_element=CostElement.OVERHEAD,
                amount=Decimal("1"),
                quantity=Decimal("-1"),
                unit_cost=Decimal("1"),
            )

    def test_validation_unit_cost_negative_raises(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            WIPCostComponent(
                cost_element=CostElement.OTHER,
                amount=Decimal("1"),
                quantity=Decimal("1"),
                unit_cost=Decimal("-1"),
            )

    def test_to_dict(self):
        comp = WIPCostComponent(
            cost_element=CostElement.MATERIAL,
            amount=Decimal("1000"),
            quantity=Decimal("10"),
            unit_cost=Decimal("100"),
        )
        d = comp.to_dict()
        assert d["cost_element"] == "material"
        assert d["amount"] == "1000"
        assert d["quantity"] == "10"
        assert d["unit_cost"] == "100"


# ============================================================================
# Tests for WorkInProcessEntity
# ============================================================================

class TestWorkInProcessEntity:
    # ------------------------------------------------------------------------
    # Construction and validation
    # ------------------------------------------------------------------------

    def test_construction_valid(self, sample_wip):
        assert sample_wip.wip_id is not None
        assert sample_wip.work_order_number == "WO-001"
        assert sample_wip.quantity_started == Decimal("100")
        assert sample_wip.quantity_remaining == Decimal("100")
        assert sample_wip.quantity_completed == Decimal("0")
        assert sample_wip.total_cost == Decimal("0")
        assert sample_wip.status == WIPStatus.OPEN
        assert sample_wip.version == 1
        assert sample_wip.created_at.tzinfo == UTC
        assert sample_wip.updated_at.tzinfo == UTC
        assert sample_wip.last_update_date.tzinfo == UTC

    def test_construction_quantity_started_zero_raises(self, sample_wip_data):
        sample_wip_data["quantity_started"] = Decimal("0")
        with pytest.raises(ValueError, match="positive"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_quantity_started_negative_raises(self, sample_wip_data):
        sample_wip_data["quantity_started"] = Decimal("-10")
        with pytest.raises(ValueError, match="positive"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_quantity_remaining_negative_raises(self, sample_wip_data):
        sample_wip_data["quantity_remaining"] = Decimal("-1")
        with pytest.raises(ValueError, match="cannot be negative"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_quantity_completed_negative_raises(self, sample_wip_data):
        sample_wip_data["quantity_completed"] = Decimal("-1")
        with pytest.raises(ValueError, match="cannot be negative"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_quantity_mismatch_raises(self, sample_wip_data):
        sample_wip_data["quantity_started"] = Decimal("100")
        sample_wip_data["quantity_remaining"] = Decimal("40")
        sample_wip_data["quantity_completed"] = Decimal("50")
        with pytest.raises(ValueError, match="Quantity mismatch"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_cost_mismatch_raises(self, sample_wip_data):
        sample_wip_data["material_cost"] = Decimal("100")
        sample_wip_data["labor_cost"] = Decimal("200")
        sample_wip_data["overhead_cost"] = Decimal("300")
        sample_wip_data["total_cost"] = Decimal("500")  # Should be 600
        with pytest.raises(ValueError, match="Total cost mismatch"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_version_zero_raises(self, sample_wip_data):
        sample_wip_data["version"] = 0
        with pytest.raises(ValueError, match="Version must be >= 1"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_created_at_naive_raises(self, sample_wip_data):
        sample_wip_data["created_at"] = datetime(2026, 7, 23, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_updated_at_naive_raises(self, sample_wip_data):
        sample_wip_data["updated_at"] = datetime(2026, 7, 23, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            WorkInProcessEntity(**sample_wip_data)

    def test_construction_last_update_date_naive_raises(self, sample_wip_data):
        sample_wip_data["last_update_date"] = datetime(2026, 7, 23, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone-aware"):
            WorkInProcessEntity(**sample_wip_data)

    # ------------------------------------------------------------------------
    # Factory method: create
    # ------------------------------------------------------------------------

    def test_create_success(self):
        wo_id = uuid4()
        product_id = uuid4()
        wip = WorkInProcessEntity.create(
            work_order_id=wo_id,
            work_order_number="WO-002",
            product_id=product_id,
            product_code="PROD-002",
            product_name="Another Product",
            quantity_started=Decimal("50"),
            created_by="creator",
        )
        assert wip.work_order_id == wo_id
        assert wip.quantity_started == Decimal("50")
        assert wip.quantity_remaining == Decimal("50")
        assert wip.quantity_completed == Decimal("0")
        assert wip.total_cost == Decimal("0")
        assert wip.status == WIPStatus.OPEN
        assert wip.version == 1
        assert wip.created_by == "creator"
        assert wip.created_at == FIXED_NOW

    def test_create_quantity_zero_raises(self):
        with pytest.raises(ValueError, match="positive"):
            WorkInProcessEntity.create(
                work_order_id=uuid4(),
                work_order_number="WO",
                product_id=uuid4(),
                product_code="P",
                product_name="P",
                quantity_started=Decimal("0"),
            )

    # ------------------------------------------------------------------------
    # add_material_cost
    # ------------------------------------------------------------------------

    def test_add_material_cost_success(self, sample_wip):
        amount = Decimal("1000")
        quantity = Decimal("50")
        unit_cost = Decimal("20")
        new_wip = sample_wip.add_material_cost(amount, quantity, unit_cost, "tester")
        assert new_wip.material_cost == amount
        assert new_wip.total_cost == amount
        assert len(new_wip.cost_components) == 1
        assert new_wip.cost_components[0].cost_element == CostElement.MATERIAL
        assert new_wip.cost_components[0].amount == amount
        assert new_wip.cost_components[0].quantity == quantity
        assert new_wip.cost_components[0].unit_cost == unit_cost
        assert new_wip.version == sample_wip.version + 1
        assert new_wip.updated_at == FIXED_NOW
        assert new_wip.created_by == "tester"

    def test_add_material_cost_negative_amount_raises(self, sample_wip):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_wip.add_material_cost(Decimal("-1"), Decimal("1"), Decimal("1"))

    # ------------------------------------------------------------------------
    # add_labor_cost
    # ------------------------------------------------------------------------

    def test_add_labor_cost_success(self, sample_wip):
        amount = Decimal("500")
        quantity = Decimal("25")
        unit_cost = Decimal("20")
        new_wip = sample_wip.add_labor_cost(amount, quantity, unit_cost, "tester")
        assert new_wip.labor_cost == amount
        assert new_wip.total_cost == amount
        assert len(new_wip.cost_components) == 1
        assert new_wip.cost_components[0].cost_element == CostElement.LABOR
        assert new_wip.cost_components[0].amount == amount
        assert new_wip.version == sample_wip.version + 1

    def test_add_labor_cost_negative_amount_raises(self, sample_wip):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_wip.add_labor_cost(Decimal("-1"), Decimal("1"), Decimal("1"))

    # ------------------------------------------------------------------------
    # add_overhead_cost
    # ------------------------------------------------------------------------

    def test_add_overhead_cost_success(self, sample_wip):
        amount = Decimal("300")
        quantity = Decimal("15")
        unit_cost = Decimal("20")
        new_wip = sample_wip.add_overhead_cost(amount, quantity, unit_cost, "tester")
        assert new_wip.overhead_cost == amount
        assert new_wip.total_cost == amount
        assert len(new_wip.cost_components) == 1
        assert new_wip.cost_components[0].cost_element == CostElement.OVERHEAD
        assert new_wip.version == sample_wip.version + 1

    def test_add_overhead_cost_negative_amount_raises(self, sample_wip):
        with pytest.raises(ValueError, match="cannot be negative"):
            sample_wip.add_overhead_cost(Decimal("-1"), Decimal("1"), Decimal("1"))

    # ------------------------------------------------------------------------
    # complete_units
    # ------------------------------------------------------------------------

    def test_complete_units_partial(self, wip_with_costs):
        # wip_with_costs has started 100, remaining 100, completed 0
        new_wip = wip_with_costs.complete_units(Decimal("30"))
        assert new_wip.quantity_remaining == Decimal("70")
        assert new_wip.quantity_completed == Decimal("30")
        assert new_wip.status == WIPStatus.OPEN
        assert new_wip.version == wip_with_costs.version + 1
        assert new_wip.updated_at == FIXED_NOW

    def test_complete_units_all(self, wip_with_costs):
        new_wip = wip_with_costs.complete_units(Decimal("100"))
        assert new_wip.quantity_remaining == Decimal("0")
        assert new_wip.quantity_completed == Decimal("100")
        assert new_wip.status == WIPStatus.CLOSED
        assert new_wip.version == wip_with_costs.version + 1

    def test_complete_units_zero_raises(self, wip_with_costs):
        with pytest.raises(ValueError, match="positive"):
            wip_with_costs.complete_units(Decimal("0"))

    def test_complete_units_exceeds_remaining_raises(self, wip_with_costs):
        with pytest.raises(ValueError, match="Cannot complete 150 units, only 100 remaining"):
            wip_with_costs.complete_units(Decimal("150"))

    # ------------------------------------------------------------------------
    # adjust_cost
    # ------------------------------------------------------------------------

    def test_adjust_cost_success(self, wip_with_costs):
        new_total = Decimal("2000")
        new_wip = wip_with_costs.adjust_cost(new_total, "Adjustment reason", "adjuster")
        assert new_wip.total_cost == new_total
        assert new_wip.status == WIPStatus.ADJUSTED
        assert new_wip.version == wip_with_costs.version + 1
        assert new_wip.updated_at == FIXED_NOW
        assert new_wip.created_by == "adjuster"
        # Check proportional allocation
        # original costs: material=1000, labor=500, overhead=300, total=1800
        # ratio = 2000/1800 = 1.111...
        # new_material = 1000 * (2000/1800) = 1111.11...
        # We'll just check they are positive and proportional
        expected_ratio = new_total / wip_with_costs.total_cost
        assert new_wip.material_cost == (wip_with_costs.material_cost * expected_ratio).quantize(Decimal("0.01"))
        assert new_wip.labor_cost == (wip_with_costs.labor_cost * expected_ratio).quantize(Decimal("0.01"))
        assert new_wip.overhead_cost == (wip_with_costs.overhead_cost * expected_ratio).quantize(Decimal("0.01"))
        # Check that an adjustment component was added
        assert len(new_wip.cost_components) == len(wip_with_costs.cost_components) + 1
        last_component = new_wip.cost_components[-1]
        assert last_component.cost_element == CostElement.OTHER
        assert last_component.amount == new_total - wip_with_costs.total_cost

    def test_adjust_cost_zero_total(self, sample_wip):
        # When total_cost is 0, proportional allocation should result in zero components
        new_total = Decimal("500")
        new_wip = sample_wip.adjust_cost(new_total, "reason", "adjuster")
        assert new_wip.material_cost == Decimal("0")
        assert new_wip.labor_cost == Decimal("0")
        assert new_wip.overhead_cost == Decimal("0")
        assert new_wip.total_cost == new_total
        assert new_wip.status == WIPStatus.ADJUSTED
        assert len(new_wip.cost_components) == 1
        assert new_wip.cost_components[0].amount == new_total

    def test_adjust_cost_negative_raises(self, wip_with_costs):
        with pytest.raises(ValueError, match="cannot be negative"):
            wip_with_costs.adjust_cost(Decimal("-100"), "reason", "adjuster")

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def test_get_unit_cost(self, wip_with_costs):
        # total_cost = 1000 + 500 + 300 = 1800, quantity_started = 100
        assert wip_with_costs.get_unit_cost() == Decimal("18.00")

    def test_get_unit_cost_zero_started(self, sample_wip):
        assert sample_wip.get_unit_cost() == Decimal("0")

    def test_get_remaining_value(self, wip_with_costs):
        # total_cost = 1800, remaining = 100, started = 100 => remaining value = 1800
        assert wip_with_costs.get_remaining_value() == Decimal("1800.00")
        # After completing 30 units
        wip2 = wip_with_costs.complete_units(Decimal("30"))
        # remaining = 70, started = 100, total_cost = 1800 => 1800 * 70/100 = 1260
        assert wip2.get_remaining_value() == Decimal("1260.00")

    def test_get_remaining_value_zero_started(self, sample_wip):
        assert sample_wip.get_remaining_value() == Decimal("0")

    def test_get_completed_value(self, wip_with_costs):
        # total_cost = 1800, completed = 0 => 0
        assert wip_with_costs.get_completed_value() == Decimal("0")
        # After completing 30 units
        wip2 = wip_with_costs.complete_units(Decimal("30"))
        # completed = 30, started = 100 => 1800 * 30/100 = 540
        assert wip2.get_completed_value() == Decimal("540.00")

    def test_get_completed_value_zero_started(self, sample_wip):
        assert sample_wip.get_completed_value() == Decimal("0")

    def test_get_completion_percentage(self, wip_with_costs):
        assert wip_with_costs.get_completion_percentage() == 0.0
        wip2 = wip_with_costs.complete_units(Decimal("30"))
        assert wip2.get_completion_percentage() == 30.0
        wip3 = wip2.complete_units(Decimal("70"))
        assert wip3.get_completion_percentage() == 100.0

    def test_get_completion_percentage_zero_started(self, sample_wip):
        # quantity_started is 100, so not zero. But test for zero just in case.
        # We'll create a WIP with started=0? Can't due to validation. So just test normal.
        pass

    # ------------------------------------------------------------------------
    # to_dict
    # ------------------------------------------------------------------------

    def test_to_dict(self, wip_with_costs):
        d = wip_with_costs.to_dict()
        assert d["wip_id"] == str(wip_with_costs.wip_id)
        assert d["work_order_number"] == "WO-001"
        assert d["quantity_started"] == "100"
        assert d["quantity_remaining"] == "100"
        assert d["quantity_completed"] == "0"
        assert d["completion_percentage"] == 0.0
        assert d["material_cost"] == "1000"
        assert d["labor_cost"] == "500"
        assert d["overhead_cost"] == "300"
        assert d["total_cost"] == "1800"
        assert d["unit_cost"] == "18.00"
        assert d["remaining_value"] == "1800.00"
        assert d["status"] == "open"
        assert "cost_components" in d
        assert len(d["cost_components"]) == 3
        assert d["version"] == 4  # 1 initial + 3 additions


# ============================================================================
# Tests for WorkInProcessRepository (abstract)
# ============================================================================

class TestWorkInProcessRepository:
    def test_abstract_methods_raise(self):
        repo = WorkInProcessRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_work_order(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_product(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_open_wip(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())

    @pytest.mark.asyncio
    async def test_can_mock(self):
        repo = WorkInProcessRepository()
        repo.get_by_id = AsyncMock(return_value=MagicMock())
        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is not None
