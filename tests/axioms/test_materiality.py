#!/usr/bin/env python3
"""
tests/unit/test_materiality.py
Test untuk axioms/materiality.py
Mencakup: MaterialityThreshold, MaterialityJudgment, MaterialityViolation,
MaterialityValidator, MaterialityAxiom, helper functions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from axioms.materiality import (
    MaterialityAxiom,
    MaterialityDimension,
    MaterialityJudgment,
    MaterialitySeverity,
    MaterialityThreshold,
    MaterialityThresholdType,
    MaterialityValidator,
    MaterialityViolation,
    MaterialityViolationError,
    QualitativeMaterialityFactor,
    calculate_materiality_threshold,
    create_qualitative_factor_from_string,
    get_materiality_axiom,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_threshold(
    legal_entity_id: UUID | None = None,
    fiscal_year: int = 2026,
    threshold_type: MaterialityThresholdType = MaterialityThresholdType.ABSOLUTE,
    value: Decimal = Decimal("1000000"),
) -> MaterialityThreshold:
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    return MaterialityThreshold(
        threshold_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=fiscal_year,
        threshold_type=threshold_type,
        value=value,
        reference_value=Decimal("10000000") if threshold_type != MaterialityThresholdType.ABSOLUTE else None,
        percentage=Decimal("5") if threshold_type != MaterialityThresholdType.ABSOLUTE else None,
        description="Test threshold",
        approved_by=["approver1", "approver2"],
    )


def create_test_judgment(
    legal_entity_id: UUID | None = None,
    fiscal_year: int = 2026,
    is_material: bool = True,
) -> MaterialityJudgment:
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    return MaterialityJudgment(
        judgment_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        fiscal_year=fiscal_year,
        item_description="Test item",
        item_amount=Decimal("5000000"),
        threshold_applied=Decimal("1000000"),
        is_material=is_material,
        qualitative_factors=["FRAUD_OR_ILLEGAL_ACT"],
        justification="Test justification",
        decided_by="admin",
        decided_at=datetime.now(UTC),
        approved_by=["approver1", "approver2"],
        referenced_standard="PSAK 1 / IFRS",
    )


def create_test_violation() -> MaterialityViolation:
    return MaterialityViolation(
        violation_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        fiscal_year=2026,
        item_amount=Decimal("5000000"),
        threshold_that_should_apply=Decimal("1000000"),
        failure_type="NON_DISCLOSURE",
        severity=MaterialitySeverity.HIGH,
        message="Test violation",
        detected_at=datetime.now(UTC),
        detected_by="tester",
        resolved=False,
        resolved_at=None,
        resolved_by=None,
        corrective_action=None,
    )


# ============================================================================
# TESTS FOR MaterialityThreshold
# ============================================================================

class TestMaterialityThreshold:
    def test_create_valid_threshold(self):
        threshold = create_test_threshold()
        assert threshold.threshold_id is not None
        assert threshold.legal_entity_id is not None
        assert threshold.fiscal_year == 2026
        assert threshold.threshold_type == MaterialityThresholdType.ABSOLUTE
        assert threshold.value == Decimal("1000000")
        assert threshold.version == 1
        assert threshold.cryptographic_hash != ""

    def test_validate_value_positive(self):
        with pytest.raises(ValueError, match="Threshold value must be positive"):
            MaterialityThreshold(
                threshold_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                fiscal_year=2026,
                threshold_type=MaterialityThresholdType.ABSOLUTE,
                value=Decimal("-100"),
            )

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            MaterialityThreshold(
                threshold_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                fiscal_year=2026,
                threshold_type=MaterialityThresholdType.ABSOLUTE,
                value=Decimal("100"),
                version=0,
            )

    def test_compute_hash_consistent(self):
        t1 = create_test_threshold()
        t2 = MaterialityThreshold(
            threshold_id=t1.threshold_id,
            legal_entity_id=t1.legal_entity_id,
            fiscal_year=t1.fiscal_year,
            threshold_type=t1.threshold_type,
            value=t1.value,
            reference_value=t1.reference_value,
            percentage=t1.percentage,
            description=t1.description,
            approved_by=t1.approved_by.copy(),
            effective_date=t1.effective_date,
        )
        assert t1.compute_hash() == t2.compute_hash()

    def test_update_creates_new_version(self):
        threshold = create_test_threshold()
        updated = threshold.update("admin", description="Updated description")
        assert updated.description == "Updated description"
        assert updated.version == threshold.version + 1

    def test_update_does_not_change_id(self):
        threshold = create_test_threshold()
        updated = threshold.update("admin", value=Decimal("2000000"))
        assert updated.threshold_id == threshold.threshold_id
        assert updated.legal_entity_id == threshold.legal_entity_id
        assert updated.fiscal_year == threshold.fiscal_year

    def test_delete_marks_deleted(self):
        threshold = create_test_threshold()
        deleted = threshold.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == threshold.version + 1

    def test_restore_recovers_deleted(self):
        threshold = create_test_threshold()
        deleted = threshold.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        threshold = create_test_threshold()
        with pytest.raises(ValueError, match="Not deleted"):
            threshold.restore("admin")

    def test_activate_returns_self(self):
        threshold = create_test_threshold()
        activated = threshold.activate("admin")
        assert activated is threshold

    def test_deactivate_returns_self(self):
        threshold = create_test_threshold()
        deactivated = threshold.deactivate("admin")
        assert deactivated is threshold

    def test_lock_returns_self(self):
        threshold = create_test_threshold()
        locked = threshold.lock("admin", "test")
        assert locked is threshold

    def test_unlock_returns_self(self):
        threshold = create_test_threshold()
        unlocked = threshold.unlock("admin")
        assert unlocked is threshold

    def test_validate_returns_valid(self):
        threshold = create_test_threshold()
        result = threshold.validate()
        assert result["is_valid"] is True
        assert result["threshold_id"] == str(threshold.threshold_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        threshold = create_test_threshold()
        object.__setattr__(threshold, "cryptographic_hash", "fake")
        result = threshold.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        threshold = create_test_threshold()
        d = threshold.to_dict()
        assert d["threshold_type"] == "ABSOLUTE"
        assert d["value"] == "1000000"
        assert d["fiscal_year"] == 2026
        assert "threshold_id" in d

    def test_from_dict_reconstructs(self):
        threshold = create_test_threshold()
        d = threshold.to_dict()
        reconstructed = MaterialityThreshold.from_dict(d)
        assert reconstructed.threshold_id == threshold.threshold_id
        assert reconstructed.legal_entity_id == threshold.legal_entity_id
        assert reconstructed.fiscal_year == threshold.fiscal_year
        assert reconstructed.threshold_type == threshold.threshold_type
        assert reconstructed.value == threshold.value

    def test_clone_creates_new_instance(self):
        threshold = create_test_threshold()
        cloned = threshold.clone()
        assert cloned.threshold_id != threshold.threshold_id
        assert cloned.legal_entity_id == threshold.legal_entity_id
        assert cloned.fiscal_year == threshold.fiscal_year
        assert cloned.threshold_type == threshold.threshold_type
        assert cloned.value == threshold.value
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        threshold = create_test_threshold()
        snap = threshold.snapshot()
        assert snap["threshold_id"] == str(threshold.threshold_id)
        assert snap["value"] == str(threshold.value)
        assert "timestamp" in snap

    def test_get_version(self):
        threshold = create_test_threshold()
        assert threshold.get_version() == 1

    def test_audit_trail_records_actions(self):
        threshold = create_test_threshold()
        assert len(threshold.audit_trail()) >= 1
        threshold.touch("toucher")
        trail = threshold.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        threshold = create_test_threshold()
        touched = threshold.touch("toucher")
        assert touched.version == threshold.version + 1

    def test_get_absolute_threshold_for_absolute_type(self):
        threshold = create_test_threshold(threshold_type=MaterialityThresholdType.ABSOLUTE, value=Decimal("500000"))
        assert threshold.get_absolute_threshold() == Decimal("500000")

    def test_get_absolute_threshold_for_percentage_type(self):
        threshold = create_test_threshold(
            threshold_type=MaterialityThresholdType.PERCENTAGE_OF_PROFIT,
            value=Decimal("500000"),
            reference_value=Decimal("10000000"),
            percentage=Decimal("5"),
        )
        expected = Decimal("10000000") * Decimal("5") / Decimal("100")  # 500000
        assert threshold.get_absolute_threshold() == expected

    def test_is_material_absolute(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        assert threshold.is_material(Decimal("2000000")) is True
        assert threshold.is_material(Decimal("500000")) is False

    def test_is_material_handles_negative(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        assert threshold.is_material(Decimal("-2000000")) is True
        assert threshold.is_material(Decimal("-500000")) is False


# ============================================================================
# TESTS FOR MaterialityJudgment
# ============================================================================

class TestMaterialityJudgment:
    def test_create_valid_judgment(self):
        judgment = create_test_judgment()
        assert judgment.judgment_id is not None
        assert judgment.legal_entity_id is not None
        assert judgment.fiscal_year == 2026
        assert judgment.item_amount == Decimal("5000000")
        assert judgment.is_material is True
        assert judgment.version == 1
        assert judgment.cryptographic_hash != ""

    def test_update_raises(self):
        judgment = create_test_judgment()
        with pytest.raises(AttributeError):
            judgment.update("admin", justification="new")

    def test_delete_marks_deleted(self):
        judgment = create_test_judgment()
        deleted = judgment.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == judgment.version + 1

    def test_restore_recovers_deleted(self):
        judgment = create_test_judgment()
        deleted = judgment.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        judgment = create_test_judgment()
        with pytest.raises(ValueError, match="Not deleted"):
            judgment.restore("admin")

    def test_activate_returns_self(self):
        judgment = create_test_judgment()
        activated = judgment.activate("admin")
        assert activated is judgment

    def test_deactivate_returns_self(self):
        judgment = create_test_judgment()
        deactivated = judgment.deactivate("admin")
        assert deactivated is judgment

    def test_lock_returns_self(self):
        judgment = create_test_judgment()
        locked = judgment.lock("admin", "test")
        assert locked is judgment

    def test_unlock_returns_self(self):
        judgment = create_test_judgment()
        unlocked = judgment.unlock("admin")
        assert unlocked is judgment

    def test_validate_returns_valid(self):
        judgment = create_test_judgment()
        result = judgment.validate()
        assert result["is_valid"] is True
        assert result["judgment_id"] == str(judgment.judgment_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        judgment = create_test_judgment()
        object.__setattr__(judgment, "cryptographic_hash", "fake")
        result = judgment.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        judgment = create_test_judgment()
        d = judgment.to_dict()
        assert d["item_description"] == "Test item"
        assert d["item_amount"] == "5000000"
        assert d["is_material"] is True
        assert d["justification"] == "Test justification"
        assert "judgment_id" in d

    def test_from_dict_reconstructs(self):
        judgment = create_test_judgment()
        d = judgment.to_dict()
        reconstructed = MaterialityJudgment.from_dict(d)
        assert reconstructed.judgment_id == judgment.judgment_id
        assert reconstructed.legal_entity_id == judgment.legal_entity_id
        assert reconstructed.fiscal_year == judgment.fiscal_year
        assert reconstructed.item_amount == judgment.item_amount
        assert reconstructed.is_material == judgment.is_material

    def test_clone_creates_new_instance(self):
        judgment = create_test_judgment()
        cloned = judgment.clone()
        assert cloned.judgment_id != judgment.judgment_id
        assert cloned.legal_entity_id == judgment.legal_entity_id
        assert cloned.fiscal_year == judgment.fiscal_year
        assert cloned.item_amount == judgment.item_amount
        assert cloned.is_material == judgment.is_material
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        judgment = create_test_judgment()
        snap = judgment.snapshot()
        assert snap["judgment_id"] == str(judgment.judgment_id)
        assert snap["is_material"] == judgment.is_material

    def test_get_version(self):
        judgment = create_test_judgment()
        assert judgment.get_version() == 1

    def test_audit_trail_records(self):
        judgment = create_test_judgment()
        assert len(judgment.audit_trail()) >= 1
        judgment.touch("toucher")
        trail = judgment.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR MaterialityViolation
# ============================================================================

class TestMaterialityViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.legal_entity_id is not None
        assert violation.fiscal_year == 2026
        assert violation.item_amount == Decimal("5000000")
        assert violation.severity == MaterialitySeverity.HIGH
        assert violation.resolved is False
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"] is True

    def test_validate_returns_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_update_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")

    def test_delete_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.delete("admin")

    def test_restore_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_returns_self(self):
        violation = create_test_violation()
        activated = violation.activate("admin")
        assert activated is violation

    def test_deactivate_returns_self(self):
        violation = create_test_violation()
        deactivated = violation.deactivate("admin")
        assert deactivated is violation

    def test_lock_returns_self(self):
        violation = create_test_violation()
        locked = violation.lock("admin", "test")
        assert locked is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["severity"] == "HIGH"
        assert d["failure_type"] == "NON_DISCLOSURE"
        assert d["item_amount"] == "5000000"
        assert d["resolved"] is False
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = MaterialityViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.legal_entity_id == violation.legal_entity_id
        assert reconstructed.fiscal_year == violation.fiscal_year
        assert reconstructed.item_amount == violation.item_amount
        assert reconstructed.severity == violation.severity

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.legal_entity_id == violation.legal_entity_id
        assert cloned.fiscal_year == violation.fiscal_year
        assert cloned.item_amount == violation.item_amount
        assert cloned.resolved is False
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["severity"] == violation.severity.name

    def test_get_version(self):
        violation = create_test_violation()
        assert violation.get_version() == 1

    def test_audit_trail_records(self):
        violation = create_test_violation()
        assert len(violation.audit_trail()) >= 1
        violation.touch("toucher")
        trail = violation.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Corrected disclosure")
        assert resolved.resolved is True
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.corrective_action == "Corrected disclosure"
        assert resolved.version == violation.version + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")


# ============================================================================
# TESTS FOR MaterialityValidator
# ============================================================================

class TestMaterialityValidator:
    def test_validate_disclosure_material_disclosed(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        legal_entity_id = uuid.uuid4()
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            item_amount=Decimal("5000000"),
            item_description="Test item",
            threshold=threshold,
            qualitative_factors=[],
            was_disclosed_separately=True,
        )
        assert is_valid is True
        assert violation is None

    def test_validate_disclosure_quantitatively_material_not_disclosed(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        legal_entity_id = uuid.uuid4()
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            is_valid, violation = MaterialityValidator.validate_disclosure(
                legal_entity_id=legal_entity_id,
                fiscal_year=2026,
                item_amount=Decimal("5000000"),
                item_description="Test item",
                threshold=threshold,
                qualitative_factors=[],
                was_disclosed_separately=False,
            )
        assert is_valid is False
        assert violation is not None
        assert violation.failure_type == "NON_DISCLOSURE"
        assert violation.severity == MaterialitySeverity.CRITICAL

    def test_validate_disclosure_qualitatively_material_not_disclosed(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        legal_entity_id = uuid.uuid4()
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            is_valid, violation = MaterialityValidator.validate_disclosure(
                legal_entity_id=legal_entity_id,
                fiscal_year=2026,
                item_amount=Decimal("100000"),
                item_description="Test item",
                threshold=threshold,
                qualitative_factors=[QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT],
                was_disclosed_separately=False,
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == MaterialitySeverity.CATASTROPHIC

    def test_validate_disclosure_material_with_qualitative_disclosed(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        legal_entity_id = uuid.uuid4()
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            item_amount=Decimal("100000"),
            item_description="Test item",
            threshold=threshold,
            qualitative_factors=[QualitativeMaterialityFactor.RELATED_PARTY],
            was_disclosed_separately=True,
        )
        assert is_valid is True
        assert violation is None

    def test_validate_disclosure_under_threshold_no_factors(self):
        threshold = create_test_threshold(value=Decimal("1000000"))
        legal_entity_id = uuid.uuid4()
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            item_amount=Decimal("100000"),
            item_description="Test item",
            threshold=threshold,
            qualitative_factors=[],
            was_disclosed_separately=False,
        )
        assert is_valid is True
        assert violation is None

    def test_determine_severity_catastrophic(self):
        severity = MaterialityValidator._determine_severity(
            amount=Decimal("100000"),
            threshold=Decimal("1000000"),
            qualitative_factors=[QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT],
        )
        assert severity == MaterialitySeverity.CATASTROPHIC

    def test_determine_severity_critical(self):
        severity = MaterialityValidator._determine_severity(
            amount=Decimal("3000000"),
            threshold=Decimal("1000000"),
            qualitative_factors=[],
        )
        assert severity == MaterialitySeverity.CRITICAL

    def test_determine_severity_high(self):
        severity = MaterialityValidator._determine_severity(
            amount=Decimal("1500000"),
            threshold=Decimal("1000000"),
            qualitative_factors=[QualitativeMaterialityFactor.PUBLIC_PERCEPTION],
        )
        assert severity == MaterialitySeverity.HIGH

    def test_determine_severity_medium(self):
        severity = MaterialityValidator._determine_severity(
            amount=Decimal("100000"),
            threshold=Decimal("1000000"),
            qualitative_factors=[],
        )
        assert severity == MaterialitySeverity.MEDIUM


# ============================================================================
# TESTS FOR MaterialityAxiom
# ============================================================================

class TestMaterialityAxiom:
    def test_singleton(self):
        axiom1 = MaterialityAxiom()
        axiom2 = MaterialityAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_threshold(self):
        axiom = MaterialityAxiom()
        threshold = create_test_threshold()
        axiom.save_threshold(threshold)
        retrieved = axiom.get_threshold(threshold.legal_entity_id, threshold.fiscal_year)
        assert retrieved is not None
        assert retrieved.threshold_id == threshold.threshold_id

    def test_get_all_thresholds(self):
        axiom = MaterialityAxiom()
        t1 = create_test_threshold(legal_entity_id=uuid.uuid4())
        t2 = create_test_threshold(legal_entity_id=uuid.uuid4())
        axiom.save_threshold(t1)
        axiom.save_threshold(t2)
        thresholds = axiom.get_all_thresholds()
        assert len(thresholds) >= 2

    def test_delete_threshold(self):
        axiom = MaterialityAxiom()
        threshold = create_test_threshold()
        axiom.save_threshold(threshold)
        result = axiom.delete_threshold(threshold.legal_entity_id, threshold.fiscal_year)
        assert result is True
        assert axiom.get_threshold(threshold.legal_entity_id, threshold.fiscal_year) is None

    def test_save_and_get_judgments(self):
        axiom = MaterialityAxiom()
        judgment = create_test_judgment()
        axiom.save_judgment(judgment)
        judgments = axiom.get_judgments()
        assert len(judgments) >= 1
        found = next((j for j in judgments if j.judgment_id == judgment.judgment_id), None)
        assert found is not None

    def test_get_judgments_filter_by_entity(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        j1 = create_test_judgment(legal_entity_id=entity_id)
        j2 = create_test_judgment(legal_entity_id=entity_id)
        j3 = create_test_judgment(legal_entity_id=uuid.uuid4())
        axiom.save_judgment(j1)
        axiom.save_judgment(j2)
        axiom.save_judgment(j3)
        results = axiom.get_judgments(legal_entity_id=entity_id)
        assert len(results) == 2

    def test_get_judgments_filter_by_fiscal_year(self):
        axiom = MaterialityAxiom()
        j1 = create_test_judgment(fiscal_year=2026)
        j2 = create_test_judgment(fiscal_year=2026)
        j3 = create_test_judgment(fiscal_year=2025)
        axiom.save_judgment(j1)
        axiom.save_judgment(j2)
        axiom.save_judgment(j3)
        results = axiom.get_judgments(fiscal_year=2026)
        assert len(results) == 2

    def test_delete_judgment(self):
        axiom = MaterialityAxiom()
        judgment = create_test_judgment()
        axiom.save_judgment(judgment)
        result = axiom.delete_judgment(judgment.judgment_id)
        assert result is True
        judgments = axiom.get_judgments()
        assert all(j.judgment_id != judgment.judgment_id for j in judgments)

    def test_save_and_get_violations(self):
        axiom = MaterialityAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_entity(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        v1 = create_test_violation()
        v1.legal_entity_id = entity_id
        v2 = create_test_violation()
        v2.legal_entity_id = entity_id
        v3 = create_test_violation()
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        axiom.save_violation(v3)
        results = axiom.get_violations(legal_entity_id=entity_id)
        assert len(results) == 2

    def test_get_violations_unresolved_only(self):
        axiom = MaterialityAxiom()
        v1 = create_test_violation()
        v1.resolved = True
        v2 = create_test_violation()
        v2.resolved = False
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        results = axiom.get_violations(unresolved_only=True)
        assert all(not v.resolved for v in results)

    def test_resolve_violation(self):
        axiom = MaterialityAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin", "Corrected")
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"

    def test_resolve_violation_not_found(self):
        axiom = MaterialityAxiom()
        result = axiom.resolve_violation(uuid.uuid4(), "admin", "Corrected")
        assert result is None

    def test_set_threshold(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        threshold = axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("500000"),
            description="Custom threshold",
            approved_by=["approver"],
        )
        assert threshold is not None
        assert threshold.legal_entity_id == entity_id
        assert threshold.fiscal_year == 2026
        assert threshold.value == Decimal("500000")
        retrieved = axiom.get_threshold(entity_id, 2026)
        assert retrieved is not None

    def test_get_or_create_default_threshold_existing(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        existing = axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        result = axiom.get_or_create_default_threshold(entity_id, 2026, Decimal("10000000"))
        assert result.threshold_id == existing.threshold_id

    def test_get_or_create_default_threshold_new_with_profit(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        result = axiom.get_or_create_default_threshold(entity_id, 2026, Decimal("10000000"))
        assert result is not None
        assert result.threshold_type == MaterialityThresholdType.PERCENTAGE_OF_PROFIT
        assert result.value == Decimal("500000")  # 5% of 10,000,000

    def test_get_or_create_default_threshold_new_without_profit(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        result = axiom.get_or_create_default_threshold(entity_id, 2026)
        assert result is not None
        assert result.threshold_type == MaterialityThresholdType.ABSOLUTE
        assert result.value == Decimal("100000000")

    def test_is_material_quantitative(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        assert axiom.is_material(entity_id, 2026, Decimal("2000000")) is True
        assert axiom.is_material(entity_id, 2026, Decimal("500000")) is False

    def test_is_material_qualitative(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        assert axiom.is_material(
            entity_id,
            2026,
            Decimal("100000"),
            qualitative_factors=[QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT],
        ) is True

    def test_is_material_uses_default_threshold(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        # No threshold set, should use default
        assert axiom.is_material(entity_id, 2026, Decimal("200000000")) is True
        assert axiom.is_material(entity_id, 2026, Decimal("10000000")) is False

    def test_record_judgment(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        judgment = axiom.record_judgment(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_description="Test item",
            item_amount=Decimal("5000000"),
            threshold_applied=Decimal("1000000"),
            is_material=True,
            qualitative_factors=["FRAUD_OR_ILLEGAL_ACT"],
            justification="Test",
            decided_by="admin",
            approved_by=["a", "b"],
        )
        assert judgment is not None
        assert judgment.legal_entity_id == entity_id
        assert judgment.is_material is True
        retrieved = axiom.get_judgments(legal_entity_id=entity_id)
        assert len(retrieved) >= 1

    def test_enforce_disclosure_passes(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        is_valid, violation = axiom.enforce_disclosure(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_amount=Decimal("500000"),
            item_description="Test item",
            was_disclosed_separately=True,
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violation is None

    def test_enforce_disclosure_fails(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            is_valid, violation = axiom.enforce_disclosure(
                legal_entity_id=entity_id,
                fiscal_year=2026,
                item_amount=Decimal("5000000"),
                item_description="Test item",
                was_disclosed_separately=False,
                raise_on_violation=False,
            )
        assert is_valid is False
        assert violation is not None

    def test_enforce_disclosure_raises(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        with pytest.raises(MaterialityViolationError):
            with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
                axiom.enforce_disclosure(
                    legal_entity_id=entity_id,
                    fiscal_year=2026,
                    item_amount=Decimal("5000000"),
                    item_description="Test item",
                    was_disclosed_separately=False,
                    raise_on_violation=True,
                )

    def test_get_statistics(self):
        axiom = MaterialityAxiom()
        threshold = create_test_threshold()
        axiom.save_threshold(threshold)
        judgment = create_test_judgment()
        axiom.save_judgment(judgment)
        violation = create_test_violation()
        axiom.save_violation(violation)
        stats = axiom.get_statistics()
        assert stats["thresholds_defined"] >= 1
        assert stats["judgments_recorded"] >= 1
        assert stats["total_violations"] >= 1
        assert "by_severity" in stats
        assert "by_failure_type" in stats

    def test_reset(self):
        axiom = MaterialityAxiom()
        threshold = create_test_threshold()
        axiom.save_threshold(threshold)
        judgment = create_test_judgment()
        axiom.save_judgment(judgment)
        axiom.reset()
        assert len(axiom._thresholds) == 0
        assert len(axiom._judgments) == 0
        assert len(axiom._violations) == 0


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_qualitative_factor_from_string(self):
        assert create_qualitative_factor_from_string("FRAUD_OR_ILLEGAL_ACT") == QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT
        assert create_qualitative_factor_from_string("REGULATORY_COMPLIANCE") == QualitativeMaterialityFactor.REGULATORY_COMPLIANCE
        assert create_qualitative_factor_from_string("DEBT_COVENANT_VIOLATION") == QualitativeMaterialityFactor.DEBT_COVENANT_VIOLATION
        assert create_qualitative_factor_from_string("TREND_REVERSAL") == QualitativeMaterialityFactor.TREND_REVERSAL
        assert create_qualitative_factor_from_string("SEGMENT_REPORTING") == QualitativeMaterialityFactor.SEGMENT_REPORTING
        assert create_qualitative_factor_from_string("RELATED_PARTY") == QualitativeMaterialityFactor.RELATED_PARTY
        assert create_qualitative_factor_from_string("EXECUTIVE_COMPENSATION") == QualitativeMaterialityFactor.EXECUTIVE_COMPENSATION
        assert create_qualitative_factor_from_string("PUBLIC_PERCEPTION") == QualitativeMaterialityFactor.PUBLIC_PERCEPTION
        assert create_qualitative_factor_from_string("GOING_CONCERN") == QualitativeMaterialityFactor.GOING_CONCERN
        assert create_qualitative_factor_from_string("ROLLOVER_EFFECT") == QualitativeMaterialityFactor.ROLLOVER_EFFECT
        assert create_qualitative_factor_from_string("unknown") == QualitativeMaterialityFactor.PUBLIC_PERCEPTION

    def test_calculate_materiality_threshold_absolute(self):
        result = calculate_materiality_threshold(
            MaterialityThresholdType.ABSOLUTE,
            Decimal("1000000"),
            Decimal("5"),
        )
        assert result == Decimal("1000000")

    def test_calculate_materiality_threshold_percentage(self):
        result = calculate_materiality_threshold(
            MaterialityThresholdType.PERCENTAGE_OF_PROFIT,
            Decimal("10000000"),
            Decimal("5"),
        )
        assert result == Decimal("500000")

    def test_get_materiality_axiom_singleton(self):
        axiom1 = get_materiality_axiom()
        axiom2 = get_materiality_axiom()
        assert axiom1 is axiom2