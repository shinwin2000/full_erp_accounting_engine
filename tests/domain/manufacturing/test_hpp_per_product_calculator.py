# test_hpp_per_product_calculator.py
# ===================================
# Comprehensive tests for domain/manufacturing/hpp_per_product_calculator.py.
# Covers all calculation methods, value objects, history, summary, and edge cases.

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.hpp_per_product_calculator import (
    HPPCalculationMethod,
    HPPCalculationResult,
    HPPComponent,
    HPPPerProductCalculator,
)
from domain.manufacturing.work_in_process_entity import WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def sample_work_order() -> MagicMock:
    """Create a mock WorkOrderEntity with realistic data."""
    wo = MagicMock(spec=WorkOrderEntity)
    wo.work_order_id = uuid4()
    wo.work_order_number = "WO-001"
    wo.product_id = uuid4()
    wo.product_code = "PROD-001"
    wo.product_name = "Test Product"
    wo.completed_quantity = Decimal("100")
    wo.material_actual_cost = Decimal("1000")
    wo.labor_actual_cost = Decimal("500")
    wo.overhead_actual_cost = Decimal("300")
    wo.actual_start_date = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    wo.actual_end_date = datetime(2025, 1, 15, 17, 0, tzinfo=UTC)
    wo.planned_start_date = datetime(2025, 1, 1, 8, 0, tzinfo=UTC)
    return wo


@pytest.fixture
def sample_wip(sample_work_order) -> MagicMock:
    """Create a mock WorkInProcessEntity."""
    wip = MagicMock(spec=WorkInProcessEntity)
    wip.material_cost = Decimal("1100")
    wip.labor_cost = Decimal("550")
    wip.overhead_cost = Decimal("330")
    wip.work_order_id = sample_work_order.work_order_id
    return wip


@pytest.fixture
def sample_work_order_list(sample_work_order) -> list[MagicMock]:
    """Create a list of work orders for process costing."""
    wo1 = sample_work_order
    wo2 = MagicMock(spec=WorkOrderEntity)
    wo2.work_order_id = uuid4()
    wo2.work_order_number = "WO-002"
    wo2.product_id = wo1.product_id
    wo2.product_code = wo1.product_code
    wo2.product_name = wo1.product_name
    wo2.completed_quantity = Decimal("50")
    wo2.material_actual_cost = Decimal("600")
    wo2.labor_actual_cost = Decimal("300")
    wo2.overhead_actual_cost = Decimal("200")
    wo2.actual_start_date = datetime(2025, 1, 5, 8, 0, tzinfo=UTC)
    wo2.actual_end_date = datetime(2025, 1, 20, 17, 0, tzinfo=UTC)
    return [wo1, wo2]


@pytest.fixture
def calculator() -> HPPPerProductCalculator:
    """Fresh HPPPerProductCalculator instance."""
    return HPPPerProductCalculator()


# ----------------------------------------------------------------------
# HPPCalculationMethod Enum
# ----------------------------------------------------------------------
class TestHPPCalculationMethod:
    def test_members_exist(self):
        assert hasattr(HPPCalculationMethod, "JOB_ORDER")
        assert hasattr(HPPCalculationMethod, "PROCESS_COSTING")
        assert hasattr(HPPCalculationMethod, "STANDARD_COSTING")

    def test_member_is_instance(self):
        assert isinstance(HPPCalculationMethod.JOB_ORDER, HPPCalculationMethod)


# ----------------------------------------------------------------------
# HPPComponent Value Object
# ----------------------------------------------------------------------
class TestHPPComponent:
    def test_construction_valid(self):
        comp = HPPComponent(
            cost_element=CostElement.MATERIAL,
            amount=Decimal("1000"),
            quantity=Decimal("100"),
            unit_cost=Decimal("10"),
        )
        assert comp.cost_element == CostElement.MATERIAL
        assert comp.amount == Decimal("1000")
        assert comp.quantity == Decimal("100")
        assert comp.unit_cost == Decimal("10")

    def test_validation_negative_amount_raises(self):
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("-100"),
                quantity=Decimal("100"),
                unit_cost=Decimal("10"),
            )

    def test_validation_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity cannot be negative"):
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("-100"),
                unit_cost=Decimal("10"),
            )

    def test_validation_negative_unit_cost_raises(self):
        with pytest.raises(ValueError, match="Unit cost cannot be negative"):
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=Decimal("100"),
                quantity=Decimal("100"),
                unit_cost=Decimal("-10"),
            )

    def test_to_dict(self):
        comp = HPPComponent(
            cost_element=CostElement.LABOR,
            amount=Decimal("500"),
            quantity=Decimal("100"),
            unit_cost=Decimal("5"),
        )
        d = comp.to_dict()
        assert d["cost_element"] == "labor"
        assert d["amount"] == "500"
        assert d["quantity"] == "100"
        assert d["unit_cost"] == "5"


