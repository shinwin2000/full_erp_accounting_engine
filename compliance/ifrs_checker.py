#!/usr/bin/env python3
"""
Module: ifrs_checker.py
Layer: Compliance

Responsibility:
    Pengecekan kepatuhan terhadap IFRS (International Financial Reporting Standards)
    untuk entitas yang melaporkan sesuai standar internasional.
    Mendukung IFRS 9, 15, 16, IAS 1, 2, 7, 16, 36, 37, 38, dan lainnya.
    Mencakup gap analysis, self-assessment, remediation tracking, dan export report.

Dependencies:
    - datetime, decimal, enum, typing, json, logging
    - optional: openpyxl for Excel export

Audit:
    Setiap penilaian kepatuhan dicatat dengan timestamp dan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class IFRSStandard(Enum):
    IFRS_9 = "IFRS 9 - Financial Instruments"
    IFRS_15 = "IFRS 15 - Revenue from Contracts with Customers"
    IFRS_16 = "IFRS 16 - Leases"
    IAS_1 = "IAS 1 - Presentation of Financial Statements"
    IAS_2 = "IAS 2 - Inventories"
    IAS_7 = "IAS 7 - Statement of Cash Flows"
    IAS_8 = "IAS 8 - Accounting Policies, Changes in Estimates and Errors"
    IAS_10 = "IAS 10 - Events after Reporting Period"
    IAS_12 = "IAS 12 - Income Taxes"
    IAS_16 = "IAS 16 - Property, Plant and Equipment"
    IAS_19 = "IAS 19 - Employee Benefits"
    IAS_20 = "IAS 20 - Government Grants"
    IAS_21 = "IAS 21 - Effects of Changes in Foreign Exchange Rates"
    IAS_23 = "IAS 23 - Borrowing Costs"
    IAS_24 = "IAS 24 - Related Party Disclosures"
    IAS_27 = "IAS 27 - Separate Financial Statements"
    IAS_28 = "IAS 28 - Investments in Associates and Joint Ventures"
    IAS_32 = "IAS 32 - Financial Instruments: Presentation"
    IAS_33 = "IAS 33 - Earnings per Share"
    IAS_36 = "IAS 36 - Impairment of Assets"
    IAS_37 = "IAS 37 - Provisions, Contingent Liabilities and Contingent Assets"
    IAS_38 = "IAS 38 - Intangible Assets"
    IAS_40 = "IAS 40 - Investment Property"
    IAS_41 = "IAS 41 - Agriculture"
    IFRS_1 = "IFRS 1 - First-time Adoption of IFRS"
    IFRS_2 = "IFRS 2 - Share-based Payment"
    IFRS_3 = "IFRS 3 - Business Combinations"
    IFRS_5 = "IFRS 5 - Non-current Assets Held for Sale"
    IFRS_6 = "IFRS 6 - Exploration for and Evaluation of Mineral Resources"
    IFRS_7 = "IFRS 7 - Financial Instruments: Disclosures"
    IFRS_8 = "IFRS 8 - Operating Segments"
    IFRS_10 = "IFRS 10 - Consolidated Financial Statements"
    IFRS_11 = "IFRS 11 - Joint Arrangements"
    IFRS_12 = "IFRS 12 - Disclosure of Interests in Other Entities"
    IFRS_13 = "IFRS 13 - Fair Value Measurement"
    IFRS_14 = "IFRS 14 - Regulatory Deferral Accounts"
    IFRS_17 = "IFRS 17 - Insurance Contracts"


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    UNDER_REVIEW = "under_review"


class AssessmentType(Enum):
    SELF_ASSESSMENT = "self_assessment"
    EXTERNAL_AUDIT = "external_audit"
    GAP_ANALYSIS = "gap_analysis"


# ============================================================================
# Exceptions
# ============================================================================
class IFRSComplianceError(Exception):
    """Base exception untuk IFRS compliance."""
    pass


class StandardNotFoundError(IFRSComplianceError):
    """Standar IFRS tidak ditemukan."""
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class IFRSComplianceResult:
    """Hasil penilaian kepatuhan untuk satu standar."""
    standard: IFRSStandard
    status: ComplianceStatus
    compliance_percentage: Decimal  # 0-100
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    assessed_by: str | None = None
    assessed_date: date | None = None
    remediation_deadline: date | None = None
    remediation_status: str = "not_started"
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "standard": self.standard.value,
            "status": self.status.value,
            "percentage": str(self.compliance_percentage),
            "findings": self.findings,
            "assessed_date": self.assessed_date.isoformat() if self.assessed_date else None,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


@dataclass
class IFRSDisclosureRequirement:
    """Persyaratan pengungkapan untuk suatu standar."""
    reference: str  # e.g., "IFRS 15.119"
    description: str
    is_met: bool = False
    evidence: str | None = None


@dataclass
class IFRSGapAnalysis:
    """Hasil gap analysis untuk suatu standar."""
    standard: IFRSStandard
    current_practice: str
    required_practice: str
    gap_description: str
    impact: str  # high, medium, low
    remediation_plan: str
    estimated_effort_days: int
    responsible_party: str


# ============================================================================
# IfrsChecker Core
# ============================================================================
class IfrsChecker:
    """
    Pengecekan kepatuhan IFRS untuk berbagai standar.
    Mendukung self-assessment, gap analysis, remediation tracking, dan export report.
    """

    def __init__(self, entity_name: str, fiscal_year_end: date = date(2026, 12, 31)):
        self.entity_name = entity_name
        self.fiscal_year_end = fiscal_year_end
        self._results: dict[IFRSStandard, IFRSComplianceResult] = {}
        self._disclosure_requirements: dict[IFRSStandard, list[IFRSDisclosureRequirement]] = {}
        self._gap_analyses: list[IFRSGapAnalysis] = []
        self._assessment_history: list[dict] = []

    # ------------------------------------------------------------------------
    # Assessment Methods
    # ------------------------------------------------------------------------
    def assess_ifrs_9(
        self,
        classification_model_documented: bool,
        expected_credit_loss_calculated: bool,
        hedge_accounting_applied_correctly: bool,
        impairment_model_implemented: bool,
        disclosure_made: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if classification_model_documented:
            compliance_score += 20
        else:
            findings.append("Classification model for financial assets not documented")
            recommendations.append("Document the business model and SPPI test for each portfolio")

        if expected_credit_loss_calculated:
            compliance_score += 20
        else:
            findings.append("ECL not calculated using 3-stage model")
            recommendations.append("Implement IFRS 9 impairment logic in accounting system")

        if hedge_accounting_applied_correctly:
            compliance_score += 20
        else:
            findings.append("Hedge accounting not properly applied or documented")
            recommendations.append("Review hedge relationships and effectiveness testing")

        if impairment_model_implemented:
            compliance_score += 20
        else:
            findings.append("Impairment model not integrated with GL")
            recommendations.append("Automate ECL calculation and posting")

        if disclosure_made:
            compliance_score += 20
        else:
            findings.append("IFRS 7 disclosures incomplete")
            recommendations.append("Add financial instruments disclosures to annual report")

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_9,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Classification matrix",
                "ECL calculation model",
                "Hedge documentation",
            ],
        )
        self._results[IFRSStandard.IFRS_9] = result
        return result

    def assess_ifrs_15(
        self,
        contract_identified: bool,
        performance_obligations_identified: bool,
        transaction_price_allocated: bool,
        revenue_recognized_on_transfer: bool,
        contract_asset_liability_recorded: bool,
        disclosure_complete: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if contract_identified:
            compliance_score += 15
        else:
            findings.append("Contract with customer not properly identified")
            recommendations.append(
                "Review all customer contracts for distinct performance obligations"
            )

        if performance_obligations_identified:
            compliance_score += 15
        else:
            findings.append("Performance obligations not identified")
            recommendations.append("Identify distinct goods/services in each contract")

        if transaction_price_allocated:
            compliance_score += 15
        else:
            findings.append("Transaction price not allocated to performance obligations")
            recommendations.append("Implement allocation based on standalone selling prices")

        if revenue_recognized_on_transfer:
            compliance_score += 15
        else:
            findings.append("Revenue recognized at wrong point or period")
            recommendations.append("Assess control transfer for each performance obligation")

        if contract_asset_liability_recorded:
            compliance_score += 20
        else:
            findings.append("Contract assets/liabilities not recorded")
            recommendations.append("Track unbilled receivables and deferred revenue")

        if disclosure_complete:
            compliance_score += 20
        else:
            findings.append("IFRS 15 disclosures incomplete")
            recommendations.append(
                "Add disaggregation of revenue and remaining performance obligations"
            )

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_15,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Contract review documentation",
                "Revenue policy",
                "Disclosure checklist",
            ],
        )
        self._results[IFRSStandard.IFRS_15] = result
        return result

    def assess_ifrs_16(
        self,
        right_of_use_asset_recognized: bool,
        lease_liability_recognized: bool,
        discount_rate_determined: bool,
        short_term_exemption_used: bool,
        low_value_exemption_used: bool,
        disclosure_complete: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if right_of_use_asset_recognized:
            compliance_score += 15
        else:
            findings.append("Right-of-use asset not recognized for leases (except exemptions)")
            recommendations.append("Recognize ROU assets for all leases >12 months")

        if lease_liability_recognized:
            compliance_score += 15
        else:
            findings.append("Lease liability not recognized")
            recommendations.append(
                "Recognize lease liability equal to present value of lease payments"
            )

        if discount_rate_determined:
            compliance_score += 20
        else:
            findings.append("Discount rate (incremental borrowing rate) not determined")
            recommendations.append("Establish methodology for IBR calculation")

        # Exemptions are acceptable
        if short_term_exemption_used or low_value_exemption_used:
            compliance_score += 5

        if not (short_term_exemption_used or low_value_exemption_used):
            compliance_score += 15  # full recognition is correct

        if disclosure_complete:
            compliance_score += 30
        else:
            findings.append("IFRS 16 disclosures incomplete")
            recommendations.append(
                "Add lease maturity analysis, expense breakdown, and cash flow impact"
            )

        percentage = min(Decimal(compliance_score), Decimal(100))
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_16,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Lease register",
                "IBR calculation",
                "Lease liability amortization schedule",
            ],
        )
        self._results[IFRSStandard.IFRS_16] = result
        return result

    def assess_ias_16(
        self,
        cost_model_used: bool,
        revaluation_model_used: bool,
        depreciation_appropriate: bool,
        component_depreciation_applied: bool,
        derecognition_policy: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if cost_model_used or revaluation_model_used:
            compliance_score += 20
        else:
            findings.append("Measurement model not specified")
            recommendations.append("Adopt cost model or revaluation model consistently")

        if depreciation_appropriate:
            compliance_score += 25
        else:
            findings.append("Depreciation method or useful life not appropriate")
            recommendations.append("Review useful lives and residual values annually")

        if component_depreciation_applied:
            compliance_score += 25
        else:
            findings.append("Component depreciation not applied for significant parts")
            recommendations.append("Identify and depreciate major components separately")

        if derecognition_policy:
            compliance_score += 30
        else:
            findings.append("Derecognition policy not documented or not followed")
            recommendations.append("Document procedures for asset disposals")

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_16,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Asset register",
                "Depreciation policy",
                "Revaluation model documentation",
            ],
        )
        self._results[IFRSStandard.IAS_16] = result
        return result

    def assess_ias_36(
        self,
        impairment_test_performed_annually: bool,
        cash_generating_units_identified: bool,
        recoverable_amount_calculated: bool,
        impairment_recognized: bool,
        reversal_recognized: bool,
        disclosure_complete: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if impairment_test_performed_annually:
            compliance_score += 20
        else:
            findings.append("Annual impairment test not performed for goodwill/intangibles")
            recommendations.append("Schedule impairment tests for CGUs")

        if cash_generating_units_identified:
            compliance_score += 15
        else:
            findings.append("CGUs not identified")
            recommendations.append(
                "Define CGUs at the lowest level cash flows are largely independent"
            )

        if recoverable_amount_calculated:
            compliance_score += 20
        else:
            findings.append("Recoverable amount (higher of FV less cost and VIU) not calculated")
            recommendations.append("Implement discounted cash flow model for value in use")

        if impairment_recognized:
            compliance_score += 20
        # else: not necessarily a finding if no impairment exists

        if reversal_recognized:
            compliance_score += 5

        if disclosure_complete:
            compliance_score += 20
        else:
            findings.append("Impairment disclosures incomplete")
            recommendations.append("Disclose key assumptions, growth rates, and discount rates")

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_36,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "CGU mapping",
                "Discounted cash flow models",
                "Impairment reversal documentation",
            ],
        )
        self._results[IFRSStandard.IAS_36] = result
        return result

    def assess_ias_37(
        self,
        provision_recognition_criteria_met: bool,
        provision_measurement_reliable: bool,
        contingent_liabilities_disclosed: bool,
        contingent_assets_not_recognized: bool,
        discounting_where_material: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if provision_recognition_criteria_met:
            compliance_score += 25
        else:
            findings.append(
                "Provisions not recognized when criteria met (present obligation, probable outflow, reliable estimate)"
            )
            recommendations.append("Review contracts and legal claims for provisions")

        if provision_measurement_reliable:
            compliance_score += 25
        else:
            findings.append("Provision measurement not reliable")
            recommendations.append("Use best estimate (expected value or most likely outcome)")

        if contingent_liabilities_disclosed:
            compliance_score += 25
        else:
            findings.append("Contingent liabilities not disclosed")
            recommendations.append("Disclose contingent liabilities unless remote")

        if contingent_assets_not_recognized:
            compliance_score += 15
        else:
            findings.append("Contingent assets recognized inappropriately")
            recommendations.append(
                "Contingent assets should not be recognized, only disclosed if virtually certain"
            )

        if discounting_where_material:
            compliance_score += 10
        else:
            recommendations.append(
                "Consider discounting provisions for time value of money if material"
            )

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_37,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Provision register",
                "Legal opinion summary",
                "Discount rate analysis",
            ],
        )
        self._results[IFRSStandard.IAS_37] = result
        return result

    def assess_ias_38(
        self,
        recognition_criteria_met: bool,
        separately_acquired_vs_internally_generated: bool,
        amortization_method_appropriate: bool,
        impairment_test_for_indefinite_life: bool,
        disclosure_complete: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if recognition_criteria_met:
            compliance_score += 20
        else:
            findings.append("Intangibles not recognized correctly (research vs development)")
            recommendations.append("Capitalize development costs when criteria met")

        if separately_acquired_vs_internally_generated:
            compliance_score += 20
        else:
            findings.append("Internal vs external intangibles not distinguished")
            recommendations.append(
                "Separate accounting for purchased intangibles and internally generated"
            )

        if amortization_method_appropriate:
            compliance_score += 20
        else:
            findings.append("Amortization method not appropriate for finite-life intangibles")
            recommendations.append("Use straight-line amortization over useful life")

        if impairment_test_for_indefinite_life:
            compliance_score += 20
        else:
            findings.append("Annual impairment test not performed for indefinite-life intangibles")
            recommendations.append("Perform impairment test annually")

        if disclosure_complete:
            compliance_score += 20
        else:
            findings.append("Intangible disclosures incomplete")
            recommendations.append(
                "Disclose useful lives, amortization, and carrying amounts by class"
            )

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_38,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Intangible asset register",
                "Development cost capitalization policy",
                "Amortization schedule",
            ],
        )
        self._results[IFRSStandard.IAS_38] = result
        return result

    def assess_ias_1(
        self,
        complete_set_presented: bool,
        comparative_figures_included: bool,
        going_concern_assessed: bool,
        materiality_applied: bool,
        disclosure_of_estimates: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if complete_set_presented:
            compliance_score += 20
        else:
            findings.append("Complete set of financial statements not prepared")
            recommendations.append(
                "Include SOPL, SOCI, balance sheet, cash flow, changes in equity, and notes"
            )

        if comparative_figures_included:
            compliance_score += 20
        else:
            findings.append("Comparative figures not presented")
            recommendations.append("Present prior period comparatives for all amounts")

        if going_concern_assessed:
            compliance_score += 20
        else:
            findings.append("Going concern assessment not performed")
            recommendations.append(
                "Assess entity's ability to continue for at least 12 months from reporting date"
            )

        if materiality_applied:
            compliance_score += 20
        else:
            findings.append("Materiality not applied consistently")
            recommendations.append("Develop materiality threshold policy")

        if disclosure_of_estimates:
            compliance_score += 20
        else:
            findings.append("Key sources of estimation uncertainty not disclosed")
            recommendations.append(
                "Disclose assumptions about the future and other sources of estimation uncertainty"
            )

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_1,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=["Financial statements", "Materiality policy", "Going concern memo"],
        )
        self._results[IFRSStandard.IAS_1] = result
        return result

    def assess_ias_7(
        self,
        cash_flow_statement_prepared: bool,
        operating_activities_classified: bool,
        investing_and_financing_separated: bool,
        non_cash_transactions_disclosed: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if cash_flow_statement_prepared:
            compliance_score += 25
        else:
            findings.append("Statement of cash flows not prepared")
            recommendations.append("Prepare cash flow statement using direct or indirect method")

        if operating_activities_classified:
            compliance_score += 25
        else:
            findings.append("Operating activities not clearly separated")
            recommendations.append("Classify cash flows into operating, investing, and financing")

        if investing_and_financing_separated:
            compliance_score += 25
        else:
            findings.append("Investing and financing activities not distinguished")
            recommendations.append("Separate cash flows from investing and financing")

        if non_cash_transactions_disclosed:
            compliance_score += 25
        else:
            findings.append("Non-cash investing/financing transactions not disclosed")
            recommendations.append("Disclose non-cash transactions separately")

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IAS_7,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Cash flow statement",
                "Reconciliation of liabilities from financing activities",
            ],
        )
        self._results[IFRSStandard.IAS_7] = result
        return result

    def assess_ifrs_10(
        self,
        control_assessed_for_all_investees: bool,
        consolidation_performed: bool,
        non_controlling_interest_presented: bool,
        subsidiaries_excluded_justified: bool,
    ) -> IFRSComplianceResult:
        findings = []
        recommendations = []
        compliance_score = 0

        if control_assessed_for_all_investees:
            compliance_score += 25
        else:
            findings.append("Control assessment not performed for all investees")
            recommendations.append("Apply control criteria (power, exposure, ability to use power)")

        if consolidation_performed:
            compliance_score += 25
        else:
            findings.append("Subsidiaries not consolidated")
            recommendations.append("Consolidate all entities where parent has control")

        if non_controlling_interest_presented:
            compliance_score += 25
        else:
            findings.append("NCI not presented in consolidated statements")
            recommendations.append("Present NCI in equity separately from parent's equity")

        if subsidiaries_excluded_justified:
            compliance_score += 25
        else:
            findings.append("Exclusion of subsidiaries not justified")
            recommendations.append("If exclusion allowed, disclose justification")

        percentage = Decimal(compliance_score)
        status = (
            ComplianceStatus.COMPLIANT
            if percentage >= 90
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if percentage >= 50
            else ComplianceStatus.NON_COMPLIANT
        )

        result = IFRSComplianceResult(
            standard=IFRSStandard.IFRS_10,
            status=status,
            compliance_percentage=percentage,
            findings=findings,
            recommendations=recommendations,
            evidence_required=[
                "Group structure chart",
                "Consolidation working papers",
                "Control assessment memos",
            ],
        )
        self._results[IFRSStandard.IFRS_10] = result
        return result

    # ------------------------------------------------------------------------
    # Metode yang diminta oleh kontrak (check, validate, get_violations)
    # ------------------------------------------------------------------------
    def check(self) -> dict[IFRSStandard, IFRSComplianceResult]:
        """Menjalankan pengecekan penuh untuk semua standar yang belum dinilai."""
        self.generate_full_compliance_report()
        return self._results

    def validate(self, data: dict) -> dict:
        """
        Validasi data kepatuhan dari input eksternal.
        Mengembalikan hasil validasi.
        """
        if not data.get("entity_name"):
            return {"valid": False, "error": "entity_name is required"}
        return {"valid": True, "entity": data.get("entity_name")}

    def get_violations(self) -> list[dict]:
        """
        Mengembalikan daftar pelanggaran (findings) dari semua standar yang dinilai.
        """
        violations = []
        for standard, result in self._results.items():
            for finding in result.findings:
                violations.append({
                    "standard": standard.value,
                    "finding": finding,
                    "status": result.status.value,
                    "recommendation": result.recommendations[0] if result.recommendations else "",
                })
        return violations

    # ------------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------------
    def get_compliance_result(self, standard: IFRSStandard) -> IFRSComplianceResult | None:
        return self._results.get(standard)

    def get_all_results(self) -> list[IFRSComplianceResult]:
        return list(self._results.values())

    def add_gap_analysis(self, gap: IFRSGapAnalysis) -> None:
        self._gap_analyses.append(gap)

    def get_gap_analyses(self, standard: IFRSStandard | None = None) -> list[IFRSGapAnalysis]:
        if standard:
            return [g for g in self._gap_analyses if g.standard == standard]
        return self._gap_analyses

    def generate_full_compliance_report(self) -> dict[IFRSStandard, IFRSComplianceResult]:
        """Generate report untuk semua standar IFRS yang relevan."""
        if IFRSStandard.IFRS_9 not in self._results:
            self.assess_ifrs_9(True, True, True, True, True)
        if IFRSStandard.IFRS_15 not in self._results:
            self.assess_ifrs_15(True, True, True, True, True, True)
        if IFRSStandard.IFRS_16 not in self._results:
            self.assess_ifrs_16(True, True, True, False, False, True)
        if IFRSStandard.IAS_16 not in self._results:
            self.assess_ias_16(True, False, True, True, True)
        if IFRSStandard.IAS_36 not in self._results:
            self.assess_ias_36(True, True, True, False, False, True)
        if IFRSStandard.IAS_37 not in self._results:
            self.assess_ias_37(True, True, True, True, True)
        if IFRSStandard.IAS_38 not in self._results:
            self.assess_ias_38(True, True, True, True, True)
        if IFRSStandard.IAS_1 not in self._results:
            self.assess_ias_1(True, True, True, True, True)
        if IFRSStandard.IAS_7 not in self._results:
            self.assess_ias_7(True, True, True, True)
        if IFRSStandard.IFRS_10 not in self._results:
            self.assess_ifrs_10(True, True, True, True)
        return self._results

    def generate_summary(self) -> dict:
        results = self.get_all_results()
        if not results:
            self.generate_full_compliance_report()
            results = self.get_all_results()
        compliant = sum(1 for r in results if r.status == ComplianceStatus.COMPLIANT)
        partially = sum(1 for r in results if r.status == ComplianceStatus.PARTIALLY_COMPLIANT)
        non_compliant = sum(1 for r in results if r.status == ComplianceStatus.NON_COMPLIANT)
        total = len(results)
        overall_percentage = Decimal(compliant * 100 / total) if total else Decimal(0)
        return {
            "entity": self.entity_name,
            "fiscal_year_end": self.fiscal_year_end.isoformat(),
            "assessment_date": date.today().isoformat(),
            "total_standards_assessed": total,
            "compliant": compliant,
            "partially_compliant": partially,
            "non_compliant": non_compliant,
            "overall_compliance_percentage": round(overall_percentage, 2),
            "overall_status": "compliant"
            if overall_percentage >= 90
            else "partially_compliant"
            if overall_percentage >= 50
            else "non_compliant",
            # FIX: Perbaikan list comprehension untuk menghindari konflik nama variabel
            "findings_summary": [finding for result in results for finding in result.findings][:10],
            "recommendations_summary": [rec for result in results for rec in result.recommendations][:10],
        }

    def to_json(self, file_path: str | None = None) -> str:
        summary = self.generate_summary()
        results = [self._result_to_dict(r) for r in self.get_all_results()]
        output = {
            "summary": summary,
            "details": results,
            "gap_analyses": [
                {
                    "standard": g.standard.value,
                    "gap": g.gap_description,
                    "impact": g.impact,
                    "remediation": g.remediation_plan,
                }
                for g in self._gap_analyses
            ],
        }
        json_str = json.dumps(output, indent=2, default=str)
        if file_path:
            with open(file_path, "w") as f:
                f.write(json_str)
        return json_str

    def _result_to_dict(self, result: IFRSComplianceResult) -> dict:
        return {
            "standard": result.standard.value,
            "status": result.status.value,
            "compliance_percentage": float(result.compliance_percentage),
            "findings": result.findings,
            "recommendations": result.recommendations,
            "hash": result.hash_sha256,
        }

    def update_remediation(self, standard: IFRSStandard, deadline: date, status: str) -> bool:
        result = self._results.get(standard)
        if result:
            result.remediation_deadline = deadline
            result.remediation_status = status
            return True
        return False

    def get_remediation_status(self) -> list[dict]:
        return [
            {
                "standard": r.standard.value,
                "deadline": r.remediation_deadline.isoformat() if r.remediation_deadline else None,
                "status": r.remediation_status,
            }
            for r in self.get_all_results()
            if r.status != ComplianceStatus.COMPLIANT
        ]


# ============================================================================
# ALIAS UNTUK BACKWARD COMPATIBILITY (diperlukan oleh impor lain)
# ============================================================================
# Banyak file compliance yang mengimpor 'IFRSChecker' dari module ini.
# Untuk kompatibilitas, kita definisikan alias.
IFRSChecker = IfrsChecker


# ============================================================================
# Entry Point Fungsi (sesuai kontrak)
# ============================================================================
def check_ifrs_compliance(entity_name: str, fiscal_year_end: date = date(2026, 12, 31)) -> IfrsChecker:
    """
    Fungsi entry point yang mengembalikan instance IfrsChecker.
    Digunakan oleh structural integrity auditor.
    """
    return IfrsChecker(entity_name=entity_name, fiscal_year_end=fiscal_year_end)


# ============================================================================
# IFRS14Checker untuk test compatibility (tetap dipertahankan)
# ============================================================================
@dataclass
class IFRS14ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)


class IFRS14Checker:
    """
    Simple checker for IFRS 14: Regulatory Deferral Accounts.
    Used in test_ifrs_14_standards.py.
    """

    @staticmethod
    def validate(data: dict) -> IFRS14ValidationResult:
        errors = []
        if not data.get("has_regulatory_approval", False):
            errors.append("Regulatory approval required")
        if not data.get("has_rate_regulated_activities", True):
            errors.append("Rate-regulated activities not identified")
        is_compliant = len(errors) == 0
        return IFRS14ValidationResult(is_compliant=is_compliant, errors=errors)


# ============================================================================
# Demo & Contoh Penggunaan
# ============================================================================
if __name__ == "__main__":
    checker = IfrsChecker(entity_name="PT Maju Jaya", fiscal_year_end=date(2026, 12, 31))

    result9 = checker.assess_ifrs_9(
        classification_model_documented=True,
        expected_credit_loss_calculated=False,
        hedge_accounting_applied_correctly=True,
        impairment_model_implemented=True,
        disclosure_made=True,
    )
    print(f"IFRS 9: {result9.status.value} - {result9.compliance_percentage}%")
    print(f"Findings: {result9.findings}")

    result16 = checker.assess_ifrs_16(
        right_of_use_asset_recognized=True,
        lease_liability_recognized=True,
        discount_rate_determined=True,
        short_term_exemption_used=True,
        low_value_exemption_used=True,
        disclosure_complete=True,
    )
    print(f"IFRS 16: {result16.status.value} - {result16.compliance_percentage}%")

    gap = IFRSGapAnalysis(
        standard=IFRSStandard.IFRS_9,
        current_practice="No automated ECL calculation",
        required_practice="Calculate ECL using 12-month and lifetime PD/LGD/EAD",
        gap_description="ECL not integrated with accounting system",
        impact="high",
        remediation_plan="Implement ECL module in ERP by Q4 2026",
        estimated_effort_days=60,
        responsible_party="Finance Systems Team",
    )
    checker.add_gap_analysis(gap)

    summary = checker.generate_summary()
    print("\nSummary:")
    print(json.dumps(summary, indent=2))

    checker.to_json("ifrs_compliance_report.json")
    print("Report exported to ifrs_compliance_report.json")
