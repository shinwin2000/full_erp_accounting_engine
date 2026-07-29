# test_variance_analysis_engine.py
# =================================
# Comprehensive tests for domain/manufacturing/variance_analysis_engine.py.
# Covers all enums, value objects, calculation methods, and aggregate statistics.

from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.variance_analysis_engine import (
    VarianceAnalysisEngine,
    VarianceAnalysisResult,
    VarianceComponent,
    VarianceType,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def mock_work_order():
    """Create a mock WorkOrderEntity with sample data."""
    wo = MagicMock()
    wo.work_order_id = uuid4()
    wo.work_order_number = "WO-001"
    wo.product_id = uuid4()
    wo.product_code = "PROD-001"
    wo.product_name = "Test Product"
    wo.completed_quantity = Decimal("100")
    wo.material_standard_cost = Decimal("10")
    wo.labor_standard_cost = Decimal("5")
    wo.overhead_standard_cost = Decimal("3")
    wo.material_actual_cost = Decimal("12")
    wo.labor_actual_cost = Decimal("6")
    wo.overhead_actual_cost = Decimal("4")
    return wo


@pytest.fixture
def mock_standard_cost():
    """Create a mock StandardCostEntity."""
    sc = MagicMock()
    sc.material_cost = Decimal("10")
    sc.labor_cost = Decimal("5")
    sc.overhead_cost = Decimal("3")
    sc.total_cost = Decimal("18")
    return sc


@pytest.fixture
def engine():
    """Fresh VarianceAnalysisEngine instance."""
    return VarianceAnalysisEngine()


# ----------------------------------------------------------------------
# VarianceType Enum
# ----------------------------------------------------------------------
class TestVarianceType:
    def test_members_exist(self):
        assert hasattr(VarianceType, "FAVORABLE")
        assert hasattr(VarianceType, "UNFAVORABLE")

    def test_member_is_instance(self):
        assert isinstance(VarianceType.FAVORABLE, VarianceType)


# ----------------------------------------------------------------------
# VarianceComponent Value Object
# ----------------------------------------------------------------------
class TestVarianceComponent:
    def test_construction_valid(self):
        comp = VarianceComponent(
            cost_element=CostElement.MATERIAL,
            variance_type=VarianceType.FAVORABLE,
            standard_cost=Decimal("100"),
            actual_cost=Decimal("80"),
            variance_amount=Decimal("20"),
            variance_percentage=20.0,
            description="Material variance: favorable",
        )
        assert comp.cost_element == CostElement.MATERIAL
        assert comp.variance_type == VarianceType.FAVORABLE
        assert comp.standard_cost == Decimal("100")
        assert comp.actual_cost == Decimal("80")
        assert comp.variance_amount == Decimal("20")
        assert comp.variance_percentage == 20.0
        assert comp.description == "Material variance: favorable"

    def test_validation_negative_variance_amount_raises(self):
        with pytest.raises(ValueError, match="Variance amount cannot be negative"):
            VarianceComponent(
                cost_element=CostElement.MATERIAL,
                variance_type=VarianceType.FAVORABLE,
                standard_cost=Decimal("100"),
                actual_cost=Decimal("80"),
                variance_amount=Decimal("-20"),
                variance_percentage=20.0,
                description="Test",
            )

    def test_validation_percentage_below_zero_raises(self):
        with pytest.raises(ValueError, match="Variance percentage must be between 0 and 100"):
            VarianceComponent(
                cost_element=CostElement.MATERIAL,
                variance_type=VarianceType.FAVORABLE,
                standard_cost=Decimal("100"),
                actual_cost=Decimal("80"),
                variance_amount=Decimal("20"),
                variance_percentage=-5.0,
                description="Test",
            )

    def test_validation_percentage_above_100_raises(self):
        with pytest.raises(ValueError, match="Variance percentage must be between 0 and 100"):
            VarianceComponent(
                cost_element=CostElement.MATERIAL,
                variance_type=VarianceType.FAVORABLE,
                standard_cost=Decimal("100"),
                actual_cost=Decimal("80"),
                variance_amount=Decimal("20"),
                variance_percentage=150.0,
                description="Test",
            )

    def test_to_dict(self):
        comp = VarianceComponent(
            cost_element=CostElement.MATERIAL,
            variance_type=VarianceType.UNFAVORABLE,
            standard_cost=Decimal("100"),
            actual_cost=Decimal("120"),
            variance_amount=Decimal("20"),
            variance_percentage=20.0,
            description="Material variance: unfavorable",
        )
        d = comp.to_dict()
        assert d["cost_element"] == "material"
        assert d["variance_type"] == "unfavorable"
        assert d["standard_cost"] == "100"
        assert d["actual_cost"] == "120"
        assert d["variance_amount"] == "20"
        assert d["variance_percentage"] == 20.0
        assert d["description"] == "Material variance: unfavorable"


# ----------------------------------------------------------------------
# VarianceAnalysisResult Value Object
# ----------------------------------------------------------------------
class TestVarianceAnalysisResult:
    def test_construction_valid(self):
        result = VarianceAnalysisResult(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="PROD-001",
            product_name="Test",
            quantity_produced=Decimal("100"),
            standard_cost_total=Decimal("1000"),
            actual_cost_total=Decimal("1200"),
            total_variance=Decimal("200"),
            total_variance_type=VarianceType.UNFAVORABLE,
            components=[],
        )
        assert result.work_order_number == "WO-001"
        assert result.quantity_produced == Decimal("100")
        assert result.standard_cost_total == Decimal("1000")
        assert result.actual_cost_total == Decimal("1200")
        assert result.total_variance == Decimal("200")
        assert result.total_variance_type == VarianceType.UNFAVORABLE

    def test_validation_negative_quantity_raises(self):
        with pytest.raises(ValueError, match="Quantity produced cannot be negative"):
            VarianceAnalysisResult(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                quantity_produced=Decimal("-10"),
                standard_cost_total=Decimal("0"),
                actual_cost_total=Decimal("0"),
                total_variance=Decimal("0"),
                total_variance_type=VarianceType.FAVORABLE,
            )

    def test_validation_negative_standard_cost_raises(self):
        with pytest.raises(ValueError, match="Standard cost total cannot be negative"):
            VarianceAnalysisResult(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                quantity_produced=Decimal("0"),
                standard_cost_total=Decimal("-10"),
                actual_cost_total=Decimal("0"),
                total_variance=Decimal("0"),
                total_variance_type=VarianceType.FAVORABLE,
            )

    def test_validation_negative_total_variance_raises(self):
        with pytest.raises(ValueError, match="Total variance cannot be negative"):
            VarianceAnalysisResult(
                work_order_id=uuid4(),
                work_order_number="WO-001",
                product_id=uuid4(),
                product_code="P",
                product_name="N",
                quantity_produced=Decimal("0"),
                standard_cost_total=Decimal("0"),
                actual_cost_total=Decimal("0"),
                total_variance=Decimal("-10"),
                total_variance_type=VarianceType.FAVORABLE,
            )

    def test_variance_percentage_property(self):
        result = VarianceAnalysisResult(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            quantity_produced=Decimal("100"),
            standard_cost_total=Decimal("1000"),
            actual_cost_total=Decimal("1200"),
            total_variance=Decimal("200"),
            total_variance_type=VarianceType.UNFAVORABLE,
        )
        assert result.variance_percentage == 20.0

    def test_variance_percentage_zero_standard(self):
        result = VarianceAnalysisResult(
            work_order_id=uuid4(),
            work_order_number="WO-001",
            product_id=uuid4(),
            product_code="P",
            product_name="N",
            quantity_produced=Decimal("0"),
            standard_cost_total=Decimal("0"),
            actual_cost_total=Decimal("0"),
            total_variance=Decimal("0"),
            total_variance_type=VarianceType.FAVORABLE,
        )
        assert result.variance_percentage == 0.0

    def test_to_dict(self):
        work_order_id = uuid4()
        product_id = uuid4()
        comp = VarianceComponent(
            cost_element=CostElement.MATERIAL,
            variance_type=VarianceType.FAVORABLE,
            standard_cost=Decimal("100"),
            actual_cost=Decimal("80"),
            variance_amount=Decimal("20"),
            variance_percentage=20.0,
            description="Test",
        )
        result = VarianceAnalysisResult(
            work_order_id=work_order_id,
            work_order_number="WO-001",
            product_id=product_id,
            product_code="PROD",
            product_name="Test",
            quantity_produced=Decimal("100"),
            standard_cost_total=Decimal("1000"),
            actual_cost_total=Decimal("800"),
            total_variance=Decimal("200"),
            total_variance_type=VarianceType.FAVORABLE,
            components=[comp],
            material_price_variance=Decimal("50"),
            material_usage_variance=Decimal("30"),
        )
        d = result.to_dict()
        assert d["work_order_id"] == str(work_order_id)
        assert d["work_order_number"] == "WO-001"
        assert d["product_id"] == str(product_id)
        assert d["quantity_produced"] == "100"
        assert d["standard_cost_total"] == "1000"
        assert d["actual_cost_total"] == "800"
        assert d["total_variance"] == "200"
        assert d["total_variance_type"] == "favorable"
        assert d["variance_percentage"] == 20.0
        assert len(d["components"]) == 1
        assert d["material_price_variance"] == "50"
        assert d["material_usage_variance"] == "30"


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - analyze_variance
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineAnalyze:
    def test_analyze_variance_with_standard_cost(self, engine, mock_work_order, mock_standard_cost):
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1200"),
            actual_labor_cost=Decimal("600"),
            actual_overhead_cost=Decimal("400"),
            standard_cost=mock_standard_cost,
        )
        assert result.work_order_id == mock_work_order.work_order_id
        assert result.work_order_number == "WO-001"
        assert result.quantity_produced == Decimal("100")
        # Standard costs: material 10*100=1000, labor 5*100=500, overhead 3*100=300
        assert result.standard_cost_total == Decimal("1800")
        assert result.actual_cost_total == Decimal("2200")
        assert result.total_variance == Decimal("400")
        assert result.total_variance_type == VarianceType.UNFAVORABLE
        assert len(result.components) == 3

        # Material component
        material_comp = result.components[0]
        assert material_comp.cost_element == CostElement.MATERIAL
        assert material_comp.standard_cost == Decimal("1000")
        assert material_comp.actual_cost == Decimal("1200")
        assert material_comp.variance_amount == Decimal("200")
        assert material_comp.variance_type == VarianceType.UNFAVORABLE
        assert material_comp.variance_percentage == 20.0

        # Labor component
        labor_comp = result.components[1]
        assert labor_comp.cost_element == CostElement.LABOR
        assert labor_comp.standard_cost == Decimal("500")
        assert labor_comp.actual_cost == Decimal("600")
        assert labor_comp.variance_amount == Decimal("100")
        assert labor_comp.variance_percentage == 20.0

        # Overhead component
        overhead_comp = result.components[2]
        assert overhead_comp.cost_element == CostElement.OVERHEAD
        assert overhead_comp.standard_cost == Decimal("300")
        assert overhead_comp.actual_cost == Decimal("400")
        assert overhead_comp.variance_amount == Decimal("100")
        assert overhead_comp.variance_percentage == pytest.approx(33.3333, rel=1e-4)

    def test_analyze_variance_without_standard_cost(self, engine, mock_work_order):
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("900"),
            actual_labor_cost=Decimal("400"),
            actual_overhead_cost=Decimal("200"),
        )
        # Uses work_order standard costs: material 10, labor 5, overhead 3
        assert result.standard_cost_total == Decimal("1800")
        assert result.actual_cost_total == Decimal("1500")
        assert result.total_variance == Decimal("300")
        assert result.total_variance_type == VarianceType.FAVORABLE

    def test_analyze_variance_no_completed_units_raises(self, engine, mock_work_order):
        mock_work_order.completed_quantity = Decimal("0")
        with pytest.raises(ValueError, match="has no completed units"):
            engine.analyze_variance(
                work_order=mock_work_order,
                actual_material_cost=Decimal("0"),
                actual_labor_cost=Decimal("0"),
                actual_overhead_cost=Decimal("0"),
            )

    def test_analyze_variance_favorable_scenario(self, engine, mock_work_order):
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("800"),
            actual_labor_cost=Decimal("400"),
            actual_overhead_cost=Decimal("200"),
        )
        assert result.total_variance_type == VarianceType.FAVORABLE
        assert result.total_variance == Decimal("400")  # 1800 - 1400 = 400

    def test_analyze_variance_stores_history(self, engine, mock_work_order):
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000"),
            actual_labor_cost=Decimal("500"),
            actual_overhead_cost=Decimal("300"),
        )
        history = engine.get_analysis_history()
        assert len(history) == 1
        assert history[0] is result


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - calculate_material_variance
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineMaterialVariance:
    def test_calculate_material_variance_favorable(self, engine):
        result = engine.calculate_material_variance(
            standard_price=Decimal("10"),
            actual_price=Decimal("8"),
            standard_quantity=Decimal("100"),
            actual_quantity=Decimal("90"),
        )
        # Price variance = (8-10)*90 = -180 (favorable)
        # Usage variance = (90-100)*10 = -100 (favorable)
        # Total = -280 (favorable)
        assert result["price_variance"] == Decimal("-180")
        assert result["usage_variance"] == Decimal("-100")
        assert result["total_variance"] == Decimal("-280")

    def test_calculate_material_variance_unfavorable(self, engine):
        result = engine.calculate_material_variance(
            standard_price=Decimal("10"),
            actual_price=Decimal("12"),
            standard_quantity=Decimal("100"),
            actual_quantity=Decimal("110"),
        )
        # Price variance = (12-10)*110 = 220 (unfavorable)
        # Usage variance = (110-100)*10 = 100 (unfavorable)
        # Total = 320 (unfavorable)
        assert result["price_variance"] == Decimal("220")
        assert result["usage_variance"] == Decimal("100")
        assert result["total_variance"] == Decimal("320")

    def test_calculate_material_variance_mixed(self, engine):
        result = engine.calculate_material_variance(
            standard_price=Decimal("10"),
            actual_price=Decimal("9"),
            standard_quantity=Decimal("100"),
            actual_quantity=Decimal("120"),
        )
        # Price variance = (9-10)*120 = -120 (favorable)
        # Usage variance = (120-100)*10 = 200 (unfavorable)
        # Total = 80 (unfavorable)
        assert result["price_variance"] == Decimal("-120")
        assert result["usage_variance"] == Decimal("200")
        assert result["total_variance"] == Decimal("80")

    def test_calculate_material_variance_zero_quantity(self, engine):
        result = engine.calculate_material_variance(
            standard_price=Decimal("10"),
            actual_price=Decimal("12"),
            standard_quantity=Decimal("0"),
            actual_quantity=Decimal("0"),
        )
        assert result["price_variance"] == Decimal("0")
        assert result["usage_variance"] == Decimal("0")
        assert result["total_variance"] == Decimal("0")


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - calculate_labor_variance
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineLaborVariance:
    def test_calculate_labor_variance_favorable(self, engine):
        result = engine.calculate_labor_variance(
            standard_rate=Decimal("20"),
            actual_rate=Decimal("18"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("90"),
        )
        # Rate variance = (18-20)*90 = -180 (favorable)
        # Efficiency variance = (90-100)*20 = -200 (favorable)
        # Total = -380 (favorable)
        assert result["rate_variance"] == Decimal("-180")
        assert result["efficiency_variance"] == Decimal("-200")
        assert result["total_variance"] == Decimal("-380")

    def test_calculate_labor_variance_unfavorable(self, engine):
        result = engine.calculate_labor_variance(
            standard_rate=Decimal("20"),
            actual_rate=Decimal("22"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("110"),
        )
        # Rate variance = (22-20)*110 = 220 (unfavorable)
        # Efficiency variance = (110-100)*20 = 200 (unfavorable)
        # Total = 420 (unfavorable)
        assert result["rate_variance"] == Decimal("220")
        assert result["efficiency_variance"] == Decimal("200")
        assert result["total_variance"] == Decimal("420")

    def test_calculate_labor_variance_mixed(self, engine):
        result = engine.calculate_labor_variance(
            standard_rate=Decimal("20"),
            actual_rate=Decimal("19"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("120"),
        )
        # Rate variance = (19-20)*120 = -120 (favorable)
        # Efficiency variance = (120-100)*20 = 400 (unfavorable)
        # Total = 280 (unfavorable)
        assert result["rate_variance"] == Decimal("-120")
        assert result["efficiency_variance"] == Decimal("400")
        assert result["total_variance"] == Decimal("280")

    def test_calculate_labor_variance_zero_hours(self, engine):
        result = engine.calculate_labor_variance(
            standard_rate=Decimal("20"),
            actual_rate=Decimal("22"),
            standard_hours=Decimal("0"),
            actual_hours=Decimal("0"),
        )
        assert result["rate_variance"] == Decimal("0")
        assert result["efficiency_variance"] == Decimal("0")
        assert result["total_variance"] == Decimal("0")


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - calculate_overhead_variance
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineOverheadVariance:
    def test_calculate_overhead_variance_favorable(self, engine):
        result = engine.calculate_overhead_variance(
            applied_overhead=Decimal("1000"),
            actual_overhead=Decimal("800"),
            budgeted_overhead=Decimal("900"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("80"),
        )
        # Volume variance = 1000 - 900 = 100 (unfavorable? Actually if applied > budgeted, it's unfavorable)
        # Spending variance = 900 - 800 = 100 (favorable)
        # Total = 0? Actually total = 200? Let's check: volume 100, spending 100, total 200? Wait:
        # volume_variance = applied - budgeted = 1000 - 900 = 100 (unfavorable)
        # spending_variance = budgeted - actual = 900 - 800 = 100 (favorable)
        # total = 100 - 100 = 0
        assert result["volume_variance"] == Decimal("100")
        assert result["spending_variance"] == Decimal("100")
        assert result["total_variance"] == Decimal("200")  # 100 + 100 = 200? Actually no, total = volume + spending = 100 + 100 = 200

    def test_calculate_overhead_variance_unfavorable(self, engine):
        result = engine.calculate_overhead_variance(
            applied_overhead=Decimal("800"),
            actual_overhead=Decimal("1000"),
            budgeted_overhead=Decimal("900"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("120"),
        )
        # volume_variance = 800 - 900 = -100 (favorable? Actually negative means favorable)
        # spending_variance = 900 - 1000 = -100 (favorable? Actually negative means favorable)
        # total = -200 (favorable)
        assert result["volume_variance"] == Decimal("-100")
        assert result["spending_variance"] == Decimal("-100")
        assert result["total_variance"] == Decimal("-200")

    def test_calculate_overhead_variance_mixed(self, engine):
        result = engine.calculate_overhead_variance(
            applied_overhead=Decimal("1200"),
            actual_overhead=Decimal("1100"),
            budgeted_overhead=Decimal("1000"),
            standard_hours=Decimal("100"),
            actual_hours=Decimal("120"),
        )
        # volume_variance = 1200 - 1000 = 200 (unfavorable)
        # spending_variance = 1000 - 1100 = -100 (favorable)
        # total = 100 (unfavorable)
        assert result["volume_variance"] == Decimal("200")
        assert result["spending_variance"] == Decimal("-100")
        assert result["total_variance"] == Decimal("100")


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - History & Statistics
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineHistory:
    def test_get_analysis_history_default(self, engine, mock_work_order):
        # Run multiple analyses
        for i in range(3):
            engine.analyze_variance(
                work_order=mock_work_order,
                actual_material_cost=Decimal("1000"),
                actual_labor_cost=Decimal("500"),
                actual_overhead_cost=Decimal("300"),
            )
        history = engine.get_analysis_history()
        assert len(history) == 3

    def test_get_analysis_history_limit(self, engine, mock_work_order):
        for i in range(5):
            engine.analyze_variance(
                work_order=mock_work_order,
                actual_material_cost=Decimal("1000"),
                actual_labor_cost=Decimal("500"),
                actual_overhead_cost=Decimal("300"),
            )
        history = engine.get_analysis_history(limit=3)
        assert len(history) == 3

    def test_get_analysis_history_filter_by_work_order(self, engine, mock_work_order):
        # Create another work order
        wo2 = MagicMock()
        wo2.work_order_id = uuid4()
        wo2.work_order_number = "WO-002"
        wo2.product_id = uuid4()
        wo2.product_code = "PROD-002"
        wo2.product_name = "Other"
        wo2.completed_quantity = Decimal("50")
        wo2.material_standard_cost = Decimal("10")
        wo2.labor_standard_cost = Decimal("5")
        wo2.overhead_standard_cost = Decimal("3")

        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000"),
            actual_labor_cost=Decimal("500"),
            actual_overhead_cost=Decimal("300"),
        )
        engine.analyze_variance(
            work_order=wo2,
            actual_material_cost=Decimal("500"),
            actual_labor_cost=Decimal("250"),
            actual_overhead_cost=Decimal("150"),
        )

        history_wo1 = engine.get_analysis_history(work_order_id=mock_work_order.work_order_id)
        assert len(history_wo1) == 1
        assert history_wo1[0].work_order_number == "WO-001"

        history_wo2 = engine.get_analysis_history(work_order_id=wo2.work_order_id)
        assert len(history_wo2) == 1
        assert history_wo2[0].work_order_number == "WO-002"

    def test_get_summary_statistics_empty(self, engine):
        stats = engine.get_summary_statistics()
        assert stats == {"total_analyses": 0}

    def test_get_summary_statistics_with_analyses(self, engine, mock_work_order):
        # Run analyses with different results
        # Analysis 1: Favorable (actual < standard)
        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("800"),
            actual_labor_cost=Decimal("400"),
            actual_overhead_cost=Decimal("200"),
        )
        # Analysis 2: Unfavorable (actual > standard)
        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1200"),
            actual_labor_cost=Decimal("600"),
            actual_overhead_cost=Decimal("400"),
        )
        # Analysis 3: Favorable
        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("900"),
            actual_labor_cost=Decimal("450"),
            actual_overhead_cost=Decimal("250"),
        )

        stats = engine.get_summary_statistics()
        assert stats["total_analyses"] == 3
        assert stats["total_quantity_produced"] == "300"
        assert stats["favorable_analyses"] == 2
        assert stats["unfavorable_analyses"] == 1

        # Favorable rate = 2/3 ≈ 0.6667
        assert stats["favorable_rate"] == pytest.approx(0.6667, rel=1e-4)

        # Weighted average variance percentage:
        # Analysis 1: standard=1800, actual=1400, variance=400, pct=22.22%, qty=100
        # Analysis 2: standard=1800, actual=2200, variance=400, pct=22.22%, qty=100
        # Analysis 3: standard=1800, actual=1600, variance=200, pct=11.11%, qty=100
        # Weighted avg = (22.22*100 + 22.22*100 + 11.11*100) / 300 = 18.52
        expected_avg = (22.2222 + 22.2222 + 11.1111) / 3
        assert stats["average_variance_percentage"] == pytest.approx(expected_avg, rel=1e-4)

    def test_reset(self, engine, mock_work_order):
        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000"),
            actual_labor_cost=Decimal("500"),
            actual_overhead_cost=Decimal("300"),
        )
        assert len(engine._analysis_history) == 1
        engine.reset()
        assert len(engine._analysis_history) == 0

    def test_get_summary_statistics_decimal_precision(self, engine, mock_work_order):
        # Test with values that produce repeating decimals
        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000"),
            actual_labor_cost=Decimal("500"),
            actual_overhead_cost=Decimal("300"),
        )
        stats = engine.get_summary_statistics()
        assert stats["average_variance_percentage"] == 0.0  # actual == standard

        # Create a scenario with non-zero variance percentage
        engine.reset()
        mock_work_order.completed_quantity = Decimal("33")
        mock_work_order.material_standard_cost = Decimal("10")
        mock_work_order.labor_standard_cost = Decimal("5")
        mock_work_order.overhead_standard_cost = Decimal("3")

        engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("400"),
            actual_labor_cost=Decimal("200"),
            actual_overhead_cost=Decimal("100"),
        )
        # Standard total = (10+5+3)*33 = 18*33 = 594
        # Actual total = 700
        # Variance = 106
        # Percentage = 106/594*100 = 17.8451...
        stats = engine.get_summary_statistics()
        expected_pct = 106 / 594 * 100
        assert stats["average_variance_percentage"] == pytest.approx(expected_pct, rel=1e-4)