# ----------------------------------------------------------------------
# HPPCalculationResult Value Object
# ----------------------------------------------------------------------
class TestHPPCalculationResult:
    @pytest.fixture
    def result(self) -> HPPCalculationResult:
        return HPPCalculationResult(
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Test Product",
            period_start=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
            period_end=datetime(2025, 1, 31, 23, 59, tzinfo=UTC),
            units_produced=Decimal("100"),
            total_material_cost=Decimal("1000"),
            total_labor_cost=Decimal("500"),
            total_overhead_cost=Decimal("300"),
            total_production_cost=Decimal("1800"),
            unit_hpp=Decimal("18"),
            opening_wip_value=Decimal("0"),
            closing_wip_value=Decimal("0"),
            calculation_method=HPPCalculationMethod.JOB_ORDER,
            components=[],
        )

    def test_construction_valid(self, result):
        assert result.product_code == "PROD-001"
        assert result.units_produced == Decimal("100")
        assert result.total_production_cost == Decimal("1800")
        assert result.unit_hpp == Decimal("18")

    def test_validation_negative_units_raises(self):
        with pytest.raises(ValueError, match="Units produced cannot be negative"):
            HPPCalculationResult(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) + timedelta(days=1),
                units_produced=Decimal("-10"),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_production_cost=Decimal(0),
                unit_hpp=Decimal(0),
                opening_wip_value=Decimal(0),
                closing_wip_value=Decimal(0),
                calculation_method=HPPCalculationMethod.JOB_ORDER,
            )

    def test_validation_negative_total_production_cost_raises(self):
        with pytest.raises(ValueError, match="Total production cost cannot be negative"):
            HPPCalculationResult(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) + timedelta(days=1),
                units_produced=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_production_cost=Decimal("-100"),
                unit_hpp=Decimal(0),
                opening_wip_value=Decimal(0),
                closing_wip_value=Decimal(0),
                calculation_method=HPPCalculationMethod.JOB_ORDER,
            )

    def test_validation_negative_unit_hpp_raises(self):
        with pytest.raises(ValueError, match="Unit HPP cannot be negative"):
            HPPCalculationResult(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) + timedelta(days=1),
                units_produced=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_production_cost=Decimal(0),
                unit_hpp=Decimal("-10"),
                opening_wip_value=Decimal(0),
                closing_wip_value=Decimal(0),
                calculation_method=HPPCalculationMethod.JOB_ORDER,
            )

    def test_validation_period_end_before_start_raises(self):
        with pytest.raises(ValueError, match="Period end must be after period start"):
            HPPCalculationResult(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) - timedelta(days=1),
                units_produced=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_production_cost=Decimal(0),
                unit_hpp=Decimal(0),
                opening_wip_value=Decimal(0),
                closing_wip_value=Decimal(0),
                calculation_method=HPPCalculationMethod.JOB_ORDER,
            )

    def test_validation_naive_dates_raises(self):
        naive_start = datetime(2025, 1, 1, 10, 0)
        naive_end = datetime(2025, 1, 2, 10, 0)
        with pytest.raises(ValueError, match="Period dates must be timezone-aware"):
            HPPCalculationResult(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=naive_start,
                period_end=naive_end,
                units_produced=Decimal(0),
                total_material_cost=Decimal(0),
                total_labor_cost=Decimal(0),
                total_overhead_cost=Decimal(0),
                total_production_cost=Decimal(0),
                unit_hpp=Decimal(0),
                opening_wip_value=Decimal(0),
                closing_wip_value=Decimal(0),
                calculation_method=HPPCalculationMethod.JOB_ORDER,
            )

    def test_to_dict(self, result):
        d = result.to_dict()
        assert d["product_id"] == str(result.product_id)
        assert d["product_code"] == "PROD-001"
        assert d["units_produced"] == "100"
        assert d["total_production_cost"] == "1800"
        assert d["unit_hpp"] == "18"
        assert d["calculation_method"] == "job_order"
        assert "components" in d


