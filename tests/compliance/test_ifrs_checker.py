# test_ifrs_checker.py
# Comprehensive tests for compliance/ifrs_checker.py

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from compliance.ifrs_checker import (
    AssessmentType,
    ComplianceStatus,
    IFRS14Checker,
    IFRS14ValidationResult,
    IFRSChecker,
    IfrsChecker,
    IFRSComplianceError,
    IFRSComplianceResult,
    IFRSDisclosureRequirement,
    IFRSGapAnalysis,
    IFRSStandard,
    StandardNotFoundError,
    check_ifrs_compliance,
)


# -------------------- Enum Tests --------------------
class TestIFRSStandard:
    def test_members(self):
        assert IFRSStandard.IFRS_9.value == "IFRS 9 - Financial Instruments"
        assert IFRSStandard.IFRS_15.value == "IFRS 15 - Revenue from Contracts with Customers"
        assert IFRSStandard.IAS_1.value == "IAS 1 - Presentation of Financial Statements"


class TestComplianceStatus:
    def test_members(self):
        assert ComplianceStatus.COMPLIANT.value == "compliant"
        assert ComplianceStatus.PARTIALLY_COMPLIANT.value == "partially_compliant"
        assert ComplianceStatus.NON_COMPLIANT.value == "non_compliant"
        assert ComplianceStatus.NOT_APPLICABLE.value == "not_applicable"
        assert ComplianceStatus.UNDER_REVIEW.value == "under_review"


class TestAssessmentType:
    def test_members(self):
        assert AssessmentType.SELF_ASSESSMENT.value == "self_assessment"
        assert AssessmentType.EXTERNAL_AUDIT.value == "external_audit"
        assert AssessmentType.GAP_ANALYSIS.value == "gap_analysis"


# -------------------- Exception Tests --------------------
class TestIFRSComplianceError:
    def test_exception(self):
        with pytest.raises(IFRSComplianceError):
            raise IFRSComplianceError("test")


class TestStandardNotFoundError:
    def test_exception(self):
        with pytest.raises(StandardNotFoundError):
            raise StandardNotFoundError("not found")


# -------------------- Data Class Tests --------------------
class TestIFRSComplianceResult:
    def test_construction(self):
        result = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_9,
            status=ComplianceStatus.COMPLIANT,
            compliance_percentage=Decimal("85.5"),
            findings=["Finding 1", "Finding 2"],
            recommendations=["Recommend 1"],
            evidence_required=["Evidence A"],
            assessed_by="auditor",
            assessed_date=date.today(),
            remediation_deadline=date.today() + timedelta(days=30),
            remediation_status="in_progress",
        )
        assert result.standard == IFRSStandard.IFRS_9
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("85.5")
        assert result.findings == ["Finding 1", "Finding 2"]
        assert result.recommendations == ["Recommend 1"]
        assert result.evidence_required == ["Evidence A"]
        assert result.assessed_by == "auditor"
        assert result.assessed_date == date.today()
        assert result.remediation_deadline == date.today() + timedelta(days=30)
        assert result.remediation_status == "in_progress"
        assert result.hash_sha256  # auto-computed

    def test_hash_computation(self):
        result1 = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_9,
            status=ComplianceStatus.COMPLIANT,
            compliance_percentage=Decimal("100"),
            findings=[],
        )
        result2 = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_9,
            status=ComplianceStatus.COMPLIANT,
            compliance_percentage=Decimal("100"),
            findings=[],
        )
        # Same data => same hash
        assert result1.hash_sha256 == result2.hash_sha256


class TestIFRSDisclosureRequirement:
    def test_construction(self):
        req = IFRSDisclosureRequirement(
            reference="IFRS 15.119",
            description="Disaggregation of revenue",
            is_met=True,
            evidence="Note 5",
        )
        assert req.reference == "IFRS 15.119"
        assert req.description == "Disaggregation of revenue"
        assert req.is_met is True
        assert req.evidence == "Note 5"


