# tests/domain/intent/test_materiality_evaluator.py
"""
Comprehensive unit tests for domain/intent/materiality_evaluator.py.
Includes proper mocking of datetime and external dependencies to avoid flakiness.
Covers all public methods with positive and negative path tests.
"""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from domain.intent.materiality_evaluator import (
    DEFAULT_MATERIALITY_THRESHOLDS,
    MaterialityDimension,
    MaterialityEvaluation,
    MaterialityEvaluator,
    MaterialityLevel,
    MaterialityThreshold,
    get_materiality_evaluator,
)
from domain.intent.risk_assessor import RiskLevel

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def mock_datetime_now(mocker):
    """Mock datetime.now in materiality_evaluator to a fixed time."""
    fixed = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
    mocker.patch("domain.intent.materiality_evaluator.datetime.now", return_value=fixed)
    return fixed


@pytest.fixture
def fixed_datetime():
    return datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def immaterial_threshold():
    return MaterialityThreshold(
        level=MaterialityLevel.IMMATERIAL,
        min_amount=Decimal(0),
        max_amount=Decimal(10_000_000),
        requires_approval=False,
        required_approvers=0,
        required_documentation=[],
    )


@pytest.fixture
def material_threshold():
    return MaterialityThreshold(
        level=MaterialityLevel.MATERIAL,
        min_amount=Decimal(10_000_000),
        max_amount=Decimal(100_000_000),
        requires_approval=True,
        required_approvers=1,
        required_documentation=["justification_memo", "supporting_calculation"],
    )


@pytest.fixture
def highly_material_threshold():
    return MaterialityThreshold(
        level=MaterialityLevel.HIGHLY_MATERIAL,
        min_amount=Decimal(100_000_000),
        max_amount=Decimal(1_000_000_000),
        requires_approval=True,
        required_approvers=2,
        required_documentation=["justification_memo", "supporting_calculation", "management_approval"],
        escalation_level="CFO",
    )


@pytest.fixture
def critical_threshold():
    return MaterialityThreshold(
        level=MaterialityLevel.CRITICAL,
        min_amount=Decimal(1_000_000_000),
        max_amount=Decimal("inf"),
        requires_approval=True,
        required_approvers=2,
        required_documentation=["justification_memo", "supporting_calculation", "board_approval"],
        escalation_level="BOARD",
    )


@pytest.fixture
def sample_evaluation(fixed_datetime):
    return MaterialityEvaluation(
        evaluation_id=uuid4(),
        intent_id=uuid4(),
        evaluated_at=fixed_datetime,
        evaluated_by="user",
        materiality_level=MaterialityLevel.MATERIAL,
        quantitative_score=Decimal("45.5"),
        qualitative_factors=["factor1", "factor2"],
        justification="test justification",
        requires_board_approval=False,
        requires_disclosure=True,
        notes="test notes",
    )


@pytest.fixture
def mock_intent_record():
    intent = MagicMock()
    intent.intent_id = uuid4()
    intent.data = {
        "amount": "50000000",  # 50M
        "is_correction": False,
        "is_related_party": False,
        "affects_compliance": False,
        "affects_covenants": False,
        "reverses_trend": False,
    }
    return intent


@pytest.fixture
def mock_risk_assessment():
    risk = MagicMock()
    risk.overall_risk = RiskLevel.LOW
    return risk


@pytest.fixture
def evaluator_with_mocks(mocker, mock_intent_record, mock_risk_assessment):
    """Return MaterialityEvaluator with mocked record and risk services."""
    mock_record_service = mocker.MagicMock()
    mock_record_service.get.return_value = mock_intent_record
    mock_risk_assessor = mocker.MagicMock()
    mock_risk_assessor.get_assessment.return_value = mock_risk_assessment

    # Patch the getters to return our mocks
    mocker.patch(
        "domain.intent.materiality_evaluator.get_immutable_intent_record_service",
        return_value=mock_record_service,
    )
    mocker.patch(
        "domain.intent.materiality_evaluator.get_risk_assessor",
        return_value=mock_risk_assessor,
    )

    evaluator = MaterialityEvaluator()
    # Override the internal references to ensure they are our mocks
    evaluator._record_service = mock_record_service
    evaluator._risk_assessor = mock_risk_assessor
    return evaluator


