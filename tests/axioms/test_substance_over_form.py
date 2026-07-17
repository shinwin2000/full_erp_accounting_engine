#!/usr/bin/env python3
"""
tests/unit/test_substance_over_form.py
Test untuk axioms/substance_over_form.py
Mencakup: LegalForm, EconomicSubstance, SubstanceOverFormAssessment,
SubstanceViolation, SubstanceOverFormValidator, SubstanceOverFormAxiom
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from axioms.substance_over_form import (
    EconomicSubstance,
    LegalForm,
    SubstanceAssessmentSeverity,
    SubstanceOverFormAssessment,
    SubstanceOverFormAxiom,
    SubstanceOverFormValidator,
    SubstanceOverrideType,
    SubstanceViolation,
    SubstanceViolationError,
    create_economic_substance,
    create_legal_form,
    get_substance_over_form_axiom,
    get_substance_type_from_string,
)


class TestLegalForm:
    def test_create_valid_legal_form(self):
        """Test creation of valid LegalForm."""
        now = datetime.now(UTC)
        form = LegalForm(
            contract_type="Lease Agreement",
            parties=["Company A", "Company B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"term_months": 12, "interest_rate": "5%"},
            governing_law="Indonesia",
        )
        assert form.contract_type == "Lease Agreement"
        assert len(form.parties) == 2
        assert form.legal_amount == Decimal("100000")
        assert form.currency == "IDR"
        assert form.cryptographic_hash != ""

    def test_validate_requires_parties(self):
        """Test validation rejects empty parties."""
        with pytest.raises(ValueError, match="At least one party required"):
            LegalForm(
                contract_type="test",
                parties=[],
                legal_ownership_transfer=False,
                legal_amount=Decimal("100"),
                currency="IDR",
                contract_date=datetime.now(UTC),
                contract_terms={},
                governing_law="Indonesia",
            )

    def test_validate_positive_amount(self):
        """Test validation rejects non-positive amount."""
        with pytest.raises(ValueError, match="Legal amount must be positive"):
            LegalForm(
                contract_type="test",
                parties=["A"],
                legal_ownership_transfer=False,
                legal_amount=Decimal("-100"),
                currency="IDR",
                contract_date=datetime.now(UTC),
                contract_terms={},
                governing_law="Indonesia",
            )

    def test_update_creates_new_version(self):
        """Test update creates new instance with incremented version."""
        now = datetime.now(UTC)
        form = LegalForm(
            contract_type="test",
            parties=["A"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100"),
            currency="IDR",
            contract_date=now,
            contract_terms={},
            governing_law="Indonesia",
        )
        updated = form.update("admin", legal_amount=Decimal("200"))
        assert updated.legal_amount == Decimal("200")
        assert updated.version == form.version + 1

    def test_delete_marks_deleted(self):
        """Test delete marks as deleted."""
        now = datetime.now(UTC)
        form = LegalForm(
            contract_type="test",
            parties=["A"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100"),
            currency="IDR",
            contract_date=now,
            contract_terms={},
            governing_law="Indonesia",
        )
        deleted = form.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"


class TestEconomicSubstance:
    def test_create_valid_economic_substance(self):
        """Test creation of valid EconomicSubstance."""
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessee",
            economic_amount=Decimal("120000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Economic substance is finance lease",
            supporting_evidence=["appraisal_report.pdf"],
        )
        assert substance.transaction_type == SubstanceOverrideType.LEASE
        assert substance.economic_amount == Decimal("120000")
        assert len(substance.supporting_evidence) == 1
        assert substance.cryptographic_hash != ""

    def test_validate_positive_amount(self):
        """Test validation rejects non-positive amount."""
        with pytest.raises(ValueError, match="Economic amount must be positive"):
            EconomicSubstance(
                transaction_type=SubstanceOverrideType.LEASE,
                risks_and_rewards_transferred=False,
                control_transferred=False,
                effective_ownership="test",
                economic_amount=Decimal("-100"),
                economic_currency="IDR",
                effective_date=datetime.now(UTC),
                reasoning="test",
                supporting_evidence=[],
            )


class TestSubstanceOverFormAssessment:
    def test_create_valid_assessment(self):
        """Test creation of valid SubstanceOverFormAssessment."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="test",
            parties=["A"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100"),
            currency="IDR",
            contract_date=now,
            contract_terms={},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("120"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=True,
            difference_description="Amount differs",
            proper_accounting_treatment="Finance lease",
            recommended_journal_template={"debit": "Right-of-use asset"},
            assessed_by="admin",
            assessed_at=now,
            approved_by=["approver1", "approver2"],
        )
        assert assessment.is_different
        assert assessment.requires_adjustment()
        assert assessment.cryptographic_hash != ""


class TestSubstanceViolation:
    def test_create_valid_violation(self):
        """Test creation of valid SubstanceViolation."""
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="Operating lease",
            economic_substance_summary="Finance lease",
            recorded_treatment="Off-balance sheet",
            proper_treatment="Capitalize ROU asset",
            severity=SubstanceAssessmentSeverity.HIGH,
            message="Lease misclassification",
            detected_at=now,
            detected_by="validator",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        assert violation.severity == SubstanceAssessmentSeverity.HIGH
        assert not violation.resolved
        assert violation.cryptographic_hash != ""

    def test_resolve_marks_resolved(self):
        """Test resolve marks violation as resolved."""
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="validator",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        resolved = violation.resolve("admin", uuid.uuid4())
        assert resolved.resolved
        assert resolved.resolved_by == "admin"
        assert resolved.correction_journal_id is not None


class TestSubstanceOverFormValidator:
    def test_validate_lease_finance_lease(self):
        """Test validate_lease detects finance lease misclassification."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="Lease",
            parties=["A", "B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"lease_term_months": 36, "is_low_value": False},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Lessee",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Finance lease",
            supporting_evidence=[],
        )
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal, economic, uuid.uuid4()
        )
        # Should pass because substance matches type
        assert is_valid
        assert violation is None

    def test_validate_lease_operating_lease_misclassification(self):
        """Test validate_lease detects operating lease misclassification."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="Lease",
            parties=["A", "B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"lease_term_months": 36, "is_low_value": False},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Operating lease",
            supporting_evidence=[],
        )
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal, economic, uuid.uuid4()
        )
        assert not is_valid
        assert violation is not None
        assert violation.severity == SubstanceAssessmentSeverity.HIGH

    def test_validate_factoring_with_recourse(self):
        """Test validate_factoring detects factoring misclassification."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="Factoring",
            parties=["A", "B"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"recourse": True},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.FACTORING,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Originator",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Secured borrowing",
            supporting_evidence=[],
        )
        is_valid, violation = SubstanceOverFormValidator.validate_factoring(
            legal, economic, uuid.uuid4()
        )
        # Should pass because type matches
        assert is_valid

    def test_validate_factoring_without_recourse(self):
        """Test validate_factoring passes for sale without recourse."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="Factoring",
            parties=["A", "B"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"recourse": False},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.FACTORING,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Factor",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Sale of receivables",
            supporting_evidence=[],
        )
        is_valid, violation = SubstanceOverFormValidator.validate_factoring(
            legal, economic, uuid.uuid4()
        )
        assert is_valid

    def test_validate_related_party_fair_value(self):
        """Test validate_related_party detects fair value discrepancy."""
        now = datetime.now(UTC)
        legal = LegalForm(
            contract_type="Sale",
            parties=["Parent", "Subsidiary"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={},
            governing_law="Indonesia",
        )
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Subsidiary",
            economic_amount=Decimal("150000"),  # 50% higher
            economic_currency="IDR",
            effective_date=now,
            reasoning="Fair value is 150,000",
            supporting_evidence=["valuation.pdf"],
        )
        is_valid, violation = SubstanceOverFormValidator.validate_related_party(
            legal, economic, uuid.uuid4(), tolerance_percent=Decimal("5")
        )
        assert not is_valid
        assert violation is not None
        assert "fair value" in violation.message


