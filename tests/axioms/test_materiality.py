#!/usr/bin/env python3
"""
tests/axioms/test_materiality.py
Comprehensive tests for axioms/materiality.py

Covers:
- Enums: MaterialityDimension, MaterialityThresholdType, MaterialitySeverity,
  QualitativeMaterialityFactor
- Data classes: MaterialityThreshold, MaterialityJudgment, MaterialityViolation
  (all construction, methods, serialization, audit, clone, etc.)
- MaterialityValidator: validate_disclosure, severity determination
- MaterialityAxiom: singleton, repository methods, business methods,
  get_or_create_default_threshold, is_material, record_judgment,
  enforce_disclosure, statistics, reset
- Helper functions: create_qualitative_factor_from_string,
  calculate_materiality_threshold, get_materiality_axiom
- All edge cases, negative paths, and error conditions
- No flaky datetime (mocked)
- No duplicate test structures (parametrized)
- Full coverage of all methods
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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

# =============================================================================
# Fixtures
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return a fixed value."""
    with patch("axioms.materiality.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.utcnow.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_threshold() -> MaterialityThreshold:
    return MaterialityThreshold(
        threshold_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        fiscal_year=2026,
        threshold_type=MaterialityThresholdType.ABSOLUTE,
        value=Decimal("1000000"),
        reference_value=None,
        percentage=None,
        description="Test threshold",
        approved_by=["approver1", "approver2"],
        effective_date=FIXED_DATETIME,
    )


@pytest.fixture
def sample_judgment() -> MaterialityJudgment:
    return MaterialityJudgment(
        judgment_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        fiscal_year=2026,
        item_description="Test item",
        item_amount=Decimal("5000000"),
        threshold_applied=Decimal("1000000"),
        is_material=True,
        qualitative_factors=["FRAUD_OR_ILLEGAL_ACT"],
        justification="Test justification",
        decided_by="admin",
        decided_at=FIXED_DATETIME,
        approved_by=["approver1", "approver2"],
        referenced_standard="PSAK 1 / IFRS",
    )


@pytest.fixture
def sample_violation() -> MaterialityViolation:
    return MaterialityViolation(
        violation_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        fiscal_year=2026,
        item_amount=Decimal("5000000"),
        threshold_that_should_apply=Decimal("1000000"),
        failure_type="NON_DISCLOSURE",
        severity=MaterialitySeverity.CRITICAL,
        message="Test violation",
        detected_at=FIXED_DATETIME,
        detected_by="tester",
        resolved=False,
        resolved_at=None,
        resolved_by=None,
        corrective_action=None,
    )


# =============================================================================
# Enums
# =============================================================================

class TestEnums:
    def test_materiality_dimension(self):
        assert MaterialityDimension.QUANTITATIVE.name == "QUANTITATIVE"
        assert MaterialityDimension.QUALITATIVE.name == "QUALITATIVE"
        assert MaterialityDimension.BOTH.name == "BOTH"

    def test_materiality_threshold_type(self):
        assert MaterialityThresholdType.ABSOLUTE.name == "ABSOLUTE"
        assert MaterialityThresholdType.PERCENTAGE_OF_ASSETS.name == "PERCENTAGE_OF_ASSETS"
        assert MaterialityThresholdType.PERCENTAGE_OF_EQUITY.name == "PERCENTAGE_OF_EQUITY"
        assert MaterialityThresholdType.PERCENTAGE_OF_REVENUE.name == "PERCENTAGE_OF_REVENUE"
        assert MaterialityThresholdType.PERCENTAGE_OF_PROFIT.name == "PERCENTAGE_OF_PROFIT"
        assert MaterialityThresholdType.CUSTOM.name == "CUSTOM"

    def test_materiality_severity(self):
        assert MaterialitySeverity.CATASTROPHIC.value == 100
        assert MaterialitySeverity.CRITICAL.value == 80
        assert MaterialitySeverity.HIGH.value == 60
        assert MaterialitySeverity.MEDIUM.value == 40
        assert MaterialitySeverity.LOW.value == 20
        assert MaterialitySeverity.INFO.value == 0

    def test_qualitative_materiality_factor(self):
        assert QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT.name == "FRAUD_OR_ILLEGAL_ACT"
        assert QualitativeMaterialityFactor.REGULATORY_COMPLIANCE.name == "REGULATORY_COMPLIANCE"
        assert QualitativeMaterialityFactor.DEBT_COVENANT_VIOLATION.name == "DEBT_COVENANT_VIOLATION"
        assert QualitativeMaterialityFactor.TREND_REVERSAL.name == "TREND_REVERSAL"
        assert QualitativeMaterialityFactor.SEGMENT_REPORTING.name == "SEGMENT_REPORTING"
        assert QualitativeMaterialityFactor.RELATED_PARTY.name == "RELATED_PARTY"
        assert QualitativeMaterialityFactor.EXECUTIVE_COMPENSATION.name == "EXECUTIVE_COMPENSATION"
        assert QualitativeMaterialityFactor.PUBLIC_PERCEPTION.name == "PUBLIC_PERCEPTION"
        assert QualitativeMaterialityFactor.GOING_CONCERN.name == "GOING_CONCERN"
        assert QualitativeMaterialityFactor.ROLLOVER_EFFECT.name == "ROLLOVER_EFFECT"


# =============================================================================
# MaterialityThreshold
# =============================================================================

class TestMaterialityThreshold:
    def test_create_valid(self, sample_threshold):
        assert sample_threshold.threshold_id is not None
        assert sample_threshold.legal_entity_id is not None
        assert sample_threshold.fiscal_year == 2026
        assert sample_threshold.threshold_type == MaterialityThresholdType.ABSOLUTE
        assert sample_threshold.value == Decimal("1000000")
        assert sample_threshold.version == 1
        assert sample_threshold.cryptographic_hash != ""

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

    def test_compute_hash_consistent(self, sample_threshold):
        h1 = sample_threshold.compute_hash()
        h2 = sample_threshold.compute_hash()
        assert h1 == h2

    def test_update(self, sample_threshold):
        updated = sample_threshold.update("admin", description="Updated desc")
        assert updated.description == "Updated desc"
        assert updated.version == sample_threshold.version + 1
        assert updated.threshold_id == sample_threshold.threshold_id

    def test_update_immutable_fields(self, sample_threshold):
        updated = sample_threshold.update("admin", threshold_id=uuid.uuid4(), legal_entity_id=uuid.uuid4())
        assert updated.threshold_id == sample_threshold.threshold_id
        assert updated.legal_entity_id == sample_threshold.legal_entity_id

    def test_delete_restore(self, sample_threshold):
        deleted = sample_threshold.delete("admin", "test")
        assert deleted.deleted_at == FIXED_DATETIME
        assert deleted.deleted_by == "admin"
        assert deleted.version == sample_threshold.version + 1

        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self, sample_threshold):
        with pytest.raises(ValueError, match="Not deleted"):
            sample_threshold.restore("admin")

    @pytest.mark.parametrize("method_name", ["activate", "deactivate", "lock", "unlock", "create"])
    def test_noop_methods_return_self(self, sample_threshold, method_name):
        method = getattr(sample_threshold, method_name)
        if method_name == "deactivate" or method_name in ("lock",):
            result = method("admin", "reason")
        else:
            result = method("admin")
        assert result is sample_threshold

    def test_validate_returns_valid(self, sample_threshold):
        result = sample_threshold.validate()
        assert result["is_valid"] is True
        assert result["threshold_id"] == str(sample_threshold.threshold_id)

    def test_validate_hash_mismatch(self, sample_threshold):
        object.__setattr__(sample_threshold, "cryptographic_hash", "fake")
        result = sample_threshold.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_from_dict(self, sample_threshold):
        d = sample_threshold.to_dict()
        reconstructed = MaterialityThreshold.from_dict(d)
        assert reconstructed.threshold_id == sample_threshold.threshold_id
        assert reconstructed.legal_entity_id == sample_threshold.legal_entity_id
        assert reconstructed.fiscal_year == sample_threshold.fiscal_year
        assert reconstructed.threshold_type == sample_threshold.threshold_type
        assert reconstructed.value == sample_threshold.value

    def test_clone(self, sample_threshold):
        cloned = sample_threshold.clone()
        assert cloned.threshold_id != sample_threshold.threshold_id
        assert cloned.legal_entity_id == sample_threshold.legal_entity_id
        assert cloned.fiscal_year == sample_threshold.fiscal_year
        assert cloned.threshold_type == sample_threshold.threshold_type
        assert cloned.value == sample_threshold.value
        assert cloned.version == 1

    def test_snapshot(self, sample_threshold):
        snap = sample_threshold.snapshot()
        assert snap["threshold_id"] == str(sample_threshold.threshold_id)
        assert snap["value"] == str(sample_threshold.value)
        assert "timestamp" in snap

    def test_version_audit_trail_touch(self, sample_threshold):
        assert sample_threshold.get_version() == 1
        assert len(sample_threshold.audit_trail()) >= 1
        touched = sample_threshold.touch("toucher")
        assert touched.version == sample_threshold.version + 1
        trail = touched.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_get_absolute_threshold(self):
        # Absolute type returns value
        th = MaterialityThreshold(
            threshold_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("500000"),
        )
        assert th.get_absolute_threshold() == Decimal("500000")

        # Percentage type computes correctly
        th2 = MaterialityThreshold(
            threshold_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.PERCENTAGE_OF_PROFIT,
            value=Decimal("500000"),
            reference_value=Decimal("10000000"),
            percentage=Decimal("5"),
        )
        assert th2.get_absolute_threshold() == Decimal("500000")  # 10M * 5% = 500k

    def test_is_material(self):
        th = MaterialityThreshold(
            threshold_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        assert th.is_material(Decimal("2000000")) is True
        assert th.is_material(Decimal("500000")) is False
        # Negative amounts
        assert th.is_material(Decimal("-2000000")) is True
        assert th.is_material(Decimal("-500000")) is False


# =============================================================================
# MaterialityJudgment
# =============================================================================

class TestMaterialityJudgment:
    def test_create_valid(self, sample_judgment):
        assert sample_judgment.judgment_id is not None
        assert sample_judgment.legal_entity_id is not None
        assert sample_judgment.fiscal_year == 2026
        assert sample_judgment.item_amount == Decimal("5000000")
        assert sample_judgment.is_material is True
        assert sample_judgment.version == 1
        assert sample_judgment.cryptographic_hash != ""

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            MaterialityJudgment(
                judgment_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                fiscal_year=2026,
                item_description="Test",
                item_amount=Decimal("1000"),
                threshold_applied=Decimal("100"),
                is_material=True,
                qualitative_factors=[],
                justification="J",
                decided_by="admin",
                decided_at=FIXED_DATETIME,
                approved_by=[],
                referenced_standard="PSAK",
                version=0,
            )

    def test_update_raises(self, sample_judgment):
        with pytest.raises(AttributeError, match="immutable"):
            sample_judgment.update("admin", justification="new")

    def test_delete_restore(self, sample_judgment):
        deleted = sample_judgment.delete("admin", "test")
        assert deleted.deleted_at == FIXED_DATETIME
        assert deleted.deleted_by == "admin"
        assert deleted.version == sample_judgment.version + 1

        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self, sample_judgment):
        with pytest.raises(ValueError, match="Not deleted"):
            sample_judgment.restore("admin")

    @pytest.mark.parametrize("method_name", ["activate", "deactivate", "lock", "unlock", "create"])
    def test_noop_methods_return_self(self, sample_judgment, method_name):
        method = getattr(sample_judgment, method_name)
        if method_name == "deactivate" or method_name in ("lock",):
            result = method("admin", "reason")
        else:
            result = method("admin")
        assert result is sample_judgment

    def test_validate_returns_valid(self, sample_judgment):
        result = sample_judgment.validate()
        assert result["is_valid"] is True
        assert result["judgment_id"] == str(sample_judgment.judgment_id)

    def test_validate_hash_mismatch(self, sample_judgment):
        object.__setattr__(sample_judgment, "cryptographic_hash", "fake")
        result = sample_judgment.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_from_dict(self, sample_judgment):
        d = sample_judgment.to_dict()
        reconstructed = MaterialityJudgment.from_dict(d)
        assert reconstructed.judgment_id == sample_judgment.judgment_id
        assert reconstructed.legal_entity_id == sample_judgment.legal_entity_id
        assert reconstructed.fiscal_year == sample_judgment.fiscal_year
        assert reconstructed.item_amount == sample_judgment.item_amount
        assert reconstructed.is_material == sample_judgment.is_material

    def test_clone(self, sample_judgment):
        cloned = sample_judgment.clone()
        assert cloned.judgment_id != sample_judgment.judgment_id
        assert cloned.legal_entity_id == sample_judgment.legal_entity_id
        assert cloned.fiscal_year == sample_judgment.fiscal_year
        assert cloned.item_amount == sample_judgment.item_amount
        assert cloned.is_material == sample_judgment.is_material
        assert cloned.version == 1

    def test_snapshot_version_audit(self, sample_judgment):
        snap = sample_judgment.snapshot()
        assert snap["judgment_id"] == str(sample_judgment.judgment_id)
        assert snap["is_material"] == sample_judgment.is_material
        assert sample_judgment.get_version() == 1
        assert len(sample_judgment.audit_trail()) >= 1
        sample_judgment.touch("toucher")
        trail = sample_judgment.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# MaterialityViolation