# ----------------------------------------------------------------------
# HPPPerProductCalculator - calculate_job_order
# ----------------------------------------------------------------------
class TestCalculatorJobOrder:
    def test_calculate_job_order_success(self, calculator, sample_work_order):
        result = calculator.calculate_job_order(sample_work_order)
        assert result.product_id == sample_work_order.product_id
        assert result.product_code == sample_work_order.product_code
        assert result.units_produced == Decimal("100")
        assert result.total_material_cost == Decimal("1000")
        assert result.total_labor_cost == Decimal("500")
        assert result.total_overhead_cost == Decimal("300")
        assert result.total_production_cost == Decimal("1800")
        assert result.unit_hpp == Decimal("18")
        assert result.calculation_method == HPPCalculationMethod.JOB_ORDER
        assert len(result.components) == 3

        # Check components
        material_comp = result.components[0]
        assert material_comp.cost_element == CostElement.MATERIAL
        assert material_comp.amount == Decimal("1000")
        assert material_comp.unit_cost == Decimal("10")

        labor_comp = result.components[1]
        assert labor_comp.cost_element == CostElement.LABOR
        assert labor_comp.unit_cost == Decimal("5")

        overhead_comp = result.components[2]
        assert overhead_comp.cost_element == CostElement.OVERHEAD
        assert overhead_comp.unit_cost == Decimal("3")

        # Check history stored
        history = calculator.get_calculation_history()
        assert len(history) == 1
        assert history[0] is result

    def test_calculate_job_order_with_wip(self, calculator, sample_work_order, sample_wip):
        result = calculator.calculate_job_order(sample_work_order, sample_wip)
        # Should use WIP costs instead of work order actual costs
        assert result.total_material_cost == Decimal("1100")
        assert result.total_labor_cost == Decimal("550")
        assert result.total_overhead_cost == Decimal("330")
        assert result.total_production_cost == Decimal("1980")
        assert result.unit_hpp == Decimal("19.80")

    def test_calculate_job_order_zero_completed_units_raises(self, calculator, sample_work_order):
        sample_work_order.completed_quantity = Decimal("0")
        with pytest.raises(ValueError, match="has no completed units"):
            calculator.calculate_job_order(sample_work_order)

    def test_calculate_job_order_uses_dates(self, calculator, sample_work_order):
        result = calculator.calculate_job_order(sample_work_order)
        assert result.period_start == sample_work_order.actual_start_date
        # actual_end_date is set
        assert result.period_end == sample_work_order.actual_end_date

    def test_calculate_job_order_missing_end_date_uses_now(self, calculator, sample_work_order):
        sample_work_order.actual_end_date = None
        with patch("domain.manufacturing.hpp_per_product_calculator.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2025, 1, 15, 17, 0, tzinfo=UTC)
            result = calculator.calculate_job_order(sample_work_order)
            assert result.period_end == mock_dt.now.return_value


# ----------------------------------------------------------------------
# HPPPerProductCalculator - calculate_process_costing
# ----------------------------------------------------------------------
class TestCalculatorProcessCosting:
    def test_calculate_process_costing_success(self, calculator, sample_work_order_list):
        product_id = sample_work_order_list[0].product_id
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        result = calculator.calculate_process_costing(
            product_id=product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
            work_orders=sample_work_order_list,
        )
        # Total material = 1000 + 600 = 1600
        # Total labor = 500 + 300 = 800
        # Total overhead = 300 + 200 = 500
        # Total cost = 2900
        # Total units = 100 + 50 = 150
        # unit_hpp = 2900 / 150 = 19.3333...
        assert result.total_material_cost == Decimal("1600")
        assert result.total_labor_cost == Decimal("800")
        assert result.total_overhead_cost == Decimal("500")
        assert result.total_production_cost == Decimal("2900")
        expected_unit = (Decimal("2900") / Decimal("150")).quantize(Decimal("0.01"))
        assert result.unit_hpp == expected_unit
        assert result.calculation_method == HPPCalculationMethod.PROCESS_COSTING

        # Components
        material_comp = result.components[0]
        assert material_comp.amount == Decimal("1600")
        assert material_comp.unit_cost == (Decimal("1600") / Decimal("150")).quantize(Decimal("0.01"))

    def test_calculate_process_costing_with_wip(self, calculator, sample_work_order_list):
        product_id = sample_work_order_list[0].product_id
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        opening_wip = Decimal("500")
        closing_wip = Decimal("300")
        result = calculator.calculate_process_costing(
            product_id=product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
            work_orders=sample_work_order_list,
            opening_wip_value=opening_wip,
            closing_wip_value=closing_wip,
        )
        # Total production cost = 2900 + 500 - 300 = 3100
        # unit_hpp = 3100 / 150 = 20.6667...
        assert result.total_production_cost == Decimal("3100")
        expected_unit = (Decimal("3100") / Decimal("150")).quantize(Decimal("0.01"))
        assert result.unit_hpp == expected_unit
        assert result.opening_wip_value == opening_wip
        assert result.closing_wip_value == closing_wip

    def test_calculate_process_costing_zero_units(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        result = calculator.calculate_process_costing(
            product_id=product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            work_orders=[],
        )
        assert result.units_produced == Decimal("0")
        assert result.unit_hpp == Decimal("0")
        assert result.total_production_cost == Decimal("0")

    def test_calculate_process_costing_handles_decimal_precision(self, calculator):
        # Create work orders with amounts that don't divide evenly
        wo1 = MagicMock(spec=WorkOrderEntity)
        wo1.completed_quantity = Decimal("30")
        wo1.material_actual_cost = Decimal("1000")
        wo1.labor_actual_cost = Decimal("500")
        wo1.overhead_actual_cost = Decimal("300")
        wo1.actual_start_date = datetime.now(UTC)
        wo1.actual_end_date = datetime.now(UTC)
        wo1.product_id = uuid4()
        wo1.product_code = "P"
        wo1.product_name = "N"

        wo2 = MagicMock(spec=WorkOrderEntity)
        wo2.completed_quantity = Decimal("70")
        wo2.material_actual_cost = Decimal("2000")
        wo2.labor_actual_cost = Decimal("1000")
        wo2.overhead_actual_cost = Decimal("600")
        wo2.actual_start_date = datetime.now(UTC)
        wo2.actual_end_date = datetime.now(UTC)
        wo2.product_id = wo1.product_id
        wo2.product_code = "P"
        wo2.product_name = "N"

        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        result = calculator.calculate_process_costing(
            product_id=wo1.product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            work_orders=[wo1, wo2],
        )
        # Total material = 3000, labor = 1500, overhead = 900, total = 5400, units = 100
        # unit_hpp = 54.00
        assert result.unit_hpp == Decimal("54.00")
        # Components:
        material_unit = (Decimal("3000") / Decimal("100")).quantize(Decimal("0.01"))
        assert result.components[0].unit_cost == material_unit


# ----------------------------------------------------------------------
# HPPPerProductCalculator - calculate_standard_costing
# ----------------------------------------------------------------------
class TestCalculatorStandardCosting:
    def test_calculate_standard_costing_success(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        standard_unit_cost = Decimal("25")
        units_produced = Decimal("200")
        result = calculator.calculate_standard_costing(
            product_id=product_id,
            product_code="PROD-001",
            product_name="Test Product",
            standard_unit_cost=standard_unit_cost,
            units_produced=units_produced,
            period_start=start,
            period_end=end,
        )
        total_standard = standard_unit_cost * units_produced  # 5000
        assert result.total_production_cost == total_standard
        assert result.unit_hpp == standard_unit_cost
        # Components allocated: material 50%, labor 30%, overhead 20%
        assert result.total_material_cost == total_standard * Decimal("0.5")
        assert result.total_labor_cost == total_standard * Decimal("0.3")
        assert result.total_overhead_cost == total_standard * Decimal("0.2")
        assert result.calculation_method == HPPCalculationMethod.STANDARD_COSTING

    def test_calculate_standard_costing_with_variance(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        standard_unit_cost = Decimal("25")
        units_produced = Decimal("200")
        variance = Decimal("200")  # unfavorable
        result = calculator.calculate_standard_costing(
            product_id=product_id,
            product_code="PROD-001",
            product_name="Test Product",
            standard_unit_cost=standard_unit_cost,
            units_produced=units_produced,
            period_start=start,
            period_end=end,
            variance_adjustment=variance,
        )
        total_adjusted = standard_unit_cost * units_produced + variance  # 5200
        unit_hpp = total_adjusted / units_produced  # 26.00
        assert result.total_production_cost == total_adjusted
        assert result.unit_hpp == unit_hpp

    def test_calculate_standard_costing_zero_units(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        result = calculator.calculate_standard_costing(
            product_id=product_id,
            product_code="P",
            product_name="N",
            standard_unit_cost=Decimal("25"),
            units_produced=Decimal("0"),
            period_start=start,
            period_end=end,
        )
        assert result.units_produced == Decimal("0")
        assert result.unit_hpp == Decimal("0")
        assert result.total_production_cost == Decimal("0")
        # Components should have zero amounts
        for comp in result.components:
            assert comp.amount == Decimal("0")
            assert comp.unit_cost == Decimal("0")


# ----------------------------------------------------------------------
# HPPPerProductCalculator - calculate_with_components
# ----------------------------------------------------------------------
class TestCalculatorWithComponents:
    def test_calculate_with_components_success(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        material = Decimal("1500")
        labor = Decimal("750")
        overhead = Decimal("450")
        units = Decimal("150")
        result = calculator.calculate_with_components(
            product_id=product_id,
            product_code="PROD-001",
            product_name="Test Product",
            period_start=start,
            period_end=end,
            units_produced=units,
            material_cost=material,
            labor_cost=labor,
            overhead_cost=overhead,
            method=HPPCalculationMethod.PROCESS_COSTING,
        )
        total = material + labor + overhead  # 2700
        assert result.total_production_cost == total
        assert result.unit_hpp == total / units  # 18.00
        assert result.calculation_method == HPPCalculationMethod.PROCESS_COSTING

        # Components
        assert result.components[0].amount == material
        assert result.components[0].unit_cost == material / units
        assert result.components[1].amount == labor
        assert result.components[1].unit_cost == labor / units
        assert result.components[2].amount == overhead
        assert result.components[2].unit_cost == overhead / units

    def test_calculate_with_components_includes_wip(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        opening = Decimal("200")
        closing = Decimal("150")
        result = calculator.calculate_with_components(
            product_id=product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            units_produced=Decimal("100"),
            material_cost=Decimal("1000"),
            labor_cost=Decimal("500"),
            overhead_cost=Decimal("300"),
            opening_wip_value=opening,
            closing_wip_value=closing,
        )
        total_cost = Decimal("1000") + Decimal("500") + Decimal("300")  # 1800
        total_prod = total_cost + opening - closing  # 1800 + 200 - 150 = 1850
        assert result.total_production_cost == total_prod
        assert result.unit_hpp == total_prod / Decimal("100")  # 18.50

    def test_calculate_with_components_zero_units(self, calculator):
        product_id = uuid4()
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        result = calculator.calculate_with_components(
            product_id=product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            units_produced=Decimal("0"),
            material_cost=Decimal("0"),
            labor_cost=Decimal("0"),
            overhead_cost=Decimal("0"),
        )
        assert result.unit_hpp == Decimal("0")
        # Components with zero units should have unit_cost = 0
        for comp in result.components:
            assert comp.unit_cost == Decimal("0")


# ----------------------------------------------------------------------
# HPPPerProductCalculator - History, Summary, Reset
# ----------------------------------------------------------------------
class TestCalculatorHistory:
    def test_get_calculation_history_default(self, calculator, sample_work_order):
        # Run multiple calculations
        for i in range(3):
            calculator.calculate_job_order(sample_work_order)
        history = calculator.get_calculation_history()
        assert len(history) == 3

    def test_get_calculation_history_limit(self, calculator, sample_work_order):
        for i in range(5):
            calculator.calculate_job_order(sample_work_order)
        history = calculator.get_calculation_history(limit=2)
        assert len(history) == 2
        # Should return latest 2 (index 3 and 4)
        # We can't easily check which, but it's fine

    def test_get_calculation_history_filter_by_product(self, calculator, sample_work_order):
        # Create another product
        wo2 = MagicMock(spec=WorkOrderEntity)
        wo2.work_order_id = uuid4()
        wo2.work_order_number = "WO-002"
        wo2.product_id = uuid4()
        wo2.product_code = "PROD-002"
        wo2.product_name = "Other"
        wo2.completed_quantity = Decimal("50")
        wo2.material_actual_cost = Decimal("600")
        wo2.labor_actual_cost = Decimal("300")
        wo2.overhead_actual_cost = Decimal("200")
        wo2.actual_start_date = datetime.now(UTC)
        wo2.actual_end_date = datetime.now(UTC)

        calculator.calculate_job_order(sample_work_order)
        calculator.calculate_job_order(wo2)

        history_prod1 = calculator.get_calculation_history(product_id=sample_work_order.product_id)
        assert len(history_prod1) == 1
        assert history_prod1[0].product_id == sample_work_order.product_id

        history_prod2 = calculator.get_calculation_history(product_id=wo2.product_id)
        assert len(history_prod2) == 1
        assert history_prod2[0].product_id == wo2.product_id

    def test_get_summary_empty(self, calculator):
        summary = calculator.get_summary()
        assert summary == {"total_calculations": 0}

    def test_get_summary_with_calculations(self, calculator, sample_work_order):
        # Job order
        calculator.calculate_job_order(sample_work_order)
        # Process costing
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        calculator.calculate_process_costing(
            product_id=sample_work_order.product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            work_orders=[sample_work_order],
        )
        # Standard costing
        calculator.calculate_standard_costing(
            product_id=sample_work_order.product_id,
            product_code="P",
            product_name="N",
            standard_unit_cost=Decimal("20"),
            units_produced=Decimal("100"),
            period_start=start,
            period_end=end,
        )

        summary = calculator.get_summary()
        assert summary["total_calculations"] == 3
        assert Decimal(summary["total_units_produced"]) == Decimal("300")  # 100 + 100 + 100
        # Weighted average HPP: (18*100 + 18*100 + 20*100) / 300 = 18.6667
        expected_avg = (Decimal("18") * 100 + Decimal("18") * 100 + Decimal("20") * 100) / Decimal("300")
        assert Decimal(summary["weighted_average_unit_hpp"]) == expected_avg.quantize(Decimal("0.01"))
        assert summary["by_method"] == {
            "job_order": 1,
            "process_costing": 1,
            "standard_costing": 1,
        }

    def test_get_summary_decimal_precision(self, calculator):
        # Create calculations with non-even units and costs
        wo = MagicMock(spec=WorkOrderEntity)
        wo.work_order_id = uuid4()
        wo.work_order_number = "WO-001"
        wo.product_id = uuid4()
        wo.product_code = "P"
        wo.product_name = "N"
        wo.completed_quantity = Decimal("30")
        wo.material_actual_cost = Decimal("1000")
        wo.labor_actual_cost = Decimal("500")
        wo.overhead_actual_cost = Decimal("300")
        wo.actual_start_date = datetime.now(UTC)
        wo.actual_end_date = datetime.now(UTC)

        calculator.calculate_job_order(wo)
        # Unit HPP = 1800/30 = 60.00
        wo2 = MagicMock(spec=WorkOrderEntity)
        wo2.work_order_id = uuid4()
        wo2.work_order_number = "WO-002"
        wo2.product_id = wo.product_id
        wo2.product_code = "P"
        wo2.product_name = "N"
        wo2.completed_quantity = Decimal("70")
        wo2.material_actual_cost = Decimal("2000")
        wo2.labor_actual_cost = Decimal("1000")
        wo2.overhead_actual_cost = Decimal("600")
        wo2.actual_start_date = datetime.now(UTC)
        wo2.actual_end_date = datetime.now(UTC)

        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 31, tzinfo=UTC)
        calculator.calculate_process_costing(
            product_id=wo.product_id,
            product_code="P",
            product_name="N",
            period_start=start,
            period_end=end,
            work_orders=[wo, wo2],
        )
        # Total units = 100, total cost = 5400, unit = 54.00
        # Weighted avg = (60*30 + 54*70)/100 = (1800 + 3780)/100 = 55.80
        summary = calculator.get_summary()
        expected_avg = Decimal("55.80")
        assert Decimal(summary["weighted_average_unit_hpp"]) == expected_avg

    def test_reset(self, calculator, sample_work_order):
        calculator.calculate_job_order(sample_work_order)
        assert len(calculator._calculation_history) == 1
        calculator.reset()
        assert len(calculator._calculation_history) == 0


# ----------------------------------------------------------------------
# Edge Cases and Decimal Precision
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_calculation_with_decimal_precision_issues(self, calculator):
        # Test with amounts that produce repeating decimals
        wo = MagicMock(spec=WorkOrderEntity)
        wo.work_order_id = uuid4()
        wo.work_order_number = "WO-001"
        wo.product_id = uuid4()
        wo.product_code = "P"
        wo.product_name = "N"
        wo.completed_quantity = Decimal("30")
        wo.material_actual_cost = Decimal("1000")
        wo.labor_actual_cost = Decimal("500")
        wo.overhead_actual_cost = Decimal("300")
        wo.actual_start_date = datetime.now(UTC)
        wo.actual_end_date = datetime.now(UTC)

        result = calculator.calculate_job_order(wo)
        # Unit HPP = 1800/30 = 60.00 (exact)
        assert result.unit_hpp == Decimal("60.00")

        # Create a scenario with non-terminating decimal
        wo2 = MagicMock(spec=WorkOrderEntity)
        wo2.work_order_id = uuid4()
        wo2.work_order_number = "WO-002"
        wo2.product_id = wo.product_id
        wo2.product_code = "P"
        wo2.product_name = "N"
        wo2.completed_quantity = Decimal("33")
        wo2.material_actual_cost = Decimal("1000")
        wo2.labor_actual_cost = Decimal("500")
        wo2.overhead_actual_cost = Decimal("300")
        wo2.actual_start_date = datetime.now(UTC)
        wo2.actual_end_date = datetime.now(UTC)

        result2 = calculator.calculate_job_order(wo2)
        # 1800/33 = 54.545454... -> quantized to 54.55
        expected = (Decimal("1800") / Decimal("33")).quantize(Decimal("0.01"))
        assert result2.unit_hpp == expected

    def test_calculation_with_large_numbers(self, calculator):
        wo = MagicMock(spec=WorkOrderEntity)
        wo.work_order_id = uuid4()
        wo.work_order_number = "WO-001"
        wo.product_id = uuid4()
        wo.product_code = "P"
        wo.product_name = "N"
        wo.completed_quantity = Decimal("1000000")
        wo.material_actual_cost = Decimal("9999999999.99")
        wo.labor_actual_cost = Decimal("4999999999.99")
        wo.overhead_actual_cost = Decimal("2999999999.99")
        wo.actual_start_date = datetime.now(UTC)
        wo.actual_end_date = datetime.now(UTC)

        result = calculator.calculate_job_order(wo)
        total = Decimal("17999999999.97")
        expected_unit = (total / Decimal("1000000")).quantize(Decimal("0.01"))
        assert result.unit_hpp == expected_unit
        assert result.total_production_cost == total

    def test_alias_hpp_calculator(self):
        from domain.manufacturing.hpp_per_product_calculator import HPPCalculator, HppCalculator
        assert HPPCalculator is HPPPerProductCalculator
        assert HppCalculator is HPPPerProductCalculator
        calc = HPPCalculator()
        assert isinstance(calc, HPPPerProductCalculator)

    def test_calculate_with_components_handles_negative_values(self, calculator):
        # Should raise validation errors? The components validation catches negative amounts.
        # The calculate_with_components itself doesn't validate the inputs (except units_produced in result validation),
        # but the HPPComponent will raise if amounts are negative.
        with pytest.raises(ValueError, match="Amount cannot be negative"):
            calculator.calculate_with_components(
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                period_start=datetime.now(UTC),
                period_end=datetime.now(UTC) + timedelta(days=1),
                units_produced=Decimal("10"),
                material_cost=Decimal("-100"),
                labor_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
            )