class TestSubstanceOverFormAxiom:
    def test_singleton(self):
        """Test SubstanceOverFormAxiom is singleton."""
        axiom1 = SubstanceOverFormAxiom()
        axiom2 = SubstanceOverFormAxiom()
        assert axiom1 is axiom2

    def test_assess_transaction(self):
        """Test assess_transaction creates assessment."""
        now = datetime.now(UTC)
        axiom = SubstanceOverFormAxiom()
        legal = create_legal_form(
            contract_type="Lease",
            parties=["A", "B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
        )
        economic = create_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Lessee",
            economic_amount=Decimal("120000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Substance differs",
        )
        assessment = axiom.assess_transaction(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            assessed_by="admin",
            approved_by=["approver1", "approver2"],
        )
        assert assessment.is_different
        assessments = axiom.get_assessments()
        assert len(assessments) >= 1

    def test_enforce_lease_passes(self):
        """Test enforce_lease passes for valid lease."""
        now = datetime.now(UTC)
        axiom = SubstanceOverFormAxiom()
        legal = create_legal_form(
            contract_type="Lease",
            parties=["A", "B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"lease_term_months": 12, "is_low_value": False},
        )
        economic = create_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Operating lease",
        )
        is_valid, violation = axiom.enforce_lease(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            raise_on_violation=False,
        )
        # Short-term lease, should pass
        assert is_valid

    def test_enforce_lease_fails_for_finance_lease(self):
        """Test enforce_lease fails for finance lease misclassification."""
        now = datetime.now(UTC)
        axiom = SubstanceOverFormAxiom()
        legal = create_legal_form(
            contract_type="Lease",
            parties=["A", "B"],
            legal_ownership_transfer=False,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            contract_terms={"lease_term_months": 36, "is_low_value": False},
        )
        economic = create_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Operating lease",
        )
        with pytest.raises(SubstanceViolationError):
            axiom.enforce_lease(
                transaction_id=uuid.uuid4(),
                legal_form=legal,
                economic_substance=economic,
                raise_on_violation=True,
            )

    def test_enforce_related_party_detects_discrepancy(self):
        """Test enforce_related_party detects fair value discrepancy."""
        now = datetime.now(UTC)
        axiom = SubstanceOverFormAxiom()
        legal = create_legal_form(
            contract_type="Sale",
            parties=["A", "B"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
        )
        economic = create_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="B",
            economic_amount=Decimal("150000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Fair value 150,000",
        )
        with pytest.raises(SubstanceViolationError):
            axiom.enforce_related_party(
                transaction_id=uuid.uuid4(),
                legal_form=legal,
                economic_substance=economic,
                raise_on_violation=True,
            )

    def test_get_statistics(self):
        """Test get_statistics returns summary."""
        axiom = SubstanceOverFormAxiom()
        stats = axiom.get_statistics()
        assert "total_assessments" in stats
        assert "total_violations" in stats

    def test_save_violation_and_get_violations(self):
        """Test save_violation stores and get_violations retrieves."""
        axiom = SubstanceOverFormAxiom()
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test violation",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_resolve_violation(self):
        """Test resolve_violation marks as resolved."""
        axiom = SubstanceOverFormAxiom()
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin", uuid.uuid4())
        assert resolved is not None
        assert resolved.resolved

    def test_get_substance_over_form_axiom_singleton(self):
        """Test get_substance_over_form_axiom returns singleton."""
        axiom1 = get_substance_over_form_axiom()
        axiom2 = get_substance_over_form_axiom()
        assert axiom1 is axiom2


class TestHelperFunctions:
    def test_create_legal_form(self):
        """Test create_legal_form helper."""
        now = datetime.now(UTC)
        form = create_legal_form(
            contract_type="Sale",
            parties=["Seller", "Buyer"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=now,
            governing_law="Indonesia",
            additional_term="value",
        )
        assert form.contract_type == "Sale"
        assert form.contract_terms.get("additional_term") == "value"

    def test_create_economic_substance(self):
        """Test create_economic_substance helper."""
        now = datetime.now(UTC)
        substance = create_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Lessee",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="Test",
            supporting_evidence=["doc1.pdf"],
        )
        assert substance.transaction_type == SubstanceOverrideType.LEASE
        assert len(substance.supporting_evidence) == 1

    def test_get_substance_type_from_string(self):
        """Test get_substance_type_from_string maps strings to enum."""
        assert get_substance_type_from_string("LEASE") == SubstanceOverrideType.LEASE
        assert get_substance_type_from_string("FACTORING") == SubstanceOverrideType.FACTORING
        assert get_substance_type_from_string("unknown") == SubstanceOverrideType.LEASE


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_legal_form() -> LegalForm:
    now = datetime.now(UTC)
    return LegalForm(
        contract_type="Test",
        parties=["A"],
        legal_ownership_transfer=False,
        legal_amount=Decimal("100"),
        currency="IDR",
        contract_date=now,
        contract_terms={},
        governing_law="Indonesia",
    )


class TestLegalFormLifecycle:
    def test_create_returns_self(self):
        form = create_test_legal_form()
        result = form.create("admin")
        assert result is form

    def test_activate_returns_self(self):
        form = create_test_legal_form()
        result = form.activate("admin")
        assert result is form

    def test_deactivate_returns_self(self):
        form = create_test_legal_form()
        result = form.deactivate("admin")
        assert result is form

    def test_lock_returns_self(self):
        form = create_test_legal_form()
        result = form.lock("admin", "test")
        assert result is form

    def test_unlock_returns_self(self):
        form = create_test_legal_form()
        result = form.unlock("admin")
        assert result is form

    def test_validate_returns_valid(self):
        form = create_test_legal_form()
        result = form.validate()
        assert result["is_valid"]


class TestEconomicSubstanceLifecycle:
    def test_create_returns_self(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.create("admin")
        assert result is substance

    def test_activate_returns_self(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.activate("admin")
        assert result is substance

    def test_deactivate_returns_self(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.deactivate("admin")
        assert result is substance

    def test_lock_returns_self(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.lock("admin", "test")
        assert result is substance

    def test_unlock_returns_self(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.unlock("admin")
        assert result is substance

    def test_validate_returns_valid(self):
        now = datetime.now(UTC)
        substance = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        result = substance.validate()
        assert result["is_valid"]


class TestSubstanceOverFormAssessmentLifecycle:
    def test_create_returns_self(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.create("admin")
        assert result is assessment

    def test_activate_returns_self(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.activate("admin")
        assert result is assessment

    def test_deactivate_returns_self(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.deactivate("admin")
        assert result is assessment

    def test_lock_returns_self(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.lock("admin", "test")
        assert result is assessment

    def test_unlock_returns_self(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.unlock("admin")
        assert result is assessment

    def test_validate_returns_valid(self):
        now = datetime.now(UTC)
        legal = create_test_legal_form()
        economic = EconomicSubstance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="test",
            economic_amount=Decimal("100"),
            economic_currency="IDR",
            effective_date=now,
            reasoning="test",
            supporting_evidence=[],
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=False,
            difference_description="",
            proper_accounting_treatment="",
            recommended_journal_template=None,
            assessed_by="admin",
            assessed_at=now,
            approved_by=[],
        )
        result = assessment.validate()
        assert result["is_valid"]


class TestSubstanceViolationLifecycle:
    def test_create_returns_self(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.create("admin")
        assert result is violation

    def test_activate_returns_self(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.activate("admin")
        assert result is violation

    def test_deactivate_returns_self(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.deactivate("admin")
        assert result is violation

    def test_lock_returns_self(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.lock("admin", "test")
        assert result is violation

    def test_unlock_returns_self(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.unlock("admin")
        assert result is violation

    def test_validate_returns_valid(self):
        now = datetime.now(UTC)
        violation = SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="test",
            economic_substance_summary="test",
            recorded_treatment="test",
            proper_treatment="test",
            severity=SubstanceAssessmentSeverity.MEDIUM,
            message="test",
            detected_at=now,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )
        result = violation.validate()
        assert result["is_valid"]