class TestIFRSGapAnalysis:
    def test_construction(self):
        gap = IFRSGapAnalysis(
            standard=IFRSStandard.IAS_36,
            current_practice="No impairment testing",
            required_practice="Annual impairment test",
            gap_description="Missing impairment model",
            impact="high",
            remediation_plan="Implement DCF model",
            estimated_effort_days=30,
            responsible_party="Finance",
        )
        assert gap.standard == IFRSStandard.IAS_36
        assert gap.current_practice == "No impairment testing"
        assert gap.required_practice == "Annual impairment test"
        assert gap.gap_description == "Missing impairment model"
        assert gap.impact == "high"
        assert gap.remediation_plan == "Implement DCF model"
        assert gap.estimated_effort_days == 30
        assert gap.responsible_party == "Finance"


# -------------------- IfrsChecker Tests --------------------
class TestIfrsChecker:
    def test_construction(self):
        checker = IfrsChecker(entity_name="PT ABC", fiscal_year_end=date(2026, 12, 31))
        assert checker.entity_name == "PT ABC"
        assert checker.fiscal_year_end == date(2026, 12, 31)
        assert checker._results == {}
        assert checker._disclosure_requirements == {}
        assert checker._gap_analyses == []
        assert checker._assessment_history == []

    # ----- Assessment Methods -----
    def test_assess_ifrs_9_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_9(
            classification_model_documented=True,
            expected_credit_loss_calculated=True,
            hedge_accounting_applied_correctly=True,
            impairment_model_implemented=True,
            disclosure_made=True,
        )
        assert result.standard == IFRSStandard.IFRS_9
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")
        assert result.findings == []
        assert len(result.recommendations) == 0

    def test_assess_ifrs_9_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_9(
            classification_model_documented=False,
            expected_credit_loss_calculated=False,
            hedge_accounting_applied_correctly=False,
            impairment_model_implemented=False,
            disclosure_made=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")
        assert len(result.findings) == 5
        assert "Classification model" in result.findings[0]
        assert "ECL not calculated" in result.findings[1]
        assert "Hedge accounting" in result.findings[2]
        assert "Impairment model" in result.findings[3]
        assert "IFRS 7 disclosures" in result.findings[4]

    def test_assess_ifrs_15_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_15(
            contract_identified=True,
            performance_obligations_identified=True,
            transaction_price_allocated=True,
            revenue_recognized_on_transfer=True,
            contract_asset_liability_recorded=True,
            disclosure_complete=True,
        )
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ifrs_15_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_15(
            contract_identified=False,
            performance_obligations_identified=False,
            transaction_price_allocated=False,
            revenue_recognized_on_transfer=False,
            contract_asset_liability_recorded=False,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ifrs_16_with_exemptions(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_16(
            right_of_use_asset_recognized=True,
            lease_liability_recognized=True,
            discount_rate_determined=True,
            short_term_exemption_used=True,
            low_value_exemption_used=True,
            disclosure_complete=True,
        )
        # With exemptions, score = 15+15+20+5+30 = 85 => partially compliant
        assert result.status == ComplianceStatus.PARTIALLY_COMPLIANT
        assert result.compliance_percentage == Decimal("85")

    def test_assess_ifrs_16_no_exemptions(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_16(
            right_of_use_asset_recognized=True,
            lease_liability_recognized=True,
            discount_rate_determined=True,
            short_term_exemption_used=False,
            low_value_exemption_used=False,
            disclosure_complete=True,
        )
        # Score = 15+15+20+15+30 = 95 => compliant
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("95")

    def test_assess_ias_16_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_16(
            cost_model_used=True,
            revaluation_model_used=False,
            depreciation_appropriate=True,
            component_depreciation_applied=True,
            derecognition_policy=True,
        )
        # 20+25+25+30 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_16_partial(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_16(
            cost_model_used=False,
            revaluation_model_used=False,
            depreciation_appropriate=False,
            component_depreciation_applied=False,
            derecognition_policy=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ias_36_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_36(
            impairment_test_performed_annually=True,
            cash_generating_units_identified=True,
            recoverable_amount_calculated=True,
            impairment_recognized=True,
            reversal_recognized=True,
            disclosure_complete=True,
        )
        # 20+15+20+20+5+20 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_36_partial(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_36(
            impairment_test_performed_annually=False,
            cash_generating_units_identified=False,
            recoverable_amount_calculated=False,
            impairment_recognized=False,
            reversal_recognized=False,
            disclosure_complete=False,
        )
        # only 0
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ias_37_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_37(
            provision_recognition_criteria_met=True,
            provision_measurement_reliable=True,
            contingent_liabilities_disclosed=True,
            contingent_assets_not_recognized=True,
            discounting_where_material=True,
        )
        # 25+25+25+15+10 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_37_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_37(
            provision_recognition_criteria_met=False,
            provision_measurement_reliable=False,
            contingent_liabilities_disclosed=False,
            contingent_assets_not_recognized=False,
            discounting_where_material=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ias_38_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_38(
            recognition_criteria_met=True,
            separately_acquired_vs_internally_generated=True,
            amortization_method_appropriate=True,
            impairment_test_for_indefinite_life=True,
            disclosure_complete=True,
        )
        # 20*5 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_38_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_38(
            recognition_criteria_met=False,
            separately_acquired_vs_internally_generated=False,
            amortization_method_appropriate=False,
            impairment_test_for_indefinite_life=False,
            disclosure_complete=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ias_1_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_1(
            complete_set_presented=True,
            comparative_figures_included=True,
            going_concern_assessed=True,
            materiality_applied=True,
            disclosure_of_estimates=True,
        )
        # 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_1_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_1(
            complete_set_presented=False,
            comparative_figures_included=False,
            going_concern_assessed=False,
            materiality_applied=False,
            disclosure_of_estimates=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ias_7_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_7(
            cash_flow_statement_prepared=True,
            operating_activities_classified=True,
            investing_and_financing_separated=True,
            non_cash_transactions_disclosed=True,
        )
        # 25*4 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ias_7_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ias_7(
            cash_flow_statement_prepared=False,
            operating_activities_classified=False,
            investing_and_financing_separated=False,
            non_cash_transactions_disclosed=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    def test_assess_ifrs_10_fully_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_10(
            control_assessed_for_all_investees=True,
            consolidation_performed=True,
            non_controlling_interest_presented=True,
            subsidiaries_excluded_justified=True,
        )
        # 25*4 = 100
        assert result.status == ComplianceStatus.COMPLIANT
        assert result.compliance_percentage == Decimal("100")

    def test_assess_ifrs_10_non_compliant(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_10(
            control_assessed_for_all_investees=False,
            consolidation_performed=False,
            non_controlling_interest_presented=False,
            subsidiaries_excluded_justified=False,
        )
        assert result.status == ComplianceStatus.NON_COMPLIANT
        assert result.compliance_percentage == Decimal("0")

    # ----- Helper Methods -----
    def test_check_runs_full_report(self):
        checker = IfrsChecker("PT ABC")
        results = checker.check()
        assert len(results) >= 10  # all major standards
        assert IFRSStandard.IFRS_9 in results
        assert IFRSStandard.IFRS_15 in results
        assert IFRSStandard.IFRS_16 in results
        assert IFRSStandard.IAS_16 in results
        assert IFRSStandard.IAS_36 in results
        assert IFRSStandard.IAS_37 in results
        assert IFRSStandard.IAS_38 in results
        assert IFRSStandard.IAS_1 in results
        assert IFRSStandard.IAS_7 in results
        assert IFRSStandard.IFRS_10 in results

    def test_validate_success(self):
        checker = IfrsChecker("PT ABC")
        result = checker.validate({"entity_name": "PT XYZ"})
        assert result["valid"] is True
        assert result["entity"] == "PT XYZ"

    def test_validate_missing_entity(self):
        checker = IfrsChecker("PT ABC")
        result = checker.validate({})
        assert result["valid"] is False
        assert result["error"] == "entity_name is required"

    def test_get_violations(self):
        checker = IfrsChecker("PT ABC")
        # Create a non-compliant result
        checker.assess_ifrs_9(
            classification_model_documented=False,
            expected_credit_loss_calculated=False,
            hedge_accounting_applied_correctly=False,
            impairment_model_implemented=False,
            disclosure_made=False,
        )
        violations = checker.get_violations()
        assert len(violations) == 5
        for v in violations:
            assert v["standard"] == "IFRS 9 - Financial Instruments"
            assert "finding" in v
            assert "status" in v
            assert "recommendation" in v

    def test_get_compliance_result(self):
        checker = IfrsChecker("PT ABC")
        checker.assess_ifrs_9(True, True, True, True, True)
        result = checker.get_compliance_result(IFRSStandard.IFRS_9)
        assert result is not None
        assert result.standard == IFRSStandard.IFRS_9
        assert checker.get_compliance_result(IFRSStandard.IAS_1) is None

    def test_get_all_results(self):
        checker = IfrsChecker("PT ABC")
        checker.assess_ifrs_9(True, True, True, True, True)
        checker.assess_ias_1(True, True, True, True, True)
        results = checker.get_all_results()
        assert len(results) == 2
        standards = {r.standard for r in results}
        assert IFRSStandard.IFRS_9 in standards
        assert IFRSStandard.IAS_1 in standards

    def test_add_and_get_gap_analyses(self):
        checker = IfrsChecker("PT ABC")
        gap = IFRSGapAnalysis(
            standard=IFRSStandard.IFRS_9,
            current_practice="X",
            required_practice="Y",
            gap_description="Gap",
            impact="high",
            remediation_plan="Plan",
            estimated_effort_days=10,
            responsible_party="Team",
        )
        checker.add_gap_analysis(gap)
        all_gaps = checker.get_gap_analyses()
        assert len(all_gaps) == 1
        assert all_gaps[0].standard == IFRSStandard.IFRS_9

        filtered = checker.get_gap_analyses(IFRSStandard.IFRS_9)
        assert len(filtered) == 1
        filtered2 = checker.get_gap_analyses(IFRSStandard.IAS_1)
        assert len(filtered2) == 0

    def test_generate_full_compliance_report(self):
        checker = IfrsChecker("PT ABC")
        results = checker.generate_full_compliance_report()
        assert len(results) >= 10
        # Ensure all major standards exist
        assert IFRSStandard.IFRS_9 in results
        assert IFRSStandard.IFRS_15 in results
        assert IFRSStandard.IFRS_16 in results
        assert IFRSStandard.IAS_16 in results
        assert IFRSStandard.IAS_36 in results
        assert IFRSStandard.IAS_37 in results
        assert IFRSStandard.IAS_38 in results
        assert IFRSStandard.IAS_1 in results
        assert IFRSStandard.IAS_7 in results
        assert IFRSStandard.IFRS_10 in results

        # Calling again should not duplicate (already stored)
        results2 = checker.generate_full_compliance_report()
        assert len(results2) == len(results)

    def test_generate_summary(self):
        checker = IfrsChecker("PT ABC")
        # Add some results
        checker.assess_ifrs_9(True, True, True, True, True)  # compliant
        checker.assess_ifrs_15(False, False, False, False, False, False)  # non-compliant
        checker.assess_ifrs_16(True, True, True, True, True, True)  # partially (85%)
        summary = checker.generate_summary()
        assert summary["entity"] == "PT ABC"
        assert summary["total_standards_assessed"] == 3
        assert summary["compliant"] == 1
        assert summary["partially_compliant"] == 1
        assert summary["non_compliant"] == 1
        assert summary["overall_compliance_percentage"] == pytest.approx(round((1*100)/3, 2))
        assert summary["overall_status"] == "partially_compliant"  # 33% < 50

    def test_generate_summary_when_empty_auto_runs(self):
        checker = IfrsChecker("PT ABC")
        summary = checker.generate_summary()
        # Should auto-generate full report
        assert summary["total_standards_assessed"] >= 10
        assert summary["overall_status"] in ("compliant", "partially_compliant", "non_compliant")

    def test_to_json(self, tmp_path):
        checker = IfrsChecker("PT ABC")
        checker.assess_ifrs_9(True, True, True, True, True)
        gap = IFRSGapAnalysis(
            standard=IFRSStandard.IFRS_9,
            current_practice="X",
            required_practice="Y",
            gap_description="Gap",
            impact="high",
            remediation_plan="Plan",
            estimated_effort_days=10,
            responsible_party="Team",
        )
        checker.add_gap_analysis(gap)

        file_path = tmp_path / "report.json"
        json_str = checker.to_json(str(file_path))
        # Check content
        data = json.loads(json_str)
        assert "summary" in data
        assert "details" in data
        assert "gap_analyses" in data
        assert len(data["details"]) == 1
        assert data["details"][0]["standard"] == "IFRS 9 - Financial Instruments"
        # Check file written
        with open(file_path) as f:
            file_data = json.load(f)
        assert file_data == data

    def test_result_to_dict(self):
        checker = IfrsChecker("PT ABC")
        result = checker.assess_ifrs_9(True, True, True, True, True)
        d = checker._result_to_dict(result)
        assert d["standard"] == "IFRS 9 - Financial Instruments"
        assert d["status"] == "compliant"
        assert d["compliance_percentage"] == 100.0
        assert isinstance(d["findings"], list)
        assert isinstance(d["recommendations"], list)
        assert d["hash"] == result.hash_sha256

    def test_update_remediation(self):
        checker = IfrsChecker("PT ABC")
        checker.assess_ifrs_9(True, True, True, True, True)
        deadline = date.today() + timedelta(days=60)
        success = checker.update_remediation(IFRSStandard.IFRS_9, deadline, "in_progress")
        assert success is True
        result = checker.get_compliance_result(IFRSStandard.IFRS_9)
        assert result.remediation_deadline == deadline
        assert result.remediation_status == "in_progress"

        # Update non-existent standard
        success2 = checker.update_remediation(IFRSStandard.IAS_1, deadline, "done")
        assert success2 is False

    def test_get_remediation_status(self):
        checker = IfrsChecker("PT ABC")
        checker.assess_ifrs_9(True, True, True, True, True)  # compliant
        checker.assess_ifrs_15(False, False, False, False, False, False)  # non-compliant
        checker.assess_ifrs_16(True, True, True, True, True, True)  # partially (85%)
        statuses = checker.get_remediation_status()
        # Should include non-compliant and partially compliant, but not compliant
        assert len(statuses) == 2
        standards = {s["standard"] for s in statuses}
        assert "IFRS 15 - Revenue from Contracts with Customers" in standards
        assert "IFRS 16 - Leases" in standards
        for s in statuses:
            assert "deadline" in s
            assert "status" in s


# -------------------- IFRS14Checker Tests --------------------
class TestIFRS14ValidationResult:
    def test_construction(self):
        res = IFRS14ValidationResult(is_compliant=True, errors=["error1"])
        assert res.is_compliant is True
        assert res.errors == ["error1"]


class TestIFRS14Checker:
    def test_validate_compliant(self):
        data = {"has_regulatory_approval": True, "has_rate_regulated_activities": True}
        result = IFRS14Checker.validate(data)
        assert result.is_compliant is True
        assert result.errors == []

    def test_validate_non_compliant_missing_approval(self):
        data = {"has_regulatory_approval": False, "has_rate_regulated_activities": True}
        result = IFRS14Checker.validate(data)
        assert result.is_compliant is False
        assert "Regulatory approval required" in result.errors

    def test_validate_non_compliant_missing_activities(self):
        data = {"has_regulatory_approval": True, "has_rate_regulated_activities": False}
        result = IFRS14Checker.validate(data)
        assert result.is_compliant is False
        assert "Rate-regulated activities not identified" in result.errors

    def test_validate_both_errors(self):
        data = {"has_regulatory_approval": False, "has_rate_regulated_activities": False}
        result = IFRS14Checker.validate(data)
        assert result.is_compliant is False
        assert len(result.errors) == 2
        assert "Regulatory approval required" in result.errors
        assert "Rate-regulated activities not identified" in result.errors


# -------------------- Entry Point Function --------------------
def test_check_ifrs_compliance():
    checker = check_ifrs_compliance("PT XYZ", fiscal_year_end=date(2026, 12, 31))
    assert isinstance(checker, IfrsChecker)
    assert checker.entity_name == "PT XYZ"
    assert checker.fiscal_year_end == date(2026, 12, 31)


# -------------------- Alias IFRSChecker --------------------
def test_ifrschecker_alias():
    # IFRSChecker is an alias for IfrsChecker
    assert IFRSChecker is IfrsChecker