# =============================================================================

class TestMaterialityViolation:
    def test_create_valid(self, sample_violation):
        assert sample_violation.violation_id is not None
        assert sample_violation.legal_entity_id is not None
        assert sample_violation.fiscal_year == 2026
        assert sample_violation.item_amount == Decimal("5000000")
        assert sample_violation.severity == MaterialitySeverity.CRITICAL
        assert sample_violation.resolved is False
        assert sample_violation.version == 1
        assert sample_violation.cryptographic_hash != ""

    def test_validate_version_positive(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            MaterialityViolation(
                violation_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                fiscal_year=2026,
                item_amount=Decimal("1000"),
                threshold_that_should_apply=Decimal("100"),
                failure_type="NON_DISCLOSURE",
                severity=MaterialitySeverity.LOW,
                message="test",
                detected_at=FIXED_DATETIME,
                detected_by="tester",
                resolved=False,
                resolved_at=None,
                resolved_by=None,
                corrective_action=None,
                version=0,
            )

    def test_update_delete_restore_raise(self, sample_violation):
        with pytest.raises(AttributeError, match="immutable"):
            sample_violation.update("admin", message="new")
        with pytest.raises(AttributeError, match="Cannot delete"):
            sample_violation.delete("admin")
        with pytest.raises(AttributeError, match="Cannot restore"):
            sample_violation.restore("admin")

    @pytest.mark.parametrize("method_name", ["activate", "deactivate", "lock", "unlock", "create"])
    def test_noop_methods_return_self(self, sample_violation, method_name):
        method = getattr(sample_violation, method_name)
        if method_name == "deactivate" or method_name in ("lock",):
            result = method("admin", "reason")
        else:
            result = method("admin")
        assert result is sample_violation

    def test_validate_returns_valid(self, sample_violation):
        result = sample_violation.validate()
        assert result["is_valid"] is True
        assert result["violation_id"] == str(sample_violation.violation_id)

    def test_validate_hash_mismatch(self, sample_violation):
        object.__setattr__(sample_violation, "cryptographic_hash", "fake")
        result = sample_violation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_from_dict(self, sample_violation):
        d = sample_violation.to_dict()
        reconstructed = MaterialityViolation.from_dict(d)
        assert reconstructed.violation_id == sample_violation.violation_id
        assert reconstructed.legal_entity_id == sample_violation.legal_entity_id
        assert reconstructed.fiscal_year == sample_violation.fiscal_year
        assert reconstructed.item_amount == sample_violation.item_amount
        assert reconstructed.severity == sample_violation.severity

    def test_clone(self, sample_violation):
        cloned = sample_violation.clone()
        assert cloned.violation_id != sample_violation.violation_id
        assert cloned.legal_entity_id == sample_violation.legal_entity_id
        assert cloned.fiscal_year == sample_violation.fiscal_year
        assert cloned.item_amount == sample_violation.item_amount
        assert cloned.resolved is False
        assert cloned.version == 1

    def test_snapshot_version_audit(self, sample_violation):
        snap = sample_violation.snapshot()
        assert snap["violation_id"] == str(sample_violation.violation_id)
        assert snap["severity"] == sample_violation.severity.name
        assert sample_violation.get_version() == 1
        assert len(sample_violation.audit_trail()) >= 1
        sample_violation.touch("toucher")
        trail = sample_violation.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_resolve(self, sample_violation):
        resolved = sample_violation.resolve("admin", "Corrected disclosure")
        assert resolved.resolved is True
        assert resolved.resolved_at == FIXED_DATETIME
        assert resolved.resolved_by == "admin"
        assert resolved.corrective_action == "Corrected disclosure"
        assert resolved.version == sample_violation.version + 1

    def test_resolve_already_resolved_raises(self, sample_violation):
        resolved = sample_violation.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")


# =============================================================================
# MaterialityValidator
# =============================================================================

class TestMaterialityValidator:
    def test_validate_disclosure_material_disclosed(self, sample_threshold):
        legal_entity_id = uuid.uuid4()
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            item_amount=Decimal("5000000"),
            item_description="Test",
            threshold=sample_threshold,
            qualitative_factors=[],
            was_disclosed_separately=True,
        )
        assert is_valid is True
        assert violation is None

    def test_validate_disclosure_not_disclosed_quantitatively(self, sample_threshold):
        legal_entity_id = uuid.uuid4()
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            is_valid, violation = MaterialityValidator.validate_disclosure(
                legal_entity_id=legal_entity_id,
                fiscal_year=2026,
                item_amount=Decimal("5000000"),
                item_description="Test",
                threshold=sample_threshold,
                qualitative_factors=[],
                was_disclosed_separately=False,
            )
        assert is_valid is False
        assert violation is not None
        assert violation.failure_type == "NON_DISCLOSURE"
        assert violation.severity == MaterialitySeverity.CRITICAL  # 5x threshold

    def test_validate_disclosure_not_disclosed_qualitatively(self, sample_threshold):
        legal_entity_id = uuid.uuid4()
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            is_valid, violation = MaterialityValidator.validate_disclosure(
                legal_entity_id=legal_entity_id,
                fiscal_year=2026,
                item_amount=Decimal("100000"),
                item_description="Test",
                threshold=sample_threshold,
                qualitative_factors=[QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT],
                was_disclosed_separately=False,
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == MaterialitySeverity.CATASTROPHIC

    def test_validate_disclosure_under_threshold_no_factors(self, sample_threshold):
        legal_entity_id = uuid.uuid4()
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id=legal_entity_id,
            fiscal_year=2026,
            item_amount=Decimal("100000"),
            item_description="Test",
            threshold=sample_threshold,
            qualitative_factors=[],
            was_disclosed_separately=False,
        )
        assert is_valid is True
        assert violation is None

    @pytest.mark.parametrize(
        "amount, threshold, factors, expected_severity",
        [
            # Catastrophic: fraud/illegal, regulatory, going concern
            (Decimal("100"), Decimal("1000"), [QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT], MaterialitySeverity.CATASTROPHIC),
            (Decimal("100"), Decimal("1000"), [QualitativeMaterialityFactor.REGULATORY_COMPLIANCE], MaterialitySeverity.CATASTROPHIC),
            (Decimal("100"), Decimal("1000"), [QualitativeMaterialityFactor.GOING_CONCERN], MaterialitySeverity.CATASTROPHIC),
            # Critical: amount > 2 * threshold
            (Decimal("3000"), Decimal("1000"), [], MaterialitySeverity.CRITICAL),
            # High: amount > threshold or has qualitative
            (Decimal("1500"), Decimal("1000"), [], MaterialitySeverity.HIGH),
            (Decimal("500"), Decimal("1000"), [QualitativeMaterialityFactor.RELATED_PARTY], MaterialitySeverity.HIGH),
            # Medium: else
            (Decimal("500"), Decimal("1000"), [], MaterialitySeverity.MEDIUM),
        ],
    )
    def test_determine_severity(self, amount, threshold, factors, expected_severity):
        severity = MaterialityValidator._determine_severity(amount, threshold, factors)
        assert severity == expected_severity


