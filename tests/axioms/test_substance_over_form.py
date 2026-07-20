#!/usr/bin/env python3
"""
tests/unit/test_substance_over_form.py
Test untuk axioms/substance_over_form.py
Mencakup: LegalForm, EconomicSubstance, SubstanceOverFormAssessment,
SubstanceViolation, SubstanceOverFormValidator, SubstanceOverFormAxiom

FIXES:
- Semua datetime.now(UTC) diganti dengan FIXED_NOW.
- Duplikasi struktural dihilangkan dengan parametrize.
- Negative path tests untuk semua validasi.
- Semua assertion bermakna.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

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

# ============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=1)
FIXED_FUTURE = FIXED_NOW + timedelta(days=1)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_legal_form(
    contract_type: str = "Test",
    parties: list[str] | None = None,
    legal_ownership_transfer: bool = False,
    legal_amount: Decimal = Decimal("100"),
    currency: str = "IDR",
    contract_date: datetime | None = None,
    governing_law: str = "Indonesia",
    **contract_terms,
) -> LegalForm:
    if parties is None:
        parties = ["A"]
    if contract_date is None:
        contract_date = FIXED_NOW
    with patch("axioms.substance_over_form.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return LegalForm(
            contract_type=contract_type,
            parties=parties,
            legal_ownership_transfer=legal_ownership_transfer,
            legal_amount=legal_amount,
            currency=currency,
            contract_date=contract_date,
            contract_terms=contract_terms,
            governing_law=governing_law,
        )


def create_test_economic_substance(
    transaction_type: SubstanceOverrideType = SubstanceOverrideType.LEASE,
    risks_and_rewards_transferred: bool = False,
    control_transferred: bool = False,
    effective_ownership: str = "Lessee",
    economic_amount: Decimal = Decimal("100"),
    economic_currency: str = "IDR",
    effective_date: datetime | None = None,
    reasoning: str = "Test",
    supporting_evidence: list[str] | None = None,
) -> EconomicSubstance:
    if effective_date is None:
        effective_date = FIXED_NOW
    if supporting_evidence is None:
        supporting_evidence = []
    with patch("axioms.substance_over_form.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return EconomicSubstance(
            transaction_type=transaction_type,
            risks_and_rewards_transferred=risks_and_rewards_transferred,
            control_transferred=control_transferred,
            effective_ownership=effective_ownership,
            economic_amount=economic_amount,
            economic_currency=economic_currency,
            effective_date=effective_date,
            reasoning=reasoning,
            supporting_evidence=supporting_evidence,
        )


def create_test_assessment(
    is_different: bool = False,
    assessed_by: str = "admin",
) -> SubstanceOverFormAssessment:
    legal = create_test_legal_form()
    economic = create_test_economic_substance()
    with patch("axioms.substance_over_form.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return SubstanceOverFormAssessment(
            assessment_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            is_different=is_different,
            difference_description="Test difference" if is_different else "",
            proper_accounting_treatment="Capitalize ROU asset" if is_different else "Record as legal",
            recommended_journal_template=None,
            assessed_by=assessed_by,
            assessed_at=FIXED_NOW,
            approved_by=["approver1"],
        )


def create_test_violation(
    severity: SubstanceAssessmentSeverity = SubstanceAssessmentSeverity.MEDIUM,
    resolved: bool = False,
) -> SubstanceViolation:
    with patch("axioms.substance_over_form.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        return SubstanceViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            legal_form_summary="Legal: lease with term 36 months",
            economic_substance_summary="Economic: finance lease",
            recorded_treatment="Operating lease",
            proper_treatment="Finance lease",
            severity=severity,
            message="Lease misclassification",
            detected_at=FIXED_NOW,
            detected_by="validator",
            resolved=resolved,
            resolved_at=FIXED_NOW if resolved else None,
            resolved_by="admin" if resolved else None,
            correction_journal_id=uuid.uuid4() if resolved else None,
        )


# ============================================================================
# PARAMETRIZE HELPERS UNTUK ENTITY DASAR
# ============================================================================

# (fixture_name, class_name, supports_update, supports_delete, supports_restore)
ENTITY_PARAMS = [
    ("legal_form", "LegalForm", True, True, True),
    ("economic_substance", "EconomicSubstance", True, True, True),
    ("assessment", "SubstanceOverFormAssessment", True, True, True),
    ("violation", "SubstanceViolation", False, False, False),
]


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def legal_form():
    return create_test_legal_form()


@pytest.fixture
def economic_substance():
    return create_test_economic_substance()


@pytest.fixture
def assessment():
    return create_test_assessment()


@pytest.fixture
def violation():
    return create_test_violation()


# ============================================================================
# TESTS UNTUK LegalForm
# ============================================================================

class TestLegalForm:
    def test_create_valid(self):
        form = create_test_legal_form()
        assert form.contract_type == "Test"
        assert len(form.parties) == 1
        assert form.legal_amount == Decimal("100")
        assert form.currency == "IDR"
        assert form.version == 1
        assert form.cryptographic_hash != ""

    def test_validate_requires_parties(self):
        with pytest.raises(ValueError, match="At least one party required"):
            create_test_legal_form(parties=[])

    def test_validate_positive_amount(self):
        with pytest.raises(ValueError, match="Legal amount must be positive"):
            create_test_legal_form(legal_amount=Decimal("-100"))

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            with patch("axioms.substance_over_form.datetime") as mock_dt:
                mock_dt.now.return_value = FIXED_NOW
                mock_dt.UTC = UTC
                LegalForm(
                    contract_type="Test",
                    parties=["A"],
                    legal_ownership_transfer=False,
                    legal_amount=Decimal("100"),
                    currency="IDR",
                    contract_date=FIXED_NOW,
                    contract_terms={},
                    governing_law="Indonesia",
                    version=0,
                )

    def test_update(self, legal_form):
        updated = legal_form.update("admin", legal_amount=Decimal("200"))
        assert updated.legal_amount == Decimal("200")
        assert updated.version == legal_form.version + 1

    def test_delete(self, legal_form):
        deleted = legal_form.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        assert deleted.version == legal_form.version + 1

    def test_restore(self, legal_form):
        deleted = legal_form.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self, legal_form):
        with pytest.raises(ValueError, match="Not deleted"):
            legal_form.restore("admin")

    def test_activate_deactivate(self, legal_form):
        assert legal_form.activate("admin") is legal_form
        assert legal_form.deactivate("admin") is legal_form

    def test_lock_unlock(self, legal_form):
        assert legal_form.lock("admin", "test") is legal_form
        assert legal_form.unlock("admin") is legal_form

    def test_validate(self, legal_form):
        result = legal_form.validate()
        assert result["is_valid"]
        object.__setattr__(legal_form, "cryptographic_hash", "fake")
        result2 = legal_form.validate()
        assert not result2["is_valid"]
        assert "Hash mismatch" in result2["errors"]

    def test_to_dict(self, legal_form):
        d = legal_form.to_dict()
        assert d["contract_type"] == "Test"
        assert d["legal_amount"] == "100"

    def test_from_dict(self, legal_form):
        d = legal_form.to_dict()
        reconstructed = LegalForm.from_dict(d)
        assert reconstructed.contract_type == legal_form.contract_type
        assert reconstructed.legal_amount == legal_form.legal_amount

    def test_clone(self, legal_form):
        cloned = legal_form.clone()
        assert cloned is not legal_form
        assert cloned.contract_type == legal_form.contract_type
        assert cloned.parties == legal_form.parties
        assert cloned.version == 1

    def test_snapshot(self, legal_form):
        snap = legal_form.snapshot()
        assert snap["contract_type"] == legal_form.contract_type

    def test_audit_trail(self, legal_form):
        trail = legal_form.audit_trail()
        assert len(trail) >= 1
        legal_form.touch("toucher")
        trail2 = legal_form.audit_trail()
        assert len(trail2) >= len(trail) + 1

    def test_touch(self, legal_form):
        touched = legal_form.touch("toucher")
        assert touched.version == legal_form.version + 1


# ============================================================================
# TESTS UNTUK EconomicSubstance
# ============================================================================

class TestEconomicSubstance:
    def test_create_valid(self, economic_substance):
        assert economic_substance.transaction_type == SubstanceOverrideType.LEASE
        assert economic_substance.economic_amount == Decimal("100")
        assert economic_substance.version == 1

    def test_validate_positive_amount(self):
        with pytest.raises(ValueError, match="Economic amount must be positive"):
            create_test_economic_substance(economic_amount=Decimal("-100"))

    def test_update(self, economic_substance):
        updated = economic_substance.update("admin", economic_amount=Decimal("200"))
        assert updated.economic_amount == Decimal("200")
        assert updated.version == economic_substance.version + 1

    def test_delete(self, economic_substance):
        deleted = economic_substance.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"

    def test_restore(self, economic_substance):
        deleted = economic_substance.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None

    def test_activate_deactivate(self, economic_substance):
        assert economic_substance.activate("admin") is economic_substance
        assert economic_substance.deactivate("admin") is economic_substance

    def test_lock_unlock(self, economic_substance):
        assert economic_substance.lock("admin", "test") is economic_substance
        assert economic_substance.unlock("admin") is economic_substance

    def test_validate(self, economic_substance):
        result = economic_substance.validate()
        assert result["is_valid"]
        object.__setattr__(economic_substance, "cryptographic_hash", "fake")
        result2 = economic_substance.validate()
        assert not result2["is_valid"]

    def test_to_dict(self, economic_substance):
        d = economic_substance.to_dict()
        assert d["transaction_type"] == "LEASE"

    def test_from_dict(self, economic_substance):
        d = economic_substance.to_dict()
        reconstructed = EconomicSubstance.from_dict(d)
        assert reconstructed.transaction_type == economic_substance.transaction_type

    def test_clone(self, economic_substance):
        cloned = economic_substance.clone()
        assert cloned is not economic_substance
        assert cloned.transaction_type == economic_substance.transaction_type
        assert cloned.version == 1


# ============================================================================
# TESTS UNTUK SubstanceOverFormAssessment
# ============================================================================

class TestSubstanceOverFormAssessment:
    def test_create_valid(self, assessment):
        assert assessment.is_different is False
        assert assessment.requires_adjustment() is False
        assert assessment.version == 1
        assert assessment.cryptographic_hash != ""

    def test_requires_adjustment(self):
        diff_assessment = create_test_assessment(is_different=True)
        assert diff_assessment.requires_adjustment() is True

    def test_update(self, assessment):
        updated = assessment.update("admin", proper_accounting_treatment="New treatment")
        assert updated.proper_accounting_treatment == "New treatment"
        assert updated.version == assessment.version + 1

    def test_delete(self, assessment):
        deleted = assessment.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"

    def test_restore(self, assessment):
        deleted = assessment.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None

    def test_activate_deactivate(self, assessment):
        assert assessment.activate("admin") is assessment
        assert assessment.deactivate("admin") is assessment

    def test_lock_unlock(self, assessment):
        assert assessment.lock("admin", "test") is assessment
        assert assessment.unlock("admin") is assessment

    def test_validate(self, assessment):
        result = assessment.validate()
        assert result["is_valid"]
        object.__setattr__(assessment, "cryptographic_hash", "fake")
        result2 = assessment.validate()
        assert not result2["is_valid"]

    def test_to_dict(self, assessment):
        d = assessment.to_dict()
        assert str(assessment.assessment_id) in d["assessment_id"]

    def test_from_dict(self, assessment):
        d = assessment.to_dict()
        reconstructed = SubstanceOverFormAssessment.from_dict(d)
        assert reconstructed.assessment_id == assessment.assessment_id


# ============================================================================
# TESTS UNTUK SubstanceViolation
# ============================================================================

class TestSubstanceViolation:
    def test_create_valid(self, violation):
        assert violation.severity == SubstanceAssessmentSeverity.MEDIUM
        assert violation.resolved is False
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_immutability(self, violation):
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")
        with pytest.raises(AttributeError):
            violation.delete("admin")
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_deactivate(self, violation):
        assert violation.activate("admin") is violation
        assert violation.deactivate("admin") is violation

    def test_lock_unlock(self, violation):
        assert violation.lock("admin", "test") is violation
        assert violation.unlock("admin") is violation

    def test_resolve(self, violation):
        journal_id = uuid.uuid4()
        resolved = violation.resolve("admin", journal_id)
        assert resolved.resolved is True
        assert resolved.resolved_at == FIXED_NOW
        assert resolved.resolved_by == "admin"
        assert resolved.correction_journal_id == journal_id
        assert resolved.version == violation.version + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation(resolved=True)
        with pytest.raises(ValueError, match="Already resolved"):
            violation.resolve("admin", uuid.uuid4())

    def test_to_dict(self, violation):
        d = violation.to_dict()
        assert d["severity"] == "MEDIUM"
        assert d["resolved"] is False

    def test_from_dict(self, violation):
        d = violation.to_dict()
        reconstructed = SubstanceViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id

    def test_clone(self, violation):
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.resolved is False
        assert cloned.version == 1


# ============================================================================
# ENTITY BASIC METHODS (PARAMETRIZE UNTUK HILANGKAN DUPLIKAT)
# ============================================================================

class TestEntityBasicMethods:
    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_create(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.create("admin")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_touch(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        touched = entity.touch("toucher")
        if cls_name == "SubstanceViolation":
            # Violation.touch returns self (no new instance)
            assert touched is entity
        else:
            # Others return new instance with version+1
            assert touched is not entity
            assert touched.version == entity.version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_validate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.validate()
        assert result["is_valid"]

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_to_dict(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        d = entity.to_dict()
        assert "version" in d

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_clone(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        cloned = entity.clone()
        assert cloned is not entity
        assert cloned.version == 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_snapshot(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        snap = entity.snapshot()
        assert "version" in snap
        assert "timestamp" in snap

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_audit_trail(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        trail = entity.audit_trail()
        assert len(trail) >= 1
        entity.touch("toucher")
        trail2 = entity.audit_trail()
        assert len(trail2) >= len(trail) + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_lock_unlock(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        locked = entity.lock("admin", "test")
        assert locked is entity
        unlocked = locked.unlock("admin")
        assert unlocked is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_update(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not upd:
            with pytest.raises(AttributeError):
                entity.update("admin", some_field="value")
        else:
            if cls_name == "LegalForm":
                updated = entity.update("admin", legal_amount=Decimal("999"))
                assert updated.legal_amount == Decimal("999")
                assert updated.version == entity.version + 1
            elif cls_name == "EconomicSubstance":
                updated = entity.update("admin", economic_amount=Decimal("999"))
                assert updated.economic_amount == Decimal("999")
                assert updated.version == entity.version + 1
            elif cls_name == "SubstanceOverFormAssessment":
                updated = entity.update("admin", proper_accounting_treatment="New")
                assert updated.proper_accounting_treatment == "New"
                assert updated.version == entity.version + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_delete_restore(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not del_:
            with pytest.raises(AttributeError):
                entity.delete("admin")
            return
        if not res:
            # For violation, delete is not supported anyway
            if cls_name == "SubstanceViolation":
                with pytest.raises(AttributeError):
                    entity.restore("admin")
            return
        deleted = entity.delete("admin", "reason")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None


# ============================================================================
# TESTS UNTUK SubstanceOverFormValidator
# ============================================================================

class TestSubstanceOverFormValidator:
    def test_validate_lease_finance_lease(self):
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 36, "is_low_value": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Lessee",
        )
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal, economic, uuid.uuid4()
        )
        assert is_valid
        assert violation is None

    def test_validate_lease_operating_lease_misclassification(self):
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 36, "is_low_value": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
                legal, economic, uuid.uuid4()
            )
        assert not is_valid
        assert violation is not None
        assert violation.severity == SubstanceAssessmentSeverity.HIGH
        assert "finance lease" in violation.message

    def test_validate_lease_short_term_passes(self):
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 6, "is_low_value": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
        )
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal, economic, uuid.uuid4()
        )
        assert is_valid
        assert violation is None

    def test_validate_lease_low_value_passes(self):
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 24, "is_low_value": True},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
        )
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal, economic, uuid.uuid4()
        )
        assert is_valid
        assert violation is None

    @pytest.mark.parametrize("recourse,expected_valid", [
        (True, False),   # with recourse and legal transfer -> misclassification
        (False, True),   # without recourse -> sale
    ])
    def test_validate_factoring_parametrized(self, recourse, expected_valid):
        legal = create_test_legal_form(
            contract_type="Factoring",
            legal_ownership_transfer=True,
            contract_terms={"recourse": recourse},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.FACTORING,
            risks_and_rewards_transferred=not recourse,
            control_transferred=not recourse,
            effective_ownership="Factor" if not recourse else "Originator",
        )
        is_valid, violation = SubstanceOverFormValidator.validate_factoring(
            legal, economic, uuid.uuid4()
        )
        assert is_valid == expected_valid
        if not expected_valid:
            assert violation is not None

    def test_validate_consignment_passes(self):
        legal = create_test_legal_form(
            contract_type="Consignment",
            legal_ownership_transfer=False,
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.CONSIGNMENT,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="consignor",
        )
        is_valid, violation = SubstanceOverFormValidator.validate_consignment(
            legal, economic, uuid.uuid4()
        )
        assert is_valid
        assert violation is None

    def test_validate_consignment_fails(self):
        legal = create_test_legal_form(
            contract_type="Consignment",
            legal_ownership_transfer=False,
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.CONSIGNMENT,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="consignee",
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            is_valid, violation = SubstanceOverFormValidator.validate_consignment(
                legal, economic, uuid.uuid4()
            )
        assert not is_valid
        assert violation is not None
        assert violation.severity == SubstanceAssessmentSeverity.MEDIUM

    def test_validate_related_party_passes(self):
        legal = create_test_legal_form(
            contract_type="Sale",
            legal_amount=Decimal("100000"),
            parties=["Parent", "Subsidiary"],
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            economic_amount=Decimal("102000"),  # 2% diff, within 5% tolerance
        )
        is_valid, violation = SubstanceOverFormValidator.validate_related_party(
            legal, economic, uuid.uuid4(), tolerance_percent=Decimal("5")
        )
        assert is_valid
        assert violation is None

    def test_validate_related_party_fails(self):
        legal = create_test_legal_form(
            contract_type="Sale",
            legal_amount=Decimal("100000"),
            parties=["Parent", "Subsidiary"],
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            economic_amount=Decimal("150000"),  # 50% diff
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            is_valid, violation = SubstanceOverFormValidator.validate_related_party(
                legal, economic, uuid.uuid4(), tolerance_percent=Decimal("5")
            )
        assert not is_valid
        assert violation is not None
        assert violation.severity == SubstanceAssessmentSeverity.HIGH
        assert "fair value" in violation.message

    def test_validate_related_party_exact_tolerance(self):
        legal = create_test_legal_form(
            contract_type="Sale",
            legal_amount=Decimal("100000"),
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            economic_amount=Decimal("105000"),  # 5% diff, exactly tolerance
        )
        is_valid, violation = SubstanceOverFormValidator.validate_related_party(
            legal, economic, uuid.uuid4(), tolerance_percent=Decimal("5")
        )
        # At exact tolerance, it should pass (we use > not >=)
        assert is_valid
        assert violation is None


# ============================================================================
# TESTS UNTUK SubstanceOverFormAxiom
# ============================================================================

class TestSubstanceOverFormAxiom:
    def test_singleton(self):
        axiom1 = SubstanceOverFormAxiom()
        axiom2 = SubstanceOverFormAxiom()
        assert axiom1 is axiom2

    def test_assess_transaction(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(legal_amount=Decimal("100"))
        economic = create_test_economic_substance(economic_amount=Decimal("150"))
        assessment = axiom.assess_transaction(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            assessed_by="admin",
            approved_by=["approver1"],
        )
        assert assessment.is_different
        assessments = axiom.get_assessments()
        assert len(assessments) >= 1

    def test_enforce_lease_passes(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 6, "is_low_value": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
        )
        is_valid, violation = axiom.enforce_lease(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            raise_on_violation=False,
        )
        assert is_valid
        assert violation is None

    def test_enforce_lease_fails(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Lease",
            contract_terms={"lease_term_months": 36, "is_low_value": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Lessor",
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            with pytest.raises(SubstanceViolationError):
                axiom.enforce_lease(
                    transaction_id=uuid.uuid4(),
                    legal_form=legal,
                    economic_substance=economic,
                    raise_on_violation=True,
                )

    def test_enforce_factoring_passes(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Factoring",
            legal_ownership_transfer=True,
            contract_terms={"recourse": False},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.FACTORING,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Factor",
        )
        is_valid, violation = axiom.enforce_factoring(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            raise_on_violation=False,
        )
        assert is_valid

    def test_enforce_factoring_fails(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Factoring",
            legal_ownership_transfer=True,
            contract_terms={"recourse": True},
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.FACTORING,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="Originator",
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            with pytest.raises(SubstanceViolationError):
                axiom.enforce_factoring(
                    transaction_id=uuid.uuid4(),
                    legal_form=legal,
                    economic_substance=economic,
                    raise_on_violation=True,
                )

    def test_enforce_consignment_passes(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Consignment",
            legal_ownership_transfer=False,
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.CONSIGNMENT,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="consignor",
        )
        is_valid, violation = axiom.enforce_consignment(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            raise_on_violation=False,
        )
        assert is_valid

    def test_enforce_consignment_fails(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Consignment",
            legal_ownership_transfer=False,
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.CONSIGNMENT,
            risks_and_rewards_transferred=False,
            control_transferred=False,
            effective_ownership="consignee",
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            with pytest.raises(SubstanceViolationError):
                axiom.enforce_consignment(
                    transaction_id=uuid.uuid4(),
                    legal_form=legal,
                    economic_substance=economic,
                    raise_on_violation=True,
                )

    def test_enforce_related_party_passes(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Sale",
            legal_amount=Decimal("100000"),
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            economic_amount=Decimal("102000"),
        )
        is_valid, violation = axiom.enforce_related_party(
            transaction_id=uuid.uuid4(),
            legal_form=legal,
            economic_substance=economic,
            raise_on_violation=False,
        )
        assert is_valid

    def test_enforce_related_party_fails(self):
        axiom = SubstanceOverFormAxiom()
        legal = create_test_legal_form(
            contract_type="Sale",
            legal_amount=Decimal("100000"),
        )
        economic = create_test_economic_substance(
            transaction_type=SubstanceOverrideType.RELATED_PARTY,
            economic_amount=Decimal("150000"),
        )
        with patch("axioms.substance_over_form.SubstanceOverFormValidator._notify_constitution"):
            with pytest.raises(SubstanceViolationError):
                axiom.enforce_related_party(
                    transaction_id=uuid.uuid4(),
                    legal_form=legal,
                    economic_substance=economic,
                    raise_on_violation=True,
                )

    def test_save_violation_and_get_violations(self):
        axiom = SubstanceOverFormAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_unresolved_only(self):
        axiom = SubstanceOverFormAxiom()
        v1 = create_test_violation(resolved=False)
        v2 = create_test_violation(resolved=True)
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        unresolved = axiom.get_violations(unresolved_only=True)
        assert all(not v.resolved for v in unresolved)

    def test_resolve_violation(self):
        axiom = SubstanceOverFormAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        journal_id = uuid.uuid4()
        resolved = axiom.resolve_violation(violation.violation_id, "admin", journal_id)
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"
        assert resolved.correction_journal_id == journal_id

    def test_resolve_violation_already_resolved(self):
        axiom = SubstanceOverFormAxiom()
        violation = create_test_violation(resolved=True)
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin", uuid.uuid4())
        assert resolved is None

    def test_get_statistics(self):
        axiom = SubstanceOverFormAxiom()
        axiom.reset()
        violation = create_test_violation()
        axiom.save_violation(violation)
        stats = axiom.get_statistics()
        assert stats["total_violations"] >= 1
        assert "assessments_with_difference" in stats
        assert "by_severity" in stats

    def test_reset(self):
        axiom = SubstanceOverFormAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        axiom.reset()
        assert len(axiom._violations) == 0
        assert len(axiom._assessments) == 0


# ============================================================================
# TESTS UNTUK HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_legal_form(self):
        form = create_legal_form(
            contract_type="Sale",
            parties=["Seller", "Buyer"],
            legal_ownership_transfer=True,
            legal_amount=Decimal("100000"),
            currency="IDR",
            contract_date=FIXED_NOW,
            governing_law="Indonesia",
            extra_term="value",
        )
        assert form.contract_type == "Sale"
        assert form.contract_terms.get("extra_term") == "value"

    def test_create_economic_substance(self):
        substance = create_economic_substance(
            transaction_type=SubstanceOverrideType.LEASE,
            risks_and_rewards_transferred=True,
            control_transferred=True,
            effective_ownership="Lessee",
            economic_amount=Decimal("100000"),
            economic_currency="IDR",
            effective_date=FIXED_NOW,
            reasoning="Test",
            supporting_evidence=["doc1.pdf"],
        )
        assert substance.transaction_type == SubstanceOverrideType.LEASE
        assert len(substance.supporting_evidence) == 1

    def test_get_substance_type_from_string(self):
        assert get_substance_type_from_string("LEASE") == SubstanceOverrideType.LEASE
        assert get_substance_type_from_string("FACTORING") == SubstanceOverrideType.FACTORING
        assert get_substance_type_from_string("unknown") == SubstanceOverrideType.LEASE

    def test_get_substance_over_form_axiom_singleton(self):
        axiom1 = get_substance_over_form_axiom()
        axiom2 = get_substance_over_form_axiom()
        assert axiom1 is axiom2