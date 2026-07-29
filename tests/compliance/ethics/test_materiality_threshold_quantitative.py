# tests/compliance/ethics/test_materiality_threshold_quantitative.py
"""
Comprehensive tests for compliance/ethics/materiality_threshold_quantitative.py
Covers all enums, data classes, and QuantitativeMateriality methods including:
- set_percentage, get_benchmark_value
- calculate_planning_materiality, calculate_performance_materiality,
  calculate_clearly_trivial_threshold, calculate_specific_materiality
- assess_error, is_material, get_all_calculations, sensitivity_analysis
- generate_report, to_json
"""

import json
import tempfile
from datetime import datetime
from decimal import Decimal

import pytest

from compliance.ethics.materiality_threshold_quantitative import (
    BenchmarkType,
    MaterialityAssessment,
    MaterialityThreshold,
    MaterialityType,
    QuantitativeMateriality,
)

# ============================================================================
# Enum tests
# ============================================================================

class TestMaterialityType:
    def test_members(self):
        assert MaterialityType.PLANNING_MATERIALITY is not None
        assert MaterialityType.PERFORMANCE_MATERIALITY is not None
        assert MaterialityType.CLEARLY_TRIVIAL is not None
        assert MaterialityType.SPECIFIC_MATERIALITY is not None
        assert MaterialityType.PLANNING_MATERIALITY.value == "planning_materiality"
        assert MaterialityType.PERFORMANCE_MATERIALITY.value == "performance_materiality"
        assert MaterialityType.CLEARLY_TRIVIAL.value == "clearly_trivial"
        assert MaterialityType.SPECIFIC_MATERIALITY.value == "specific_materiality"


class TestBenchmarkType:
    def test_members(self):
        assert BenchmarkType.REVENUE is not None
        assert BenchmarkType.TOTAL_ASSETS is not None
        assert BenchmarkType.TOTAL_EQUITY is not None
        assert BenchmarkType.PROFIT_BEFORE_TAX is not None
        assert BenchmarkType.NET_PROFIT is not None
        assert BenchmarkType.GROSS_PROFIT is not None
        assert BenchmarkType.OPERATING_CASH_FLOW is not None
        assert BenchmarkType.REVENUE.value == "revenue"
        assert BenchmarkType.PROFIT_BEFORE_TAX.value == "profit_before_tax"


# ============================================================================
# MaterialityThreshold tests
# ============================================================================

class TestMaterialityThreshold:
    def test_construction(self):
        now = datetime(2026, 1, 15, 12, 0, 0)
        threshold = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            benchmark_value=Decimal("100000000"),
            percentage=Decimal("0.05"),
            threshold_value=Decimal("5000000"),
            calculated_at=now,
            calculated_by="auditor",
        )
        assert threshold.materiality_type == MaterialityType.PLANNING_MATERIALITY
        assert threshold.benchmark == BenchmarkType.PROFIT_BEFORE_TAX
        assert threshold.benchmark_value == Decimal("100000000")
        assert threshold.percentage == Decimal("0.05")
        assert threshold.threshold_value == Decimal("5000000")
        assert threshold.calculated_at == now
        assert threshold.calculated_by == "auditor"
        assert threshold._hash is not None
        assert isinstance(threshold._hash, str)
        assert len(threshold._hash) == 64  # SHA256

    def test_compute_hash_consistent(self):
        threshold1 = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.REVENUE,
            benchmark_value=Decimal("100"),
            percentage=Decimal("0.01"),
            threshold_value=Decimal("1"),
            calculated_at=datetime(2026, 1, 1),
            calculated_by="system",
        )
        threshold2 = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.REVENUE,
            benchmark_value=Decimal("100"),
            percentage=Decimal("0.01"),
            threshold_value=Decimal("1"),
            calculated_at=datetime(2026, 1, 2),  # different timestamp but should not affect hash
            calculated_by="system",
        )
        # Hash should be same because timestamp and calculated_by are not included in hash
        assert threshold1._hash == threshold2._hash

        # Different percentage changes hash
        threshold3 = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.REVENUE,
            benchmark_value=Decimal("100"),
            percentage=Decimal("0.02"),
            threshold_value=Decimal("2"),
            calculated_at=datetime(2026, 1, 1),
            calculated_by="system",
        )
        assert threshold1._hash != threshold3._hash

    def test_to_dict(self):
        now = datetime(2026, 1, 15, 12, 0, 0)
        threshold = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            benchmark_value=Decimal("100000000"),
            percentage=Decimal("0.05"),
            threshold_value=Decimal("5000000"),
            calculated_at=now,
            calculated_by="auditor",
        )
        d = threshold.to_dict()
        assert d["materiality_type"] == "planning_materiality"
        assert d["benchmark"] == "profit_before_tax"
        assert d["benchmark_value"] == "100000000"
        assert d["percentage"] == 0.05
        assert d["threshold_value"] == "5000000"
        assert d["calculated_at"] == now.isoformat()
        assert d["calculated_by"] == "auditor"
        assert "hash" in d


