#!/usr/bin/env python3
"""
Comprehensive tests for compliance/psak_checker.py

Covers:
- All enums (PSAKStandard, ComplianceStatus)
- Exceptions (PSAKComplianceError, StandardNotFoundError)
- Data classes (PSAKComplianceResult, PSAKGapAnalysis)
- PsakChecker:
  - All assess_* methods (PSAK 1, 2, 14, 16, 46, 48, 71, 72, 73, 101)
  - Helper methods: get_compliance_result, get_all_results, add_gap_analysis,
    get_gap_analyses, generate_full_compliance_report, generate_summary,
    to_json, to_csv, _result_to_dict, update_remediation, get_remediation_status,
    check, validate, get_violations
- Module-level function check_psak_compliance
- All edge cases (partial, non-compliance, empty results)
- No flaky tests (mocked date)
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from compliance.psak_checker import (
    ComplianceStatus,
    PsakChecker,
    PSAKComplianceError,
    PSAKComplianceResult,
    PSAKGapAnalysis,
    PSAKStandard,
    StandardNotFoundError,
    check_psak_compliance,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_today() -> date:
    """Return a fixed date for today to avoid flaky tests."""
    return date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_date_today(fixed_today):
    """Mock date.today() to return fixed_today."""
    with patch("compliance.psak_checker.date") as mock_date:
        mock_date.today.return_value = fixed_today
        yield mock_date


@pytest.fixture
def checker(fixed_today) -> PsakChecker:
    """Create a PsakChecker instance with default values."""
    return PsakChecker(entity_name="PT Test", fiscal_year_end=fixed_today)


# =============================================================================
# Enums
# =============================================================================

class TestPSAKStandard:
    def test_members_exist(self):
        # Check a few members
        assert PSAKStandard.PSAK_1.value == "PSAK 1 - Penyajian Laporan Keuangan"
        assert PSAKStandard.PSAK_14.value == "PSAK 14 - Persediaan"
        assert PSAKStandard.PSAK_72.value == "PSAK 72 - Pendapatan dari Kontrak dengan Pelanggan"
        assert PSAKStandard.PSAK_101.value == "PSAK 101 - Penyajian Laporan Keuangan Entitas UMKM"
        assert isinstance(PSAKStandard.PSAK_1, PSAKStandard)


class TestComplianceStatus:
    def test_members_exist(self):
        assert ComplianceStatus.COMPLIANT.value == "compliant"
        assert ComplianceStatus.PARTIALLY_COMPLIANT.value == "partially_compliant"
        assert ComplianceStatus.NON_COMPLIANT.value == "non_compliant"
        assert isinstance(ComplianceStatus.COMPLIANT, ComplianceStatus)


# =============================================================================
# Exceptions
# =============================================================================

class TestExceptions:
    def test_psak_compliance_error(self):
        with pytest.raises(PSAKComplianceError):
            raise PSAKComplianceError("test")

    def test_standard_not_found_error(self):
        with pytest.raises(StandardNotFoundError):
            raise StandardNotFoundError("test")


# =============================================================================
# Data Classes
# =============================================================================

class TestPSAKComplianceResult:
    def test_creation_and_hash(self):
        result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_1,
            status=ComplianceStatus.COMPLIANT,
            compliance_percentage=Decimal("85.00"),
            findings=["Finding 1"],
            recommendations=["Recommendation 1"],
            evidence_required=["Evidence 1"],
            assessed_by="auditor",
            assessed_date=date(2026, 1, 1),
            remediation_deadline=date(2026, 6, 30),
            remediation_status="in_progress",
        )
        assert result.standard == PSAKStandard.PSAK_1
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("85.00")
        assert result.findings == ["Finding 1"]
        assert result.recommendations == ["Recommendation 1"]
        assert result.evidence_required == ["Evidence 1"]
        assert result.assessed_by == "auditor"
        assert result.assessed_date == date(2026, 1, 1)
        assert result.remediation_deadline == date(2026, 6, 30)
        assert result.remediation_status == "in_progress"
        assert result.hash_sha256 != ""
        assert len(result.hash_sha256) == 64


class TestPSAKGapAnalysis:
    def test_creation(self):
        gap = PSAKGapAnalysis(
            standard=PSAKStandard.PSAK_72,
            current_practice="Legacy revenue recognition",
            required_practice="5-step model",
            gap_description="No identification of performance obligations",
            impact="high",
            remediation_plan="Train staff",
            estimated_effort_days=30,
            responsible_party="Finance",
        )
        assert gap.standard == PSAKStandard.PSAK_72
        assert gap.current_practice == "Legacy revenue recognition"
        assert gap.required_practice == "5-step model"
        assert gap.gap_description == "No identification of performance obligations"
        assert gap.impact == "high"
        assert gap.remediation_plan == "Train staff"
        assert gap.estimated_effort_days == 30
        assert gap.responsible_party == "Finance"


# =============================================================================
# PsakChecker - Assess Methods
# =============================================================================

class TestAssessPSAK1:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_1(
            financial_statements_prepared=True,
            comparative_figures=True,
            going_concern_assessed=True,
            materiality_applied=True,
            disclosure_of_estimates=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")
        assert result.findings == []
        assert result.recommendations == []
        assert result.standard == PSAKStandard.PSAK_1

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_1(
            financial_statements_prepared=True,
            comparative_figures=False,
            going_concern_assessed=True,
            materiality_applied=False,
            disclosure_of_estimates=True,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("60")
        assert len(result.findings) == 2
        assert any("komparatif" in f for f in result.findings)
        assert any("Materialitas" in f for f in result.findings)
        assert len(result.recommendations) == 2

    def test_non_compliant(self, checker):
        result = checker.assess_psak_1(
            financial_statements_prepared=False,
            comparative_figures=False,
            going_concern_assessed=False,
            materiality_applied=False,
            disclosure_of_estimates=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")
        assert len(result.findings) == 5


class TestAssessPSAK2:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_2(
            cash_flow_statement_prepared=True,
            operating_activities_classified=True,
            investing_financing_separated=True,
            non_cash_transactions_disclosed=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_2(
            cash_flow_statement_prepared=True,
            operating_activities_classified=False,
            investing_financing_separated=True,
            non_cash_transactions_disclosed=False,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("50")
        assert len(result.findings) == 2


class TestAssessPSAK14:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_14(
            cost_formula_consistent=True,
            nrv_assessed=True,
            inventory_measured_at_lower_cost_nrv=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_non_compliant(self, checker):
        result = checker.assess_psak_14(
            cost_formula_consistent=False,
            nrv_assessed=False,
            inventory_measured_at_lower_cost_nrv=False,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")


class TestAssessPSAK16:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_16(
            depreciation_appropriate=True,
            revaluation_model_applied_correctly=True,
            component_depreciation=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")


class TestAssessPSAK46:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_46(
            tax_reconciliation=True,
            deferred_tax_recognized=True,
            current_tax_accurate=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_46(
            tax_reconciliation=True,
            deferred_tax_recognized=False,
            current_tax_accurate=True,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("50")


class TestAssessPSAK48:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_48(
            impairment_test_performed=True,
            cgu_identified=True,
            recoverable_amount_calculated=True,
            impairment_recognized_if_needed=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_non_compliant(self, checker):
        result = checker.assess_psak_48(
            impairment_test_performed=False,
            cgu_identified=False,
            recoverable_amount_calculated=False,
            impairment_recognized_if_needed=False,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")


class TestAssessPSAK71:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_71(
            classification_documented=True,
            ecl_calculated=True,
            hedge_effectiveness_tested=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_71(
            classification_documented=True,
            ecl_calculated=False,
            hedge_effectiveness_tested=True,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("50")


class TestAssessPSAK72:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_72(
            five_step_model_followed=True,
            contract_asset_liability_recognized=True,
            performance_obligations_identified=True,
            transaction_price_allocated=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_72(
            five_step_model_followed=True,
            contract_asset_liability_recognized=False,
            performance_obligations_identified=True,
            transaction_price_allocated=True,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("60")
        assert len(result.findings) == 2


class TestAssessPSAK73:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_73(
            lessee_model_applied=True,
            right_of_use_asset_recognized=True,
            lease_liability_recognized=True,
            discount_rate_determined=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_non_compliant(self, checker):
        result = checker.assess_psak_73(
            lessee_model_applied=False,
            right_of_use_asset_recognized=False,
            lease_liability_recognized=False,
            discount_rate_determined=False,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")


class TestAssessPSAK101:
    def test_full_compliance(self, checker):
        result = checker.assess_psak_101(
            simplified_statements=True,
            tax_compliance_helper_used=True,
            disclosure_appropriate=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_partial_compliance(self, checker):
        result = checker.assess_psak_101(
            simplified_statements=True,
            tax_compliance_helper_used=False,
            disclosure_appropriate=True,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("70")


# =============================================================================
# PsakChecker - Helper Methods
# =============================================================================

class TestHelperMethods:
    def test_get_compliance_result(self, checker):
        # Assess one standard
        checker.assess_psak_1(
            financial_statements_prepared=True,
            comparative_figures=True,
            going_concern_assessed=True,
            materiality_applied=True,
            disclosure_of_estimates=True,
        )
        result = checker.get_compliance_result(PSAKStandard.PSAK_1)
        assert result is not None
        assert result.standard == PSAKStandard.PSAK_1
        # Non-existent
        result = checker.get_compliance_result(PSAKStandard.PSAK_14)
        assert result is None

    def test_get_all_results(self, checker):
        assert checker.get_all_results() == []
        checker.assess_psak_1(True, True, True, True, True)
        results = checker.get_all_results()
        assert len(results) == 1
        assert results[0].standard == PSAKStandard.PSAK_1

    def test_add_gap_analysis(self, checker):
        gap = PSAKGapAnalysis(
            standard=PSAKStandard.PSAK_72,
            current_practice="Old",
            required_practice="New",
            gap_description="Gap",
            impact="high",
            remediation_plan="Plan",
            estimated_effort_days=10,
            responsible_party="Team",
        )
        checker.add_gap_analysis(gap)
        assert len(checker._gap_analyses) == 1
        assert checker._gap_analyses[0] == gap

    def test_get_gap_analyses(self, checker):
        gap1 = PSAKGapAnalysis(
            standard=PSAKStandard.PSAK_72,
            current_practice="A",
            required_practice="B",
            gap_description="Gap1",
            impact="medium",
            remediation_plan="P1",
            estimated_effort_days=5,
            responsible_party="R1",
        )
        gap2 = PSAKGapAnalysis(
            standard=PSAKStandard.PSAK_73,
            current_practice="C",
            required_practice="D",
            gap_description="Gap2",
            impact="low",
            remediation_plan="P2",
            estimated_effort_days=3,
            responsible_party="R2",
        )
        checker.add_gap_analysis(gap1)
        checker.add_gap_analysis(gap2)
        all_gaps = checker.get_gap_analyses()
        assert len(all_gaps) == 2
        filtered = checker.get_gap_analyses(standard=PSAKStandard.PSAK_72)
        assert len(filtered) == 1
        assert filtered[0].standard == PSAKStandard.PSAK_72


class TestGenerateFullComplianceReport:
    def test_generate_full_report(self, checker):
        report = checker.generate_full_compliance_report()
        # Should assess all standards (27)
        assert len(report) == len([s for s in PSAKStandard])
        # Check that at least some results exist
        assert PSAKStandard.PSAK_1 in report
        assert PSAKStandard.PSAK_2 in report
        assert PSAKStandard.PSAK_14 in report
        assert PSAKStandard.PSAK_16 in report
        assert PSAKStandard.PSAK_46 in report
        assert PSAKStandard.PSAK_48 in report
        assert PSAKStandard.PSAK_71 in report
        assert PSAKStandard.PSAK_72 in report
        assert PSAKStandard.PSAK_73 in report
        assert PSAKStandard.PSAK_101 in report
        # All should be compliant (we passed True to all assess calls)
        for std, result in report.items():
            assert result.status == ComplianceStatus.COMPLIANT
            assert result.compliance_percentage == Decimal("100")


class TestGenerateSummary:
    def test_generate_summary_empty(self, checker):
        # No assessments, should run full report
        summary = checker.generate_summary()
        assert summary["entity"] == "PT Test"
        assert "fiscal_year_end" in summary
        assert "assessment_date" in summary
        assert summary["total_standards_assessed"] == len([s for s in PSAKStandard])
        assert summary["compliant"] == len([s for s in PSAKStandard])
        assert summary["partially_compliant"] == 0
        assert summary["non_compliant"] == 0
        assert summary["overall_status"] == "compliant"
        assert summary["overall_compliance_percentage"] == 100.0

    def test_generate_summary_with_partial(self, checker):
        # Add some partial results
        checker.assess_psak_1(True, False, True, False, True)  # 60%
        checker.assess_psak_2(True, False, True, False)        # 50%
        # Generate summary
        summary = checker.generate_summary()
        # Since we only assessed 2 standards, but generate_summary calls generate_full_compliance_report
        # which assesses all and sets all to 100% compliant. So the summary will show all compliant.
        # To test with partial, we need to override the results after full report.
        # Let's get full report then modify a result
        checker.generate_full_compliance_report()
        # Modify one result to partial
        partial_result = PSAKComplianceResult(
            standard=PSAKStandard.PSAK_1,
            status=ComplianceStatus.PARTIALLY_COMPLIANT,
            compliance_percentage=Decimal("60"),
            findings=["Test finding"],
            recommendations=["Test rec"],
        )
        checker._results[PSAKStandard.PSAK_1] = partial_result
        summary = checker.generate_summary()
        assert summary["compliant"] == len([s for s in PSAKStandard]) - 1
        assert summary["partially_compliant"] == 1
        assert summary["non_compliant"] == 0
        assert summary["overall_compliance_percentage"] == pytest.approx((len([s for s in PSAKStandard]) - 1) * 100 / len([s for s in PSAKStandard]), 0.1)


class TestExportMethods:
    def test_to_json(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        json_str = checker.to_json()
        data = json.loads(json_str)
        assert "summary" in data
        assert "details" in data
        assert len(data["details"]) == 1
        assert data["details"][0]["standard"] == PSAKStandard.PSAK_1.value
        assert data["details"][0]["compliance_percentage"] == 100.0

    def test_to_json_file(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            checker.to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "summary" in data
            assert "details" in data
        finally:
            os.remove(file_path)

    def test_to_csv(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        checker.assess_psak_14(True, True, True, True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            file_path = f.name
        try:
            checker.to_csv(file_path)
            with open(file_path) as f:
                content = f.read()
            assert "PSAK 1 - Penyajian Laporan Keuangan" in content
            assert "PSAK 14 - Persediaan" in content
            assert "compliant" in content
        finally:
            os.remove(file_path)

    def test_result_to_dict(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        result = checker.get_compliance_result(PSAKStandard.PSAK_1)
        d = checker._result_to_dict(result)
        assert d["standard"] == PSAKStandard.PSAK_1.value
        assert d["status"] == "compliant"
        assert d["compliance_percentage"] == 100.0
        assert "hash" in d


class TestRemediation:
    def test_update_remediation(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        deadline = date(2026, 12, 31)
        success = checker.update_remediation(PSAKStandard.PSAK_1, deadline, "in_progress")
        assert success is True
        result = checker.get_compliance_result(PSAKStandard.PSAK_1)
        assert result.remediation_deadline == deadline
        assert result.remediation_status == "in_progress"

    def test_update_remediation_not_found(self, checker):
        deadline = date(2026, 12, 31)
        success = checker.update_remediation(PSAKStandard.PSAK_1, deadline, "in_progress")
        assert success is False

    def test_get_remediation_status(self, checker):
        # Assess some with non-compliant and partial
        checker.assess_psak_1(True, False, True, False, True)  # partially compliant
        checker.assess_psak_14(False, False, False, False)      # non-compliant
        # Update remediation for PSAK 1
        checker.update_remediation(PSAKStandard.PSAK_1, date(2026, 6, 30), "in_progress")
        statuses = checker.get_remediation_status()
        # Should only include non-compliant and partially compliant (not fully compliant)
        # But since we haven't called generate_full_compliance_report, only assessed two standards.
        # They are both non-compliant or partially, so both should appear.
        assert len(statuses) == 2
        standards = [s["standard"] for s in statuses]
        assert PSAKStandard.PSAK_1.value in standards
        assert PSAKStandard.PSAK_14.value in standards
        # Check deadline for PSAK 1
        for s in statuses:
            if s["standard"] == PSAKStandard.PSAK_1.value:
                assert s["deadline"] == "2026-06-30"
                assert s["status"] == "in_progress"
            else:
                assert s["deadline"] is None


class TestCheckValidateGetViolations:
    def test_check(self, checker):
        # check() runs full assessment
        results = checker.check()
        assert isinstance(results, dict)
        assert len(results) == len([s for s in PSAKStandard])
        # Should have stored results
        assert len(checker._results) == len([s for s in PSAKStandard])

    def test_validate(self, checker):
        data_valid = {"entity_name": "PT Valid"}
        result = checker.validate(data_valid)
        assert result["valid"] is True
        assert result["entity"] == "PT Valid"

        data_invalid = {}
        result = checker.validate(data_invalid)
        assert result["valid"] is False
        assert "error" in result

    def test_get_violations(self, checker):
        # Assess a non-compliant standard
        checker.assess_psak_1(
            financial_statements_prepared=False,
            comparative_figures=False,
            going_concern_assessed=False,
            materiality_applied=False,
            disclosure_of_estimates=False,
        )
        violations = checker.get_violations()
        assert len(violations) == 5
        for v in violations:
            assert v["standard"] == PSAKStandard.PSAK_1.value
            assert "finding" in v
            assert "status" in v
            assert "recommendation" in v
        # Check that the findings are as expected
        findings = [v["finding"] for v in violations]
        assert any("Laporan keuangan" in f for f in findings)
        assert any("Angka komparatif" in f for f in findings)
        assert any("going concern" in f for f in findings)
        assert any("Materialitas" in f for f in findings)
        assert any("estimasi" in f for f in findings)


# =============================================================================
# Module-level Function
# =============================================================================

def test_check_psak_compliance():
    entity = "PT Test"
    fiscal_end = date(2026, 12, 31)
    checker = check_psak_compliance(entity, fiscal_end)
    assert isinstance(checker, PsakChecker)
    assert checker.entity_name == entity
    assert checker.fiscal_year_end == fiscal_end


# =============================================================================
# Additional Edge Cases
# =============================================================================

class TestEdgeCases:
    def test_assess_psak_1_with_all_false(self, checker):
        result = checker.assess_psak_1(False, False, False, False, False)
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")
        assert len(result.findings) == 5
        assert len(result.recommendations) == 5

    def test_assess_psak_72_partial_edge(self, checker):
        result = checker.assess_psak_72(
            five_step_model_followed=True,
            contract_asset_liability_recognized=True,
            performance_obligations_identified=False,
            transaction_price_allocated=True,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("60")

    def test_generate_full_report_does_not_overwrite_existing(self, checker):
        # Assess one standard with non-compliant
        checker.assess_psak_1(False, False, False, False, False)
        # Generate full report (should keep existing assessments and add others)
        report = checker.generate_full_compliance_report()
        # PSAK 1 should still be non-compliant
        assert checker._results[PSAKStandard.PSAK_1].status == ComplianceStatus.NON_COMPLIANT
        # Other standards should be compliant
        assert checker._results[PSAKStandard.PSAK_2].status == ComplianceStatus.COMPLIANT

    def test_to_json_with_gaps(self, checker):
        checker.assess_psak_1(True, True, True, True, True)
        gap = PSAKGapAnalysis(
            standard=PSAKStandard.PSAK_72,
            current_practice="Old",
            required_practice="New",
            gap_description="No proper identification",
            impact="high",
            remediation_plan="Training",
            estimated_effort_days=20,
            responsible_party="Finance",
        )
        checker.add_gap_analysis(gap)
        json_str = checker.to_json()
        data = json.loads(json_str)
        assert "gap_analyses" in data
        assert len(data["gap_analyses"]) == 1
        assert data["gap_analyses"][0]["standard"] == PSAKStandard.PSAK_72.value
        assert data["gap_analyses"][0]["gap"] == "No proper identification"
