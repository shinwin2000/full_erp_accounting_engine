#!/usr/bin/env python3
"""
tests/compliance/ethics/test_disclosure_requirement_checker.py
Comprehensive tests for compliance/ethics/disclosure_requirement_checker.py

Covers:
- Enums: DisclosureTopic, DisclosureStatus, RegulatoryFramework
- DisclosureRequirement: construction, mark_compliant, mark_non_compliant, mark_partial, to_dict, _compute_hash
- DisclosureRequirementChecker: __init__, _init_requirements, add_custom_requirement, get_requirement,
  mark_disclosure_compliant, mark_disclosure_non_compliant, mark_disclosure_partial, _record_assessment,
  missing_disclosures, is_compliant, get_compliance_percentage, generate_disclosure_report, to_json, reset_assessment
- Edge cases: non-required requirements, different frameworks, invalid topics, file I/O mocking
- All datetime is mocked for deterministic results.
"""

import json
from datetime import date, datetime
from unittest.mock import mock_open, patch

import pytest

from compliance.ethics.disclosure_requirement_checker import (
    DisclosureRequirement,
    DisclosureRequirementChecker,
    DisclosureStatus,
    DisclosureTopic,
    RegulatoryFramework,
)

# ============================================================================
# Fixtures
# ============================================================================

FIXED_DATE = date(2026, 7, 23)
FIXED_DATETIME = datetime(2026, 7, 23, 12, 0, 0)