# ============================================================================
# MaterialityAssessment tests
# ============================================================================

class TestMaterialityAssessment:
    def test_construction(self):
        now = datetime(2026, 1, 15, 12, 0, 0)
        threshold = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            benchmark_value=Decimal("100000000"),
            percentage=Decimal("0.05"),
            threshold_value=Decimal("5000000"),
            calculated_at=now,
            calculated_by="auditor",
        )
        error = Decimal("3000000")
        assessment = MaterialityAssessment(error, threshold)
        assert assessment.error_amount == error
        assert assessment.threshold is threshold
        assert assessment.is_material is False  # 3M < 5M
        # Percentage of threshold: (3M / 5M) * 100 = 60.00
        assert assessment.percentage_of_threshold == Decimal("60.00")
        assert assessment.assessed_at is not None

        # Material error
        error2 = Decimal("6000000")
        assessment2 = MaterialityAssessment(error2, threshold)
        assert assessment2.is_material is True
        # Percentage: (6M / 5M) * 100 = 120.00
        assert assessment2.percentage_of_threshold == Decimal("120.00")

        # Zero threshold edge case
        zero_threshold = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.REVENUE,
            benchmark_value=Decimal("0"),
            percentage=Decimal("0"),
            threshold_value=Decimal("0"),
            calculated_at=now,
            calculated_by="system",
        )
        assessment3 = MaterialityAssessment(Decimal("100"), zero_threshold)
        assert assessment3.percentage_of_threshold == Decimal("0")

    def test_to_dict(self):
        now = datetime(2026, 1, 15, 12, 0, 0)
        threshold = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            benchmark_value=Decimal("100000000"),
            percentage=Decimal("0.05"),
            threshold_value=Decimal("5000000"),
            calculated_at=now,
            calculated_by="auditor",
        )
        error = Decimal("3000000")
        assessment = MaterialityAssessment(error, threshold)
        d = assessment.to_dict()
        assert d["error_amount"] == "3000000"
        assert d["threshold"] == "5000000"
        assert d["is_material"] is False
        assert d["percentage_of_threshold"] == 60.0


# ============================================================================
# QuantitativeMateriality tests
# ============================================================================