# ============================================================================
# Tests for Enums
# ============================================================================

class TestEnums:
    def test_materiality_level(self):
        assert MaterialityLevel.IMMATERIAL.value == 1
        assert MaterialityLevel.MATERIAL.value == 2
        assert MaterialityLevel.HIGHLY_MATERIAL.value == 3
        assert MaterialityLevel.CRITICAL.value == 4

    def test_materiality_dimension(self):
        assert MaterialityDimension.QUANTITATIVE.value == "quantitative"
        assert MaterialityDimension.QUALITATIVE.value == "qualitative"
        assert MaterialityDimension.BOTH.value == "both"


# ============================================================================
# Tests for MaterialityThreshold
# ============================================================================

class TestMaterialityThreshold:
    def test_construction_valid(self, immaterial_threshold):
        assert immaterial_threshold.level == MaterialityLevel.IMMATERIAL
        assert immaterial_threshold.min_amount == Decimal(0)
        assert immaterial_threshold.max_amount == Decimal(10_000_000)
        assert immaterial_threshold.requires_approval is False
        assert immaterial_threshold.required_approvers == 0
        assert immaterial_threshold.required_documentation == []
        assert immaterial_threshold.version == 1
        # Check that __post_init__ called and snapshots/audit exist
        assert len(immaterial_threshold._snapshots) == 1

    # ----- Negative path tests for validation -----
    def test_validation_level_invalid(self):
        with pytest.raises(ValueError, match="level must be MaterialityLevel"):
            MaterialityThreshold(
                level="invalid",  # type: ignore
                min_amount=Decimal(0),
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            )

    def test_validation_min_amount_not_decimal(self):
        with pytest.raises(ValueError, match="min_amount must be Decimal"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=10,  # type: ignore
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            )

    def test_validation_max_amount_not_decimal(self):
        with pytest.raises(ValueError, match="max_amount must be Decimal"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(0),
                max_amount=10,  # type: ignore
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            )

    def test_validation_min_amount_negative(self):
        with pytest.raises(ValueError, match="min_amount cannot be negative"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(-1),
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            )

    def test_validation_max_amount_less_than_min(self):
        with pytest.raises(ValueError, match="max_amount must be >= min_amount"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(10),
                max_amount=Decimal(5),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            )

    def test_validation_required_approvers_negative(self):
        with pytest.raises(ValueError, match="required_approvers must be non-negative integer"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(0),
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=-1,  # type: ignore
                required_documentation=[],
            )

    def test_validation_required_approvers_non_int(self):
        with pytest.raises(ValueError, match="required_approvers must be non-negative integer"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(0),
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=1.5,  # type: ignore
                required_documentation=[],
            )

    def test_validation_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(0),
                max_amount=Decimal(10),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
                version=0,
            )

    # ----- contains_amount -----
    def test_contains_amount(self, material_threshold):
        assert material_threshold.contains_amount(Decimal(50_000_000)) is True
        assert material_threshold.contains_amount(Decimal(10_000_000)) is True
        assert material_threshold.contains_amount(Decimal(100_000_000)) is True
        assert material_threshold.contains_amount(Decimal(9_999_999)) is False
        assert material_threshold.contains_amount(Decimal(100_000_001)) is False
        # Test with non-Decimal input
        assert material_threshold.contains_amount(50_000_000) is True

    def test_contains_amount_with_inf(self, critical_threshold):
        assert critical_threshold.contains_amount(Decimal(2_000_000_000)) is True
        assert critical_threshold.contains_amount(Decimal(1_000_000_000)) is True
        assert critical_threshold.contains_amount(Decimal(999_999_999)) is False

    # ----- Entity lifecycle methods -----
    def test_create(self, immaterial_threshold):
        result = immaterial_threshold.create("user")
        assert result is immaterial_threshold
        trail = immaterial_threshold.audit_trail()
        assert any(entry["action"] == "CREATE" for entry in trail)

    def test_update(self, material_threshold):
        new = material_threshold.update("user", min_amount=Decimal(20_000_000), required_approvers=2)
        assert new is not material_threshold
        assert new.version == material_threshold.version + 1
        assert new.min_amount == Decimal(20_000_000)
        assert new.required_approvers == 2
        # Other fields unchanged
        assert new.max_amount == material_threshold.max_amount
        trail = new.audit_trail()
        assert any(entry["action"] == "UPDATE" for entry in trail)

    def test_delete(self, immaterial_threshold):
        result = immaterial_threshold.delete("user", "reason")
        assert result is immaterial_threshold
        trail = immaterial_threshold.audit_trail()
        assert any(entry["action"] == "DELETE" for entry in trail)

    def test_restore(self, immaterial_threshold):
        result = immaterial_threshold.restore("user")
        assert result is immaterial_threshold
        trail = immaterial_threshold.audit_trail()
        assert any(entry["action"] == "RESTORE" for entry in trail)

    def test_activate(self, immaterial_threshold):
        result = immaterial_threshold.activate("user")
        assert result is immaterial_threshold

    def test_deactivate(self, immaterial_threshold):
        result = immaterial_threshold.deactivate("user", "reason")
        assert result is immaterial_threshold

    def test_lock(self, immaterial_threshold):
        result = immaterial_threshold.lock("user", "reason")
        assert result is immaterial_threshold

    def test_unlock(self, immaterial_threshold):
        result = immaterial_threshold.unlock("user")
        assert result is immaterial_threshold

    def test_validate_valid(self, immaterial_threshold):
        result = immaterial_threshold.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["level"] == "IMMATERIAL"
        assert result["version"] == 1

    def test_validate_invalid(self, material_threshold):
        # Manually corrupt
        material_threshold.min_amount = Decimal(-5)
        result = material_threshold.validate()
        assert result["is_valid"] is False
        assert any("min_amount cannot be negative" in e for e in result["errors"])

    def test_to_dict(self, critical_threshold):
        d = critical_threshold.to_dict()
        assert d["level"] == "CRITICAL"
        assert d["min_amount"] == "1000000000"
        assert d["max_amount"] == "inf"
        assert d["requires_approval"] is True
        assert d["required_approvers"] == 2
        assert d["required_documentation"] == ["justification_memo", "supporting_calculation", "board_approval"]
        assert d["escalation_level"] == "BOARD"
        assert d["version"] == 1

    def test_from_dict(self, critical_threshold):
        d = critical_threshold.to_dict()
        new = MaterialityThreshold.from_dict(d)
        assert new.level == critical_threshold.level
        assert new.min_amount == critical_threshold.min_amount
        assert new.max_amount == critical_threshold.max_amount
        assert new.requires_approval == critical_threshold.requires_approval
        assert new.required_approvers == critical_threshold.required_approvers
        assert new.required_documentation == critical_threshold.required_documentation
        assert new.escalation_level == critical_threshold.escalation_level
        assert new.version == critical_threshold.version

    def test_clone(self, material_threshold):
        clone = material_threshold.clone()
        assert clone is not material_threshold
        assert clone.level == material_threshold.level
        assert clone.min_amount == material_threshold.min_amount
        assert clone.max_amount == material_threshold.max_amount
        assert clone.required_documentation == material_threshold.required_documentation
        assert clone.version == 1

    def test_snapshot(self, material_threshold):
        snap = material_threshold.snapshot()
        assert snap["version"] == 1
        assert snap["level"] == "MATERIAL"
        assert snap["min_amount"] == "10000000"
        assert snap["max_amount"] == "100000000"
        assert "timestamp" in snap

    def test_audit_trail(self, material_threshold):
        trail = material_threshold.audit_trail()
        assert len(trail) >= 1

    def test_touch(self, material_threshold):
        old_version = material_threshold.version
        touched = material_threshold.touch("user")
        assert touched is not material_threshold
        assert touched.version == old_version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    # Additional negative: update with invalid field
    def test_update_invalid_field(self, material_threshold):
        with pytest.raises(AttributeError):
            material_threshold.update("user", invalid_field=123)