# ----------------------------------------------------------------------
# VarianceAnalysisEngine - Helper Method
# ----------------------------------------------------------------------
class TestVarianceAnalysisEngineHelper:
    def test_calc_percentage_zero_base(self, engine):
        # _calc_percentage is a static method, but we can access it via the class
        result = VarianceAnalysisEngine._calc_percentage(Decimal("100"), Decimal("0"))
        assert result == 0.0

    def test_calc_percentage_normal(self, engine):
        result = VarianceAnalysisEngine._calc_percentage(Decimal("20"), Decimal("100"))
        assert result == 20.0

    def test_calc_percentage_with_decimal_precision(self, engine):
        result = VarianceAnalysisEngine._calc_percentage(Decimal("33.33"), Decimal("100"))
        assert result == 33.33
        # The result is a float, so it should be close to 33.33
        assert result == pytest.approx(33.33, rel=1e-5)


# ----------------------------------------------------------------------
# Edge Cases and Integration
# ----------------------------------------------------------------------
class TestEdgeCases:
    def test_all_variances_with_zero_standard_costs(self, engine, mock_work_order):
        mock_work_order.material_standard_cost = Decimal("0")
        mock_work_order.labor_standard_cost = Decimal("0")
        mock_work_order.overhead_standard_cost = Decimal("0")
        # When standard costs are zero, variance percentage should be 0
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("100"),
            actual_labor_cost=Decimal("50"),
            actual_overhead_cost=Decimal("25"),
        )
        # All variance percentages should be 0 (no standard base)
        for comp in result.components:
            assert comp.variance_percentage == 0.0
        assert result.variance_percentage == 0.0

    def test_exact_match_no_variance(self, engine, mock_work_order):
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000"),
            actual_labor_cost=Decimal("500"),
            actual_overhead_cost=Decimal("300"),
        )
        assert result.total_variance == Decimal("0")
        assert result.total_variance_type == VarianceType.FAVORABLE  # 0 is considered favorable
        for comp in result.components:
            assert comp.variance_amount == Decimal("0")

    def test_large_numbers(self, engine, mock_work_order):
        mock_work_order.completed_quantity = Decimal("1000000")
        mock_work_order.material_standard_cost = Decimal("999.99")
        mock_work_order.labor_standard_cost = Decimal("499.99")
        mock_work_order.overhead_standard_cost = Decimal("299.99")
        result = engine.analyze_variance(
            work_order=mock_work_order,
            actual_material_cost=Decimal("1000000000"),
            actual_labor_cost=Decimal("500000000"),
            actual_overhead_cost=Decimal("300000000"),
        )
        # Standard total = (999.99+499.99+299.99)*1000000 = 1799.97*1000000 = 1799970000
        # Actual total = 1800000000
        # Variance = 30000
        # Should handle large numbers without overflow
        assert result.total_variance == Decimal("30000")
        # Variance percentage = 30000/1799970000*100 ≈ 0.0016667%
        assert result.variance_percentage == pytest.approx(0.0016667, rel=1e-4)