class TestQuantitativeMateriality:
    @pytest.fixture
    def qm(self):
        return QuantitativeMateriality()

    @pytest.fixture
    def sample_financials(self):
        return {
            BenchmarkType.PROFIT_BEFORE_TAX: Decimal("100000000"),
            BenchmarkType.REVENUE: Decimal("500000000"),
            BenchmarkType.TOTAL_ASSETS: Decimal("800000000"),
            BenchmarkType.TOTAL_EQUITY: Decimal("300000000"),
        }

    @pytest.fixture
    def fixed_now(self):
        with patch('compliance.ethics.materiality_threshold_quantitative.datetime') as mock_dt:
            fixed = datetime(2026, 1, 15, 12, 0, 0)
            mock_dt.utcnow.return_value = fixed
            yield fixed

    # ---- set_percentage ----
    def test_set_percentage_valid(self, qm):
        qm.set_percentage(BenchmarkType.REVENUE, Decimal("0.01"))
        assert qm._percentages[BenchmarkType.REVENUE] == Decimal("0.01")

    def test_set_percentage_invalid_negative(self, qm):
        with pytest.raises(ValueError, match="Percentage must be between 0 and 1"):
            qm.set_percentage(BenchmarkType.REVENUE, Decimal("-0.01"))

    def test_set_percentage_invalid_gt_one(self, qm):
        with pytest.raises(ValueError, match="Percentage must be between 0 and 1"):
            qm.set_percentage(BenchmarkType.REVENUE, Decimal("1.1"))

    # ---- get_benchmark_value ----
    def test_get_benchmark_value_positive(self, qm, sample_financials):
        val = qm.get_benchmark_value(sample_financials, BenchmarkType.PROFIT_BEFORE_TAX)
        assert val == Decimal("100000000")

    def test_get_benchmark_value_missing(self, qm):
        val = qm.get_benchmark_value({}, BenchmarkType.REVENUE)
        assert val == Decimal("0")

    def test_get_benchmark_value_negative_becomes_positive(self, qm):
        financials = {BenchmarkType.PROFIT_BEFORE_TAX: Decimal("-50000000")}
        val = qm.get_benchmark_value(financials, BenchmarkType.PROFIT_BEFORE_TAX)
        assert val == Decimal("50000000")

    # ---- calculate_planning_materiality ----
    def test_calculate_planning_materiality_primary(self, qm, sample_financials, fixed_now):
        mat = qm.calculate_planning_materiality(
            sample_financials,
            primary_benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            fallback_benchmark=BenchmarkType.TOTAL_ASSETS,
            calculated_by="tester",
        )
        assert mat.materiality_type == MaterialityType.PLANNING_MATERIALITY
        assert mat.benchmark == BenchmarkType.PROFIT_BEFORE_TAX
        assert mat.benchmark_value == Decimal("100000000")
        # Default percentage for profit_before_tax is 0.05
        assert mat.percentage == Decimal("0.05")
        # threshold = 100,000,000 * 0.05 = 5,000,000
        assert mat.threshold_value == Decimal("5000000")
        assert mat.calculated_by == "tester"
        assert mat.calculated_at == fixed_now
        # Check that calculation was stored
        assert len(qm._calculations) == 1
        assert qm._calculations[0] is mat

    def test_calculate_planning_materiality_uses_fallback(self, qm, sample_financials):
        # Set primary benchmark value to 0 (or negative) so fallback is used
        financials = sample_financials.copy()
        financials[BenchmarkType.PROFIT_BEFORE_TAX] = Decimal("0")
        mat = qm.calculate_planning_materiality(
            financials,
            primary_benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            fallback_benchmark=BenchmarkType.TOTAL_ASSETS,
        )
        # Should use TOTAL_ASSETS (800,000,000) with default percentage 0.005 -> 4,000,000
        assert mat.benchmark == BenchmarkType.TOTAL_ASSETS
        assert mat.benchmark_value == Decimal("800000000")
        assert mat.percentage == Decimal("0.005")
        assert mat.threshold_value == Decimal("4000000")

    def test_calculate_planning_materiality_fallback_zero_raises(self, qm):
        financials = {BenchmarkType.PROFIT_BEFORE_TAX: Decimal("0"), BenchmarkType.TOTAL_ASSETS: Decimal("0")}
        with pytest.raises(ValueError, match="No valid benchmark with positive value found"):
            qm.calculate_planning_materiality(financials)

    def test_calculate_planning_materiality_uses_absolute_for_negative(self, qm):
        financials = {BenchmarkType.PROFIT_BEFORE_TAX: Decimal("-50000000")}
        mat = qm.calculate_planning_materiality(financials)
        # Should use absolute value 50,000,000 * 0.05 = 2,500,000
        assert mat.benchmark_value == Decimal("50000000")
        assert mat.threshold_value == Decimal("2500000")

    # ---- calculate_performance_materiality ----
    def test_calculate_performance_materiality(self, qm, sample_financials):
        planning = qm.calculate_planning_materiality(sample_financials)
        performance = qm.calculate_performance_materiality(planning, calculated_by="tester")
        assert performance.materiality_type == MaterialityType.PERFORMANCE_MATERIALITY
        assert performance.benchmark == planning.benchmark
        assert performance.benchmark_value == planning.benchmark_value
        # percentage = 0.05 * 0.75 = 0.0375
        assert performance.percentage == Decimal("0.05") * Decimal("0.75")
        # threshold = 5,000,000 * 0.75 = 3,750,000
        assert performance.threshold_value == Decimal("3750000")
        assert performance.calculated_by == "tester"

    # ---- calculate_clearly_trivial_threshold ----
    def test_calculate_clearly_trivial_threshold(self, qm, sample_financials):
        planning = qm.calculate_planning_materiality(sample_financials)
        trivial = qm.calculate_clearly_trivial_threshold(planning, calculated_by="tester")
        assert trivial.materiality_type == MaterialityType.CLEARLY_TRIVIAL
        assert trivial.benchmark == planning.benchmark
        assert trivial.percentage == Decimal("0.05") * Decimal("0.05")  # 0.05 * 0.05 = 0.0025
        assert trivial.threshold_value == Decimal("5000000") * Decimal("0.05")  # 250,000
        assert trivial.calculated_by == "tester"

    # ---- calculate_specific_materiality ----
    def test_calculate_specific_materiality_with_default_percentage(self, qm, fixed_now):
        benchmark = BenchmarkType.REVENUE
        benchmark_value = Decimal("20000000")
        mat = qm.calculate_specific_materiality(
            benchmark=benchmark,
            benchmark_value=benchmark_value,
            calculated_by="spec_tester",
        )
        assert mat.materiality_type == MaterialityType.SPECIFIC_MATERIALITY
        assert mat.benchmark == benchmark
        assert mat.benchmark_value == benchmark_value
        # Default percentage for REVENUE is 0.005
        assert mat.percentage == Decimal("0.005")
        assert mat.threshold_value == benchmark_value * Decimal("0.005")  # 100,000
        assert mat.calculated_by == "spec_tester"
        assert mat.calculated_at == fixed_now
        # Stored
        assert len(qm._calculations) == 1

    def test_calculate_specific_materiality_with_custom_percentage(self, qm):
        benchmark = BenchmarkType.TOTAL_EQUITY
        benchmark_value = Decimal("500000000")
        custom_pct = Decimal("0.02")
        mat = qm.calculate_specific_materiality(
            benchmark=benchmark,
            benchmark_value=benchmark_value,
            percentage=custom_pct,
        )
        assert mat.percentage == custom_pct
        assert mat.threshold_value == benchmark_value * custom_pct  # 10,000,000

    # ---- assess_error ----
    def test_assess_error(self, qm, sample_financials):
        planning = qm.calculate_planning_materiality(sample_financials)
        error = Decimal("3000000")
        assessment = qm.assess_error(error, planning)
        assert isinstance(assessment, MaterialityAssessment)
        assert assessment.error_amount == error
        assert assessment.threshold is planning
        assert assessment.is_material is False
        # 3M / 5M * 100 = 60.0
        assert assessment.percentage_of_threshold == Decimal("60.00")

        error2 = Decimal("6000000")
        assessment2 = qm.assess_error(error2, planning)
        assert assessment2.is_material is True
        assert assessment2.percentage_of_threshold == Decimal("120.00")

    # ---- is_material convenience ----
    def test_is_material(self, qm, sample_financials):
        error = Decimal("3000000")
        is_mat, threshold = qm.is_material(
            error,
            sample_financials,
            primary_benchmark=BenchmarkType.PROFIT_BEFORE_TAX,
            fallback_benchmark=BenchmarkType.TOTAL_ASSETS,
        )
        assert is_mat is False
        assert threshold.threshold_value == Decimal("5000000")
        # Should also have stored the calculation
        assert len(qm._calculations) == 1

    # ---- get_all_calculations ----
    def test_get_all_calculations(self, qm, sample_financials):
        assert qm.get_all_calculations() == []
        # Add some calculations
        planning = qm.calculate_planning_materiality(sample_financials)
        qm.calculate_performance_materiality(planning)
        qm.calculate_clearly_trivial_threshold(planning)
        all_calcs = qm.get_all_calculations()
        assert len(all_calcs) == 3
        assert all_calcs[0].materiality_type == MaterialityType.PLANNING_MATERIALITY
        assert all_calcs[1].materiality_type == MaterialityType.PERFORMANCE_MATERIALITY
        assert all_calcs[2].materiality_type == MaterialityType.CLEARLY_TRIVIAL

    # ---- sensitivity_analysis ----
    def test_sensitivity_analysis(self, qm, sample_financials):
        # Default variations: 0.002, 0.005, 0.01, 0.02
        results = qm.sensitivity_analysis(sample_financials)
        # For profit_before_tax = 100,000,000:
        # 0.002 -> 200,000
        # 0.005 -> 500,000
        # 0.01 -> 1,000,000
        # 0.02 -> 2,000,000
        assert results["0.002"] == 200000.0
        assert results["0.005"] == 500000.0
        assert results["0.01"] == 1000000.0
        assert results["0.02"] == 2000000.0

    def test_sensitivity_analysis_custom_variations(self, qm, sample_financials):
        variations = [Decimal("0.001"), Decimal("0.003")]
        results = qm.sensitivity_analysis(sample_financials, variations)
        assert results["0.001"] == 100000.0  # 100,000,000 * 0.001 = 100,000
        assert results["0.003"] == 300000.0

    def test_sensitivity_analysis_handles_value_error(self, qm):
        # Financial data with no valid benchmark (all zero)
        financials = {
            BenchmarkType.PROFIT_BEFORE_TAX: Decimal("0"),
            BenchmarkType.REVENUE: Decimal("0"),
            BenchmarkType.TOTAL_ASSETS: Decimal("0"),
        }
        results = qm.sensitivity_analysis(financials)
        for pct, val in results.items():
            assert val is None

    # ---- generate_report ----
    def test_generate_report_empty(self, qm):
        report = qm.generate_report()
        assert report["total_calculations"] == 0

    def test_generate_report_with_calculations(self, qm, sample_financials):
        planning = qm.calculate_planning_materiality(sample_financials)
        qm.calculate_performance_materiality(planning)
        report = qm.generate_report()
        assert report["total_calculations"] == 2
        assert report["by_type"]["planning_materiality"] == 1
        assert report["by_type"]["performance_materiality"] == 1
        assert report["by_type"]["clearly_trivial"] == 0
        assert report["by_type"]["specific_materiality"] == 0
        assert report["latest"] is not None
        assert report["latest"]["materiality_type"] == "performance_materiality"

    # ---- to_json ----
    def test_to_json(self, qm, sample_financials):
        qm.calculate_planning_materiality(sample_financials)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            qm.to_json(f.name)
            with open(f.name) as f2:
                data = json.load(f2)
                assert "report" in data
                assert "calculations" in data
                assert len(data["calculations"]) == 1
                assert data["calculations"][0]["materiality_type"] == "planning_materiality"

    # ---- default percentages ----
    def test_default_percentages(self):
        qm = QuantitativeMateriality()
        # Verify that default percentages are set
        assert qm._percentages[BenchmarkType.REVENUE] == Decimal("0.005")
        assert qm._percentages[BenchmarkType.TOTAL_ASSETS] == Decimal("0.005")
        assert qm._percentages[BenchmarkType.PROFIT_BEFORE_TAX] == Decimal("0.05")
        # Also check constants
        assert Decimal("0.75") == QuantitativeMateriality.PERFORMANCE_MATERIALITY_FACTOR
        assert Decimal("0.05") == QuantitativeMateriality.CLEARLY_TRIVIAL_FACTOR