# =============================================================================
# MaterialityAxiom
# =============================================================================

class TestMaterialityAxiom:
    def test_singleton(self):
        a1 = MaterialityAxiom()
        a2 = MaterialityAxiom()
        assert a1 is a2

    def test_save_and_get_threshold(self, sample_threshold):
        axiom = MaterialityAxiom()
        axiom.save_threshold(sample_threshold)
        retrieved = axiom.get_threshold(sample_threshold.legal_entity_id, sample_threshold.fiscal_year)
        assert retrieved is not None
        assert retrieved.threshold_id == sample_threshold.threshold_id

    def test_get_all_thresholds(self):
        axiom = MaterialityAxiom()
        t1 = MaterialityThreshold(
            threshold_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000"),
        )
        t2 = MaterialityThreshold(
            threshold_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2027,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("2000"),
        )
        axiom.save_threshold(t1)
        axiom.save_threshold(t2)
        all_th = axiom.get_all_thresholds()
        assert len(all_th) >= 2

    def test_delete_threshold(self, sample_threshold):
        axiom = MaterialityAxiom()
        axiom.save_threshold(sample_threshold)
        result = axiom.delete_threshold(sample_threshold.legal_entity_id, sample_threshold.fiscal_year)
        assert result is True
        assert axiom.get_threshold(sample_threshold.legal_entity_id, sample_threshold.fiscal_year) is None
        # Delete non-existent
        result2 = axiom.delete_threshold(uuid.uuid4(), 9999)
        assert result2 is False

    def test_save_and_get_judgments(self, sample_judgment):
        axiom = MaterialityAxiom()
        axiom.save_judgment(sample_judgment)
        judgments = axiom.get_judgments()
        assert len(judgments) == 1
        assert judgments[0].judgment_id == sample_judgment.judgment_id

    def test_get_judgments_filter_by_entity_and_year(self, sample_judgment):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        j1 = MaterialityJudgment(
            judgment_id=uuid.uuid4(),
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_description="A",
            item_amount=Decimal("100"),
            threshold_applied=Decimal("10"),
            is_material=True,
            qualitative_factors=[],
            justification="J",
            decided_by="admin",
            decided_at=FIXED_DATETIME,
            approved_by=[],
            referenced_standard="PSAK",
        )
        j2 = MaterialityJudgment(
            judgment_id=uuid.uuid4(),
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_description="B",
            item_amount=Decimal("200"),
            threshold_applied=Decimal("10"),
            is_material=True,
            qualitative_factors=[],
            justification="J",
            decided_by="admin",
            decided_at=FIXED_DATETIME,
            approved_by=[],
            referenced_standard="PSAK",
        )
        j3 = MaterialityJudgment(
            judgment_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            fiscal_year=2025,
            item_description="C",
            item_amount=Decimal("100"),
            threshold_applied=Decimal("10"),
            is_material=True,
            qualitative_factors=[],
            justification="J",
            decided_by="admin",
            decided_at=FIXED_DATETIME,
            approved_by=[],
            referenced_standard="PSAK",
        )
        axiom.save_judgment(j1)
        axiom.save_judgment(j2)
        axiom.save_judgment(j3)

        by_entity = axiom.get_judgments(legal_entity_id=entity_id)
        assert len(by_entity) == 2
        by_year = axiom.get_judgments(fiscal_year=2026)
        assert len(by_year) == 2
        by_both = axiom.get_judgments(legal_entity_id=entity_id, fiscal_year=2026)
        assert len(by_both) == 2

    def test_delete_judgment(self, sample_judgment):
        axiom = MaterialityAxiom()
        axiom.save_judgment(sample_judgment)
        result = axiom.delete_judgment(sample_judgment.judgment_id)
        assert result is True
        judgments = axiom.get_judgments()
        assert all(j.judgment_id != sample_judgment.judgment_id for j in judgments)
        # Delete again returns False
        result2 = axiom.delete_judgment(sample_judgment.judgment_id)
        assert result2 is False

    def test_save_and_get_violations(self, sample_violation):
        axiom = MaterialityAxiom()
        axiom.save_violation(sample_violation)
        violations = axiom.get_violations()
        assert len(violations) == 1
        assert violations[0].violation_id == sample_violation.violation_id

    def test_get_violations_filter(self, sample_violation):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        v1 = MaterialityViolation(
            violation_id=uuid.uuid4(),
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_amount=Decimal("1000"),
            threshold_that_should_apply=Decimal("100"),
            failure_type="NON_DISCLOSURE",
            severity=MaterialitySeverity.LOW,
            message="m1",
            detected_at=FIXED_DATETIME,
            detected_by="tester",
            resolved=True,
            resolved_at=FIXED_DATETIME,
            resolved_by="admin",
            corrective_action="CA",
        )
        v2 = MaterialityViolation(
            violation_id=uuid.uuid4(),
            legal_entity_id=entity_id,
            fiscal_year=2027,
            item_amount=Decimal("2000"),
            threshold_that_should_apply=Decimal("100"),
            failure_type="MISCLASSIFICATION",
            severity=MaterialitySeverity.HIGH,
            message="m2",
            detected_at=FIXED_DATETIME,
            detected_by="tester",
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            corrective_action=None,
        )
        axiom.save_violation(v1)
        axiom.save_violation(v2)

        by_entity = axiom.get_violations(legal_entity_id=entity_id)
        assert len(by_entity) == 2
        by_year = axiom.get_violations(fiscal_year=2026)
        assert len(by_year) == 1
        unresolved = axiom.get_violations(unresolved_only=True)
        assert len(unresolved) == 1
        assert unresolved[0].violation_id == v2.violation_id

    def test_resolve_violation(self, sample_violation):
        axiom = MaterialityAxiom()
        axiom.save_violation(sample_violation)
        resolved = axiom.resolve_violation(sample_violation.violation_id, "admin", "Corrected")
        assert resolved is not None
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        # Resolving again returns None
        resolved2 = axiom.resolve_violation(sample_violation.violation_id, "admin2", "Again")
        assert resolved2 is None

    def test_set_threshold(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        threshold = axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("500000"),
            description="Custom",
            approved_by=["a"],
        )
        assert threshold is not None
        assert threshold.legal_entity_id == entity_id
        assert threshold.fiscal_year == 2026
        assert threshold.value == Decimal("500000")
        assert threshold.description == "Custom"
        retrieved = axiom.get_threshold(entity_id, 2026)
        assert retrieved is not None
        assert retrieved.threshold_id == threshold.threshold_id

    def test_get_or_create_default_threshold_existing(self, sample_threshold):
        axiom = MaterialityAxiom()
        axiom.save_threshold(sample_threshold)
        result = axiom.get_or_create_default_threshold(
            sample_threshold.legal_entity_id, sample_threshold.fiscal_year, Decimal("10000000")
        )
        assert result.threshold_id == sample_threshold.threshold_id

    def test_get_or_create_default_threshold_new_with_profit(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        result = axiom.get_or_create_default_threshold(entity_id, 2026, Decimal("10000000"))
        assert result.threshold_type == MaterialityThresholdType.PERCENTAGE_OF_PROFIT
        assert result.value == Decimal("500000")  # 5% of 10M
        assert result.percentage == Decimal("5")
        assert result.reference_value == Decimal("10000000")

    def test_get_or_create_default_threshold_new_without_profit(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        result = axiom.get_or_create_default_threshold(entity_id, 2026)
        assert result.threshold_type == MaterialityThresholdType.ABSOLUTE
        assert result.value == Decimal("100000000")
        assert result.percentage is None

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
            entity_id, 2026, Decimal("100000"), qualitative_factors=[QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT]
        ) is True

    def test_is_material_uses_default(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        assert axiom.is_material(entity_id, 2026, Decimal("200000000")) is True
        assert axiom.is_material(entity_id, 2026, Decimal("10000000")) is False

    def test_record_judgment(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        judgment = axiom.record_judgment(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            item_description="Item",
            item_amount=Decimal("5000000"),
            threshold_applied=Decimal("1000000"),
            is_material=True,
            qualitative_factors=["FRAUD_OR_ILLEGAL_ACT"],
            justification="Justification",
            decided_by="admin",
            approved_by=["a", "b"],
            referenced_standard="PSAK",
        )
        assert judgment is not None
        assert judgment.legal_entity_id == entity_id
        assert judgment.is_material is True
        retrieved = axiom.get_judgments(legal_entity_id=entity_id)
        assert len(retrieved) == 1
        assert retrieved[0].judgment_id == judgment.judgment_id

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
            item_description="Test",
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
                item_description="Test",
                was_disclosed_separately=False,
                raise_on_violation=False,
            )
        assert is_valid is False
        assert violation is not None
        assert violation.failure_type == "NON_DISCLOSURE"

    def test_enforce_disclosure_raises(self):
        axiom = MaterialityAxiom()
        entity_id = uuid.uuid4()
        axiom.set_threshold(
            legal_entity_id=entity_id,
            fiscal_year=2026,
            threshold_type=MaterialityThresholdType.ABSOLUTE,
            value=Decimal("1000000"),
        )
        with patch("axioms.materiality.MaterialityValidator._notify_constitution"):
            with pytest.raises(MaterialityViolationError, match="NON_DISCLOSURE"):
                axiom.enforce_disclosure(
                    legal_entity_id=entity_id,
                    fiscal_year=2026,
                    item_amount=Decimal("5000000"),
                    item_description="Test",
                    was_disclosed_separately=False,
                    raise_on_violation=True,
                )

    def test_get_statistics(self):
        axiom = MaterialityAxiom()
        # Add some data
        entity_id = uuid.uuid4()
        axiom.set_threshold(entity_id, 2026, MaterialityThresholdType.ABSOLUTE, Decimal("1000"))
        axiom.record_judgment(
            entity_id, 2026, "Item", Decimal("2000"), Decimal("1000"), True, [], "J", "admin", ["a"]
        )
        axiom.save_violation(
            MaterialityViolation(
                violation_id=uuid.uuid4(),
                legal_entity_id=entity_id,
                fiscal_year=2026,
                item_amount=Decimal("2000"),
                threshold_that_should_apply=Decimal("1000"),
                failure_type="NON_DISCLOSURE",
                severity=MaterialitySeverity.CRITICAL,
                message="",
                detected_at=FIXED_DATETIME,
                detected_by="tester",
                resolved=False,
                resolved_at=None,
                resolved_by=None,
                corrective_action=None,
            )
        )
        stats = axiom.get_statistics()
        assert stats["thresholds_defined"] >= 1
        assert stats["judgments_recorded"] >= 1
        assert stats["total_violations"] >= 1
        assert stats["unresolved_violations"] >= 1
        assert "by_severity" in stats
        assert "by_failure_type" in stats

    def test_reset(self):
        axiom = MaterialityAxiom()
        axiom.set_threshold(uuid.uuid4(), 2026, MaterialityThresholdType.ABSOLUTE, Decimal("1000"))
        axiom.reset()
        assert len(axiom._thresholds) == 0
        assert len(axiom._judgments) == 0
        assert len(axiom._violations) == 0


# =============================================================================
# Helper functions
# =============================================================================

class TestHelperFunctions:
    @pytest.mark.parametrize(
        "input_str, expected",
        [
            ("FRAUD_OR_ILLEGAL_ACT", QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT),
            ("REGULATORY_COMPLIANCE", QualitativeMaterialityFactor.REGULATORY_COMPLIANCE),
            ("DEBT_COVENANT_VIOLATION", QualitativeMaterialityFactor.DEBT_COVENANT_VIOLATION),
            ("TREND_REVERSAL", QualitativeMaterialityFactor.TREND_REVERSAL),
            ("SEGMENT_REPORTING", QualitativeMaterialityFactor.SEGMENT_REPORTING),
            ("RELATED_PARTY", QualitativeMaterialityFactor.RELATED_PARTY),
            ("EXECUTIVE_COMPENSATION", QualitativeMaterialityFactor.EXECUTIVE_COMPENSATION),
            ("PUBLIC_PERCEPTION", QualitativeMaterialityFactor.PUBLIC_PERCEPTION),
            ("GOING_CONCERN", QualitativeMaterialityFactor.GOING_CONCERN),
            ("ROLLOVER_EFFECT", QualitativeMaterialityFactor.ROLLOVER_EFFECT),
            ("unknown", QualitativeMaterialityFactor.PUBLIC_PERCEPTION),
        ],
    )
    def test_create_qualitative_factor_from_string(self, input_str, expected):
        assert create_qualitative_factor_from_string(input_str) == expected

    @pytest.mark.parametrize(
        "threshold_type, base, percentage, expected",
        [
            (MaterialityThresholdType.ABSOLUTE, Decimal("1000000"), Decimal("5"), Decimal("1000000")),
            (MaterialityThresholdType.PERCENTAGE_OF_PROFIT, Decimal("10000000"), Decimal("5"), Decimal("500000")),
            (MaterialityThresholdType.PERCENTAGE_OF_ASSETS, Decimal("10000000"), Decimal("5"), Decimal("500000")),
            (MaterialityThresholdType.PERCENTAGE_OF_EQUITY, Decimal("10000000"), Decimal("5"), Decimal("500000")),
            (MaterialityThresholdType.PERCENTAGE_OF_REVENUE, Decimal("10000000"), Decimal("5"), Decimal("500000")),
        ],
    )
    def test_calculate_materiality_threshold(self, threshold_type, base, percentage, expected):
        result = calculate_materiality_threshold(threshold_type, base, percentage)
        assert result == expected

    def test_get_materiality_axiom_singleton(self):
        a1 = get_materiality_axiom()
        a2 = get_materiality_axiom()
        assert a1 is a2
        assert isinstance(a1, MaterialityAxiom)