# ============================================================================
# Tests for MaterialityEvaluation
# ============================================================================

class TestMaterialityEvaluation:
    def test_construction_valid(self, sample_evaluation):
        assert sample_evaluation.evaluation_id is not None
        assert sample_evaluation.intent_id is not None
        assert sample_evaluation.evaluated_at.tzinfo == UTC
        assert sample_evaluation.materiality_level == MaterialityLevel.MATERIAL
        assert sample_evaluation.quantitative_score == Decimal("45.5")
        assert sample_evaluation.qualitative_factors == ["factor1", "factor2"]
        assert sample_evaluation.justification == "test justification"
        assert sample_evaluation.requires_board_approval is False
        assert sample_evaluation.requires_disclosure is True
        assert sample_evaluation.version == 1
        assert sample_evaluation.cryptographic_hash != ""
        assert len(sample_evaluation._snapshots) == 1
        trail = sample_evaluation.audit_trail()
        assert any(entry["action"] == "CREATE" for entry in trail)

    # ----- Negative path tests for validation -----
    def test_validation_evaluation_id_not_uuid(self):
        with pytest.raises(ValueError, match="evaluation_id must be UUID"):
            MaterialityEvaluation(
                evaluation_id="not-uuid",  # type: ignore
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_intent_id_not_uuid(self):
        with pytest.raises(ValueError, match="intent_id must be UUID"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id="not-uuid",  # type: ignore
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_evaluated_at_not_datetime(self):
        with pytest.raises(ValueError, match="evaluated_at must be datetime"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at="2025-01-01",  # type: ignore
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_evaluated_by_empty(self):
        with pytest.raises(ValueError, match="evaluated_by cannot be empty"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_materiality_level_invalid(self):
        with pytest.raises(ValueError, match="materiality_level must be MaterialityLevel"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level="invalid",  # type: ignore
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_quantitative_score_not_decimal(self):
        with pytest.raises(ValueError, match="quantitative_score must be Decimal"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=50,  # type: ignore
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_quantitative_score_out_of_range(self):
        with pytest.raises(ValueError, match="quantitative_score must be between 0 and 100"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(-1),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )
        with pytest.raises(ValueError, match="quantitative_score must be between 0 and 100"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(101),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
            )

    def test_validation_version_zero(self):
        with pytest.raises(ValueError, match="version must be >= 1"):
            MaterialityEvaluation(
                evaluation_id=uuid4(),
                intent_id=uuid4(),
                evaluated_at=datetime.now(UTC),
                evaluated_by="user",
                materiality_level=MaterialityLevel.IMMATERIAL,
                quantitative_score=Decimal(50),
                qualitative_factors=[],
                justification="",
                requires_board_approval=False,
                requires_disclosure=False,
                version=0,
            )

    # ----- compute_hash -----
    def test_compute_hash(self, sample_evaluation):
        h = sample_evaluation.compute_hash()
        assert len(h) == 64  # SHA3-256
        # Ensure hash changes if content changes
        eval2 = MaterialityEvaluation(
            evaluation_id=sample_evaluation.evaluation_id,
            intent_id=sample_evaluation.intent_id,
            evaluated_at=sample_evaluation.evaluated_at,
            evaluated_by=sample_evaluation.evaluated_by,
            materiality_level=sample_evaluation.materiality_level,
            quantitative_score=sample_evaluation.quantitative_score,
            qualitative_factors=sample_evaluation.qualitative_factors,
            justification=sample_evaluation.justification,
            requires_board_approval=sample_evaluation.requires_board_approval,
            requires_disclosure=not sample_evaluation.requires_disclosure,  # change
            notes=sample_evaluation.notes,
            version=sample_evaluation.version,
        )
        # __post_init__ recomputes hash
        assert eval2.cryptographic_hash != sample_evaluation.cryptographic_hash

    # ----- validate -----
    def test_validate(self, sample_evaluation):
        result = sample_evaluation.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_hash_mismatch(self, sample_evaluation):
        # Tamper with the hash
        sample_evaluation.cryptographic_hash = "tampered"
        result = sample_evaluation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    # ----- Immutability methods -----
    def test_entity_methods_immutable(self, sample_evaluation):
        with pytest.raises(AttributeError, match="immutable"):
            sample_evaluation.update("user")
        with pytest.raises(AttributeError, match="cannot be deleted"):
            sample_evaluation.delete("user")
        with pytest.raises(AttributeError, match="cannot be restored"):
            sample_evaluation.restore("user")

    def test_activate(self, sample_evaluation):
        result = sample_evaluation.activate("user")
        assert result is sample_evaluation

    def test_deactivate(self, sample_evaluation):
        result = sample_evaluation.deactivate("user", "reason")
        assert result is sample_evaluation

    def test_lock(self, sample_evaluation):
        result = sample_evaluation.lock("user", "reason")
        assert result is sample_evaluation

    def test_unlock(self, sample_evaluation):
        result = sample_evaluation.unlock("user")
        assert result is sample_evaluation

    # ----- to_dict / from_dict -----
    def test_to_dict(self, sample_evaluation):
        d = sample_evaluation.to_dict()
        assert d["evaluation_id"] == str(sample_evaluation.evaluation_id)
        assert d["intent_id"] == str(sample_evaluation.intent_id)
        assert d["evaluated_at"] == sample_evaluation.evaluated_at.isoformat()
        assert d["evaluated_by"] == "user"
        assert d["materiality_level"] == "MATERIAL"
        assert d["quantitative_score"] == "45.5"
        assert d["qualitative_factors"] == ["factor1", "factor2"]
        assert d["justification"] == "test justification"
        assert d["requires_board_approval"] is False
        assert d["requires_disclosure"] is True
        assert d["notes"] == "test notes"
        assert d["version"] == 1
        assert "cryptographic_hash" in d

    def test_from_dict(self, sample_evaluation):
        d = sample_evaluation.to_dict()
        # Full hash is truncated in to_dict; we need to provide full hash for roundtrip
        d["cryptographic_hash"] = sample_evaluation.cryptographic_hash
        restored = MaterialityEvaluation.from_dict(d)
        assert restored.evaluation_id == sample_evaluation.evaluation_id
        assert restored.intent_id == sample_evaluation.intent_id
        assert restored.evaluated_at == sample_evaluation.evaluated_at
        assert restored.evaluated_by == sample_evaluation.evaluated_by
        assert restored.materiality_level == sample_evaluation.materiality_level
        assert restored.quantitative_score == sample_evaluation.quantitative_score
        assert restored.qualitative_factors == sample_evaluation.qualitative_factors
        assert restored.justification == sample_evaluation.justification
        assert restored.requires_board_approval == sample_evaluation.requires_board_approval
        assert restored.requires_disclosure == sample_evaluation.requires_disclosure
        assert restored.notes == sample_evaluation.notes
        assert restored.version == sample_evaluation.version
        assert restored.cryptographic_hash == sample_evaluation.cryptographic_hash

    # Negative: from_dict with missing required field
    def test_from_dict_missing_field(self):
        d = {
            "evaluation_id": str(uuid4()),
            "intent_id": str(uuid4()),
            "evaluated_at": datetime.now(UTC).isoformat(),
            "evaluated_by": "user",
            "materiality_level": "IMMATERIAL",
            "quantitative_score": "10",
            "requires_board_approval": False,
            "requires_disclosure": False,
            # missing qualitative_factors, justification, notes, version, hash
        }
        with pytest.raises(KeyError):
            MaterialityEvaluation.from_dict(d)

    # ----- clone, snapshot, audit_trail, touch -----
    def test_clone(self, sample_evaluation):
        clone = sample_evaluation.clone()
        assert clone.evaluation_id != sample_evaluation.evaluation_id
        assert clone.intent_id == sample_evaluation.intent_id
        assert clone.materiality_level == sample_evaluation.materiality_level
        assert clone.quantitative_score == sample_evaluation.quantitative_score
        assert clone.qualitative_factors == sample_evaluation.qualitative_factors
        assert clone.justification == sample_evaluation.justification
        assert clone.version == 1

    def test_snapshot(self, sample_evaluation):
        snap = sample_evaluation.snapshot()
        assert snap["version"] == 1
        assert snap["evaluation_id"] == str(sample_evaluation.evaluation_id)
        assert snap["materiality_level"] == "MATERIAL"
        assert "timestamp" in snap

    def test_audit_trail(self, sample_evaluation):
        trail = sample_evaluation.audit_trail()
        assert len(trail) >= 1
        assert any(entry["action"] == "CREATE" for entry in trail)

    def test_touch(self, sample_evaluation):
        touched = sample_evaluation.touch("user")
        assert touched is sample_evaluation
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)


# ============================================================================
# Tests for MaterialityEvaluator
# ============================================================================

class TestMaterialityEvaluator:
    def test_singleton(self):
        e1 = MaterialityEvaluator()
        e2 = MaterialityEvaluator()
        assert e1 is e2

    def test_initialization(self, mocker):
        # Mock the service getters
        mock_record = mocker.MagicMock()
        mock_risk = mocker.MagicMock()
        mocker.patch(
            "domain.intent.materiality_evaluator.get_immutable_intent_record_service",
            return_value=mock_record,
        )
        mocker.patch(
            "domain.intent.materiality_evaluator.get_risk_assessor",
            return_value=mock_risk,
        )
        evaluator = MaterialityEvaluator()
        assert evaluator._thresholds == DEFAULT_MATERIALITY_THRESHOLDS
        assert evaluator._evaluations == {}
        assert evaluator._record_service == mock_record
        assert evaluator._risk_assessor == mock_risk

    def test_set_thresholds(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        new_thresholds = [
            MaterialityThreshold(
                level=MaterialityLevel.IMMATERIAL,
                min_amount=Decimal(0),
                max_amount=Decimal(5000),
                requires_approval=False,
                required_approvers=0,
                required_documentation=[],
            ),
            MaterialityThreshold(
                level=MaterialityLevel.MATERIAL,
                min_amount=Decimal(5000),
                max_amount=Decimal(10000),
                requires_approval=True,
                required_approvers=1,
                required_documentation=[],
            ),
        ]
        evaluator.set_thresholds(new_thresholds)
        assert evaluator._thresholds == sorted(new_thresholds, key=lambda t: t.min_amount)

    def test_get_threshold_for_amount(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        # Default thresholds
        assert evaluator.get_threshold_for_amount(Decimal(5_000_000)).level == MaterialityLevel.IMMATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(10_000_000)).level == MaterialityLevel.IMMATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(10_000_001)).level == MaterialityLevel.MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(50_000_000)).level == MaterialityLevel.MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(100_000_000)).level == MaterialityLevel.MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(100_000_001)).level == MaterialityLevel.HIGHLY_MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(500_000_000)).level == MaterialityLevel.HIGHLY_MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(1_000_000_000)).level == MaterialityLevel.HIGHLY_MATERIAL
        assert evaluator.get_threshold_for_amount(Decimal(1_000_000_001)).level == MaterialityLevel.CRITICAL

    def test_add_threshold(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        new_threshold = MaterialityThreshold(
            level=MaterialityLevel.CRITICAL,
            min_amount=Decimal(500_000_000),
            max_amount=Decimal("inf"),
            requires_approval=True,
            required_approvers=3,
            required_documentation=[],
        )
        evaluator.add_threshold(new_threshold)
        assert new_threshold in evaluator._thresholds
        # Verify sorting
        thresholds = evaluator.get_all_thresholds()
        assert thresholds == sorted(thresholds, key=lambda t: t.min_amount)

    def test_get_all_thresholds(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        thresholds = evaluator.get_all_thresholds()
        assert len(thresholds) == 4
        assert thresholds == DEFAULT_MATERIALITY_THRESHOLDS

    # ----- evaluate -----
    def test_evaluate_immaterial(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "5000000"  # 5M
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation is not None
        assert evaluation.materiality_level == MaterialityLevel.IMMATERIAL
        assert evaluation.quantitative_score == Decimal(50)  # (5M / 10M) * 100 = 50
        assert evaluation.qualitative_factors == []
        assert evaluation.requires_board_approval is False
        assert evaluation.requires_disclosure is False
        assert "immaterial" in evaluation.justification.lower()
        # Saved in _evaluations
        assert evaluator.get_evaluation(intent_id) == evaluation

    def test_evaluate_material(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "50000000"  # 50M
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation.materiality_level == MaterialityLevel.MATERIAL
        assert evaluation.quantitative_score == Decimal(50)
        assert evaluation.requires_board_approval is False
        assert evaluation.requires_disclosure is True
        assert "requires 1 approval" in evaluation.justification

    def test_evaluate_highly_material(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "500000000"  # 500M
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation.materiality_level == MaterialityLevel.HIGHLY_MATERIAL
        assert evaluation.quantitative_score == Decimal(50)
        assert evaluation.requires_board_approval is False
        assert evaluation.requires_disclosure is True
        assert "requires 2 approval(s)" in evaluation.justification

    def test_evaluate_critical(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "2000000000"  # 2B
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation.materiality_level == MaterialityLevel.CRITICAL
        assert evaluation.quantitative_score == Decimal(100)
        assert evaluation.requires_board_approval is True
        assert evaluation.requires_disclosure is True
        assert "CRITICAL" in evaluation.justification

    def test_evaluate_with_qualitative_factors(self, evaluator_with_mocks, mock_intent_record, mock_risk_assessment):
        # Provide an intent with qualitative factors and high risk
        mock_intent_record.data.update({
            "amount": "5000000",  # 5M (would be immaterial)
            "is_correction": True,
            "is_related_party": True,
            "affects_compliance": True,
        })
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record
        # Risk assessment with HIGH risk
        mock_risk_assessment.overall_risk = RiskLevel.HIGH
        evaluator._risk_assessor.get_assessment.return_value = mock_risk_assessment

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation.materiality_level == MaterialityLevel.MATERIAL  # bumped from immaterial
        assert "Correction/amendment of prior period" in evaluation.qualitative_factors
        assert "Related party transaction" in evaluation.qualitative_factors
        assert "Affects regulatory compliance" in evaluation.qualitative_factors
        assert "High risk transaction (HIGH)" in evaluation.qualitative_factors
        assert len(evaluation.qualitative_factors) == 4

    def test_evaluate_qualitative_bump_to_highly_material(self, evaluator_with_mocks, mock_intent_record):
        # Start with amount that is MATERIAL (50M) and have >=2 qualitative factors
        mock_intent_record.data.update({
            "amount": "50000000",
            "is_correction": True,
            "affects_covenants": True,
            "reverses_trend": True,
        })
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        assert evaluation.materiality_level == MaterialityLevel.HIGHLY_MATERIAL
        assert len(evaluation.qualitative_factors) >= 2

    def test_evaluate_intent_not_found(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        evaluator._record_service.get.return_value = None
        with pytest.raises(ValueError, match="Intent .* not found"):
            evaluator.evaluate(uuid4(), "user")

    # ----- get_required_approvals -----
    def test_get_required_approvals(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "50000000"
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record

        evaluation = evaluator.evaluate(intent_id, "user")
        req = evaluator.get_required_approvals(intent_id)
        assert req["materiality_level"] == "MATERIAL"
        assert req["requires_approval"] is True
        assert req["required_approvers"] == 1
        assert "justification_memo" in req["required_documentation"]
        assert req["requires_board_approval"] is False
        assert req["requires_disclosure"] is True
        assert req["escalation_level"] is None

    def test_get_required_approvals_not_found(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        req = evaluator.get_required_approvals(uuid4())
        assert req == {"error": "No materiality evaluation found"}

    # ----- repository methods -----
    def test_save_evaluation(self, evaluator_with_mocks, fixed_datetime):
        evaluator = evaluator_with_mocks
        eval_obj = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="user",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="test",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        evaluator.save_evaluation(eval_obj)
        assert evaluator.get_evaluation(eval_obj.intent_id) == eval_obj

    def test_get_evaluations_by_intent(self, evaluator_with_mocks, fixed_datetime):
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        eval_obj = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=intent_id,
            evaluated_at=fixed_datetime,
            evaluated_by="user",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="test",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        evaluator.save_evaluation(eval_obj)
        evals = evaluator.get_evaluations_by_intent(intent_id)
        assert len(evals) == 1
        assert evals[0] == eval_obj
        # for non-existent
        evals2 = evaluator.get_evaluations_by_intent(uuid4())
        assert evals2 == []

    def test_get_all_evaluations(self, evaluator_with_mocks, fixed_datetime):
        evaluator = evaluator_with_mocks
        e1 = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="u1",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="j1",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        e2 = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="u2",
            materiality_level=MaterialityLevel.MATERIAL,
            quantitative_score=Decimal(50),
            qualitative_factors=[],
            justification="j2",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        evaluator.save_evaluation(e1)
        evaluator.save_evaluation(e2)
        all_evals = evaluator.get_all_evaluations()
        assert len(all_evals) == 2
        assert e1 in all_evals
        assert e2 in all_evals

    def test_delete_evaluation(self, evaluator_with_mocks, fixed_datetime):
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        eval_obj = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=intent_id,
            evaluated_at=fixed_datetime,
            evaluated_by="user",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="test",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        evaluator.save_evaluation(eval_obj)
        assert evaluator.delete_evaluation(intent_id) is True
        assert evaluator.get_evaluation(intent_id) is None
        assert evaluator.delete_evaluation(uuid4()) is False

    # ----- get_statistics -----
    def test_get_statistics(self, evaluator_with_mocks, fixed_datetime):
        evaluator = evaluator_with_mocks
        # No evaluations
        stats = evaluator.get_statistics()
        assert stats["total_evaluations"] == 0

        # Add evaluations
        e1 = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="u1",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="j1",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        e2 = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="u2",
            materiality_level=MaterialityLevel.MATERIAL,
            quantitative_score=Decimal(50),
            qualitative_factors=[],
            justification="j2",
            requires_board_approval=False,
            requires_disclosure=True,
        )
        e3 = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=fixed_datetime,
            evaluated_by="u3",
            materiality_level=MaterialityLevel.CRITICAL,
            quantitative_score=Decimal(100),
            qualitative_factors=[],
            justification="j3",
            requires_board_approval=True,
            requires_disclosure=True,
        )
        evaluator.save_evaluation(e1)
        evaluator.save_evaluation(e2)
        evaluator.save_evaluation(e3)
        stats = evaluator.get_statistics()
        assert stats["total_evaluations"] == 3
        assert stats["by_materiality_level"]["IMMATERIAL"] == 1
        assert stats["by_materiality_level"]["MATERIAL"] == 1
        assert stats["by_materiality_level"]["CRITICAL"] == 1
        assert stats["board_approval_count"] == 1
        assert stats["disclosure_required_count"] == 2

    def test_reset(self, evaluator_with_mocks):
        evaluator = evaluator_with_mocks
        # Add custom threshold and evaluation
        custom_threshold = MaterialityThreshold(
            level=MaterialityLevel.IMMATERIAL,
            min_amount=Decimal(0),
            max_amount=Decimal(1),
            requires_approval=False,
            required_approvers=0,
            required_documentation=[],
        )
        evaluator.add_threshold(custom_threshold)
        eval_obj = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=uuid4(),
            evaluated_at=datetime.now(UTC),
            evaluated_by="user",
            materiality_level=MaterialityLevel.IMMATERIAL,
            quantitative_score=Decimal(10),
            qualitative_factors=[],
            justification="test",
            requires_board_approval=False,
            requires_disclosure=False,
        )
        evaluator.save_evaluation(eval_obj)
        # Reset
        evaluator.reset()
        assert evaluator._thresholds == DEFAULT_MATERIALITY_THRESHOLDS
        assert evaluator._evaluations == {}
        assert custom_threshold not in evaluator._thresholds

    # Additional negative: evaluate with invalid amount type (non-numeric)
    def test_evaluate_invalid_amount_type(self, evaluator_with_mocks, mock_intent_record):
        mock_intent_record.data["amount"] = "not_a_number"
        evaluator = evaluator_with_mocks
        intent_id = uuid4()
        mock_intent_record.intent_id = intent_id
        evaluator._record_service.get.return_value = mock_intent_record
        with pytest.raises(Exception):
            evaluator.evaluate(intent_id, "user")


# ============================================================================
# Tests for module-level getter
# ============================================================================

def test_get_materiality_evaluator():
    evaluator1 = get_materiality_evaluator()
    evaluator2 = get_materiality_evaluator()
    assert evaluator1 is evaluator2
    assert isinstance(evaluator1, MaterialityEvaluator)