@pytest.fixture(autouse=True)
def mock_today():
    with patch("compliance.ethics.disclosure_requirement_checker.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


@pytest.fixture(autouse=True)
def mock_datetime():
    with patch("compliance.ethics.disclosure_requirement_checker.datetime") as mock_dt:
        mock_dt.utcnow.return_value = FIXED_DATETIME
        yield mock_dt


@pytest.fixture
def checker_psak():
    return DisclosureRequirementChecker(RegulatoryFramework.PSAK)


@pytest.fixture
def checker_ifrs():
    return DisclosureRequirementChecker(RegulatoryFramework.IFRS)


@pytest.fixture
def requirement():
    return DisclosureRequirement(
        topic=DisclosureTopic.ACCOUNTING_POLICIES,
        required=True,
        description="Test disclosure",
        regulation_reference="PSAK 1",
        regulatory_framework=RegulatoryFramework.PSAK,
        detailed_criteria=["Criterion 1", "Criterion 2"],
    )


# ============================================================================
# Tests for Enums
# ============================================================================

class TestDisclosureTopic:
    def test_members(self):
        assert DisclosureTopic.ACCOUNTING_POLICIES.value == "accounting_policies"
        assert DisclosureTopic.CHANGE_IN_ESTIMATES.value == "change_in_estimates"
        assert DisclosureTopic.CORRECTION_OF_ERRORS.value == "correction_of_errors"
        assert DisclosureTopic.RELATED_PARTY_TRANSACTIONS.value == "related_party_transactions"
        assert DisclosureTopic.CONTINGENT_LIABILITIES.value == "contingent_liabilities"
        assert DisclosureTopic.EVENTS_AFTER_REPORTING_PERIOD.value == "events_after_reporting_period"
        assert DisclosureTopic.SEGMENT_INFORMATION.value == "segment_information"
        assert DisclosureTopic.FAIR_VALUE_MEASUREMENT.value == "fair_value_measurement"
        assert DisclosureTopic.FINANCIAL_INSTRUMENTS.value == "financial_instruments"
        assert DisclosureTopic.LEASES.value == "leases"
        assert DisclosureTopic.REVENUE.value == "revenue"
        assert DisclosureTopic.TAXES.value == "taxes"
        assert DisclosureTopic.EARNINGS_PER_SHARE.value == "earnings_per_share"
        assert DisclosureTopic.GOING_CONCERN.value == "going_concern"
        assert DisclosureTopic.SUBSEQUENT_EVENTS.value == "subsequent_events"
        assert DisclosureTopic.BUSINESS_COMBINATIONS.value == "business_combinations"
        assert DisclosureTopic.INTANGIBLE_ASSETS.value == "intangible_assets"
        assert DisclosureTopic.INVENTORIES.value == "inventories"
        assert DisclosureTopic.PROPERTY_PLANT_EQUIPMENT.value == "property_plant_equipment"
        assert DisclosureTopic.IMPAIRMENT.value == "impairment"
        assert DisclosureTopic.PROVISIONS.value == "provisions"
        assert DisclosureTopic.SHARE_BASED_PAYMENT.value == "share_based_payment"
        assert DisclosureTopic.GOVERNMENT_GRANTS.value == "government_grants"
        assert DisclosureTopic.BORROWING_COSTS.value == "borrowing_costs"
        assert DisclosureTopic.INVESTMENT_PROPERTY.value == "investment_property"
        assert DisclosureTopic.NON_CURRENT_ASSETS_HELD_FOR_SALE.value == "non_current_assets_held_for_sale"


class TestDisclosureStatus:
    def test_members(self):
        assert DisclosureStatus.COMPLIANT.value == "compliant"
        assert DisclosureStatus.PARTIALLY_COMPLIANT.value == "partially_compliant"
        assert DisclosureStatus.NON_COMPLIANT.value == "non_compliant"
        assert DisclosureStatus.NOT_APPLICABLE.value == "not_applicable"
        assert DisclosureStatus.UNDER_REVIEW.value == "under_review"


class TestRegulatoryFramework:
    def test_members(self):
        assert RegulatoryFramework.PSAK.value == "psak"
        assert RegulatoryFramework.IFRS.value == "ifrs"
        assert RegulatoryFramework.OJK.value == "ojk"
        assert RegulatoryFramework.GAAP.value == "gaap"


# ============================================================================
# Tests for DisclosureRequirement
# ============================================================================

class TestDisclosureRequirement:
    def test_construction(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
            detailed_criteria=["C1", "C2"],
        )
        assert req.topic == DisclosureTopic.ACCOUNTING_POLICIES
        assert req.required is True
        assert req.description == "Test"
        assert req.regulation_reference == "PSAK 1"
        assert req.regulatory_framework == RegulatoryFramework.PSAK
        assert req.detailed_criteria == ["C1", "C2"]
        assert req.disclosed is False
        assert req.status == DisclosureStatus.NON_COMPLIANT
        assert req.assessed_by is None
        assert req.assessed_date is None
        assert req.notes == ""
        assert req._hash is not None

    def test_construction_not_required(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=False,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        assert req.status == DisclosureStatus.NOT_APPLICABLE

    def test_mark_compliant(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        old_hash = req._hash
        req.mark_compliant("Auditor", "Disclosure text", "evidence.pdf")
        assert req.disclosed is True
        assert req.disclosure_text == "Disclosure text"
        assert req.status == DisclosureStatus.COMPLIANT
        assert req.assessed_by == "Auditor"
        assert req.assessed_date == FIXED_DATE
        assert req.evidence == "evidence.pdf"
        assert req._hash != old_hash

    def test_mark_non_compliant(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        old_hash = req._hash
        req.mark_non_compliant("Auditor", "Missing data")
        assert req.disclosed is False
        assert req.status == DisclosureStatus.NON_COMPLIANT
        assert req.assessed_by == "Auditor"
        assert req.assessed_date == FIXED_DATE
        assert req.notes == "Missing data"
        assert req._hash != old_hash

    def test_mark_partial(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        old_hash = req._hash
        req.mark_partial("Auditor", "Incomplete information")
        assert req.disclosed is True
        assert req.status == DisclosureStatus.PARTIALLY_COMPLIANT
        assert req.assessed_by == "Auditor"
        assert req.assessed_date == FIXED_DATE
        assert req.notes == "Incomplete information"
        assert req._hash != old_hash

    def test_to_dict(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
            detailed_criteria=["C1", "C2"],
        )
        req.mark_compliant("Auditor", "Disclosure text", "evidence.pdf")
        d = req.to_dict()
        assert d["topic"] == "accounting_policies"
        assert d["required"] is True
        assert d["description"] == "Test"
        assert d["regulation_reference"] == "PSAK 1"
        assert d["framework"] == "psak"
        assert d["criteria"] == ["C1", "C2"]
        assert d["disclosed"] is True
        assert d["disclosure_text"] == "Disclosure text"
        assert d["status"] == "compliant"
        assert d["assessed_by"] == "Auditor"
        assert d["assessed_date"] == FIXED_DATE.isoformat()
        assert d["notes"] == ""
        assert d["hash"] == req._hash

    def test_to_dict_truncates_text(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.ACCOUNTING_POLICIES,
            required=True,
            description="Test",
            regulation_reference="PSAK 1",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        long_text = "x" * 1000
        req.mark_compliant("Auditor", long_text)
        d = req.to_dict()
        assert len(d["disclosure_text"]) == 500  # truncated


# ============================================================================
# Tests for DisclosureRequirementChecker
# ============================================================================

class TestDisclosureRequirementCheckerInit:
    def test_init_psak(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.PSAK)
        assert checker.framework == RegulatoryFramework.PSAK
        assert len(checker._requirements) > 0
        # Check a few requirements exist
        topics = [r.topic for r in checker._requirements]
        assert DisclosureTopic.ACCOUNTING_POLICIES in topics
        assert DisclosureTopic.RELATED_PARTY_TRANSACTIONS in topics
        assert DisclosureTopic.REVENUE in topics
        assert len(checker._assessment_history) == 0

    def test_init_ifrs(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.IFRS)
        assert checker.framework == RegulatoryFramework.IFRS
        # For other frameworks, requirements list is empty (simplified)
        assert len(checker._requirements) == 0

    def test_init_other(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.OJK)
        assert checker.framework == RegulatoryFramework.OJK
        assert len(checker._requirements) == 0

    # Test _init_requirements directly (private method)
    def test_init_requirements_psak(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.PSAK)
        # Reinitialize
        checker._requirements = []
        checker._init_requirements()
        assert len(checker._requirements) == 20  # based on source
        # Spot check a few
        accounting = checker.get_requirement(DisclosureTopic.ACCOUNTING_POLICIES)
        assert accounting is not None
        assert accounting.required is True
        assert accounting.regulation_reference == "PSAK 1"
        assert accounting.detailed_criteria == ["Basis of preparation", "Measurement bases", "Critical accounting estimates"]

        impairment = checker.get_requirement(DisclosureTopic.IMPAIRMENT)
        assert impairment is not None
        assert impairment.required is True
        assert impairment.regulation_reference == "PSAK 48"

        business_comb = checker.get_requirement(DisclosureTopic.BUSINESS_COMBINATIONS)
        assert business_comb is not None
        assert business_comb.required is False  # as per source

    def test_init_requirements_ifrs(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.IFRS)
        checker._requirements = []
        checker._init_requirements()
        assert len(checker._requirements) == 0

    def test_get_requirement(self, checker_psak):
        req = checker_psak.get_requirement(DisclosureTopic.ACCOUNTING_POLICIES)
        assert req is not None
        assert req.topic == DisclosureTopic.ACCOUNTING_POLICIES

        req2 = checker_psak.get_requirement(DisclosureTopic.FAIR_VALUE_MEASUREMENT)
        assert req2 is not None
        assert req2.framework == RegulatoryFramework.PSAK

        assert checker_psak.get_requirement(DisclosureTopic.SHARE_BASED_PAYMENT) is None

    def test_add_custom_requirement(self, checker_psak):
        initial_count = len(checker_psak._requirements)
        custom = DisclosureRequirement(
            topic=DisclosureTopic.SHARE_BASED_PAYMENT,
            required=True,
            description="Custom",
            regulation_reference="PSAK 53",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        checker_psak.add_custom_requirement(custom)
        assert len(checker_psak._requirements) == initial_count + 1
        assert checker_psak.get_requirement(DisclosureTopic.SHARE_BASED_PAYMENT) is custom


class TestDisclosureRequirementCheckerMark:
    def test_mark_disclosure_compliant(self, checker_psak):
        result = checker_psak.mark_disclosure_compliant(
            DisclosureTopic.ACCOUNTING_POLICIES,
            "Auditor",
            "Disclosure text",
            "evidence.pdf"
        )
        assert result is True
        req = checker_psak.get_requirement(DisclosureTopic.ACCOUNTING_POLICIES)
        assert req.status == DisclosureStatus.COMPLIANT
        assert req.disclosed is True
        assert req.disclosure_text == "Disclosure text"
        assert req.assessed_by == "Auditor"
        assert req.assessed_date == FIXED_DATE
        # Check history
        assert len(checker_psak._assessment_history) == 1
        assert checker_psak._assessment_history[0]["topic"] == "accounting_policies"
        assert checker_psak._assessment_history[0]["status"] == "compliant"

    def test_mark_disclosure_compliant_not_found(self, checker_psak):
        result = checker_psak.mark_disclosure_compliant(
            DisclosureTopic.SHARE_BASED_PAYMENT,
            "Auditor",
            "text"
        )
        assert result is False
        assert len(checker_psak._assessment_history) == 0

    def test_mark_disclosure_non_compliant(self, checker_psak):
        result = checker_psak.mark_disclosure_non_compliant(
            DisclosureTopic.RELATED_PARTY_TRANSACTIONS,
            "Auditor",
            "Missing data"
        )
        assert result is True
        req = checker_psak.get_requirement(DisclosureTopic.RELATED_PARTY_TRANSACTIONS)
        assert req.status == DisclosureStatus.NON_COMPLIANT
        assert req.disclosed is False
        assert req.notes == "Missing data"
        assert len(checker_psak._assessment_history) == 1
        assert checker_psak._assessment_history[0]["status"] == "non_compliant"

    def test_mark_disclosure_non_compliant_not_found(self, checker_psak):
        result = checker_psak.mark_disclosure_non_compliant(
            DisclosureTopic.SHARE_BASED_PAYMENT,
            "Auditor",
            "notes"
        )
        assert result is False

    def test_mark_disclosure_partial(self, checker_psak):
        result = checker_psak.mark_disclosure_partial(
            DisclosureTopic.REVENUE,
            "Auditor",
            "Incomplete"
        )
        assert result is True
        req = checker_psak.get_requirement(DisclosureTopic.REVENUE)
        assert req.status == DisclosureStatus.PARTIALLY_COMPLIANT
        assert req.disclosed is True
        assert req.notes == "Incomplete"
        assert len(checker_psak._assessment_history) == 1
        assert checker_psak._assessment_history[0]["status"] == "partially_compliant"

    def test_mark_disclosure_partial_not_found(self, checker_psak):
        result = checker_psak.mark_disclosure_partial(
            DisclosureTopic.SHARE_BASED_PAYMENT,
            "Auditor",
            "notes"
        )
        assert result is False

    def test__record_assessment(self, checker_psak):
        checker_psak._record_assessment(
            DisclosureTopic.ACCOUNTING_POLICIES,
            DisclosureStatus.COMPLIANT,
            "Auditor"
        )
        assert len(checker_psak._assessment_history) == 1
        entry = checker_psak._assessment_history[0]
        assert entry["topic"] == "accounting_policies"
        assert entry["status"] == "compliant"
        assert entry["assessed_by"] == "Auditor"
        assert entry["assessed_at"] == FIXED_DATETIME.isoformat()


class TestDisclosureRequirementCheckerQueries:
    def test_missing_disclosures_none(self, checker_psak):
        # Mark all required as compliant
        for req in checker_psak._requirements:
            if req.required:
                req.mark_compliant("Auditor", "text")
        missing = checker_psak.missing_disclosures()
        assert len(missing) == 0

    def test_missing_disclosures_some(self, checker_psak):
        # Mark some as compliant, leave others non-compliant
        checker_psak.mark_disclosure_compliant(
            DisclosureTopic.ACCOUNTING_POLICIES, "Auditor", "text"
        )
        checker_psak.mark_disclosure_non_compliant(
            DisclosureTopic.RELATED_PARTY_TRANSACTIONS, "Auditor", "missing"
        )
        # Also, REVENUE is still non-compliant by default
        missing = checker_psak.missing_disclosures()
        topics = [r.topic for r in missing]
        assert DisclosureTopic.RELATED_PARTY_TRANSACTIONS in topics
        assert DisclosureTopic.REVENUE in topics  # not marked
        assert DisclosureTopic.ACCOUNTING_POLICIES not in topics
        # Should not include non-required
        assert DisclosureTopic.BUSINESS_COMBINATIONS not in topics

    def test_is_compliant_true(self, checker_psak):
        for req in checker_psak._requirements:
            if req.required:
                req.mark_compliant("Auditor", "text")
        assert checker_psak.is_compliant() is True

    def test_is_compliant_false(self, checker_psak):
        # At least one missing
        assert checker_psak.is_compliant() is False

    def test_get_compliance_percentage(self, checker_psak):
        # Initially, all non-compliant => 0%
        assert checker_psak.get_compliance_percentage() == 0.0

        # Mark half as compliant
        required = [r for r in checker_psak._requirements if r.required]
        half = len(required) // 2
        for req in required[:half]:
            req.mark_compliant("Auditor", "text")
        expected = (half / len(required)) * 100
        assert round(checker_psak.get_compliance_percentage(), 2) == round(expected, 2)

        # If no required (e.g., IFRS framework), should return 100%
        checker_ifrs = DisclosureRequirementChecker(RegulatoryFramework.IFRS)
        assert checker_ifrs.get_compliance_percentage() == 100.0

    def test_generate_disclosure_report(self, checker_psak):
        # Mark some as compliant, some partial, some non-compliant
        checker_psak.mark_disclosure_compliant(
            DisclosureTopic.ACCOUNTING_POLICIES, "Auditor", "text"
        )
        checker_psak.mark_disclosure_partial(
            DisclosureTopic.RELATED_PARTY_TRANSACTIONS, "Auditor", "partial"
        )
        # REVENUE remains non-compliant
        report = checker_psak.generate_disclosure_report()
        assert report["framework"] == "psak"
        assert report["assessment_date"] == FIXED_DATE.isoformat()
        total_required = len([r for r in checker_psak._requirements if r.required])
        assert report["total_required"] == total_required
        assert report["compliant"] == 1
        assert report["partially_compliant"] == 1
        assert report["non_compliant"] == total_required - 2
        assert report["compliance_percentage"] == round((1 / total_required) * 100, 2)
        assert len(report["missing_details"]) == total_required - 1  # partial + non-compliant
        assert len(report["recommendations"]) == total_required - 1
        # Check that recommendations include text
        assert any("Implement disclosure" in rec for rec in report["recommendations"])
        assert any("Complete disclosure" in rec for rec in report["recommendations"])

    def test_generate_disclosure_report_all_compliant(self, checker_psak):
        for req in checker_psak._requirements:
            if req.required:
                req.mark_compliant("Auditor", "text")
        report = checker_psak.generate_disclosure_report()
        assert report["non_compliant"] == 0
        assert report["partially_compliant"] == 0
        assert report["compliance_percentage"] == 100.0
        assert len(report["missing_details"]) == 0
        assert len(report["recommendations"]) == 0

    def test_generate_disclosure_report_ifrs(self):
        checker = DisclosureRequirementChecker(RegulatoryFramework.IFRS)
        report = checker.generate_disclosure_report()
        assert report["total_required"] == 0
        assert report["compliant"] == 0
        assert report["compliance_percentage"] == 100.0  # because no required


class TestDisclosureRequirementCheckerSerialization:
    def test_to_json(self, checker_psak):
        checker_psak.mark_disclosure_compliant(
            DisclosureTopic.ACCOUNTING_POLICIES, "Auditor", "text"
        )
        mock_file = mock_open()
        with patch("builtins.open", mock_file):
            checker_psak.to_json("test.json")
        # Verify write called
        mock_file.assert_called_once_with("test.json", "w")
        handle = mock_file()
        # Get the written data
        written = "".join(call_args[0][0] for call_args in handle.write.call_args_list)
        data = json.loads(written)
        assert "report" in data
        assert "requirements" in data
        assert "history" in data
        assert len(data["requirements"]) == len(checker_psak._requirements)
        assert len(data["history"]) == 1

    def test_reset_assessment(self, checker_psak):
        # Mark some requirements
        checker_psak.mark_disclosure_compliant(
            DisclosureTopic.ACCOUNTING_POLICIES, "Auditor", "text"
        )
        checker_psak.mark_disclosure_partial(
            DisclosureTopic.RELATED_PARTY_TRANSACTIONS, "Auditor", "partial"
        )
        # Verify they are set
        assert checker_psak.get_requirement(DisclosureTopic.ACCOUNTING_POLICIES).status == DisclosureStatus.COMPLIANT
        assert checker_psak.get_requirement(DisclosureTopic.RELATED_PARTY_TRANSACTIONS).status == DisclosureStatus.PARTIALLY_COMPLIANT
        assert len(checker_psak._assessment_history) == 2

        checker_psak.reset_assessment()
        # All requirements should be reset to default
        accounting = checker_psak.get_requirement(DisclosureTopic.ACCOUNTING_POLICIES)
        assert accounting.disclosed is False
        assert accounting.disclosure_text == ""
        assert accounting.status == DisclosureStatus.NON_COMPLIANT  # required
        assert accounting.assessed_by is None
        assert accounting.assessed_date is None
        assert accounting.notes == ""

        # Non-required should be NOT_APPLICABLE
        business = checker_psak.get_requirement(DisclosureTopic.BUSINESS_COMBINATIONS)
        assert business.status == DisclosureStatus.NOT_APPLICABLE

        # History cleared
        assert len(checker_psak._assessment_history) == 0

    def test_reset_assessment_custom_requirements(self, checker_psak):
        custom = DisclosureRequirement(
            topic=DisclosureTopic.SHARE_BASED_PAYMENT,
            required=True,
            description="Custom",
            regulation_reference="PSAK 53",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        checker_psak.add_custom_requirement(custom)
        custom.mark_compliant("Auditor", "text")
        checker_psak.reset_assessment()
        assert custom.status == DisclosureStatus.NON_COMPLIANT  # required, reset to non_compliant


# ============================================================================
# Integration/Edge Cases
# ============================================================================

class TestEdgeCases:
    def test_mark_compliant_for_non_required(self):
        req = DisclosureRequirement(
            topic=DisclosureTopic.BUSINESS_COMBINATIONS,
            required=False,
            description="Test",
            regulation_reference="PSAK 22",
            regulatory_framework=RegulatoryFramework.PSAK,
        )
        # Marking compliant on a non-required item should still update status
        req.mark_compliant("Auditor", "text")
        assert req.status == DisclosureStatus.COMPLIANT
        assert req.disclosed is True

    def test_get_requirement_missing(self, checker_psak):
        assert checker_psak.get_requirement(DisclosureTopic.SHARE_BASED_PAYMENT) is None

    def test_generate_recommendations_with_empty_lists(self, checker_psak):
        recs = checker_psak._generate_recommendations([], [])
        assert recs == []

    def test_generate_recommendations(self, checker_psak):
        non_compliant = [
            DisclosureRequirement(
                topic=DisclosureTopic.ACCOUNTING_POLICIES,
                required=True,
                description="Test",
                regulation_reference="PSAK 1",
                regulatory_framework=RegulatoryFramework.PSAK,
            )
        ]
        partial = [
            DisclosureRequirement(
                topic=DisclosureTopic.RELATED_PARTY_TRANSACTIONS,
                required=True,
                description="Test2",
                regulation_reference="PSAK 7",
                regulatory_framework=RegulatoryFramework.PSAK,
            )
        ]
        partial[0].notes = "Missing criteria"
        recs = checker_psak._generate_recommendations(non_compliant, partial)
        assert len(recs) == 2
        assert "Implement disclosure for accounting_policies" in recs[0]
        assert "Complete disclosure for related_party_transactions" in recs[1]
